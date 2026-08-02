import Carbon.HIToolbox
import AppKit

/// Global hotkeys via Carbon RegisterEventHotKey.
/// Parse: ⌥A — Recall last result: ⌥Z.
struct HotkeyFailure: Error, Equatable, Sendable {
    let operation: String
    let status: Int32

    var message: String {
        "\(operation) 失败（OSStatus \(status)），对应快捷键不可用。"
            + "请检查快捷键是否被其他应用占用，并确认 Thorn 已获得辅助功能权限。"
    }
}

final class HotkeyManager {
    private var hotKeyRefs: [EventHotKeyRef] = []
    private var eventHandler: EventHandlerRef?
    private var callbacks: [UInt32: () -> Void] = [:]
    private let callbackLock = NSLock()
    private(set) var eventHandlerStatus: OSStatus = noErr
    private(set) var failures: [HotkeyFailure] = []

    init() {
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                      eventKind: UInt32(kEventHotKeyPressed))
        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        let status = InstallEventHandler(GetApplicationEventTarget(), { _, event, userData in
            guard let userData, let event else { return noErr }
            var hotKeyID = EventHotKeyID()
            let parameterStatus = GetEventParameter(
                event,
                EventParamName(kEventParamDirectObject),
                EventParamType(typeEventHotKeyID),
                nil,
                MemoryLayout<EventHotKeyID>.size,
                nil,
                &hotKeyID
            )
            guard parameterStatus == noErr else {
                ThornLog.info("hotkey event parameter failed (OSStatus \(parameterStatus))")
                return noErr
            }
            let manager = Unmanaged<HotkeyManager>.fromOpaque(userData).takeUnretainedValue()
            manager.callbackLock.lock()
            let callback = manager.callbacks[hotKeyID.id]
            manager.callbackLock.unlock()
            if let callback {
                DispatchQueue.main.async { callback() }
            }
            return noErr
        }, 1, &eventType, selfPtr, &eventHandler)
        eventHandlerStatus = status
        if status != noErr {
            recordFailure(HotkeyFailure(operation: "InstallEventHandler", status: status))
        } else if eventHandler == nil {
            recordFailure(HotkeyFailure(operation: "InstallEventHandler", status: -1))
        }
    }

    @discardableResult
    func register(id: UInt32, keyCode: UInt32, modifiers: UInt32, callback: @escaping () -> Void) -> Bool {
        guard eventHandler != nil, eventHandlerStatus == noErr else {
            let status = eventHandlerStatus == noErr ? -1 : eventHandlerStatus
            recordFailure(HotkeyFailure(operation: "RegisterEventHotKey", status: status))
            return false
        }
        let hotKeyID = EventHotKeyID(signature: OSType(0x5448_524E), id: id) // "THRN"
        var ref: EventHotKeyRef?
        let status = RegisterEventHotKey(
            keyCode,
            modifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &ref
        )
        guard status == noErr, let ref else {
            recordFailure(HotkeyFailure(operation: "RegisterEventHotKey", status: status))
            return false
        }
        callbackLock.lock()
        callbacks[id] = callback
        callbackLock.unlock()
        hotKeyRefs.append(ref)
        return true
    }

    private func recordFailure(_ failure: HotkeyFailure) {
        guard !failures.contains(failure) else { return }
        failures.append(failure)
        ThornLog.info(failure.message)
    }

    deinit {
        for ref in hotKeyRefs { UnregisterEventHotKey(ref) }
        if let eventHandler { RemoveEventHandler(eventHandler) }
    }
}
