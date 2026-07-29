import SwiftUI

struct SettingsView: View {
    @ObservedObject var settings = SettingsStore.shared
    @State private var ollamaModels: [String] = []
    @State private var modelListLoaded = false

    var body: some View {
        Form {
            Section("本地 Ollama") {
                modelPicker("整句翻译", selection: $settings.translationModel)
                HStack {
                    Text("端点固定为 \(SettingsStore.ollamaNativeBaseURL)")
                    Spacer()
                    Button("刷新模型") { Task { await fetchOllamaModels() } }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                if modelListLoaded,
                   !ollamaModels.contains(settings.translationModel) {
                    Text("缺少翻译模型：ollama pull \(settings.translationModel)")
                        .font(.caption.monospaced())
                        .foregroundStyle(.orange)
                        .textSelection(.enabled)
                }
                Text("句法拆分由本地 spaCy/Benepar 引擎完成，不经过大模型。")
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
        if let models = try? await OllamaCoordinator.shared.listModels() {
            ollamaModels = models
            modelListLoaded = true
        } else {
            modelListLoaded = false
        }
    }

    @ViewBuilder
    private func modelPicker(_ title: String, selection: Binding<String>) -> some View {
        if ollamaModels.isEmpty {
            TextField(title, text: selection)
        } else {
            let choices = ollamaModels.contains(selection.wrappedValue)
                ? ollamaModels
                : [selection.wrappedValue] + ollamaModels
            Picker(title, selection: selection) {
                ForEach(choices, id: \.self) { model in
                    Text(model + (ollamaModels.contains(model) ? "" : "（未安装）")).tag(model)
                }
            }
        }
    }
}
