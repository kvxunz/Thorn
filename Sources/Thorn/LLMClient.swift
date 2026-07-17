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
        case .notConfigured: return "本地模型未配置，请在设置里选择 Ollama 模型"
        case .badURL: return "端点 URL 无效"
        case .http(let code, let body): return "HTTP \(code): \(body.prefix(200))"
        case .emptyResponse: return "模型返回为空"
        case .badJSON(let raw): return "JSON 解析失败: \(raw.prefix(200))"
        case .connectionFailed: return "无法连接端点（服务未启动或正在重启？）"
        }
    }
}

/// Minimal OpenAI-compatible chat client for the local Ollama endpoint.
struct LLMClient {
    let baseURL: String
    let model: String

    private struct ChatRequest: Encodable {
        struct Message: Encodable {
            let role: String
            let content: String
        }
        let model: String
        let messages: [Message]
        let temperature: Double
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
        temperature: Double = 0.2
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
            stream: false
        )
        let data = try await post(path: "/chat/completions", body: try JSONEncoder().encode(body))
        let decoded = try JSONDecoder().decode(ChatResponse.self, from: data)
        guard let content = decoded.choices.first?.message.content, !content.isEmpty else {
            throw LLMError.emptyResponse
        }
        return content
    }

    private func post(path: String, body: Data) async throws -> Data {
        guard let url = URL(string: baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + path) else {
            throw LLMError.badURL
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 120
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
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

    /// GET /models — for the settings model picker.
    func listModels() async throws -> [String] {
        guard let url = URL(string: baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/models") else {
            throw LLMError.badURL
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 15
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
