import XCTest
@testable import Thorn

final class AlignmentPipelineTests: XCTestCase {
    func testChunkMetadataRoundTripsThroughSidecarJSON() throws {
        let json = """
        {
          "text": "that fails",
          "role": "clause-relative",
          "gloss": "",
          "children": null,
          "id": "3",
          "s": 7,
          "e": 9
        }
        """

        let decoded = try JSONDecoder().decode(Chunk.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.nodeKey, "3")
        XCTAssertEqual(decoded.sourceStart, 7)
        XCTAssertEqual(decoded.sourceEnd, 9)

        let encoded = try JSONSerialization.jsonObject(with: JSONEncoder().encode(decoded)) as? [String: Any]
        XCTAssertEqual(encoded?["id"] as? String, "3")
        XCTAssertEqual(encoded?["s"] as? Int, 7)
        XCTAssertEqual(encoded?["e"] as? Int, 9)
    }
}
