import Foundation

/// Former on-disk parse cache. Disabled: every ⌥A runs the live pipeline so
/// alignment/prompt changes are never masked by a stale JSON file.
///
/// `purge()` deletes any leftover files from earlier builds under
/// Application Support/Thorn/cache.
enum ParseCache {
    private static var dir: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("Thorn/cache", isDirectory: true)
    }()

    /// Remove historical cache files (best-effort).
    static func purge() {
        try? FileManager.default.removeItem(at: dir)
    }
}
