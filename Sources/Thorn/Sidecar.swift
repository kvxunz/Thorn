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

/// Pure lifecycle state for the sidecar process. A failed launch returns to
/// `idle`, allowing the next parse request to retry; an idle-exited process
/// follows the same path and is therefore respawned on demand.
enum SidecarLifecyclePhase: Equatable, Sendable {
    case idle
    case launching
    case running
}

struct SidecarLifecycleState: Equatable, Sendable {
    private(set) var phase: SidecarLifecyclePhase = .idle
    private(set) var generation: UInt64 = 0

    mutating func beginLaunch() -> Bool {
        guard phase == .idle else { return false }
        phase = .launching
        return true
    }

    mutating func launchSucceeded() -> Bool {
        guard phase == .launching else { return false }
        phase = .running
        generation &+= 1
        return true
    }

    mutating func launchFailed() {
        phase = .idle
    }

    mutating func processExited() {
        phase = .idle
    }

    func acceptsHealthResponse(generation expected: UInt64, processIsRunning: Bool) -> Bool {
        phase == .running && generation == expected && processIsRunning
    }
}

struct SidecarShutdownState: Equatable, Sendable {
    private(set) var isShuttingDown = false

    var allowsProcessRegistration: Bool { !isShuttingDown }

    mutating func beginShutdown() {
        isShuttingDown = true
    }
}

/// Process output is useful when a model fails to load, but it must not be
/// retained indefinitely (or include a sentence sent after startup). The
/// buffer is shared with Pipe readability callbacks, hence the small lock.
private final class SidecarDiagnosticBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private let limit: Int
    private var bytes = Data()
    private var accepting = true

    init(limit: Int) {
        self.limit = max(0, limit)
    }

    func append(_ data: Data, stream: String) {
        guard !data.isEmpty else { return }
        lock.lock()
        defer { lock.unlock() }
        guard accepting, bytes.count < limit else { return }
        let prefix = Data(("\(stream): ").utf8)
        let remaining = limit - bytes.count
        bytes.append(prefix.prefix(remaining))
        guard bytes.count < limit else { return }
        bytes.append(data.prefix(limit - bytes.count))
    }

    func stopAndSnapshot() -> String {
        lock.lock()
        accepting = false
        let captured = bytes
        lock.unlock()
        guard !captured.isEmpty else { return "" }

        // Startup diagnostics are emitted only before /health succeeds. Keep
        // control characters out of the log and cap the rendered message too.
        let text = String(decoding: captured, as: UTF8.self)
        let lines = text.split(whereSeparator: \.isNewline).prefix(24)
        let sanitized = lines.map { line in
            line.unicodeScalars.filter { scalar in
                scalar == "\t" || scalar.value >= 0x20
            }
        }.map(String.init).joined(separator: " | ")
        return String(sanitized.prefix(2_000))
    }

    func stop() {
        lock.lock()
        accepting = false
        lock.unlock()
    }
}

/// A synchronous shutdown hook for AppKit's non-async termination delegate.
/// The actor remains the source of truth during normal operation; this holder
/// only protects the Process reference needed to send SIGTERM before the app
/// exits.
private final class SidecarProcessRegistry: @unchecked Sendable {
    private let lock = NSLock()
    private var process: Process?
    private var shutdown = SidecarShutdownState()

    /// Atomically hands a launched process to the termination path. If AppKit
    /// has already begun shutdown, the just-launched process is terminated
    /// here so it cannot escape through the run/register race window.
    @discardableResult
    func register(_ process: Process) -> Bool {
        lock.lock()
        guard shutdown.allowsProcessRegistration else {
            lock.unlock()
            process.terminate()
            return false
        }
        self.process = process
        lock.unlock()
        return true
    }

    func clear(_ process: Process) {
        lock.lock()
        if self.process === process {
            self.process = nil
        }
        lock.unlock()
    }

    func terminateSynchronously() {
        lock.lock()
        shutdown.beginShutdown()
        let process = self.process
        self.process = nil
        lock.unlock()
        process?.terminate()
    }
}

/// Client + lifecycle for the Python structure sidecar (spaCy + benepar).
/// The sidecar delivers deterministic teaching chunk trees; whole-sentence
/// translation comes separately from the local HY-MT2 model.
actor Sidecar {
    static let shared = Sidecar()

    /// Passed explicitly rather than left to server.py's default, so the cost
    /// of an idle sidecar (~3.2 GB) is visible on the side that spawns it.
    ///
    /// 120s was too eager to be a study tool: reading one paragraph between two
    /// lookups already exceeded it, and a restart costs 3.2s warm or ~19s once
    /// the OS has evicted torch's pages. Ten minutes covers a reading session
    /// while still releasing the memory when the app is genuinely idle.
    private static let idleExitSeconds = 600

    private let port: Int
    private let authToken: String
    private var process: Process?
    private var lifecycle = SidecarLifecycleState()
    private var startupDiagnostics: SidecarDiagnosticBuffer?
    private var sidecarReady = false
    private var structureCache: [String: SidecarStructure] = [:]
    private var structureOrder: [String] = []

    private static let processRegistry = SidecarProcessRegistry()
    private static let maxStartupDiagnosticBytes = 16 * 1024
    /// Must match `PARSE_PROTOCOL_VERSION` in sidecar/server.py.
    private static let parseProtocolVersion = 4

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
        let parseProtocolVersion: Int?
    }

    /// Pure probe: asks whether *our* sidecar is answering with a protocol we
    /// speak. Recording that fact is `markReady()`'s job — a predicate that
    /// also flipped `sidecarReady` meant a bare health check silently decided
    /// whether a later crash counted as a startup failure.
    private func probeHealth(expectedGeneration: UInt64? = nil) async -> Bool {
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
        // Only the current tree protocol. Accepting v3 as well let an old
        // checkout answer through `sidecarScript` and hand this build a shape
        // it decodes wrong — a stricter probe fails loudly instead.
        guard health.ok,
              health.parseProtocolVersion == Self.parseProtocolVersion else { return false }
        if let expectedGeneration,
           !lifecycle.acceptsHealthResponse(
               generation: expectedGeneration,
               processIsRunning: process?.isRunning == true
           ) {
            return false
        }
        return true
    }

    /// Startup is over: stop buffering the child's stderr, and stop reading a
    /// later exit as a launch failure whose diagnostics are worth logging.
    private func markReady() {
        startupDiagnostics?.stop()
        sidecarReady = true
    }

    private func ensureHealthy() async -> Bool {
        let currentGeneration = process?.isRunning == true ? lifecycle.generation : nil
        if await probeHealth(expectedGeneration: currentGeneration) {
            markReady()
            return true
        }
        launchIfNeeded()
        guard process?.isRunning == true, lifecycle.phase == .running else { return false }
        let launchedGeneration = lifecycle.generation
        // Measured on this machine: a warm start reaches /health in ~3.2s, but
        // once the OS has evicted torch's pages the import alone costs 15s and
        // the whole start ~19s. Eviction happens precisely under memory
        // pressure, i.e. when everything else is slow too, so a 30s budget had
        // barely 1.5x headroom and would have reported "engine unavailable" for
        // a sidecar that was merely still loading. 60s costs nothing when fast.
        for _ in 0..<120 {
            do {
                try await Task.sleep(nanoseconds: 500_000_000)
            } catch {
                return false
            }
            if await probeHealth(expectedGeneration: launchedGeneration) {
                markReady()
                return true
            }
        }
        return false
    }

    /// Start and load the deterministic parser without parsing a fake sentence.
    /// App launch uses this so the first user request can return structure fast.
    func warmUp() async {
        _ = await ensureHealthy()
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
        if let staleProcess = process {
            Self.processRegistry.clear(staleProcess)
            self.process = nil
            lifecycle.processExited()
        }
        guard lifecycle.beginLaunch() else { return }

        let script = sidecarScriptPath()
        guard FileManager.default.fileExists(atPath: script) else {
            ThornLog.info("sidecar script not found at \(script)")
            lifecycle.launchFailed()
            return
        }
        let p = Process()
        Self.configureProcess(
            p,
            script: script,
            port: port,
            idleExitSeconds: Self.idleExitSeconds,
            authToken: authToken,
            environment: ProcessInfo.processInfo.environment
        )
        let diagnostics = SidecarDiagnosticBuffer(limit: Self.maxStartupDiagnosticBytes)
        let stdout = Pipe()
        let stderr = Pipe()
        stdout.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            diagnostics.append(data, stream: "stdout")
            if data.isEmpty { handle.readabilityHandler = nil }
        }
        stderr.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            diagnostics.append(data, stream: "stderr")
            if data.isEmpty { handle.readabilityHandler = nil }
        }
        p.standardOutput = stdout
        p.standardError = stderr
        p.terminationHandler = { [weak self, diagnostics] terminated in
            let summary = diagnostics.stopAndSnapshot()
            let reason = terminated.terminationReason
            let status = terminated.terminationStatus
            Task { [weak self] in
                await self?.sidecarDidTerminate(
                    terminated,
                    reason: reason,
                    status: status,
                    diagnostics: summary
                )
            }
        }
        do {
            try p.run()
            guard Self.processRegistry.register(p) else {
                diagnostics.stop()
                lifecycle.launchFailed()
                ThornLog.info("sidecar launch cancelled because the app is terminating")
                return
            }
            process = p
            startupDiagnostics = diagnostics
            sidecarReady = false
            _ = lifecycle.launchSucceeded()
            ThornLog.info("sidecar launched, pid \(p.processIdentifier)")
        } catch {
            diagnostics.stop()
            lifecycle.launchFailed()
            ThornLog.info("sidecar launch failed: \(error)")
        }
    }

    /// Finder launches UI-element apps with `/` as their working directory.
    /// NLTK's import-security hook treats every absolute module path as being
    /// inside that directory and aborts during startup, so anchor the child to
    /// the narrow directory that contains its script instead.
    static func configureProcess(
        _ process: Process,
        script: String,
        port: Int,
        idleExitSeconds: Int,
        authToken: String,
        environment inheritedEnvironment: [String: String]
    ) {
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.currentDirectoryURL = URL(fileURLWithPath: script)
            .deletingLastPathComponent()
        // Login shell keeps uv on PATH. Values are passed as positional
        // parameters so a custom path cannot be interpreted as shell syntax.
        process.arguments = [
            "-lc",
            "exec uv run --script \"$1\" --port \"$2\" --idle-exit \"$3\"",
            "thorn-sidecar",
            script,
            String(port),
            String(idleExitSeconds),
        ]
        var environment = inheritedEnvironment
        environment["THORN_SIDECAR_TOKEN"] = authToken
        process.environment = environment
    }

    private func sidecarDidTerminate(
        _ terminated: Process,
        reason: Process.TerminationReason,
        status: Int32,
        diagnostics: String
    ) {
        let isCurrent = process === terminated
        let wasReady = sidecarReady
        if isCurrent {
            process = nil
            lifecycle.processExited()
            startupDiagnostics = nil
            sidecarReady = false
            Self.processRegistry.clear(terminated)
        }
        // A process that never reached /health failed before any sentence was
        // sent. Its bounded startup diagnostics are safe and actionable.
        if !wasReady, !diagnostics.isEmpty {
            let reasonText = reason == .uncaughtSignal ? "signal" : "exit"
            ThornLog.info(
                "sidecar \(reasonText) status=\(status), startup diagnostics: \(diagnostics)"
            )
        } else if status != 0 {
            ThornLog.info("sidecar exited with status \(status)")
        }
    }

    private func sidecarScriptPath() -> String {
        // An explicit override remains useful while developing a sidecar in a
        // separate checkout.
        if let custom = UserDefaults.standard.string(forKey: "sidecarScript") {
            return custom
        }

        // Installed builds carry the complete runtime sidecar next to the app
        // resources, so moving or deleting the source checkout cannot break
        // parsing.
        if let resourceURL = Bundle.main.resourceURL {
            let bundled = resourceURL
                .appendingPathComponent("sidecar", isDirectory: true)
                .appendingPathComponent("server.py")
            if FileManager.default.fileExists(atPath: bundled.path) {
                return bundled.path
            }
        }

        // SwiftPM development builds do not run bundle.sh. #filePath points
        // back into Sources/Thorn, from which the repository sidecar is stable.
        let sourceCheckout = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent("sidecar", isDirectory: true)
            .appendingPathComponent("server.py")
        if FileManager.default.fileExists(atPath: sourceCheckout.path) {
            return sourceCheckout.path
        }

        // Keep the historical fallback only to produce an actionable missing-
        // script error for old unbundled installs.
        return NSString(string: "~/xznm/code/Thorn/sidecar/server.py").expandingTildeInPath
    }

    func terminate() {
        let activeProcess = process
        activeProcess?.terminate()
        if let activeProcess {
            Self.processRegistry.clear(activeProcess)
        }
        process = nil
        lifecycle.processExited()
        startupDiagnostics?.stop()
        startupDiagnostics = nil
        sidecarReady = false
    }

    /// Called synchronously by `applicationWillTerminate`; unlike an
    /// un-awaited detached task this sends SIGTERM before AppKit tears down
    /// the process hosting the actor.
    nonisolated static func terminateSynchronously() {
        processRegistry.terminateSynchronously()
    }
}
