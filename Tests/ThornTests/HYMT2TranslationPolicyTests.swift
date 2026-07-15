import XCTest
@testable import Thorn

final class HYMT2TranslationPolicyTests: XCTestCase {
    func testTranslationIsDeterministic() {
        XCTAssertEqual(HYMT2TranslationPolicy.temperature, 0)
    }

    func testGlossPromptContainsOnlyTheRequestedSourceText() {
        let prompt = HYMT2TranslationPolicy.glossPrompt(source: "people")

        XCTAssertTrue(prompt.contains("people"))
        XCTAssertFalse(prompt.contains("Background Information"))
        XCTAssertFalse(prompt.contains("The notion is that"))
    }

    func testSentencePromptRequiresEveryClauseAndOpeningFrame() {
        let source = "The notion is that people have failed."
        let prompt = HYMT2TranslationPolicy.sentencePrompt(source: source)

        XCTAssertTrue(prompt.contains("Preserve every clause"))
        XCTAssertTrue(prompt.contains("framing expression at the beginning"))
        XCTAssertTrue(prompt.hasSuffix(source))
    }

    func testStructuralConjunctionsUseDeterministicGlosses() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "that",
                role: .conjunction,
                parentRole: .clauseNoun
            ),
            "即"
        )
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "because",
                role: .conjunction,
                parentRole: .clauseAdverbial
            ),
            "因为"
        )
    }

    func testShortChunkRejectsExpandedSentenceGloss() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.validatedGloss(
                "人们",
                source: "people",
                role: .subject
            ),
            "人们"
        )
        XCTAssertNil(
            HYMT2TranslationPolicy.validatedGloss(
                "人们未能察觉海洋中的巨大变化，是因为他们回顾的时间太短",
                source: "people",
                role: .subject
            )
        )
        XCTAssertEqual(
            HYMT2TranslationPolicy.validatedGloss(
                "已经发生了",
                source: "have happened",
                role: .verb
            ),
            "已经发生了"
        )
    }

    func testFailBeforeInfinitiveComplementMeansUnableToDoIt() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "have failed",
                role: .verb,
                parentRole: .clauseNoun,
                followingText: "to detect the massive changes",
                followingRole: .complement
            ),
            "未能"
        )
    }

    func testNotionBeforeLinkingVerbAndNounClauseMeansViewpoint() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "The notion",
                role: .subject,
                parentRole: nil,
                followingText: "is",
                followingRole: .verb,
                subsequentRole: .clauseNoun
            ),
            "这种观点"
        )
    }

    func testDetectAbstractChangesMeansNoticeRatherThanInspect() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "to detect",
                role: .verb,
                parentRole: .complement,
                followingText: "the massive changes",
                followingRole: .object
            ),
            "察觉到"
        )
    }

    func testIntoThePastAfterLookBackMeansTraceBackInTime() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "into the past",
                role: .prepPhrase,
                parentRole: .clauseAdverbial,
                governingVerbText: "have been looking back"
            ),
            "向过去追溯"
        )
    }

    func testGovernAdvertisingTermsMeansRegulate() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "govern",
                role: .verb,
                parentRole: .clauseNoun,
                followingText: "the terms of advertising",
                followingRole: .object
            ),
            "规定"
        )
    }

    func testNoRegularAdvertiserMeansNoLegitimateAdvertiser() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "no regular advertiser",
                role: .subject,
                parentRole: nil
            ),
            "没有哪家正规的广告商"
        )
    }

    func testLiveUpBeforePromiseMeansMeetThePromisedStandard() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "to live up",
                role: .verb,
                parentRole: .complement,
                followingText: "to the promise of his advertisements",
                followingRole: .prepPhrase
            ),
            "达到承诺的标准"
        )
    }

    func testPromisePrepositionalComplementIsNotCausal() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "to the promise of his advertisements",
                role: .prepPhrase,
                parentRole: .complement,
                governingVerbText: "to live up"
            ),
            "其广告宣传中所作的承诺"
        )
    }

    func testPromisePrepositionalComplementDoesNotInventAdvertisingContext() {
        XCTAssertNil(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "to the promise of his parents",
                role: .prepPhrase,
                parentRole: .complement,
                governingVerbText: "to live up"
            )
        )
    }

    func testDarePromoteProductMeansDareAdvertiseIt() {
        XCTAssertEqual(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "dare promote",
                role: .verb,
                parentRole: nil,
                followingText: "a product",
                followingRole: .object
            ),
            "敢于宣传"
        )
    }

    func testLieInAbstractCriterionMeansConsistInRatherThanTellFalsehood() {
        let variants = [
            (verb: "lies", following: "not in how well it can control expression but in whether it gives freedom", expected: "不在于"),
            (verb: "lies not", following: "in how well it can control expression but in whether it gives freedom", expected: "不在于"),
            (verb: "lies", following: "in whether the test is fair", expected: "在于"),
        ]

        for variant in variants {
            XCTAssertEqual(
                HYMT2TranslationPolicy.deterministicGloss(
                    text: variant.verb,
                    role: .verb,
                    parentRole: nil,
                    followingText: variant.following,
                    followingRole: .prepPhrase
                ),
                variant.expected
            )
        }
    }

    func testConcreteLieInLocationIsLeftToTheTranslationModel() {
        XCTAssertNil(
            HYMT2TranslationPolicy.deterministicGloss(
                text: "lies",
                role: .verb,
                parentRole: nil,
                followingText: "in the drawer",
                followingRole: .prepPhrase
            )
        )
    }
}
