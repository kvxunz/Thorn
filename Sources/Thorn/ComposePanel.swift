import AppKit
import SwiftUI

/// The ⌥X input box: a Spotlight-shaped panel that takes typed Chinese.
///
/// Unlike the result panel this one must own the keyboard, which is the whole
/// reason it is a separate window rather than another `PanelState` case. A
/// borderless `NSWindow` returns false from `canBecomeKey`, and an `.accessory`
/// app is not frontmost, so both have to be arranged explicitly.
@MainActor
final class ComposePanelController: NSObject, NSWindowDelegate {
    private var panel: ComposeWindow?
    private var keyMonitor: Any?
    /// Set while the panel is up so a second ⌥X focuses it instead of
    /// discarding a half-typed sentence.
    private var isShowing: Bool { panel != nil }

    /// Called with the typed Chinese when the user commits with Return.
    var onSubmit: ((String) -> Void)?

    func toggle() {
        if isShowing {
            hide()
        } else {
            show()
        }
    }

    func show() {
        guard !isShowing else {
            panel?.makeKeyAndOrderFront(nil)
            return
        }
        let view = ComposeView(
            onSubmit: { [weak self] text in
                let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else {
                    NSSound.beep()
                    return
                }
                self?.hide()
                self?.onSubmit?(trimmed)
            },
            onCancel: { [weak self] in self?.hide() }
        )
        let hosting = NSHostingController(rootView: view)
        hosting.sizingOptions = [.intrinsicContentSize]

        let panel = ComposeWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 64),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.delegate = self
        panel.contentViewController = hosting
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

        // A hosting controller installed as `contentViewController` re-sizes
        // the window from its own fitting size, which is zero until the first
        // layout pass -- a 0x0 window is on screen and invisible. Lay out
        // first, and keep the designed size when the measurement is nonsense.
        panel.layoutIfNeeded()
        let fitted = hosting.view.fittingSize
        panel.setContentSize(
            fitted.width > 100 && fitted.height > 20
                ? fitted
                : CGSize(width: 520, height: 64)
        )
        position(panel)
        // Typing needs the keyboard, and a menubar-only app has to ask for it.
        // The reading path deliberately does *not* do this -- there the user's
        // selection in another app must survive -- so the two panels differ
        // exactly here.
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        ThornLog.info(
            "compose panel shown, frame=\(panel.frame), visible=\(panel.isVisible),"
                + " key=\(panel.isKeyWindow), active=\(NSApp.isActive)"
        )

        // Esc must work even if focus has wandered out of the text field.
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard event.keyCode == 53 else { return event } // Esc
            Task { @MainActor in self?.hide() }
            return nil
        }
    }

    func hide() {
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        keyMonitor = nil
        panel?.orderOut(nil)
        panel = nil
    }

    /// Upper third of the screen holding the pointer: eye level for something
    /// being typed. The result panel then hangs from this same line, so the
    /// tree unfolds where the sentence was typed.
    private func position(_ panel: NSPanel) {
        let size = panel.frame.size
        let visible = ComposeAnchor.visibleFrame()
        let frame = CGRect(origin: ComposeAnchor.origin(for: size, in: visible), size: size)
        panel.setFrame(frame, display: true)
        ComposeAnchor.lastBox = (frame: frame, visible: visible)
    }
}

/// Where a result panel opens. Set by whoever asked for it, because the
/// answer is "wherever the user is already looking", and only the entry
/// point knows where that is.
enum PanelAnchor {
    case mouse
    case composeBox
}

/// Where the ⌥X box sits — and therefore where its result must appear.
///
/// The reading paths open the result next to the mouse, because that is where
/// the user just selected something. Compose has no such gesture: the pointer
/// can be anywhere while the eyes are on the box. Both windows read this so
/// the tree replaces the box instead of jumping across the screen.
enum ComposeAnchor {
    static let designedSize = CGSize(width: 520, height: 64)

    /// The box, and the screen it was placed on, as of the last time it was
    /// shown — the pointer may have moved to another display since.
    static var lastBox: (frame: CGRect, visible: CGRect)?

    /// ⌥X can be pressed from anywhere; the box lands where the eyes are.
    static func visibleFrame() -> CGRect {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) }
            ?? NSScreen.main
        return screen?.visibleFrame ?? .zero
    }

    static func origin(for size: CGSize, in visible: CGRect) -> CGPoint {
        CGPoint(x: visible.midX - size.width / 2, y: visible.minY + visible.height * 0.62)
    }

    /// The line the result panel's top edge sits on. Falls back to the
    /// designed geometry if a result somehow arrives before a box was shown.
    static func topEdge() -> (y: CGFloat, visible: CGRect) {
        if let lastBox { return (lastBox.frame.maxY, lastBox.visible) }
        let visible = visibleFrame()
        return (origin(for: designedSize, in: visible).y + designedSize.height, visible)
    }
}

/// A borderless window says no to `canBecomeKey` by default, which would make
/// the text field un-typeable.
final class ComposeWindow: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

// MARK: - View

private struct ComposeView: View {
    let onSubmit: (String) -> Void
    let onCancel: () -> Void
    @State private var text = ""

    var body: some View {
        HStack(spacing: ThornSpace.md) {
            Text("中")
                .font(ThornType.ui(ThornType.reading, .medium))
                .foregroundStyle(.tertiary)
                .frame(width: 22)

            ChineseInputField(
                text: $text,
                placeholder: "写一句中文，回车换成英文",
                onSubmit: { onSubmit(text) },
                onCancel: onCancel
            )
            .frame(height: 26)

            Image(systemName: "return")
                .font(ThornType.ui(ThornType.small))
                .foregroundStyle(text.isEmpty ? Color.secondary.opacity(0.25) : .secondary)
                .animation(ThornMotion.hover, value: text.isEmpty)
        }
        .padding(.horizontal, ThornSpace.lg)
        .padding(.vertical, ThornSpace.md)
        .frame(width: 520)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: ThornRadius.panel))
        .clipShape(RoundedRectangle(cornerRadius: ThornRadius.panel))
        .overlay(
            RoundedRectangle(cornerRadius: ThornRadius.panel)
                .strokeBorder(
                    LinearGradient(
                        colors: [Color.white.opacity(0.22), Color.white.opacity(0.04)],
                        startPoint: .top,
                        endPoint: .bottom
                    ),
                    lineWidth: 0.5
                )
                .padding(0.5)
        )
        .overlay(
            RoundedRectangle(cornerRadius: ThornRadius.panel)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5)
        )
    }
}

/// An `NSTextField` rather than SwiftUI's `TextField`, for one reason: the
/// Return that confirms an IME candidate and the Return that commits the
/// sentence are the same keystroke, and this field is going to be typed into
/// in Chinese every single time. `hasMarkedText()` is the only way to tell
/// them apart, and SwiftUI's `onSubmit` gives no access to it.
private struct ChineseInputField: NSViewRepresentable {
    @Binding var text: String
    let placeholder: String
    let onSubmit: () -> Void
    let onCancel: () -> Void

    func makeNSView(context: Context) -> NSTextField {
        let field = NSTextField()
        field.delegate = context.coordinator
        field.isBordered = false
        field.drawsBackground = false
        field.focusRingType = .none
        field.font = .systemFont(ofSize: ThornType.reading)
        field.placeholderString = placeholder
        field.lineBreakMode = .byTruncatingTail
        field.cell?.isScrollable = true
        field.cell?.wraps = false
        DispatchQueue.main.async { field.window?.makeFirstResponder(field) }
        return field
    }

    func updateNSView(_ field: NSTextField, context: Context) {
        context.coordinator.parent = self
        if field.stringValue != text { field.stringValue = text }
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: ChineseInputField

        init(_ parent: ChineseInputField) { self.parent = parent }

        func controlTextDidChange(_ notification: Notification) {
            guard let field = notification.object as? NSTextField else { return }
            parent.text = field.stringValue
        }

        func control(_ control: NSControl,
                     textView: NSTextView,
                     doCommandBy selector: Selector) -> Bool {
            switch selector {
            case #selector(NSResponder.insertNewline(_:)):
                // Mid-composition the pinyin buffer owns this Return: it is
                // choosing a candidate, not finishing a sentence. Most input
                // methods swallow it before it reaches here, but the ones that
                // do not would otherwise submit "ni hao" as a sentence.
                if textView.hasMarkedText() { return false }
                parent.text = control.stringValue
                parent.onSubmit()
                return true
            case #selector(NSResponder.cancelOperation(_:)):
                if textView.hasMarkedText() { return false }
                parent.onCancel()
                return true
            default:
                return false
            }
        }
    }
}
