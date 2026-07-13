import AppKit
import SwiftUI
import Combine

/// Borderless non-activating panel that shows the parse result near the mouse.
/// Closes on Esc or click outside.
@MainActor
final class ResultPanelController {
    private var panel: NSPanel?
    private var clickMonitor: Any?
    private var keyMonitor: Any?
    private var statusObserver: AnyCancellable?
    let state = PanelState()

    func show(sentence: String) {
        close()
        state.start(sentence: sentence)

        let hosting = NSHostingView(rootView: ResultView(state: state))

        let panel = NSPanel(
            contentRect: .zero,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.contentView = hosting
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        self.panel = panel

        positionNearMouse(panel)
        panel.orderFrontRegardless()
        ThornLog.info("panel shown, frame=\(panel.frame), visible=\(panel.isVisible)")
        installMonitors()

        // Re-fit the panel whenever content changes (loading -> result/error).
        statusObserver = state.$status
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async { self?.fitToContent() }
            }
    }

    /// Resize to the content's real size: keep top edge fixed, clamp to screen.
    private func fitToContent() {
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

        var origin = CGPoint(x: mouse.x + 12, y: mouse.y - size.height - 12)
        if origin.x + size.width > visible.maxX { origin.x = visible.maxX - size.width - 8 }
        if origin.x < visible.minX { origin.x = visible.minX + 8 }
        if origin.y < visible.minY { origin.y = mouse.y + 12 }
        if origin.y + size.height > visible.maxY { origin.y = visible.maxY - size.height - 8 }

        panel.setFrame(CGRect(origin: origin, size: size), display: true)
    }

    private func installMonitors() {
        clickMonitor = NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown]) { [weak self] _ in
            Task { @MainActor in self?.close() }
        }
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if event.keyCode == 53 { // Esc
                Task { @MainActor in self?.close() }
                return nil
            }
            return event
        }
    }

    func close() {
        state.cancel()
        statusObserver = nil
        if let clickMonitor { NSEvent.removeMonitor(clickMonitor) }
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        clickMonitor = nil
        keyMonitor = nil
        panel?.orderOut(nil)
        panel = nil
    }
}
