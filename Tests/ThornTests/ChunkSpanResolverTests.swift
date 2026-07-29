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

        let layout = ChunkSpanResolver.layout(for: chunks)
        let firstRange = try XCTUnwrap(layout.spans[firstThat.id])
        let secondRange = try XCTUnwrap(layout.spans[secondThat.id])

        XCTAssertEqual(layout.text, "the fact that law governs a product that fails")
        XCTAssertEqual(firstRange, 9..<13)
        XCTAssertEqual(secondRange, 36..<40)
        XCTAssertNotEqual(firstRange, secondRange)
        XCTAssertEqual(substring(layout.text, in: firstRange), "that")
        XCTAssertEqual(substring(layout.text, in: secondRange), "that")
    }

    private func substring(_ text: String, in range: Range<Int>) -> String {
        let lower = text.index(text.startIndex, offsetBy: range.lowerBound)
        let upper = text.index(text.startIndex, offsetBy: range.upperBound)
        return String(text[lower..<upper])
    }
}
