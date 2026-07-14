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
        .frame(minWidth: 400, idealWidth: 460, maxWidth: .infinity,
               maxHeight: .infinity, alignment: .topLeading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(Color.primary.opacity(0.08))
        )
        .overlay(alignment: .topTrailing) {
            if case .result = state.status {
                HStack(spacing: 10) {
                    engineToggle
                    pinButton
                }
                .padding(10)
            }
        }
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
            // Sentence flows like the original text: trunk bold and dark,
            // modifiers in their role color — sense groups read by shade.
            Text(attributedSentence(headerChunks(result)))
                .lineSpacing(5)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .padding(.leading, 16)
                .padding(.trailing, 60) // room for cloud + pin in the corner
                .padding(.top, 16)
                .padding(.bottom, 12)

            Divider().padding(.horizontal, 12)

            // Chunk cards; children nest under their parent with a guide line.
            // Same descent as the header: skip a single all-covering wrapper.
            // Deep trees scroll so the translation stays visible.
            let cards = VStack(alignment: .leading, spacing: 2) {
                ForEach(headerChunks(result)) { chunk in
                    chunkTree(chunk, depth: 0)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)

            if nodeCount(result.chunks) > 14 {
                ScrollView(.vertical, showsIndicators: true) {
                    cards
                }
                .frame(minHeight: 180,
                       idealHeight: min(540, (NSScreen.main?.visibleFrame.height ?? 900) * 0.45),
                       maxHeight: .infinity)
            } else {
                cards
            }

            Divider().padding(.horizontal, 12)

            // Full translation (arrives last while streaming)
            Group {
                if result.translation.isEmpty {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("拆解中…")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Text(result.translation)
                        .font(.system(size: 13))
                        .foregroundStyle(.primary.opacity(0.85))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
    }

    /// Single cloud button that flips engines: filled = cloud active, outline = local.
    @ViewBuilder
    private var engineToggle: some View {
        if settings.hasCustomEndpoint {
            Button {
                state.switchEngine(to: state.usingCloud ? .ollama : .custom)
            } label: {
                Image(systemName: state.usingCloud ? "cloud.fill" : "cloud")
                    .font(.system(size: 12))
                    .foregroundStyle(state.usingCloud ? Color.accentColor : Color.secondary.opacity(0.6))
            }
            .buttonStyle(.plain)
            .help(state.usingCloud ? "当前：云端 — 点击切回本地" : "当前：本地 — 点击用云端拆")
        }
    }

    private func nodeCount(_ chunks: [Chunk]) -> Int {
        chunks.reduce(0) { $0 + 1 + nodeCount($1.children ?? []) }
    }

    /// The level worth showing: descend while the model wrapped everything
    /// into one container chunk (e.g. imperative "imagine that ...").
    private func headerChunks(_ result: ParseResult) -> [Chunk] {
        var chunks = result.chunks
        while chunks.count == 1, let kids = chunks[0].children, !kids.isEmpty {
            chunks = kids
        }
        return chunks
    }

    /// Three tiers: S/V/O heaviest (near-black bold), complement middle, and
    /// every other role in its fixed role color — same hues as the cards, so
    /// the color itself teaches the component type.
    private func attributedSentence(_ chunks: [Chunk]) -> AttributedString {
        var out = AttributedString()
        for (index, chunk) in chunks.enumerated() {
            var piece = AttributedString(chunk.text)
            let weight: Font.Weight
            let color: Color
            switch chunk.role {
            case .subject, .verb, .object:
                weight = .bold
                color = chunk.role.emphaticColor
            case .complement:
                weight = .medium
                color = Color.primary.opacity(0.62)
            default:
                weight = .regular
                color = chunk.role.color
            }
            piece.font = .system(size: 15, weight: weight, design: .serif)
            piece.foregroundColor = color
            if state.hoveredChunkID == chunk.id {
                piece.backgroundColor = chunk.role.color.opacity(0.22)
            }
            out += piece
            if index < chunks.count - 1, !chunk.text.hasSuffix(" ") {
                out += AttributedString(" ")
            }
        }
        return out
    }

    /// Parent row, then children indented behind a guide line in the parent's color.
    private func chunkTree(_ chunk: Chunk, depth: Int) -> AnyView {
        AnyView(
            VStack(alignment: .leading, spacing: 2) {
                chunkRow(chunk, depth: depth)
                if let kids = chunk.children {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(kids) { chunkTree($0, depth: depth + 1) }
                    }
                    .padding(.leading, 16)
                    .overlay(alignment: .leading) {
                        RoundedRectangle(cornerRadius: 1)
                            .fill(chunk.role.color.opacity(0.25))
                            .frame(width: 2)
                            .padding(.leading, 7)
                            .padding(.vertical, 3)
                    }
                }
            }
        )
    }

    private func chunkRow(_ chunk: Chunk, depth: Int = 0) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(chunk.role.color.opacity(depth > 0 ? 0.55 : 1))
                .frame(width: 3, height: 14)
                .offset(y: 1)

            Text(chunk.text)
                .font(.system(size: depth > 0 ? 11.5 : 12.5, design: .serif))
                // A chunk about to be decomposed below is a summary line: dim it.
                .foregroundStyle(.primary.opacity(chunk.children != nil ? 0.55 : (depth > 0 ? 0.75 : 0.9)))
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
                .font(.system(size: depth > 0 ? 11 : 12))
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
