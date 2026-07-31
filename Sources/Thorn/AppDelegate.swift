import AppKit
import SwiftUI
import Carbon.HIToolbox

/// Diagnostics logger, off by default — captured text would otherwise sit in
/// world-readable /tmp. Enable: defaults write com.xvz.thorn debugLog -bool true
enum ThornLog {
    private static let enabled = UserDefaults.standard.bool(forKey: "debugLog")
    private static let logURL: URL? = {
        guard let base = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else { return nil }
        let directory = base.appendingPathComponent("Thorn", isDirectory: true)
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            let url = directory.appendingPathComponent("diagnostics.log")
            if !FileManager.default.fileExists(atPath: url.path) {
                _ = FileManager.default.createFile(atPath: url.path, contents: nil)
            }
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o600],
                ofItemAtPath: url.path
            )
            return url
        } catch {
            return nil
        }
    }()

    static func info(_ message: String) {
        guard enabled, let url = logURL else { return }
        let line = "\(Date()) \(message)\n"
        if let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(Data(line.utf8))
            try? handle.close()
        } else {
            try? line.write(to: url, atomically: true, encoding: .utf8)
        }
    }

    static func removeLegacyTemporaryLog() {
        try? FileManager.default.removeItem(
            at: URL(fileURLWithPath: "/tmp/thorn.log")
        )
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var hotkey: HotkeyManager!
    private let panelController = ResultPanelController()
    private var settingsWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        ThornLog.removeLegacyTemporaryLog()
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "text.line.magnify", accessibilityDescription: "Thorn")
        }

        let menu = NSMenu()
        menu.addItem(withTitle: "选中英文后按 ⌥A 拆句（单词则拆拼读）", action: nil, keyEquivalent: "")
        menu.addItem(withTitle: "框选图片文字后按 ⌥S 识别并拆句", action: nil, keyEquivalent: "")
        menu.addItem(withTitle: "⌥Z 重现上次结果", action: nil, keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "设置…", action: #selector(openSettings), keyEquivalent: ",")
        menu.addItem(.separator())
        menu.addItem(withTitle: "退出 Thorn", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        statusItem.menu = menu

        let trusted = TextCapture.ensureAccessibilityPermission()
        ThornLog.info("launched, axTrusted=\(trusted)")

        hotkey = HotkeyManager()
        hotkey.register(id: 1, keyCode: UInt32(kVK_ANSI_A), modifiers: UInt32(optionKey)) { [weak self] in
            self?.handleTextHotkey()
        }
        hotkey.register(id: 2, keyCode: UInt32(kVK_ANSI_Z), modifiers: UInt32(optionKey)) { [weak self] in
            self?.panelController.recall()
        }
        hotkey.register(id: 3, keyCode: UInt32(kVK_ANSI_S), modifiers: UInt32(optionKey)) { [weak self] in
            self?.handleOCRHotkey()
        }

        // Warm the structure sidecar so the first parse isn't a cold start.
        Task.detached { _ = try? await Sidecar.shared.structure(for: "Warm up.") }
    }

    func applicationWillTerminate(_ notification: Notification) {
        let sidecar = Sidecar.shared
        Task.detached { await sidecar.terminate() }
    }

    private var capturing = false

    private func handleTextHotkey() {
        // Concurrent captures fight over the pasteboard save/restore dance.
        guard !capturing else { return }
        capturing = true
        ThornLog.info("hotkey fired, axTrusted=\(AXIsProcessTrusted())")
        Task { @MainActor in
            defer { capturing = false }
            let text = await TextCapture.capture()
            ThornLog.info("capture result: \(text.map { "\($0.count) characters" } ?? "none")")
            guard let text else {
                NSSound.beep()
                return
            }
            parseCapturedText(text)
        }
    }

    private func handleOCRHotkey() {
        guard !capturing else { return }
        capturing = true
        ThornLog.info("OCR hotkey fired")
        Task { @MainActor in
            defer { capturing = false }
            do {
                guard let text = try await ScreenshotOCRService.captureText() else {
                    return // Escape cancels without an error panel.
                }
                ThornLog.info("OCR captured \(text.count) characters")
                parseCapturedText(text)
            } catch is CancellationError {
                return
            } catch {
                panelController.showError(error.localizedDescription)
            }
        }
    }

    private func parseCapturedText(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.unicodeScalars.contains(where: { CharacterSet.letters.contains($0) }) else {
            NSSound.beep()
            return
        }
        // Bilingual study material and OCR both pass through the same single
        // cleanup boundary before the sidecar sees the sentence.
        let sentence = ParseService.extractEnglish(ParseService.normalizedInput(trimmed))
        let letters = sentence.unicodeScalars.filter { CharacterSet.letters.contains($0) }
        guard !letters.isEmpty else {
            panelController.showError("内容主要是中文注释，没有找到可拆解的英文句子。")
            return
        }
        let asciiRatio = Double(letters.filter(\.isASCII).count) / Double(letters.count)
        guard asciiRatio > 0.5 else {
            panelController.showError("Thorn 只拆解英文文本，当前内容主要是非英文字符。")
            return
        }
        guard sentence.count <= 1200 else {
            panelController.showError("内容过长（超过 1200 字符）。请只选取一句或一小段。")
            return
        }
        // A single word has no syntax to teach — decompose its spelling into
        // phonics blocks instead of sending it to the sentence parser.
        if let word = ParseService.singleWord(in: sentence) {
            ThornLog.info("single word capture, phonics path")
            panelController.show(word: word)
            return
        }
        panelController.show(sentence: sentence)
    }

    @objc private func openSettings() {
        if settingsWindow == nil {
            let hosting = NSHostingController(rootView: SettingsView())
            let window = NSWindow(contentViewController: hosting)
            window.styleMask = [.titled, .closable]
            window.title = "Thorn 设置"
            window.isReleasedWhenClosed = false
            window.setContentSize(NSSize(width: 440, height: 300))
            window.center()
            settingsWindow = window
        }
        settingsWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}
