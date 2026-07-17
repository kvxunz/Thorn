import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings = SettingsStore.shared
    @State private var ollamaModels: [String] = []

    var body: some View {
        Form {
            Section("本地 Ollama") {
                HStack {
                    if ollamaModels.isEmpty {
                        TextField("模型", text: $settings.ollamaModel)
                    } else {
                        Picker("模型", selection: $settings.ollamaModel) {
                            ForEach(ollamaModels, id: \.self) { Text($0).tag($0) }
                        }
                    }
                    Button("刷新") { Task { await fetchOllamaModels() } }
                }
                Text("端点固定为 \(SettingsStore.ollamaBaseURL)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Section("使用") {
                Text("在任意应用中选中英文句子，按 ⌥A 拆解，⌥Z 重现上次结果。Esc 或点击外部关闭浮窗。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 440, height: 300)
        .task { await fetchOllamaModels() }
    }

    private func fetchOllamaModels() async {
        let client = LLMClient(baseURL: SettingsStore.ollamaBaseURL, model: "")
        if let models = try? await client.listModels(), !models.isEmpty {
            ollamaModels = models
            if !models.contains(settings.ollamaModel), let first = models.first {
                settings.ollamaModel = first
            }
        }
    }
}
