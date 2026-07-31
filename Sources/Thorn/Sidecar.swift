import Foundation

struct SidecarStructure: Sendable {
    let chunks: [Chunk]
    let sourceTokens: [String]
}

enum SidecarFailure: LocalizedError, Sendable {
    case unavailable
    case rejected(String)
    case busy
    case invalidResponse
    case invalidStructure

    var errorDescription: String? {
        switch self {
        case .unavailable:
            return "本地句法引擎暂不可用。"
        case .rejected(let detail):
            return "这段文字未能完成句法拆解：\(detail)"
        case .busy:
            return "本地句法引擎正忙，请稍后再试。"
        case .invalidResponse:
            return "本地句法引擎返回了无法读取的结果。"
        case .invalidStructure:
            return "句法结果未通过完整性校验，请缩短文本后重试。"
        }
    }
}

/// Client + lifecycle for the Python structure sidecar (spaCy + benepar).
/// The sidecar delivers deterministic teaching chunk trees; whole-sentence
/// translation comes separately from the local HY-MT2 model.
actor Sidecar {
    static let shared = Sidecar()

    /// Passed explicitly rather than left to server.py's default, so the cost
    /// of an idle sidecar (~3.2 GB) is visible on the side that spawns it.
    private static let idleExitSeconds = 120

    private let port: Int
    private let authToken: String
    private var process: Process?
    private var launchAttempted = false
    private var structureCache: [String: SidecarStructure] = [:]
    private var structureOrder: [String] = []

    private var baseURL: String { "http://127.0.0.1:\(port)" }

    private init() {
        let environment = ProcessInfo.processInfo.environment
        if let configured = environment["THORN_SIDECAR_PORT"],
           let port = Int(configured), (1024...65535).contains(port) {
            self.port = port
        } else {
            // A per-launch port avoids old protocol processes blocking an app
            // upgrade and makes blind localhost sidecar impersonation harder.
            self.port = Int.random(in: 49152...65535)
        }
        if let configuredToken = environment["THORN_SIDECAR_TOKEN"],
           !configuredToken.isEmpty {
            self.authToken = configuredToken
        } else {
            self.authToken = UUID().uuidString
        }
    }

    private struct StructureResponse: Decodable {
        let chunks: [Chunk]
        let sourceTokens: [String]
    }

    private struct ErrorResponse: Decodable {
        let detail: String
    }

    /// The launch script path when it does not exist on disk — so the panel
    /// can name the actual problem instead of a generic "engine unavailable".
    func missingScriptPath() -> String? {
        let script = sidecarScriptPath()
        return FileManager.default.fileExists(atPath: script) ? nil : script
    }

    func modelInstallCommand() -> String {
        let quoted = "'" + sidecarScriptPath().replacingOccurrences(of: "'", with: "'\\''") + "'"
        return "uv run --script \(quoted) --install-models"
    }

    /// Fetch the deterministic teaching tree while preserving the distinction
    /// between startup/model failures and sentence-specific parse failures.
    func structure(for sentence: String) async throws -> SidecarStructure {
        if let cached = structureCache[sentence] {
            structureOrder.removeAll { $0 == sentence }
            structureOrder.append(sentence)
            return cached
        }
        if !(await ensureHealthy()) { throw SidecarFailure.unavailable }
        guard let url = URL(string: baseURL + "/parse") else {
            throw SidecarFailure.invalidResponse
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 30
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        authorize(&request)
        request.httpBody = try JSONEncoder().encode(["text": sentence])

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            ThornLog.info("sidecar request failed: \(error.localizedDescription)")
            throw SidecarFailure.unavailable
        }
        try Task.checkCancellation()
        guard data.count <= 2_000_000,
              let http = response as? HTTPURLResponse else {
            throw SidecarFailure.invalidResponse
        }
        switch http.statusCode {
        case 200:
            break
        case 422:
            let detail = (try? JSONDecoder().decode(ErrorResponse.self, from: data).detail)
                ?? "解析器无法覆盖完整句子"
            throw SidecarFailure.rejected(detail)
        case 429:
            throw SidecarFailure.busy
        default:
            ThornLog.info("sidecar returned HTTP \(http.statusCode)")
            throw SidecarFailure.invalidResponse
        }
        guard let decoded = try? JSONDecoder().decode(StructureResponse.self, from: data) else {
            throw SidecarFailure.invalidResponse
        }
        guard !decoded.chunks.isEmpty,
              validate(chunks: decoded.chunks, sourceTokens: decoded.sourceTokens) else {
            throw SidecarFailure.invalidStructure
        }
        let structure = SidecarStructure(chunks: decoded.chunks, sourceTokens: decoded.sourceTokens)
        cache(structure, for: sentence)
        return structure
    }

    private struct HealthResponse: Decodable {
        let ok: Bool
        let protocolVersion: Int?
        let parseProtocolVersion: Int?
    }

    private func isHealthy() async -> Bool {
        guard let url = URL(string: baseURL + "/health") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        authorize(&req)
        guard let (data, response) = try? await URLSession.shared.data(for: req),
              data.count <= 16_384,
              (response as? HTTPURLResponse)?.statusCode == 200,
              let health = try? JSONDecoder().decode(HealthResponse.self, from: data) else {
            return false
        }
        // Structure compatibility is independent from the optional /analyze
        // evidence schema. New sidecars advertise it explicitly; historical
        // v3/v4 sidecars only have the legacy protocolVersion key.
        guard health.ok,
              let version = health.parseProtocolVersion ?? health.protocolVersion
        else { return false }
        return version == 3 || version == 4
    }

    private func ensureHealthy() async -> Bool {
        if await isHealthy() { return true }
        launchIfNeeded()
        // Transformer + Benepar cold starts can exceed 10s. Poll up to 30s.
        for _ in 0..<60 {
            do {
                try await Task.sleep(nanoseconds: 500_000_000)
            } catch {
                return false
            }
            if await isHealthy() { return true }
        }
        return false
    }

    private func authorize(_ request: inout URLRequest) {
        request.setValue(authToken, forHTTPHeaderField: "X-Thorn-Token")
    }

    private func validate(chunks: [Chunk], sourceTokens: [String]) -> Bool {
        guard !sourceTokens.isEmpty, sourceTokens.count <= 512,
              sourceTokens.allSatisfy({ !$0.isEmpty && $0.count <= 256 }),
              sourceTokens.reduce(0, { $0 + $1.count }) <= 12_000 else { return false }
        var keys = Set<String>()
        var count = 0
        var totalTextCharacters = 0

        func normalized(_ text: String) -> String {
            text.filter { !$0.isWhitespace }
        }

        func walk(_ nodes: [Chunk], parent: Range<Int>, path: [Int], depth: Int) -> Bool {
            guard depth <= 32 else { return false }
            var previousEnd = parent.lowerBound
            for (position, node) in nodes.enumerated() {
                count += 1
                totalTextCharacters += node.text.count
                let expectedKey = (path + [position]).map(String.init).joined(separator: ".")
                guard count <= 256,
                      totalTextCharacters <= 100_000,
                      node.text.count <= 12_000,
                      let key = node.nodeKey, key == expectedKey, key.count <= 64,
                      keys.insert(key).inserted,
                      let start = node.sourceStart, let end = node.sourceEnd,
                      parent.contains(start), start < end, end <= parent.upperBound,
                      start >= previousEnd,
                      normalized(node.text) == normalized(sourceTokens[start..<end].joined()) else {
                    return false
                }
                if let children = node.children,
                   !walk(children, parent: start..<end, path: path + [position], depth: depth + 1) {
                    return false
                }
                previousEnd = end
            }
            return true
        }
        return !chunks.isEmpty
            && walk(chunks, parent: 0..<sourceTokens.count, path: [], depth: 1)
    }

    private func cache(_ structure: SidecarStructure, for sentence: String) {
        structureCache[sentence] = structure
        structureOrder.removeAll { $0 == sentence }
        structureOrder.append(sentence)
        if structureOrder.count > 128 {
            let evicted = structureOrder.removeFirst()
            structureCache.removeValue(forKey: evicted)
        }
    }

    /// Spawn `uv run server.py` once per app session. The sidecar exits itself
    /// after `idleExitSeconds` idle; we respawn on the next request.
    private func launchIfNeeded() {
        if let process, process.isRunning { return }
        // Re-allow launching after a previous sidecar exited (idle timeout).
        if launchAttempted, let process, !process.isRunning { launchAttempted = false }
        guard !launchAttempted else { return }
        launchAttempted = true

        let script = sidecarScriptPath()
        guard FileManager.default.fileExists(atPath: script) else {
            ThornLog.info("sidecar script not found at \(script)")
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        // Login shell keeps uv on PATH. Values are passed as positional
        // parameters so a custom path cannot be interpreted as shell syntax.
        p.arguments = [
            "-lc",
            "exec uv run --script \"$1\" --port \"$2\" --idle-exit \"$3\"",
            "thorn-sidecar",
            script,
            String(port),
            String(Self.idleExitSeconds),
        ]
        var environment = ProcessInfo.processInfo.environment
        environment["THORN_SIDECAR_TOKEN"] = authToken
        p.environment = environment
        p.standardOutput = FileHandle.nullDevice
        p.standardError = FileHandle.nullDevice
        do {
            try p.run()
            process = p
            ThornLog.info("sidecar launched, pid \(p.processIdentifier)")
        } catch {
            ThornLog.info("sidecar launch failed: \(error)")
        }
    }

    private func sidecarScriptPath() -> String {
        // Development layout: repo/sidecar/server.py next to the app sources.
        // Overridable for custom installs.
        if let custom = UserDefaults.standard.string(forKey: "sidecarScript") {
            return custom
        }
        return NSString(string: "~/xznm/code/Thorn/sidecar/server.py").expandingTildeInPath
    }

    func terminate() {
        process?.terminate()
        process = nil
    }
}
