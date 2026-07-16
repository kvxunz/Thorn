import XCTest
@testable import Thorn

/// Live smoke tests for the local pipeline: deterministic structure from the
/// sidecar plus one whole-sentence HY-MT2 translation. Per-chunk glosses were
/// removed; only syntax-derived glosses (relative-pronoun referents) remain.
final class LiveHYMT2IntegrationTests: XCTestCase {
    func testNotionSentenceProducesStructureAndTranslation() async throws {
        try XCTSkipUnless(
            ProcessInfo.processInfo.environment["THORN_LIVE_MODEL_TEST"] == "1",
            "Requires the local sidecar and HY-MT2 model"
        )

        let sentence = "The notion is that people have failed to detect the massive changes which have happened in the ocean because they have been looking back only a relatively short time into the past."
        let result = try await ParseService.parse(
            sentence: sentence,
            provider: .ollama,
            force: true
        )
        let chunks = flatten(result.chunks)

        // Backbone: subject + verb present, and the reassembled chunk text
        // covers the whole input.
        XCTAssertTrue(chunks.contains { $0.role == .subject })
        XCTAssertTrue(chunks.contains { $0.role == .verb })
        assertTopLevelTextCoversInput(result.chunks, sentence: sentence)

        // The which-clause survives as a relative clause with a deterministic
        // referent gloss from the dependency tree.
        XCTAssertTrue(chunks.contains { $0.role == .clauseRelative })
        XCTAssertTrue(chunks.contains {
            $0.role == .relative && $0.gloss.contains("指代前述的")
        })

        XCTAssertFalse(result.translation.isEmpty)
        XCTAssertTrue(result.translation.contains("观点") || result.translation.contains("观念"))
    }

    func testDemocraticSocietySentenceTreatsHoweverAsConcessiveClause() async throws {
        try XCTSkipUnless(
            ProcessInfo.processInfo.environment["THORN_LIVE_MODEL_TEST"] == "1",
            "Requires the local sidecar and HY-MT2 model"
        )

        let sentence = "\"The test of any democratic society,\" he wrote in a Wall Street Journal column, \"lies not in how well it can control expression but in whether it gives freedom of thought and expression the widest possible latitude, however disputable or irritating the results may sometimes be"
        let result = try await ParseService.parse(
            sentence: sentence,
            provider: .ollama,
            force: true
        )
        let chunks = flatten(result.chunks)
        let howeverClause = try XCTUnwrap(chunks.first {
            $0.text == "however disputable or irritating the results may sometimes be"
        })

        XCTAssertEqual(howeverClause.role, .clauseAdverbial)
        XCTAssertFalse(result.translation.isEmpty)
        XCTAssertTrue(result.translation.contains("在于"))
    }

    func testReorderedIdiomAndRelativeModifierStayInTheirOwnChunks() async throws {
        try XCTSkipUnless(
            ProcessInfo.processInfo.environment["THORN_LIVE_MODEL_TEST"] == "1",
            "Requires the local sidecar and HY-MT2 model"
        )

        let sentence = "Last year Mitsuo Setoyama, who was then education minister, raised eyebrows when he argued that reforms had weakened the morality."
        let result = try await ParseService.parse(sentence: sentence, provider: .ollama, force: true)
        let chunks = flatten(result.chunks)

        XCTAssertNotNil(chunks.first { $0.text == "raised eyebrows" })
        XCTAssertNotNil(chunks.first { $0.role == .clauseRelative })
        XCTAssertFalse(result.translation.isEmpty)
    }

    private func flatten(_ chunks: [Chunk]) -> [Chunk] {
        chunks.flatMap { [$0] + flatten($0.children ?? []) }
    }

    private func assertTopLevelTextCoversInput(
        _ chunks: [Chunk],
        sentence: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let normalized = { (text: String) in text.filter { !$0.isWhitespace } }
        XCTAssertEqual(
            normalized(chunks.map(\.text).joined()),
            normalized(sentence),
            file: file,
            line: line
        )
    }
}
