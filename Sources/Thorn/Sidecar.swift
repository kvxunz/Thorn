import Foundation

/// Client + lifecycle for the Python structure sidecar (spaCy + benepar).
/// The sidecar delivers deterministic chunk trees with empty glosses; the
/// local LLM then only fills glosses and the translation.
actor Sidecar {
    static let shared = Sidecar()

    static let port = 48620
    private var process: Process?
    private var launchAttempted = false

    private var baseURL: String { "http://127.0.0.1:\(Self.port)" }

    private struct StructureResponse: Decodable {
        let chunks: [Chunk]
    }

    /// Fetch the deterministic structure; nil if the sidecar is unavailable.
    func structure(for sentence: String) async -> [Chunk]? {
        if !(await isHealthy()) {
            launchIfNeeded()
            // give a cold sidecar a moment; models take a few seconds to load
            for _ in 0..<20 {
                try? await Task.sleep(nanoseconds: 500_000_000)
                if await isHealthy() { break }
            }
            guard await isHealthy() else { return nil }
        }
        guard let url = URL(string: baseURL + "/parse") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 30
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONEncoder().encode(["text": sentence])
        guard let (data, response) = try? await URLSession.shared.data(for: req),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let decoded = try? JSONDecoder().decode(StructureResponse.self, from: data),
              !decoded.chunks.isEmpty else {
            ThornLog.info("sidecar parse failed")
            return nil
        }
        return decoded.chunks
    }

    private func isHealthy() async -> Bool {
        guard let url = URL(string: baseURL + "/health") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        guard let (data, _) = try? await URLSession.shared.data(for: req) else { return false }
        return String(data: data, encoding: .utf8)?.contains("true") == true
    }

    /// Spawn `uv run server.py` once per app session. The sidecar exits itself
    /// after 15 minutes idle; we respawn on the next request.
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
        // login shell so uv (~/.local/bin) is on PATH
        p.arguments = ["-lc", "exec uv run --script '\(script)' --port \(Self.port)"]
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
