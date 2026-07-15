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
    private var isLoadingCustomAPIKey = false

    @Published var provider: Provider {
        didSet {
            defaults.set(provider.rawValue, forKey: "provider")
            if Self.shouldLoadCustomAPIKey(for: provider, currentAPIKey: customAPIKey) {
                loadCustomAPIKeyIfNeeded()
            }
        }
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
        didSet {
            if !isLoadingCustomAPIKey {
                KeychainHelper.set(customAPIKey, account: "customAPIKey")
            }
        }
    }
    @Published var customWireAPI: WireAPI {
        didSet { defaults.set(customWireAPI.rawValue, forKey: "customWireAPI") }
    }

    static let ollamaBaseURL = "http://127.0.0.1:11434/v1"
    static let defaultOllamaModel = "hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K"

    /// Models retired from Thorn's local pipeline. Migrate an existing saved
    /// selection so deleting their Ollama weights cannot leave the app broken.
    private static let retiredOllamaModels: Set<String> = [
        "qwen3:30b-a3b-instruct-2507-q4_K_M",
        "qwen3:4b-instruct-2507-q4_K_M",
        "sun_leaf/HY-MT:7b",
        "kaelri/hy-mt2:7b",
    ]

    private init() {
        provider = Provider(rawValue: defaults.string(forKey: "provider") ?? "") ?? .ollama
        let savedModel = defaults.string(forKey: "ollamaModel")
        if let savedModel, !Self.retiredOllamaModels.contains(savedModel) {
            ollamaModel = savedModel
        } else {
            ollamaModel = Self.defaultOllamaModel
        }
        customBaseURL = defaults.string(forKey: "customBaseURL") ?? ""
        customModel = defaults.string(forKey: "customModel") ?? ""
        customAPIKey = ""
        customWireAPI = WireAPI(rawValue: defaults.string(forKey: "customWireAPI") ?? "") ?? .chatCompletions

        if Self.shouldLoadCustomAPIKey(for: provider, currentAPIKey: customAPIKey) {
            loadCustomAPIKeyIfNeeded()
        }

        if savedModel != ollamaModel {
            defaults.set(ollamaModel, forKey: "ollamaModel")
        }
        defaults.removeObject(forKey: "translationModel")
    }

    static func shouldLoadCustomAPIKey(
        for provider: Provider,
        currentAPIKey: String
    ) -> Bool {
        provider == .custom && currentAPIKey.isEmpty
    }

    private func loadCustomAPIKeyIfNeeded() {
        guard customAPIKey.isEmpty else { return }
        isLoadingCustomAPIKey = true
        customAPIKey = KeychainHelper.get(account: "customAPIKey") ?? ""
        isLoadingCustomAPIKey = false
    }

    /// Endpoint config for a given provider (nil = current provider).
    func endpoint(for provider: Provider? = nil) -> (baseURL: String, model: String, apiKey: String?, wireAPI: WireAPI) {
        let endpointProvider = provider ?? self.provider
        switch endpointProvider {
        case .ollama:
            return (Self.ollamaBaseURL, ollamaModel, nil, .chatCompletions)
        case .custom:
            if Self.shouldLoadCustomAPIKey(
                for: endpointProvider,
                currentAPIKey: customAPIKey
            ) {
                loadCustomAPIKeyIfNeeded()
            }
            return (customBaseURL, customModel, customAPIKey.isEmpty ? nil : customAPIKey, customWireAPI)
        }
    }

    var hasCustomEndpoint: Bool {
        !customBaseURL.isEmpty && !customModel.isEmpty
    }
}
