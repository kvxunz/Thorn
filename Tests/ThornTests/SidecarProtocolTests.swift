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
          "function": "modifier",
          "form": "relative-clause",
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
        XCTAssertEqual(decoded.role, .clauseRelative)
        XCTAssertEqual(decoded.function, .modifier)
        XCTAssertEqual(decoded.form, .relativeClause)
        XCTAssertEqual(decoded.primaryLabel, "定语")
        XCTAssertEqual(decoded.secondaryLabel, "关系从句")
        XCTAssertEqual(decoded.displayRole, .clauseRelative)
        XCTAssertTrue(decoded.preservesTeachingWrapper)
    }

    func testAbsoluteRoleDecodes() throws {
        let json = """
        {
          "text": "my sister dead and gone",
          "role": "absolute",
          "gloss": "",
          "children": null,
          "id": "0.2",
          "s": 10,
          "e": 15
        }
        """
        let decoded = try JSONDecoder().decode(Chunk.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.role, .absolute)
        XCTAssertNil(decoded.function)
        XCTAssertEqual(decoded.primaryLabel, "独立主格")
        XCTAssertFalse(decoded.preservesTeachingWrapper)
    }

    func testUnknownOptionalTeachingMetadataFallsBackToRole() throws {
        let json = """
        {
          "text": "future form",
          "role": "complement",
          "function": "future-function",
          "form": "future-form",
          "gloss": "",
          "children": null,
          "id": "1",
          "s": 2,
          "e": 4
        }
        """
        let decoded = try JSONDecoder().decode(Chunk.self, from: Data(json.utf8))
        XCTAssertNil(decoded.function)
        XCTAssertNil(decoded.form)
        XCTAssertEqual(decoded.primaryLabel, "补语")
    }
}
