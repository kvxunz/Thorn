import XCTest
@testable import Thorn

final class LiveHYMT2IntegrationTests: XCTestCase {
    func testNotionSentenceUsesScopedGlossesEndToEnd() async throws {
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
        let glosses = Dictionary(chunks.map { ($0.text, $0.gloss) }) { first, _ in first }

        XCTAssertEqual(glosses["The notion"], "这种观点")
        XCTAssertEqual(glosses["is"], "是")
        XCTAssertEqual(glosses["people"], "人们")
        XCTAssertEqual(glosses["have failed"], "未能")
        XCTAssertEqual(
            glosses["to detect the massive changes which have happened in the ocean"],
            "察觉到海洋中发生的巨大变化"
        )
        XCTAssertEqual(glosses["to detect"], "察觉到")
        XCTAssertEqual(glosses["the massive changes"], "巨大的变化")
        XCTAssertEqual(glosses["which have happened in the ocean"], "发生在海洋中的")
        XCTAssertEqual(glosses["have happened"], "已经发生了")
        XCTAssertEqual(glosses["in the ocean"], "在海洋中")
        XCTAssertEqual(glosses["because"], "因为")
        XCTAssertEqual(glosses["they"], "他们")
        XCTAssertEqual(glosses["have been looking back"], "一直在回顾过去")
        XCTAssertEqual(glosses["only a relatively short time"], "只有相对较短的时间")
        XCTAssertEqual(glosses["into the past"], "向过去追溯")
        XCTAssertNil(glosses["back"])
        XCTAssertTrue(result.translation.contains("观点"))
    }

    func testAdvertiserSentenceKeepsParentAndChildGlossesConsistent() async throws {
        try XCTSkipUnless(
            ProcessInfo.processInfo.environment["THORN_LIVE_MODEL_TEST"] == "1",
            "Requires the local sidecar and HY-MT2 model"
        )

        let sentence = "Apart from the fact that twenty-seven acts of Parliament govern the terms of advertising no regular advertiser dare promote a product that fails to live up to the promise of his advertisements"
        let result = try await ParseService.parse(
            sentence: sentence,
            provider: .ollama,
            force: true
        )
        let chunks = flatten(result.chunks)
        let glosses = Dictionary(chunks.map { ($0.text, $0.gloss) }) { first, _ in first }

        XCTAssertEqual(
            glosses["that twenty-seven acts of Parliament govern the terms of advertising"],
            "27项议会法案规定广告条款"
        )
        XCTAssertEqual(glosses["govern"], "规定")
        XCTAssertEqual(glosses["no regular advertiser"], "没有哪家正规的广告商")
        XCTAssertEqual(glosses["dare promote"], "敢于宣传")
        XCTAssertEqual(
            glosses["that fails to live up to the promise of his advertisements"],
            "未能达到其广告宣传所承诺的水平"
        )
        XCTAssertEqual(glosses["fails"], "未能")
        XCTAssertEqual(
            glosses["to live up to the promise of his advertisements"],
            "达到其广告宣传所承诺的水平"
        )
        XCTAssertEqual(glosses["to live up"], "达到承诺的标准")
        XCTAssertEqual(
            glosses["to the promise of his advertisements"],
            "其广告宣传中所作的承诺"
        )
        XCTAssertTrue(result.translation.contains("正规"))
        XCTAssertTrue(result.translation.contains("广告"))
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
        let liesNot = try XCTUnwrap(chunks.first { $0.text == "lies not" })

        XCTAssertEqual(howeverClause.role, .clauseAdverbial)
        XCTAssertEqual(liesNot.gloss, "不在于")
        XCTAssertNotEqual(liesNot.gloss, "不说谎")
        XCTAssertTrue(result.translation.contains("不在于"))
        XCTAssertTrue(result.translation.contains("而在于"))
    }

    private func flatten(_ chunks: [Chunk]) -> [Chunk] {
        chunks.flatMap { [$0] + flatten($0.children ?? []) }
    }
}
