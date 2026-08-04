import AppKit
import SwiftUI
import Carbon.HIToolbox

/// Diagnostics logger, off by default — captured text would otherwise sit in
/// world-readable /tmp. Enable: defaults write com.xvz.thorn debugLog -bool true
enum ThornLog {
    private static let enabled = UserDefaults.standard.bool(forKey: "debugLog")
    private static let writeLock = NSLock()
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
        writeLock.lock()
        defer { writeLock.unlock() }
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
    private let composeController = ComposePanelController()
    private var settingsWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        ThornLog.removeLegacyTemporaryLog()
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            // Swap the glyph to retaste the icon: ⊢ (formal-grammar "derives"),
            // ∇, λ, þ (the Old English letter the app is named after).
            button.image = Self.glyphIcon("∂")
        }

        let menu = NSMenu()
        // Verb left, shortcut right-aligned in its own column. The old hints
        // were sentences ("选中英文后按 ⌥A 拆句（单词则拆拼读）") and NSMenu
        // sizes itself to its widest item, so one of them set the width of
        // the whole menu.
        for (title, key) in [("拆解选中英文", "a"), ("截图取词拆解", "s"),
                             ("写中文换英文", "x"), ("重现上次结果", "z")] {
            let item = NSMenuItem(title: title, action: nil, keyEquivalent: key)
            item.keyEquivalentModifierMask = .option
            menu.addItem(item) // nil action -> auto-disabled, i.e. a hint
        }
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
        composeController.onSubmit = { [weak self] chinese in
            self?.panelController.show(chinese: chinese, anchor: .composeBox)
        }
        let composeRegistered = hotkey.register(
            id: 4, keyCode: UInt32(kVK_ANSI_X), modifiers: UInt32(optionKey)
        ) { [weak self] in
            // Toggle, not show: ⌥X is also how you dismiss a box you opened by
            // accident, without reaching for Esc.
            ThornLog.info("compose hotkey fired")
            self?.composeController.toggle()
        }
        ThornLog.info("compose hotkey registered=\(composeRegistered)")
        let hotkeyFailures = hotkey.failures
        if !hotkeyFailures.isEmpty {
            panelController.showError(
                hotkeyFailures.map(\.message).joined(separator: "\n")
            )
        }

        // Keep the first real sentence off the cold-start path. This only
        // starts the deterministic structure engine; HY-MT2 stays idle until
        // a sentence has already been split and shown.
        Task.detached(priority: .utility) {
            await Sidecar.shared.warmUp()
        }
    }

    /// A single glyph as the menubar icon. SF Symbols carry fine detail that
    /// dies at the menubar's ~16pt: `text.line.magnify`'s magnifier ring
    /// degraded into a fourth horizontal line, so the icon read as a smudge
    /// of stripes. A glyph has no detail to lose.
    private static func glyphIcon(_ glyph: String) -> NSImage {
        let font = NSFont(name: "NewYork-Medium", size: 16)
            ?? .systemFont(ofSize: 16, weight: .medium)
        let text = NSAttributedString(string: glyph, attributes: [
            .font: font,
            .foregroundColor: NSColor.black,
        ])
        let bounds = text.size()
        let image = NSImage(size: NSSize(width: ceil(bounds.width) + 2,
                                         height: ceil(bounds.height)))
        image.lockFocus()
        text.draw(at: NSPoint(x: 1, y: 0))
        image.unlockFocus()
        // Template: AppKit recolours it for light/dark menubars *and* for the
        // highlighted state. A baked-in colour inverts wrong on selection.
        image.isTemplate = true
        image.accessibilityDescription = "Thorn"
        return image
    }

    func applicationWillTerminate(_ notification: Notification) {
        Sidecar.terminateSynchronously()
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
        guard sentence.unicodeScalars.contains(where: { CharacterSet.letters.contains($0) }) else {
            routeChineseOrError("内容主要是中文注释，没有找到可拆解的英文句子。", from: trimmed)
            return
        }
        // Same measure the compose path applies to a model reply: whether an
        // English parser is about to be handed English.
        guard ComposeService.looksEnglish(sentence) else {
            routeChineseOrError("Thorn 只拆解英文文本，当前内容主要是非英文字符。", from: trimmed)
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

    /// A Chinese selection is not a mistake — it is exactly what ⌥X asks you
    /// to type, only already on screen. Send it down the compose path instead
    /// of an error the user can do nothing with. Every other non-English
    /// script still errors: Thorn has nothing to offer them.
    ///
    /// The raw selection goes to the model, not the normalized text: the
    /// normalizer rewrites CJK punctuation into ASCII for the English parser's
    /// benefit, which is the wrong thing to hand a Chinese sentence.
    private func routeChineseOrError(_ message: String, from raw: String) {
        guard ComposeService.looksChinese(raw) else {
            panelController.showError(message)
            return
        }
        guard raw.count <= ComposeService.inputLimit else {
            panelController.showError(
                "中文内容过长（超过 \(ComposeService.inputLimit) 字）。请只选取一句。"
            )
            return
        }
        ThornLog.info("chinese capture, compose path")
        panelController.show(chinese: raw, anchor: .mouse)
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
