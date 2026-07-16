import AppKit
import SwiftUI
import Combine

/// Borderless non-activating panel that shows the parse result near the mouse.
/// Closes on Esc or click outside. Resizable from its edges; once the user
/// resizes manually, auto-fitting backs off.
@MainActor
final class ResultPanelController: NSObject, NSWindowDelegate {
    private var panel: NSPanel?
    private var hosting: NSHostingController<ResultView>?
    private var clickMonitor: Any?
    private var keyMonitor: Any?
    private var globalKeyMonitor: Any?
    private var statusObserver: AnyCancellable?
    private var expandObserver: AnyCancellable?
    private var userResized = false
    let state = PanelState()

    func show(sentence: String) {
        // Tear down the panel UI only. `start` cancels any previous parse and
        // begins a new one — do not cancel twice (that left empty partials).
        hidePanel()
        userResized = false
        state.start(sentence: sentence)
        presentPanel()
    }

    nonisolated func windowDidEndLiveResize(_ notification: Notification) {
        Task { @MainActor in self.userResized = true }
    }

    /// Bring back the last result after the panel was dismissed (⌥Z).
    func recall() {
        guard !state.sentence.isEmpty else {
            NSSound.beep()
            return
        }
        if let panel {
            panel.orderFrontRegardless()
            return
        }
        if case .result = state.status {
            presentPanel() // show as-is, no re-parse
        } else {
            // was closed mid-parse or errored: run again
            state.start(sentence: state.sentence)
            presentPanel()
        }
    }

    /// The content's true minimum height at a given width: the window must
    /// never go below it, or SwiftUI overflows and the window clips corners.
    private func minContentHeight(atWidth width: CGFloat) -> CGFloat {
        guard let hosting else { return 240 }
        return max(240, hosting.sizeThatFits(in: CGSize(width: width, height: 1)).height)
    }

    nonisolated func windowWillResize(_ sender: NSWindow, to frameSize: NSSize) -> NSSize {
        MainActor.assumeIsolated {
            let minH = minContentHeight(atWidth: max(400, frameSize.width))
            return NSSize(width: max(400, frameSize.width), height: max(minH, frameSize.height))
        }
    }

    /// Grip-driven resize: grow right/down, keep the top-left corner fixed.
    private func resizeBy(_ delta: CGSize) {
        guard let panel else { return }
        userResized = true
        var frame = panel.frame
        let newWidth = max(400, frame.width + delta.width)
        let newHeight = max(minContentHeight(atWidth: newWidth), frame.height + delta.height)
        frame.origin.y -= (newHeight - frame.height)
        frame.size = CGSize(width: newWidth, height: newHeight)
        panel.setFrame(frame, display: true)
    }

    /// Show a standalone message (e.g. selection too long) without parsing.
    func showError(_ message: String) {
        hidePanel()
        state.presentError(message)
        presentPanel()
    }

    private func presentPanel() {
        let controller = NSHostingController(rootView: ResultView(state: state) { [weak self] delta in
            self?.resizeBy(delta)
        })
        hosting = controller

        let panel = NSPanel(
            contentRect: .zero,
            styleMask: [.borderless, .nonactivatingPanel, .resizable],
            backing: .buffered,
            defer: false
        )
        panel.delegate = self
        panel.contentView = controller.view
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        self.panel = panel

        positionNearMouse(panel)
        panel.orderFrontRegardless()
        ThornLog.info("panel shown, frame=\(panel.frame), visible=\(panel.isVisible)")
        installMonitors()

        // Re-fit the panel whenever content changes (loading -> result/error)
        // or the user expands/collapses a clause.
        statusObserver = state.$status
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async { self?.fitToContent() }
            }
        expandObserver = state.$expanded
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async { self?.fitToContent() }
            }
    }

    /// Content changed while the user holds a manual size: keep their size,
    /// but never smaller than the content's new minimum (or it overflows).
    private func enforceMinimum() {
        guard let panel else { return }
        let minH = minContentHeight(atWidth: panel.frame.width)
        guard panel.frame.height < minH else { return }
        var frame = panel.frame
        frame.origin.y = frame.maxY - minH
        frame.size.height = minH
        if let visible = panel.screen?.visibleFrame {
            frame.origin.y = max(visible.minY + 8, frame.origin.y)
        }
        panel.setFrame(frame, display: true)
    }

    /// Resize to the content's real size: keep top edge fixed, clamp to screen.
    /// Backs off once the user has resized the panel manually.
    private func fitToContent() {
        guard !userResized else { return enforceMinimum() }
        guard let panel, let content = panel.contentView else { return }
        content.layoutSubtreeIfNeeded()
        let size = content.fittingSize
        ThornLog.info("fitToContent: fitting=\(size), current=\(panel.frame.size)")
        guard size.width > 10, size.height > 10, size != panel.frame.size else { return }
        var frame = panel.frame
        frame.origin.y = frame.maxY - size.height
        frame.size = size
        if let visible = panel.screen?.visibleFrame {
            frame.size.height = min(frame.height, visible.height - 16)
            frame.origin.x = max(visible.minX + 8, min(frame.origin.x, visible.maxX - frame.width - 8))
            frame.origin.y = max(visible.minY + 8, min(frame.origin.y, visible.maxY - frame.height - 8))
        }
        panel.setFrame(frame, display: true, animate: false)
    }

    private func positionNearMouse(_ panel: NSPanel) {
        panel.layoutIfNeeded()
        var size = panel.contentView?.fittingSize ?? .zero
        if size.width < 50 || size.height < 30 {
            size = CGSize(width: 460, height: 64) // loading placeholder; resize() corrects it
        }
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) } ?? NSScreen.main
        let visible = screen?.visibleFrame ?? .zero

        var origin = CGPoint(x: mouse.x - size.width / 2, y: mouse.y - size.height - 12)
        if origin.x + size.width > visible.maxX { origin.x = visible.maxX - size.width - 8 }
        if origin.x < visible.minX { origin.x = visible.minX + 8 }
        if origin.y < visible.minY { origin.y = mouse.y + 12 }
        if origin.y + size.height > visible.maxY { origin.y = visible.maxY - size.height - 8 }

        panel.setFrame(CGRect(origin: origin, size: size), display: true)
    }

    private func installMonitors() {
        // Click *outside* the panel hides it. Clicks on the panel must not —
        // otherwise expanding a clause or dragging cancels the in-flight
        // HY-MT2 translation and freezes the UI on an empty-translation partial.
        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor in
                guard let self, !self.state.pinned else { return }
                if self.clickIsInsidePanel() { return }
                self.hidePanel()
            }
        }
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if event.keyCode == 53 { // Esc
                Task { @MainActor in self?.hidePanel() }
                return nil
            }
            return event
        }
        // The panel is non-activating, so key events go to the frontmost app,
        // not to us: without a global monitor Esc never reaches Thorn at all
        // (and a pinned panel would have no keyboard way to close).
        globalKeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if event.keyCode == 53 { // Esc
                Task { @MainActor in self?.hidePanel() }
            }
        }
    }

    private func clickIsInsidePanel() -> Bool {
        guard let panel else { return false }
        return panel.frame.contains(NSEvent.mouseLocation)
    }

    /// Hide the floating panel without cancelling an in-flight parse.
    /// Parse continues so ⌥Z can recall a finished result; a new ⌥A still
    /// cancels the previous run via `PanelState.start` → `run`.
    func hidePanel() {
        statusObserver = nil
        expandObserver = nil
        if let clickMonitor { NSEvent.removeMonitor(clickMonitor) }
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        if let globalKeyMonitor { NSEvent.removeMonitor(globalKeyMonitor) }
        clickMonitor = nil
        keyMonitor = nil
        globalKeyMonitor = nil
        panel?.orderOut(nil)
        panel = nil
    }

    /// Hide panel and cancel any in-flight parse (used on quit paths if needed).
    func close() {
        state.cancel()
        hidePanel()
    }
}
