import AppKit
import SwiftUI

/// Dead-simple file logger for diagnostics: /tmp/thorn.log
enum ThornLog {
    static func info(_ message: String) {
        let line = "\(Date()) \(message)\n"
        let url = URL(fileURLWithPath: "/tmp/thorn.log")
        if let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(Data(line.utf8))
            try? handle.close()
        } else {
            try? line.write(to: url, atomically: true, encoding: .utf8)
        }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var hotkey: HotkeyManager!
    private let panelController = ResultPanelController()
    private var settingsWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "text.line.magnify", accessibilityDescription: "Thorn")
        }

        let menu = NSMenu()
        menu.addItem(withTitle: "选中英文后按 ⌥D 拆句", action: nil, keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "设置…", action: #selector(openSettings), keyEquivalent: ",")
        menu.addItem(.separator())
        menu.addItem(withTitle: "退出 Thorn", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        statusItem.menu = menu

        let trusted = TextCapture.ensureAccessibilityPermission()
        ThornLog.info("launched, axTrusted=\(trusted)")

        hotkey = HotkeyManager { [weak self] in
            self?.handleHotkey()
        }
    }

    private func handleHotkey() {
        ThornLog.info("hotkey fired, axTrusted=\(AXIsProcessTrusted())")
        Task { @MainActor in
            let text = await TextCapture.capture()
            ThornLog.info("captured: \(text.map { String($0.prefix(60)) } ?? "<nil>")")
            guard let text, isParseable(text) else {
                NSSound.beep()
                return
            }
            panelController.show(sentence: text)
        }
    }

    /// Accept English-ish selections of sane length; reject empty or huge blobs.
    private func isParseable(_ text: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 1200 else { return false }
        return trimmed.rangeOfCharacter(from: CharacterSet.letters) != nil
    }

    @objc private func openSettings() {
        if settingsWindow == nil {
            let hosting = NSHostingController(rootView: SettingsView())
            let window = NSWindow(contentViewController: hosting)
            window.styleMask = [.titled, .closable]
            window.title = "Thorn 设置"
            window.isReleasedWhenClosed = false
            window.setContentSize(NSSize(width: 440, height: 500))
            window.center()
            settingsWindow = window
        }
        settingsWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
