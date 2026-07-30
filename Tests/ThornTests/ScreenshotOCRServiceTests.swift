import XCTest
@testable import Thorn

final class ScreenshotOCRServiceTests: XCTestCase {
    func testReadingOrderIsTopToBottomThenLeftToRight() {
        let lines = [
            OCRTextLine(text: "right", boundingBox: CGRect(x: 0.55, y: 0.70, width: 0.3, height: 0.08)),
            OCRTextLine(text: "bottom", boundingBox: CGRect(x: 0.10, y: 0.30, width: 0.4, height: 0.08)),
            OCRTextLine(text: "left", boundingBox: CGRect(x: 0.10, y: 0.71, width: 0.3, height: 0.08)),
        ]

        XCTAssertEqual(
            ScreenshotOCRService.readingOrder(lines).map(\.text),
            ["left", "right", "bottom"]
        )
    }
}
