import XCTest
@testable import Thorn

final class ChunkSpanResolverTests: XCTestCase {
    func testRepeatedChildTextResolvesInsideItsOwnParent() throws {
        let firstThat = Chunk(text: "that", role: .conjunction, gloss: "")
        let firstClause = Chunk(
            text: "that law governs",
            role: .clauseNoun,
            gloss: "",
            children: [
                firstThat,
                Chunk(text: "law", role: .subject, gloss: ""),
                Chunk(text: "governs", role: .verb, gloss: ""),
            ]
        )
        let secondThat = Chunk(text: "that", role: .relative, gloss: "指代前述的 product")
        let secondClause = Chunk(
            text: "that fails",
            role: .clauseRelative,
            gloss: "",
            children: [
                secondThat,
                Chunk(text: "fails", role: .verb, gloss: ""),
            ]
        )
        let chunks = [
            Chunk(text: "the fact", role: .object, gloss: ""),
            firstClause,
            Chunk(text: "a product", role: .object, gloss: ""),
            secondClause,
        ]

        let sentence = "the fact that law governs a product that fails"
        let layout = ChunkSpanResolver.layout(for: chunks, in: sentence)
        let firstRange = try XCTUnwrap(layout.spans[firstThat.id])
        let secondRange = try XCTUnwrap(layout.spans[secondThat.id])

        XCTAssertEqual(layout.text, "the fact that law governs a product that fails")
        XCTAssertEqual(firstRange, 9..<13)
        XCTAssertEqual(secondRange, 36..<40)
        XCTAssertNotEqual(firstRange, secondRange)
        XCTAssertEqual(substring(layout.text, in: firstRange), "that")
        XCTAssertEqual(substring(layout.text, in: secondRange), "that")
    }

    /// Regression: the header used to be glued back together from chunk text,
    /// which cannot restore English spacing. spaCy splits `It's` into two
    /// tokens, so the panel rendered `It ’s all deliciously ironic`.
    func testCliticKeepsOriginalSpacing() throws {
        let sentence = "It's all deliciously ironic."
        let clitic = Chunk(text: "'s", role: .verb, gloss: "")
        let chunks = [
            Chunk(text: "It", role: .subject, gloss: ""),
            clitic,
            Chunk(text: "all", role: .other, gloss: ""),
            Chunk(text: "deliciously ironic", role: .complement, gloss: ""),
        ]

        let layout = ChunkSpanResolver.layout(for: chunks, in: sentence)

        XCTAssertEqual(layout.text, sentence)
        XCTAssertFalse(layout.text.contains("It 's"), "clitic must stay attached")
        let range = try XCTUnwrap(layout.spans[clitic.id])
        XCTAssertEqual(substring(layout.text, in: range), "'s")
    }

    /// A tree that cannot be located in the sentence still has to yield a span
    /// for every chunk, or the header loses its coloring entirely.
    func testUnmatchableTreeFallsBackToReassembly() throws {
        let orphan = Chunk(text: "governs", role: .verb, gloss: "")
        let chunks = [Chunk(text: "law", role: .subject, gloss: ""), orphan]

        let layout = ChunkSpanResolver.layout(for: chunks, in: "A different sentence.")

        XCTAssertEqual(layout.text, "law governs")
        XCTAssertEqual(substring(layout.text, in: try XCTUnwrap(layout.spans[orphan.id])), "governs")
    }

    private func substring(_ text: String, in range: Range<Int>) -> String {
        let lower = text.index(text.startIndex, offsetBy: range.lowerBound)
        let upper = text.index(text.startIndex, offsetBy: range.upperBound)
        return String(text[lower..<upper])
    }
}
