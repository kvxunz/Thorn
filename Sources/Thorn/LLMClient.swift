import Foundation

enum LLMError: LocalizedError {
    case notConfigured
    case badURL
    case http(Int, String)
    case emptyResponse
    case badJSON(String)
    case connectionFailed

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "自定义端点未配置，请在设置里填写 Base URL 和模型"
        case .badURL: return "端点 URL 无效"
        case .http(let code, let body): return "HTTP \(code): \(body.prefix(200))"
        case .emptyResponse: return "模型返回为空"
        case .badJSON(let raw): return "JSON 解析失败: \(raw.prefix(200))"
        case .connectionFailed: return "无法连接端点（服务未启动或正在重启？）"
        }
    }
}

enum WireAPI: String, CaseIterable, Identifiable {
    case chatCompletions = "chat"
    case responses = "responses"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .chatCompletions: return "Chat Completions"
        case .responses: return "Responses (Codex)"
        }
    }
}

/// Minimal OpenAI-compatible chat client. Works for Ollama and any relay (Sub2API etc.).
struct LLMClient {
    let baseURL: String
    let model: String
    let apiKey: String?
    var wireAPI: WireAPI = .chatCompletions

    private struct ChatRequest: Encodable {
        struct Message: Encodable {
            let role: String
            let content: String
        }
        struct ResponseFormat: Encodable {
            let type: String
        }
        let model: String
        let messages: [Message]
        let temperature: Double
        let response_format: ResponseFormat?
        let stream: Bool
    }

    private struct ChatResponse: Decodable {
        struct Choice: Decodable {
            struct Message: Decodable { let content: String? }
            let message: Message
        }
        let choices: [Choice]
    }

    func chat(
        system: String,
        user: String,
        jsonMode: Bool,
        temperature: Double = 0.2
    ) async throws -> String {
        switch wireAPI {
        case .chatCompletions:
            return try await chatCompletions(
                system: system,
                user: user,
                jsonMode: jsonMode,
                temperature: temperature
            )
        case .responses:
            return try await responses(system: system, user: user)
        }
    }

    private func post(path: String, body: Data) async throws -> Data {
        guard let url = URL(string: baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + path) else {
            throw LLMError.badURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 120
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let apiKey {
            req.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        req.httpBody = body

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: req)
        } catch {
            ThornLog.info("network error: \(error)")
            throw LLMError.connectionFailed
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw LLMError.http(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }
        return data
    }

    private func chatCompletions(
        system: String,
        user: String,
        jsonMode: Bool,
        temperature: Double
    ) async throws -> String {
        var messages: [ChatRequest.Message] = []
        if !system.isEmpty {
            messages.append(.init(role: "system", content: system))
        }
        messages.append(.init(role: "user", content: user))
        let body = ChatRequest(
            model: model,
            messages: messages,
            temperature: temperature,
            response_format: jsonMode ? .init(type: "json_object") : nil,
            stream: false
        )
        let data = try await post(path: "/chat/completions", body: try JSONEncoder().encode(body))
        let decoded = try JSONDecoder().decode(ChatResponse.self, from: data)
        guard let content = decoded.choices.first?.message.content, !content.isEmpty else {
            throw LLMError.emptyResponse
        }
        return content
    }

    /// OpenAI Responses API (Codex-style gateways). JSON output enforced by prompt only.
    private func responses(system: String, user: String) async throws -> String {
        struct ResponsesRequest: Encodable {
            let model: String
            let instructions: String
            let input: String
            let stream: Bool
        }
        struct ResponsesResponse: Decodable {
            struct Output: Decodable {
                struct Content: Decodable {
                    let type: String?
                    let text: String?
                }
                let type: String?
                let content: [Content]?
            }
            let output: [Output]?
            let output_text: String?
        }
        let body = ResponsesRequest(model: model, instructions: system, input: user, stream: false)
        let data = try await post(path: "/responses", body: try JSONEncoder().encode(body))
        let decoded = try JSONDecoder().decode(ResponsesResponse.self, from: data)

        if let direct = decoded.output_text, !direct.isEmpty { return direct }
        // Take any content item carrying text; gateways vary on type labels
        // ("output_text" / "text") and item ordering (reasoning first).
        let text = (decoded.output ?? [])
            .filter { $0.type != "reasoning" }
            .flatMap { $0.content ?? [] }
            .compactMap(\.text)
            .joined()
        guard !text.isEmpty else {
            ThornLog.info("responses raw body: \(String(data: data, encoding: .utf8)?.prefix(6000) ?? "<binary>")")
            throw LLMError.emptyResponse
        }
        return text
    }

    var supportsStreaming: Bool { wireAPI == .chatCompletions }

    /// SSE stream of content deltas (Chat Completions wire only).
    func chatStream(system: String, user: String, jsonMode: Bool) async throws -> AsyncThrowingStream<String, Error> {
        guard let url = URL(string: baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/chat/completions") else {
            throw LLMError.badURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 120
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let apiKey {
            req.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        var messages: [ChatRequest.Message] = []
        if !system.isEmpty {
            messages.append(.init(role: "system", content: system))
        }
        messages.append(.init(role: "user", content: user))
        let body = ChatRequest(
            model: model,
            messages: messages,
            temperature: 0.2,
            response_format: jsonMode ? .init(type: "json_object") : nil,
            stream: true
        )
        req.httpBody = try JSONEncoder().encode(body)

        let bytes: URLSession.AsyncBytes
        let response: URLResponse
        do {
            (bytes, response) = try await URLSession.shared.bytes(for: req)
        } catch {
            ThornLog.info("stream network error: \(error)")
            throw LLMError.connectionFailed
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            var body = ""
            for try await line in bytes.lines {
                body += line
                if body.count > 500 { break }
            }
            throw LLMError.http(http.statusCode, body)
        }

        struct Event: Decodable {
            struct Choice: Decodable {
                struct Delta: Decodable { let content: String? }
                let delta: Delta
            }
            let choices: [Choice]
        }

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    for try await line in bytes.lines {
                        guard line.hasPrefix("data: ") else { continue }
                        let payload = String(line.dropFirst(6))
                        if payload == "[DONE]" { break }
                        if let event = try? JSONDecoder().decode(Event.self, from: Data(payload.utf8)),
                           let content = event.choices.first?.delta.content, !content.isEmpty {
                            continuation.yield(content)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    /// GET /models — for the settings model picker.
    func listModels() async throws -> [String] {
        guard let url = URL(string: baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/models") else {
            throw LLMError.badURL
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 15
        if let apiKey {
            req.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: req)
        } catch {
            throw LLMError.connectionFailed
        }
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw LLMError.http(http.statusCode, String(data: data, encoding: .utf8) ?? "")
        }

        // Accept common shapes: {"data":[{"id":..}]}, {"models":[..]}, ["m1","m2"]
        struct Entry: Decodable {
            let id: String?
            let name: String?
            var modelID: String? { id ?? name }
        }
        struct Wrapped: Decodable {
            let data: [Entry]?
            let models: [Entry]?
        }
        let decoder = JSONDecoder()
        if let wrapped = try? decoder.decode(Wrapped.self, from: data),
           let entries = wrapped.data ?? wrapped.models {
            return entries.compactMap(\.modelID).sorted()
        }
        if let plain = try? decoder.decode([String].self, from: data) {
            return plain.sorted()
        }
        throw LLMError.badJSON(String(data: data, encoding: .utf8) ?? "")
    }
}
