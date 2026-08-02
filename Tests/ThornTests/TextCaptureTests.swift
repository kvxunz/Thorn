import XCTest
@testable import Thorn

final class TextCaptureTests: XCTestCase {
    func testClipboardRestoreRequiresTheCapturedSyntheticGeneration() {
        XCTAssertTrue(
            TextCapture.ClipboardCapturePolicy.shouldRestore(
                originalChangeCount: 17,
                capturedChangeCount: 19,
                currentChangeCount: 19
            )
        )
    }

    func testClipboardRestoreSkipsPostCaptureUserCopy() {
        XCTAssertFalse(
            TextCapture.ClipboardCapturePolicy.shouldRestore(
                originalChangeCount: 17,
                capturedChangeCount: 19,
                currentChangeCount: 20
            ),
            "a user copy after capture must not be overwritten by restoration"
        )
    }

    func testClipboardRestoreRequiresAClipboardChange() {
        XCTAssertFalse(
            TextCapture.ClipboardCapturePolicy.shouldRestore(
                originalChangeCount: 17,
                capturedChangeCount: 17,
                currentChangeCount: 17
            )
        )
    }

    func testTraversalPolicyBoundsDepthNodesAndTime() {
        let deadline: UInt64 = 1_000
        XCTAssertTrue(
            TextCapture.AccessibilityTraversalPolicy.canVisitNode(
                depth: TextCapture.AccessibilityTraversalPolicy.maxDepth,
                visitedNodes: TextCapture.AccessibilityTraversalPolicy.maxNodes - 1,
                now: 999,
                deadline: deadline
            )
        )
        XCTAssertFalse(
            TextCapture.AccessibilityTraversalPolicy.canVisitNode(
                depth: TextCapture.AccessibilityTraversalPolicy.maxDepth + 1,
                visitedNodes: 0,
                now: 0,
                deadline: deadline
            )
        )
        XCTAssertFalse(
            TextCapture.AccessibilityTraversalPolicy.canVisitNode(
                depth: 0,
                visitedNodes: TextCapture.AccessibilityTraversalPolicy.maxNodes,
                now: 0,
                deadline: deadline
            )
        )
        XCTAssertFalse(
            TextCapture.AccessibilityTraversalPolicy.canVisitNode(
                depth: 0,
                visitedNodes: 0,
                now: deadline,
                deadline: deadline
            )
        )
    }

    func testTraversalPolicyCapsChildrenWithoutNegativeCounts() {
        XCTAssertEqual(
            TextCapture.AccessibilityTraversalPolicy.childLimit(for: 100),
            TextCapture.AccessibilityTraversalPolicy.maxChildrenPerNode
        )
        XCTAssertEqual(TextCapture.AccessibilityTraversalPolicy.childLimit(for: -1), 0)
        XCTAssertEqual(TextCapture.AccessibilityTraversalPolicy.childLimit(for: 4), 4)
    }
}
