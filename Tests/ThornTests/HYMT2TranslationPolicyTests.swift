import XCTest
@testable import Thorn

final class HYMT2TranslationPolicyTests: XCTestCase {
    func testTranslationIsDeterministic() {
        XCTAssertEqual(HYMT2TranslationPolicy.temperature, 0)
    }

    func testSentencePromptRequiresEveryClauseAndOpeningFrame() {
        let source = "The notion is that people have failed."
        let prompt = HYMT2TranslationPolicy.sentencePrompt(source: source)

        XCTAssertTrue(prompt.contains("Preserve every clause"))
        XCTAssertTrue(prompt.contains("framing expression at the beginning"))
        XCTAssertTrue(prompt.hasSuffix(source))
    }
}
