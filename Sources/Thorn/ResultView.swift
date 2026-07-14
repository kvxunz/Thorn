import SwiftUI

struct ResultView: View {
    @ObservedObject var state: PanelState
    @ObservedObject var settings = SettingsStore.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            switch state.status {
            case .loading:
                loadingView
            case .error(let message):
                errorView(message)
            case .result(let result):
                resultView(result)
            }
        }
        .frame(width: 460)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(Color.primary.opacity(0.08))
        )
    }

    private var pinButton: some View {
        Button {
            state.pinned.toggle()
        } label: {
            Image(systemName: state.pinned ? "pin.fill" : "pin")
                .font(.system(size: 11))
                .foregroundStyle(state.pinned ? Color.orange : Color.secondary.opacity(0.6))
        }
        .buttonStyle(.plain)
        .help(state.pinned ? "取消固定" : "固定：点击外部不再关闭")
    }

    private var loadingView: some View {
        HStack(spacing: 10) {
            ProgressView().controlSize(.small)
            Text(state.usingCloud ? "云端拆解中…" : "拆解中…")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func errorView(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("拆解失败", systemImage: "exclamationmark.triangle")
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                engineToggle
            }
            Text(message)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func resultView(_ result: ParseResult) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            // Sentence with trunk emphasis
            FlowLayout(spacing: 5) {
                ForEach(result.chunks) { chunk in
                    Text(chunk.text)
                        .font(.system(size: 14, weight: chunk.role.isTrunk ? .semibold : .regular, design: .serif))
                        .foregroundStyle(chunk.role.isTrunk ? Color.primary : Color.primary.opacity(0.55))
                        .padding(.horizontal, 3)
                        .padding(.vertical, 1)
                        .background(
                            RoundedRectangle(cornerRadius: 4)
                                .fill(state.hoveredChunkID == chunk.id
                                      ? chunk.role.color.opacity(0.28)
                                      : Color.clear)
                        )
                        .onHover { hovering in
                            state.hoveredChunkID = hovering ? chunk.id : nil
                        }
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)
            .padding(.bottom, 12)

            Divider().padding(.horizontal, 12)

            // Chunk cards
            VStack(alignment: .leading, spacing: 2) {
                ForEach(result.chunks) { chunk in
                    chunkRow(chunk)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)

            Divider().padding(.horizontal, 12)

            // Full translation + controls, one row
            HStack(alignment: .bottom, spacing: 10) {
                Text(result.translation)
                    .font(.system(size: 13))
                    .foregroundStyle(.primary.opacity(0.85))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)

                engineToggle
                pinButton
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
    }

    @ViewBuilder
    private var engineToggle: some View {
        if settings.hasCustomEndpoint {
            HStack(spacing: 2) {
                engineButton("本地", .ollama)
                engineButton("云端", .custom)
            }
            .padding(2)
            .background(Color.primary.opacity(0.06), in: Capsule())
        }
    }

    private func engineButton(_ title: String, _ provider: Provider) -> some View {
        let active = state.activeProvider == provider
        return Button {
            state.switchEngine(to: provider)
        } label: {
            Text(title)
                .font(.system(size: 10.5, weight: active ? .semibold : .regular))
                .foregroundStyle(active ? Color.primary : Color.secondary)
                .padding(.horizontal, 8)
                .padding(.vertical, 2)
                .background(active ? AnyShapeStyle(.regularMaterial) : AnyShapeStyle(Color.clear), in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private func chunkRow(_ chunk: Chunk) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(chunk.role.color)
                .frame(width: 3, height: 14)
                .offset(y: 1)

            Text(chunk.text)
                .font(.system(size: 12.5, design: .serif))
                .foregroundStyle(.primary.opacity(0.9))
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(chunk.role.label)
                .font(.system(size: 10))
                .foregroundStyle(chunk.role.color)
                .padding(.horizontal, 5)
                .padding(.vertical, 1)
                .background(chunk.role.color.opacity(0.12), in: Capsule())
                .fixedSize()

            Text(chunk.gloss)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
                .frame(width: 130, alignment: .leading)
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(state.hoveredChunkID == chunk.id ? chunk.role.color.opacity(0.10) : Color.clear)
        )
        .onHover { hovering in
            state.hoveredChunkID = hovering ? chunk.id : nil
        }
    }
}
