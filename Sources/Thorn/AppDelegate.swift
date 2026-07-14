import AppKit
import SwiftUI

/// Diagnostics logger, off by default — captured text would otherwise sit in
/// world-readable /tmp. Enable: defaults write com.xvz.thorn debugLog -bool true
enum ThornLog {
    private static let enabled = UserDefaults.standard.bool(forKey: "debugLog")

    static func info(_ message: String) {
        guard enabled else { return }
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

    private var capturing = false

    private func handleHotkey() {
        // Concurrent captures fight over the pasteboard save/restore dance.
        guard !capturing else { return }
        capturing = true
        ThornLog.info("hotkey fired, axTrusted=\(AXIsProcessTrusted())")
        Task { @MainActor in
            defer { capturing = false }
            let text = await TextCapture.capture()
            ThornLog.info("captured: \(text.map { String($0.prefix(60)) } ?? "<nil>")")
            guard let text else {
                NSSound.beep()
                return
            }
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard trimmed.rangeOfCharacter(from: CharacterSet.letters) != nil else {
                NSSound.beep()
                return
            }
            guard trimmed.count <= 1200 else {
                panelController.showError("选中内容过长（超过 1200 字符）。请划选一句或一小段。")
                return
            }
            panelController.show(sentence: trimmed)
        }
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
