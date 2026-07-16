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
