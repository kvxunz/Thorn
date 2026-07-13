import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings = SettingsStore.shared
    @State private var ollamaModels: [String] = []
    @State private var customModels: [String] = []
    @State private var modelFetchError: String?

    var body: some View {
        Form {
            Section("引擎") {
                Picker("默认引擎", selection: $settings.provider) {
                    ForEach(Provider.allCases) { p in
                        Text(p.label).tag(p)
                    }
                }
                .pickerStyle(.segmented)
            }

            if settings.provider == .ollama {
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
            } else {
                Section("自定义端点（Sub2API 等 OpenAI 兼容）") {
                    TextField("Base URL", text: $settings.customBaseURL, prompt: Text("https://your-relay.example.com/v1"))
                    SecureField("API Key", text: $settings.customAPIKey)
                    Picker("协议", selection: $settings.customWireAPI) {
                        ForEach(WireAPI.allCases) { wire in
                            Text(wire.label).tag(wire)
                        }
                    }
                    .pickerStyle(.segmented)
                    HStack {
                        if customModels.isEmpty {
                            TextField("模型", text: $settings.customModel, prompt: Text("如 gpt-5.4，可手动填写"))
                        } else {
                            Picker("模型", selection: $settings.customModel) {
                                ForEach(customModels, id: \.self) { Text($0).tag($0) }
                            }
                        }
                        Button("获取模型列表") { Task { await fetchCustomModels() } }
                            .disabled(settings.customBaseURL.isEmpty)
                    }
                    Text("Codex 订阅型网关选 Responses；普通中转选 Chat Completions。模型列表拉不到就手动填模型名。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let modelFetchError {
                        Text(modelFetchError)
                            .font(.caption)
                            .foregroundStyle(.red)
                    }
                }
            }

            Section("使用") {
                Text("在任意应用中选中英文句子，按 ⌥D 拆解。Esc 或点击外部关闭浮窗。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 440, height: 500)
        .task { await fetchOllamaModels() }
    }

    private func fetchOllamaModels() async {
        let client = LLMClient(baseURL: SettingsStore.ollamaBaseURL, model: "", apiKey: nil)
        if let models = try? await client.listModels(), !models.isEmpty {
            ollamaModels = models
            if !models.contains(settings.ollamaModel), let first = models.first {
                settings.ollamaModel = first
            }
        }
    }

    private func fetchCustomModels() async {
        modelFetchError = nil
        let ep = SettingsStore.shared.endpoint(for: .custom)
        let client = LLMClient(baseURL: ep.baseURL, model: "", apiKey: ep.apiKey)
        do {
            let models = try await client.listModels()
            customModels = models
            if !models.contains(settings.customModel), let first = models.first {
                settings.customModel = first
            }
        } catch {
            modelFetchError = error.localizedDescription
        }
    }
}
