import Foundation

enum Provider: String, Codable, CaseIterable, Identifiable {
    case ollama
    case custom

    var id: String { rawValue }

    var label: String {
        switch self {
        case .ollama: return "本地 Ollama"
        case .custom: return "自定义端点"
        }
    }
}

/// App settings. API key lives in Keychain; the rest in UserDefaults.
final class SettingsStore: ObservableObject {
    static let shared = SettingsStore()

    private let defaults = UserDefaults.standard

    @Published var provider: Provider {
        didSet { defaults.set(provider.rawValue, forKey: "provider") }
    }
    @Published var ollamaModel: String {
        didSet { defaults.set(ollamaModel, forKey: "ollamaModel") }
    }
    @Published var customBaseURL: String {
        didSet { defaults.set(customBaseURL, forKey: "customBaseURL") }
    }
    @Published var customModel: String {
        didSet { defaults.set(customModel, forKey: "customModel") }
    }
    @Published var customAPIKey: String {
        didSet { KeychainHelper.set(customAPIKey, account: "customAPIKey") }
    }

    static let ollamaBaseURL = "http://127.0.0.1:11434/v1"

    private init() {
        provider = Provider(rawValue: defaults.string(forKey: "provider") ?? "") ?? .ollama
        ollamaModel = defaults.string(forKey: "ollamaModel") ?? "qwen3:30b-a3b-instruct-2507-q4_K_M"
        customBaseURL = defaults.string(forKey: "customBaseURL") ?? ""
        customModel = defaults.string(forKey: "customModel") ?? ""
        customAPIKey = KeychainHelper.get(account: "customAPIKey") ?? ""
    }

    /// Endpoint config for a given provider (nil = current provider).
    func endpoint(for provider: Provider? = nil) -> (baseURL: String, model: String, apiKey: String?) {
        switch provider ?? self.provider {
        case .ollama:
            return (Self.ollamaBaseURL, ollamaModel, nil)
        case .custom:
            return (customBaseURL, customModel, customAPIKey.isEmpty ? nil : customAPIKey)
        }
    }

    var hasCustomEndpoint: Bool {
        !customBaseURL.isEmpty && !customModel.isEmpty
    }
}
