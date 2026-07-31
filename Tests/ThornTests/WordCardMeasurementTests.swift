import AppKit
import SwiftUI
import XCTest
@testable import Thorn

/// Probe the real AppKit-reported sizes of the word card. The panel sizing
/// path (ResultPanelController.fitToContent) trusts these numbers; when the
/// card shows slack the bug is here, not in the SwiftUI code you can see.
@MainActor
final class WordCardMeasurementTests: XCTestCase {

    private func interfering(meaning: String) -> PhonicsResult {
        func syllable(_ pairs: [(String, String)], _ stress: PhonicsStress) -> PhonicsSyllable {
            PhonicsSyllable(
                chunks: pairs.map { PhonicsChunk(grapheme: $0.0, ipa: $0.1) },
                stress: stress
            )
        }
        return PhonicsResult(
            word: "interfering",
            ipa: "ˌɪntərˈfɪrɪŋ",
            syllables: [
                syllable([("i", "ɪ"), ("n", "n")], .secondary),
                syllable([("t", "t"), ("er", "ər")], .none),
                syllable([("f", "f"), ("e", "ɪ")], .primary),
                syllable([("r", "r"), ("i", "ɪ"), ("ng", "ŋ")], .none),
            ],
            approximate: false,
            meaning: meaning
        )
    }

    /// Regression for the phantom-height bug: with default sizingOptions the
    /// hosting controller resized the window itself using the ideal height
    /// at the panel's *narrow* initial width (blocks wrapped to two rows),
    /// and that extra height survived forever. With sizingOptions = [] and
    /// manual fitting, the window must end up exactly content-sized through
    /// the whole loading -> partial -> final flow.
    func testInstalledPanelHugsContent() {
        let state = PanelState()
        state.wordMode = true
        state.status = .loading

        let hosting = NSHostingController(rootView: ResultView(state: state))
        hosting.sizingOptions = [.intrinsicContentSize] // same as presentPanel
        let panel = NSPanel(
            contentRect: .zero,
            styleMask: [.borderless, .nonactivatingPanel, .resizable],
            backing: .buffered,
            defer: false
        )
        panel.contentView = hosting.view
        panel.setFrame(CGRect(x: 0, y: 0, width: 280, height: 56), display: true)

        func fitAndCheck(_ label: String) {
            hosting.view.layoutSubtreeIfNeeded()
            let fitting = hosting.view.fittingSize
            panel.setFrame(CGRect(origin: .zero, size: fitting), display: true)
            hosting.view.layoutSubtreeIfNeeded()
            XCTAssertEqual(panel.frame.size.width, fitting.width, accuracy: 1.0, label)
            XCTAssertEqual(panel.frame.size.height, fitting.height, accuracy: 1.0, label)
            // The re-measure at the fitted width must not report extra rows.
            let tight = hosting.sizeThatFits(in: CGSize(width: fitting.width, height: 1))
            XCTAssertEqual(tight.height, fitting.height, accuracy: 1.0, label)
        }

        state.status = .word(interfering(meaning: ""))
        fitAndCheck("partial")
        state.status = .word(interfering(meaning: "干涉；干预；打扰"))
        fitAndCheck("final")

        // Sanity: a one-row word card is compact, not sentence-panel sized.
        let final = panel.frame.size
        XCTAssertLessThan(final.height, 170, "word card must stay compact")
        XCTAssertLessThan(final.width, 400, "word card must hug its content")
        panel.orderOut(nil)
    }
}
