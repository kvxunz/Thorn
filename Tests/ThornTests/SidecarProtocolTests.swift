import XCTest
@testable import Thorn

/// Wire-contract check for the sidecar /parse response: node identity (`id`)
/// and source token span (`s`/`e`) must decode into Chunk metadata.
final class SidecarProtocolTests: XCTestCase {
    func testChunkMetadataDecodesFromSidecarJSON() throws {
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
    }
}
