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
        case .connectionFailed: return "无法连接端点（Ollama 未启动？）"
        }
    }
}

/// Minimal OpenAI-compatible chat client. Works for Ollama and any relay (Sub2API etc.).
struct LLMClient {
    let baseURL: String
    let model: String
    let apiKey: String?

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

    func chat(system: String, user: String, jsonMode: Bool) async throws -> String {
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
        let body = ChatRequest(
            model: model,
            messages: [
                .init(role: "system", content: system),
                .init(role: "user", content: user),
            ],
            temperature: 0.2,
            response_format: jsonMode ? .init(type: "json_object") : nil,
            stream: false
        )
        req.httpBody = try JSONEncoder().encode(body)

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
        let decoded = try JSONDecoder().decode(ChatResponse.self, from: data)
        guard let content = decoded.choices.first?.message.content, !content.isEmpty else {
            throw LLMError.emptyResponse
        }
        return content
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
        struct ModelList: Decodable {
            struct Model: Decodable { let id: String }
            let data: [Model]
        }
        let data: Data
        do {
            (data, _) = try await URLSession.shared.data(for: req)
        } catch {
            throw LLMError.connectionFailed
        }
        let list = try JSONDecoder().decode(ModelList.self, from: data)
        return list.data.map(\.id).sorted()
    }
}
