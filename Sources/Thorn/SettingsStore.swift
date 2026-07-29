import Foundation

/// App settings, stored in UserDefaults. Local pipeline only: the sidecar
/// delivers structure; the Ollama translation model is the single knob.
final class SettingsStore: ObservableObject {
    static let shared = SettingsStore()

    private let defaults = UserDefaults.standard

    @Published var translationModel: String {
        didSet { defaults.set(translationModel, forKey: "translationModel") }
    }

    static let ollamaNativeBaseURL = "http://127.0.0.1:11434"
    static let defaultTranslationModel = "hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K"

    /// Models retired from Thorn's local pipeline. Migrate an existing saved
    /// selection so deleting their Ollama weights cannot leave the app broken.
    private static let retiredOllamaModels: Set<String> = [
        "qwen3:30b-a3b-instruct-2507-q4_K_M",
        "qwen3:4b-instruct-2507-q4_K_M",
        "qwen3.5:4b-mlx",
        "qwen3.5:9b",
        "sun_leaf/HY-MT:7b",
        "kaelri/hy-mt2:7b",
    ]

    private init() {
        // Prefer the dedicated translation key; fall back to the older single
        // ollamaModel knob from the pre-fusion settings layout.
        let legacyModel = defaults.string(forKey: "ollamaModel")
        let saved = defaults.string(forKey: "translationModel") ?? legacyModel
        if let saved, !Self.retiredOllamaModels.contains(saved) {
            translationModel = saved
        } else {
            translationModel = Self.defaultTranslationModel
        }
        defaults.set(translationModel, forKey: "translationModel")
        defaults.removeObject(forKey: "ollamaModel")
        defaults.removeObject(forKey: "fusionModel")

        // Cloud parsing and teaching-fusion knobs were removed.
        for staleKey in ["provider", "customBaseURL",
                         "customModel", "customWireAPI"] {
            defaults.removeObject(forKey: staleKey)
        }
    }
}
