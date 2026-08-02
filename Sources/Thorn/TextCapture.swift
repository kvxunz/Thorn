import AppKit
import ApplicationServices

/// Grabs the selected text from whatever app is frontmost.
/// Strategy: Accessibility API first; fall back to simulated ⌘C with pasteboard restore.
enum TextCapture {
    /// Limits for the fallback AX walk. The focused window can expose an
    /// unexpectedly large or cyclic tree (especially in web views), so depth
    /// and per-node child caps alone are not enough to bound the work done on
    /// the global executor.
    struct AccessibilityTraversalPolicy {
        static let maxDepth = 12
        static let maxChildrenPerNode = 40
        static let maxNodes = 500
        static let timeBudgetNanoseconds: UInt64 = 300_000_000

        static func canVisitNode(
            depth: Int,
            visitedNodes: Int,
            now: UInt64,
            deadline: UInt64
        ) -> Bool {
            depth <= maxDepth && visitedNodes < maxNodes && now < deadline
        }

        static func childLimit(for count: Int) -> Int {
            min(max(0, count), maxChildrenPerNode)
        }
    }

    /// Pure ownership check used immediately before restoring the clipboard.
    /// A user copy increments `changeCount`; when that happens, the synthetic
    /// generation is no longer ours and the user's clipboard must be left
    /// untouched.
    struct ClipboardCapturePolicy {
        static func shouldRestore(
            originalChangeCount: Int,
            capturedChangeCount: Int,
            currentChangeCount: Int
        ) -> Bool {
            capturedChangeCount != originalChangeCount
                && currentChangeCount == capturedChangeCount
        }
    }

    private struct AccessibilityTraversalBudget {
        private(set) var visitedNodes = 0
        let deadline: UInt64

        init(now: UInt64 = DispatchTime.now().uptimeNanoseconds) {
            deadline = now &+ AccessibilityTraversalPolicy.timeBudgetNanoseconds
        }

        mutating func reserveNode(
            at depth: Int,
            now: UInt64 = DispatchTime.now().uptimeNanoseconds
        ) -> Bool {
            guard AccessibilityTraversalPolicy.canVisitNode(
                depth: depth,
                visitedNodes: visitedNodes,
                now: now,
                deadline: deadline
            ) else { return false }
            visitedNodes += 1
            return true
        }
    }

    static func ensureAccessibilityPermission() -> Bool {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    /// Nonisolated async: runs on the global executor (SE-0338), so the
    /// synchronous AX tree walk below never blocks the main thread.
    static func capture() async -> String? {
        if let text = viaAccessibility(), !text.isEmpty {
            ThornLog.info("capture path: AX focused")
            return text
        }
        if let text = viaAccessibilityDeep(), !text.isEmpty {
            ThornLog.info("capture path: AX deep walk")
            return text
        }
        ThornLog.info("capture path: AX failed, trying clipboard")
        return await viaClipboard()
    }

    private static func viaAccessibility() -> String? {
        let system = AXUIElementCreateSystemWide()
        var focused: CFTypeRef?
        guard AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
              let element = focused, CFGetTypeID(element) == AXUIElementGetTypeID() else { return nil }
        // Safe: type verified above; unchecked cast avoids conditional-downcast warning for CF types.
        let axElement = unsafeDowncast(element as AnyObject, to: AXUIElement.self)

        var selected: CFTypeRef?
        guard AXUIElementCopyAttributeValue(axElement, kAXSelectedTextAttribute as CFString, &selected) == .success,
              let text = selected as? String else { return nil }
        return text
    }

    /// Web views (WKWebView/Tauri/Electron) hang the selection on an AXWebArea
    /// descendant, not on the system-wide focused element. Walk the focused
    /// window's AX tree looking for a non-empty AXSelectedText.
    private static func viaAccessibilityDeep() -> String? {
        guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        var window: CFTypeRef?
        guard AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &window) == .success,
              let win = window, CFGetTypeID(win) == AXUIElementGetTypeID() else { return nil }
        let windowElement = unsafeDowncast(win as AnyObject, to: AXUIElement.self)
        var budget = AccessibilityTraversalBudget()
        return findSelectedText(in: windowElement, depth: 0, budget: &budget)
    }

    private static func findSelectedText(
        in element: AXUIElement,
        depth: Int,
        budget: inout AccessibilityTraversalBudget
    ) -> String? {
        guard budget.reserveNode(at: depth) else { return nil }
        var selected: CFTypeRef?
        if AXUIElementCopyAttributeValue(element, kAXSelectedTextAttribute as CFString, &selected) == .success,
           let text = selected as? String,
           !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return text
        }
        var children: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &children) == .success,
              let array = children as? [AnyObject] else { return nil }
        for child in array.prefix(AccessibilityTraversalPolicy.childLimit(for: array.count)) {
            guard CFGetTypeID(child) == AXUIElementGetTypeID() else { continue }
            let childElement = unsafeDowncast(child, to: AXUIElement.self)
            if let found = findSelectedText(in: childElement, depth: depth + 1, budget: &budget) {
                return found
            }
        }
        return nil
    }

    private static func viaClipboard() async -> String? {
        let pasteboard = NSPasteboard.general
        let savedItems = pasteboard.pasteboardItems?.map { item -> [NSPasteboard.PasteboardType: Data] in
            var copy: [NSPasteboard.PasteboardType: Data] = [:]
            for type in item.types {
                if let data = item.data(forType: type) { copy[type] = data }
            }
            return copy
        } ?? []
        let savedChangeCount = pasteboard.changeCount

        // The user is still holding ⌥ (and maybe A) from the hotkey; a synthetic ⌘C
        // posted now arrives as ⌘⌥C and most apps ignore it. Wait for release.
        await waitForModifiersUp()
        postCmdC()

        // Wait up to 1.5s for the frontmost app to write the pasteboard.
        var changed = false
        var syntheticChangeCount: Int?
        for _ in 0..<30 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if pasteboard.changeCount != savedChangeCount {
                changed = true
                syntheticChangeCount = pasteboard.changeCount
                break
            }
        }

        var text: String?
        if changed, syntheticChangeCount != nil {
            // Some apps (Readest/Tauri) clear-then-write: the first change is empty.
            // Give the real write a beat to land before reading.
            try? await Task.sleep(nanoseconds: 150_000_000)
            // Capture the generation after the app has had time to finish its
            // clear-then-write sequence. This is the generation Thorn owns for
            // the restore check below.
            syntheticChangeCount = pasteboard.changeCount
            text = pasteboard.string(forType: .string)
        }

        // Restore the user's original clipboard.
        if let capturedChangeCount = syntheticChangeCount,
           ClipboardCapturePolicy.shouldRestore(
               originalChangeCount: savedChangeCount,
               capturedChangeCount: capturedChangeCount,
               currentChangeCount: pasteboard.changeCount
           ) {
            pasteboard.clearContents()
            for saved in savedItems {
                let item = NSPasteboardItem()
                for (type, data) in saved { item.setData(data, forType: type) }
                pasteboard.writeObjects([item])
            }
        } else if changed {
            ThornLog.info("clipboard changed after capture; leaving current contents intact")
        }
        return (text?.isEmpty == false) ? text : nil
    }

    private static func waitForModifiersUp() async {
        for _ in 0..<40 { // up to 1s
            let flags = CGEventSource.flagsState(.hidSystemState)
            if !flags.contains(.maskAlternate), !flags.contains(.maskCommand),
               !flags.contains(.maskShift), !flags.contains(.maskControl) {
                return
            }
            try? await Task.sleep(nanoseconds: 25_000_000)
        }
    }

    private static func postCmdC() {
        let source = CGEventSource(stateID: .combinedSessionState)
        let cmdKey: CGKeyCode = 0x37 // kVK_Command
        let cKey: CGKeyCode = 0x08   // kVK_ANSI_C

        // Full simulation (real Cmd keydown, not just flags): web-view apps
        // like Tauri/Electron ignore a bare flagged C keypress.
        let events: [(CGKeyCode, Bool, CGEventFlags)] = [
            (cmdKey, true, .maskCommand),
            (cKey, true, .maskCommand),
            (cKey, false, .maskCommand),
            (cmdKey, false, []),
        ]
        for (key, down, flags) in events {
            guard let event = CGEvent(keyboardEventSource: source, virtualKey: key, keyDown: down) else { continue }
            event.flags = flags
            event.post(tap: .cghidEventTap)
            usleep(8_000)
        }
    }
}
