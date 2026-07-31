import XCTest
@testable import Thorn

@MainActor
final class ChunkRowTextTests: XCTestCase {
    private func clause(_ text: String) -> Chunk {
        Chunk(
            text: text,
            role: .clauseAdverbial,
            gloss: "",
            children: [Chunk(text: "when", role: .conjunction, gloss: "")]
        )
    }

    /// Expanded, the parent's words are already on screen twice — once in the
    /// header, once in the child rows beneath it. Repeating them a third time
    /// is what made deep trees wrap to several lines each.
    func testExpandedParentIsAbbreviated() {
        let long = clause("when you consider that Shakespeare was himself an actor")

        let text = ResultView.rowText(long, expanded: true)

        XCTAssertEqual(text, "when you consider that…")
    }

    /// Collapsed, the row holds the only copy of the phrase, so it stays whole.
    func testCollapsedParentKeepsWholePhrase() {
        let long = clause("when you consider that Shakespeare was himself an actor")

        let text = ResultView.rowText(long, expanded: false)

        XCTAssertEqual(text, "when you consider that Shakespeare was himself an actor")
    }

    /// Nothing is gained by truncating a phrase that already fits.
    func testShortParentIsNotTruncated() {
        XCTAssertEqual(ResultView.rowText(clause("when you consider"), expanded: true),
                       "when you consider")
    }

    /// Leaves have no children to defer to, so expansion cannot apply.
    func testLeafIsNeverAbbreviated() {
        let leaf = Chunk(text: "his share of noise-making", role: .object, gloss: "")

        XCTAssertEqual(ResultView.rowText(leaf, expanded: true), "his share of noise-making")
    }

    /// Sentence punctuation is kept in the data (span math needs it) and
    /// stripped only here.
    func testTrailingPunctuationIsTrimmed() {
        let leaf = Chunk(text: "deliciously ironic.", role: .complement, gloss: "")

        XCTAssertEqual(ResultView.rowText(leaf, expanded: false), "deliciously ironic")
    }
}
