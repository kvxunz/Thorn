import XCTest
@testable import Thorn

final class ParseServiceTranslationTests: XCTestCase {
    func testNormalizesCJKPunctuationLeakedFromBilingualMaterial() {
        XCTAssertEqual(
            ParseService.normalizedInput("for your troubles，  or so the thinking has gone"),
            "for your troubles, or so the thinking has gone"
        )
        // Curly apostrophes are normal English typography and must survive.
        XCTAssertEqual(
            ParseService.normalizedInput("their customers’ misfortunes。"),
            "their customers’ misfortunes."
        )
        // Invisible control/format characters (ZWSP, BOM, LRM) become tofu in
        // the header — strip them without leaving a stray space.
        XCTAssertEqual(
            ParseService.normalizedInput("Futurist poetry\u{200B}, however"),
            "Futurist poetry, however"
        )
        XCTAssertEqual(
            ParseService.normalizedInput("\u{FEFF}the case\u{200E} is"),
            "the case is"
        )
        // Dash parentheticals must not glue to neighboring words; PDF junk
        // brackets like [tObj] are stripped.
        XCTAssertEqual(
            ParseService.normalizedInput(
                "New ways of organizing the workplace--all that reengineering--are only one"
            ),
            "New ways of organizing the workplace -- all that reengineering -- are only one"
        )
        XCTAssertEqual(
            ParseService.normalizedInput("downsizing[tObj] --are"),
            "downsizing -- are"
        )
        // Preserve meaningful dash typography, repair safe punctuation
        // boundaries, and drop copied object placeholders. Never guess a
        // missing space inside an alphabetic token such as "orall".
        XCTAssertEqual(
            ParseService.normalizedInput("model,with—Security\u{FFFC}retirees orall"),
            "model, with — Security retirees orall"
        )
    }

    func testExtractsEnglishSentenceFromBilingualAnnotations() {
        // Real material: vocabulary glosses and a 【翻译技巧】 header wrap the
        // actual numbered sentence. Only the English sentence must survive.
        let mixed = "【翻译技巧】the big seven industrial economies 是指西方 七大工业国。"
            + "close to 是靠近的意思。fall to 是“跌落至……”的意思。"
            + "15．Economists have been particularly surprised by favorable inflation "
            + "figures in Britain and the United States, since conventional measures "
            + "suggest that both economies, and especially America's, have little productive slack."

        XCTAssertEqual(
            ParseService.extractEnglish(ParseService.normalizedInput(mixed)),
            "Economists have been particularly surprised by favorable inflation "
                + "figures in Britain and the United States, since conventional measures "
                + "suggest that both economies, and especially America's, have little productive slack."
        )
        // Nothing sentence-like left -> empty, caller shows a clear error.
        XCTAssertEqual(
            ParseService.extractEnglish(ParseService.normalizedInput("close to 是靠近的意思。")),
            ""
        )
        // Pure English is untouched.
        XCTAssertEqual(
            ParseService.extractEnglish("He left early. It rained."),
            "He left early. It rained."
        )
    }

    func testCleansCommonTranslationWrappers() {
        let raw = """
        ```text
        <translation>
        译文：这款产品没有兑现广告中的承诺。
        </translation>
        ```
        """

        XCTAssertEqual(
            ParseService.cleanTranslationOutput(raw),
            "这款产品没有兑现广告中的承诺。"
        )
    }
}
