import SwiftUI

struct ResultView: View {
    @ObservedObject var state: PanelState
    var onResizeDrag: ((CGSize) -> Void)? = nil
    @State private var lastDrag: CGSize = .zero

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
        // Whatever squeezing happens, the panel silhouette stays rounded.
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .strokeBorder(Color.primary.opacity(0.08))
        )
        .overlay(alignment: .topTrailing) {
            if case .result = state.status {
                pinButton.padding(10)
            }
        }
        .overlay(alignment: .bottomTrailing) {
            // Dedicated resize grip: the borderless window's system resize
            // border is only ~4px and hard to grab.
            if case .result = state.status {
                Image(systemName: "line.3.horizontal.decrease")
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                    .rotationEffect(.degrees(-45))
                    .frame(width: 20, height: 20, alignment: .bottomTrailing)
                    .padding(4)
                    .contentShape(Rectangle())
                    .gesture(
                        DragGesture(minimumDistance: 1, coordinateSpace: .global)
                            .onChanged { value in
                                let delta = CGSize(width: value.translation.width - lastDrag.width,
                                                   height: value.translation.height - lastDrag.height)
                                lastDrag = value.translation
                                onResizeDrag?(delta)
                            }
                            .onEnded { _ in lastDrag = .zero }
                    )
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
            Text("拆解中…")
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func errorView(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label("拆解失败", systemImage: "exclamationmark.triangle")
                .font(.system(size: 13, weight: .semibold))
            Text(message)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func resultView(_ result: ParseResult) -> some View {
        let chunks = headerChunks(result)
        let spans = ChunkSpanResolver.layout(for: chunks).spans

        return VStack(alignment: .leading, spacing: 0) {
            // Sentence flows like the original text: trunk bold and dark,
            // modifiers in their role color — sense groups read by shade.
            Text(attributedSentence(chunks))
                .lineSpacing(5)
                .lineLimit(12) // monster sentences: cap by lines, not by a greedy frame
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .padding(.leading, 16)
                .padding(.trailing, 40) // room for the pin in the corner
                .padding(.top, 16)
                .padding(.bottom, 12)

            Divider().padding(.horizontal, 12)

            // Chunk cards; children nest under their parent with a guide line.
            // Same descent as the header: skip a single all-covering wrapper.
            // Deep trees scroll so the translation stays visible.
            let cards = VStack(alignment: .leading, spacing: 2) {
                ForEach(chunks) { chunk in
                    chunkTree(chunk, depth: 0, spans: spans)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)

            // Always a ScrollView: it absorbs extra height when the user
            // enlarges the panel and compresses when they shrink it.
            ScrollView(.vertical, showsIndicators: true) {
                cards
            }
            .frame(minHeight: 80,
                   idealHeight: estimatedCardsHeight(result),
                   maxHeight: .infinity)

            Divider().padding(.horizontal, 12)

            // Full translation (arrives last while streaming)
            Group {
                if result.translation.isEmpty {
                    HStack(spacing: 6) {
                        ProgressView().controlSize(.small)
                        Text("整句翻译中…")
                            .font(.system(size: 12))
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Text(result.translation)
                        .font(.system(size: 13))
                        .foregroundStyle(.primary.opacity(0.85))
                        .textSelection(.enabled)
                        // Rigid: the min-height clamp must count every line,
                        // or the window shrinks under it and clips.
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
    }

    /// Rough per-row estimate so the default panel height fits the content;
    /// only counts rows that are visible given the current expansion state.
    private func estimatedCardsHeight(_ result: ParseResult) -> CGFloat {
        var total: CGFloat = 16
        func walk(_ chunks: [Chunk]) {
            for c in chunks {
                total += 30 + CGFloat(c.text.count / 42) * 16
                if state.expanded.contains(c.id) {
                    walk(c.children ?? [])
                }
            }
        }
        walk(headerChunks(result))
        return min(total, (NSScreen.main?.visibleFrame.height ?? 900) * 0.5)
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

    /// Three tiers: S/V/O bold + emphatic; complement medium; modifiers in
    /// their role color (not washed-out primary gray). Same hues as the cards.
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
                weight = .semibold
                color = chunk.role.emphaticColor
            default:
                // Medium weight so modifier colors stay readable on material.
                weight = .medium
                color = chunk.role.color
            }
            piece.font = .system(size: 15, weight: weight, design: .serif)
            piece.foregroundColor = color
            out += piece
            if index < chunks.count - 1, !chunk.text.hasSuffix(" ") {
                out += AttributedString(" ")
            }
        }
        // Hover from ANY tree depth lights up its pre-resolved source span.
        // Never search by text here: repeated words must remain distinct.
        if let highlight = state.hoveredHighlight {
            let characters = out.characters
            if highlight.range.lowerBound >= 0,
               highlight.range.upperBound <= characters.count {
                let lower = characters.index(
                    characters.startIndex,
                    offsetBy: highlight.range.lowerBound
                )
                let upper = characters.index(
                    characters.startIndex,
                    offsetBy: highlight.range.upperBound
                )
                out[lower..<upper].backgroundColor = highlight.color.opacity(0.28)
            }
        }
        return out
    }

    /// Parent row, then children indented behind a guide line in the parent's
    /// color. Children start collapsed; clicking the parent row toggles them.
    private func chunkTree(
        _ chunk: Chunk,
        depth: Int,
        spans: [UUID: Range<Int>]
    ) -> AnyView {
        AnyView(
            VStack(alignment: .leading, spacing: 2) {
                chunkRow(chunk, depth: depth, span: spans[chunk.id])
                    .contentShape(Rectangle())
                    .onTapGesture {
                        guard chunk.children != nil else { return }
                        if state.expanded.contains(chunk.id) {
                            state.expanded.remove(chunk.id)
                        } else {
                            state.expanded.insert(chunk.id)
                        }
                    }
                if let kids = chunk.children, state.expanded.contains(chunk.id) {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(kids) { chunkTree($0, depth: depth + 1, spans: spans) }
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

    private func chunkRow(
        _ chunk: Chunk,
        depth: Int = 0,
        span: Range<Int>?
    ) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            RoundedRectangle(cornerRadius: 1.5)
                .fill(chunk.role.color.opacity(depth > 0 ? 0.55 : 1))
                .frame(width: 3, height: 14)
                .offset(y: 1)

            if chunk.children != nil {
                Image(systemName: state.expanded.contains(chunk.id) ? "chevron.down" : "chevron.right")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(.tertiary)
                    .frame(width: 10)
            }

            // Cards show clean phrases: sentence punctuation the data layer
            // must keep (header reassembly + span math) is trimmed here only.
            Text(chunk.text.trimmingCharacters(in: CharacterSet(charactersIn: ",.;:!? ")))
                .font(.system(size: depth > 0 ? 11.5 : 12.5, design: .serif))
                // Keep English readable; only slightly dim expandable parents.
                .foregroundStyle(.primary.opacity(chunk.children != nil ? 0.72 : (depth > 0 ? 0.88 : 0.95)))
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            Text(chunk.role.label)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(chunk.role.color)
                .padding(.horizontal, 6)
                .padding(.vertical, 2)
                .background(chunk.role.badgeFill, in: Capsule())
                .fixedSize()

            // Local pipeline delivers no per-chunk glosses; don't reserve a
            // blank 130pt column for them.
            if !chunk.gloss.isEmpty {
                Text(chunk.gloss)
                    .font(.system(size: depth > 0 ? 11 : 12))
                    .foregroundStyle(.primary.opacity(0.72))
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(minWidth: 130, maxWidth: 260, alignment: .leading)
            }
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 4)
        .background(
            RoundedRectangle(cornerRadius: 6)
                .fill(state.hoveredChunkID == chunk.id ? chunk.role.color.opacity(0.14) : Color.clear)
        )
        .onHover { hovering in
            if hovering {
                state.hoveredChunkID = chunk.id
                state.hoveredHighlight = span.map { ($0, chunk.role.color) }
            } else if state.hoveredChunkID == chunk.id {
                state.hoveredChunkID = nil
                state.hoveredHighlight = nil
            }
        }
    }
}
