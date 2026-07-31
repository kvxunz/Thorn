import Foundation

struct OllamaMessage: Sendable {
    let role: String
    let content: String
}

enum OllamaError: LocalizedError {
    case badURL
    case unavailable
    case http(Int, String)
    case emptyResponse
    case badResponse(String)
    case missingModel(String)
    case timedOut(TimeInterval)

    var errorDescription: String? {
        switch self {
        case .badURL: return "Ollama 地址无效"
        case .unavailable: return "无法连接本地 Ollama，请确认服务已经启动"
        case .http(let status, let body): return "Ollama HTTP \(status)：\(body.prefix(200))"
        case .emptyResponse: return "本地模型返回为空"
        case .badResponse(let body): return "无法读取 Ollama 返回：\(body.prefix(200))"
        case .missingModel(let model):
            return "本地缺少模型 \(model)\n请执行：ollama pull \(model)"
        case .timedOut(let seconds):
            return "本地模型在 \(Int(seconds)) 秒内未完成"
        }
    }
}

enum OllamaRequestFactory {
    static func chatBody(
        model: String,
        messages: [OllamaMessage],
        schema: Data?,
        temperature: Double,
        contextWindow: Int,
        maximumOutputTokens: Int,
        thinking: Bool?
    ) throws -> Data {
        var body: [String: Any] = [
            "model": model,
            "messages": messages.map { ["role": $0.role, "content": $0.content] },
            "stream": false,
            // A resident HY-MT2 weighs ~6.5 GB, and translation here is
            // one-shot: no history, no shared prefix, so a warm model buys
            // nothing after the panel closes. Note this per-request value
            // overrides OLLAMA_KEEP_ALIVE — setting the env var has no effect.
            "keep_alive": "60s",
            "options": [
                "temperature": temperature,
                "num_ctx": contextWindow,
                "num_predict": maximumOutputTokens,
            ],
        ]
        if let thinking { body["think"] = thinking }
        if let schema {
            body["format"] = try JSONSerialization.jsonObject(with: schema)
        }
        return try JSONSerialization.data(withJSONObject: body)
    }
}

/// Local Ollama gateway for whole-sentence HY-MT2 translation.
/// Cancellation of the owning Task cancels URLSession work from stale panels.
actor OllamaCoordinator {
    static let shared = OllamaCoordinator()

    private var verifiedModels = Set<String>()

    func chat(
        model: String,
        messages: [OllamaMessage],
        schema: Data? = nil,
        temperature: Double,
        contextWindow: Int,
        maximumOutputTokens: Int,
        thinking: Bool? = false,
        timeout: TimeInterval = 120
    ) async throws -> String {
        try Task.checkCancellation()
        try await ensureModel(model)
        let body = try OllamaRequestFactory.chatBody(
            model: model,
            messages: messages,
            schema: schema,
            temperature: temperature,
            contextWindow: contextWindow,
            maximumOutputTokens: maximumOutputTokens,
            thinking: thinking
        )
        let data = try await request(path: "/api/chat", body: body, timeout: timeout)
        struct Response: Decodable {
            struct Message: Decodable { let content: String? }
            let message: Message
        }
        guard let decoded = try? JSONDecoder().decode(Response.self, from: data) else {
            throw OllamaError.badResponse(String(data: data, encoding: .utf8) ?? "")
        }
        guard let content = decoded.message.content,
              !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw OllamaError.emptyResponse
        }
        return content
    }

    func listModels() async throws -> [String] {
        let data = try await request(path: "/api/tags", body: nil, timeout: 15)
        struct Response: Decodable {
            struct Model: Decodable {
                let name: String?
                let model: String?
            }
            let models: [Model]
        }
        guard let response = try? JSONDecoder().decode(Response.self, from: data) else {
            throw OllamaError.badResponse(String(data: data, encoding: .utf8) ?? "")
        }
        let names = response.models.compactMap { $0.name ?? $0.model }.sorted()
        verifiedModels.formUnion(names)
        return names
    }

    private func ensureModel(_ model: String) async throws {
        guard !model.isEmpty else { throw OllamaError.missingModel(model) }
        if verifiedModels.contains(model) { return }
        let body = try JSONSerialization.data(withJSONObject: ["model": model])
        do {
            _ = try await request(path: "/api/show", body: body, timeout: 15)
            verifiedModels.insert(model)
        } catch OllamaError.http(let status, _) where status == 404 {
            throw OllamaError.missingModel(model)
        }
    }

    private func request(
        path: String,
        body: Data?,
        timeout: TimeInterval
    ) async throws -> Data {
        guard let url = URL(string: SettingsStore.ollamaNativeBaseURL + path) else {
            throw OllamaError.badURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = body == nil ? "GET" : "POST"
        request.timeoutInterval = timeout
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as URLError where error.code == .timedOut {
            throw OllamaError.timedOut(timeout)
        } catch {
            ThornLog.info("Ollama request failed: \(error.localizedDescription)")
            throw OllamaError.unavailable
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw OllamaError.http(
                http.statusCode,
                String(data: data, encoding: .utf8) ?? ""
            )
        }
        return data
    }
}
