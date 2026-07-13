import Foundation
import CryptoKit

/// Disk cache: one JSON file per sentence, keyed by SHA-256 of model + sentence.
enum ParseCache {
    private static var dir: URL = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let url = base.appendingPathComponent("Thorn/cache", isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }()

    private static func key(model: String, sentence: String) -> String {
        let digest = SHA256.hash(data: Data((model + "\n" + sentence).utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    static func get(model: String, sentence: String) -> ParseResult? {
        let url = dir.appendingPathComponent(key(model: model, sentence: sentence) + ".json")
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(ParseResult.self, from: data)
    }

    static func set(model: String, sentence: String, result: ParseResult) {
        let url = dir.appendingPathComponent(key(model: model, sentence: sentence) + ".json")
        if let data = try? JSONEncoder().encode(result) {
            try? data.write(to: url)
        }
    }
}
