import XCTest
@testable import Thorn

final class GlossConsistencyTests: XCTestCase {
    func testRelativeClauseDropsInventedGenericAntecedent() throws {
        let clause = Chunk(
            text: "which have happened in the ocean",
            role: .clauseRelative,
            gloss: "发生在海洋中的那些事情",
            children: [
                Chunk(text: "which", role: .relative, gloss: "指代前述的 changes"),
                Chunk(text: "have happened", role: .verb, gloss: "已经发生了"),
                Chunk(text: "in the ocean", role: .prepPhrase, gloss: "在海洋中"),
            ]
        )

        let result = try XCTUnwrap(GlossConsistency.reconcile([clause]).first)

        XCTAssertEqual(result.gloss, "发生在海洋中的")
    }

    func testComplementInheritsDetectVerbFromChild() throws {
        let complement = Chunk(
            text: "to detect the massive changes which have happened in the ocean",
            role: .complement,
            gloss: "检测海洋中发生的巨大变化",
            children: [
                Chunk(text: "to detect", role: .verb, gloss: "察觉到"),
                Chunk(text: "the massive changes", role: .object, gloss: "巨大的变化"),
                Chunk(
                    text: "which have happened in the ocean",
                    role: .clauseRelative,
                    gloss: "发生在海洋中的"
                ),
            ]
        )

        let result = try XCTUnwrap(GlossConsistency.reconcile([complement]).first)

        XCTAssertEqual(result.gloss, "察觉到海洋中发生的巨大变化")
    }

    func testLiveUpComplementUsesPromisedPerformanceMeaning() throws {
        let complement = Chunk(
            text: "to live up to the promise of his advertisements",
            role: .complement,
            gloss: "履行广告中的承诺",
            children: [
                Chunk(text: "to live up", role: .verb, gloss: "达到承诺的标准"),
                Chunk(
                    text: "to the promise of his advertisements",
                    role: .prepPhrase,
                    gloss: "其广告宣传中所作的承诺"
                ),
            ]
        )

        let result = try XCTUnwrap(GlossConsistency.reconcile([complement]).first)

        XCTAssertEqual(result.gloss, "达到其广告宣传所承诺的水平")
    }

    func testLiveUpComplementDoesNotInventAdvertisingOutsideAdvertisingContext() throws {
        let complement = Chunk(
            text: "to live up to the promise of his parents",
            role: .complement,
            gloss: "不辜负父母的承诺",
            children: [
                Chunk(text: "to live up", role: .verb, gloss: "不辜负"),
                Chunk(
                    text: "to the promise of his parents",
                    role: .prepPhrase,
                    gloss: "对父母的承诺"
                ),
            ]
        )

        let result = try XCTUnwrap(GlossConsistency.reconcile([complement]).first)

        XCTAssertEqual(result.gloss, "不辜负父母的承诺")
    }

    func testRelativeClauseInheritsLiveUpComplementMeaning() throws {
        let clause = Chunk(
            text: "that fails to live up to the promise of his advertisements",
            role: .clauseRelative,
            gloss: "未能兑现广告中的承诺",
            children: [
                Chunk(text: "that", role: .relative, gloss: "指代前述的 product"),
                Chunk(text: "fails", role: .verb, gloss: "未能"),
                Chunk(
                    text: "to live up to the promise of his advertisements",
                    role: .complement,
                    gloss: "达到其广告宣传所承诺的水平"
                ),
            ]
        )

        let result = try XCTUnwrap(GlossConsistency.reconcile([clause]).first)

        XCTAssertEqual(result.gloss, "未能达到其广告宣传所承诺的水平")
    }

    func testNounClauseDoesNotTurnComplementizerThatIntoDemonstrative() throws {
        let clause = Chunk(
            text: "that twenty-seven acts of Parliament govern the terms of advertising",
            role: .clauseNoun,
            gloss: "那27项议会法案规定了广告的相关条款",
            children: [
                Chunk(text: "that", role: .conjunction, gloss: "即"),
                Chunk(text: "twenty-seven acts of Parliament", role: .subject, gloss: "27项议会法案"),
                Chunk(text: "govern", role: .verb, gloss: "规定"),
                Chunk(text: "the terms of advertising", role: .object, gloss: "广告条款"),
            ]
        )

        let result = try XCTUnwrap(GlossConsistency.reconcile([clause]).first)

        XCTAssertEqual(result.gloss, "27项议会法案规定广告条款")
    }
}
