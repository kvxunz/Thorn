import XCTest
@testable import Thorn

final class ChunkSpanResolverTests: XCTestCase {
    func testRepeatedChildTextResolvesInsideItsOwnParent() throws {
        let firstThat = Chunk(text: "that", role: .conjunction, gloss: "即")
        let firstClause = Chunk(
            text: "that law governs",
            role: .clauseNoun,
            gloss: "法律规定",
            children: [
                firstThat,
                Chunk(text: "law", role: .subject, gloss: "法律"),
                Chunk(text: "governs", role: .verb, gloss: "规定"),
            ]
        )
        let secondThat = Chunk(text: "that", role: .relative, gloss: "指代产品")
        let secondClause = Chunk(
            text: "that fails",
            role: .clauseRelative,
            gloss: "未能做到的",
            children: [
                secondThat,
                Chunk(text: "fails", role: .verb, gloss: "未能"),
            ]
        )
        let chunks = [
            Chunk(text: "the fact", role: .object, gloss: "事实"),
            firstClause,
            Chunk(text: "a product", role: .object, gloss: "一种产品"),
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
