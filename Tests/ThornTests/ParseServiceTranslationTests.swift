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
