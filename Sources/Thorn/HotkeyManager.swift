import Carbon.HIToolbox
import AppKit

/// Global hotkey via Carbon RegisterEventHotKey. Default: ⌥D.
final class HotkeyManager {
    private var hotKeyRef: EventHotKeyRef?
    private var eventHandler: EventHandlerRef?
    private let callback: () -> Void

    init(callback: @escaping () -> Void) {
        self.callback = callback
        register()
    }

    private func register() {
        let hotKeyID = EventHotKeyID(signature: OSType(0x5448_524E), id: 1) // "THRN"
        var eventType = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))

        let selfPtr = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, _, userData in
            guard let userData else { return noErr }
            let manager = Unmanaged<HotkeyManager>.fromOpaque(userData).takeUnretainedValue()
            DispatchQueue.main.async { manager.callback() }
            return noErr
        }, 1, &eventType, selfPtr, &eventHandler)

        // kVK_ANSI_D = 0x02, optionKey modifier
        RegisterEventHotKey(UInt32(kVK_ANSI_D), UInt32(optionKey), hotKeyID,
                            GetApplicationEventTarget(), 0, &hotKeyRef)
    }

    deinit {
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        if let eventHandler { RemoveEventHandler(eventHandler) }
    }
}
