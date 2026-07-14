import Carbon.HIToolbox
import AppKit

/// Global hotkeys via Carbon RegisterEventHotKey.
/// Parse: ⌥A — Recall last result: ⌥Z.
final class HotkeyManager {
    private var hotKeyRefs: [EventHotKeyRef] = []
    private var eventHandler: EventHandlerRef?
    private var callbacks: [UInt32: () -> Void] = [:]

    init() {
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                      eventKind: UInt32(kEventHotKeyPressed))
        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, event, userData in
            guard let userData, let event else { return noErr }
            var hotKeyID = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject),
                              EventParamType(typeEventHotKeyID), nil,
                              MemoryLayout<EventHotKeyID>.size, nil, &hotKeyID)
            let manager = Unmanaged<HotkeyManager>.fromOpaque(userData).takeUnretainedValue()
            if let callback = manager.callbacks[hotKeyID.id] {
                DispatchQueue.main.async { callback() }
            }
            return noErr
        }, 1, &eventType, selfPtr, &eventHandler)
    }

    func register(id: UInt32, keyCode: UInt32, modifiers: UInt32, callback: @escaping () -> Void) {
        callbacks[id] = callback
        let hotKeyID = EventHotKeyID(signature: OSType(0x5448_524E), id: id) // "THRN"
        var ref: EventHotKeyRef?
        RegisterEventHotKey(keyCode, modifiers, hotKeyID, GetApplicationEventTarget(), 0, &ref)
        if let ref { hotKeyRefs.append(ref) }
    }

    deinit {
        for ref in hotKeyRefs { UnregisterEventHotKey(ref) }
        if let eventHandler { RemoveEventHandler(eventHandler) }
    }
}
