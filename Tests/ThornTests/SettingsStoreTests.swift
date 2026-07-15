import XCTest
@testable import Thorn

final class SettingsStoreTests: XCTestCase {
    func testOnlyCustomProviderRequiresCustomEndpointKeychain() {
        XCTAssertFalse(
            SettingsStore.shouldLoadCustomAPIKey(for: .ollama, currentAPIKey: "")
        )
        XCTAssertTrue(
            SettingsStore.shouldLoadCustomAPIKey(for: .custom, currentAPIKey: "")
        )
        XCTAssertFalse(
            SettingsStore.shouldLoadCustomAPIKey(for: .custom, currentAPIKey: "saved-token")
        )
    }
}
