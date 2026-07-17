import Foundation

/// App settings, stored in UserDefaults. Local pipeline only: the sidecar
/// delivers structure, the Ollama translation model is the single knob.
final class SettingsStore: ObservableObject {
    static let shared = SettingsStore()

    private let defaults = UserDefaults.standard

    @Published var ollamaModel: String {
        didSet { defaults.set(ollamaModel, forKey: "ollamaModel") }
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
        let savedModel = defaults.string(forKey: "ollamaModel")
        if let savedModel, !Self.retiredOllamaModels.contains(savedModel) {
            ollamaModel = savedModel
        } else {
            ollamaModel = Self.defaultOllamaModel
        }
        if savedModel != ollamaModel {
            defaults.set(ollamaModel, forKey: "ollamaModel")
        }

        // Cloud parsing was removed; scrub its persisted settings. The old
        // Keychain item ("customAPIKey") is left behind — deleting it would
        // need a Keychain prompt for nothing.
        for staleKey in ["translationModel", "provider", "customBaseURL",
                         "customModel", "customWireAPI"] {
            defaults.removeObject(forKey: staleKey)
        }
    }

    /// Endpoint config for the local pipeline.
    func endpoint() -> (baseURL: String, model: String) {
        (Self.ollamaBaseURL, ollamaModel)
    }
}
