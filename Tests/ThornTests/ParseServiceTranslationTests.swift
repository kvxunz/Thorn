import XCTest
@testable import Thorn

final class ParseServiceTranslationTests: XCTestCase {
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

    func testChunkGlossDropsInventedTerminalPunctuation() {
        XCTAssertEqual(
            ParseService.cleanGlossOutput("无法达到预期标准。", source: "cannot live up to"),
            "无法达到预期标准"
        )
        XCTAssertEqual(
            ParseService.cleanGlossOutput("到来。", source: "comes."),
            "到来。"
        )
    }
}
