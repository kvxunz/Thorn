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
            case .word(let result):
                wordView(result)
            }
        }
        .frame(minWidth: minPanelWidth, idealWidth: idealPanelWidth,
               maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: ThornRadius.panel))
        // Whatever squeezing happens, the panel silhouette stays rounded.
        .clipShape(RoundedRectangle(cornerRadius: ThornRadius.panel))
        .overlay(
            // Two hairlines: a bright inner one catches the top edge like a
            // bevel, the outer one keeps the silhouette legible on any
            // wallpaper. One flat border reads as a screenshot of a box.
            RoundedRectangle(cornerRadius: ThornRadius.panel)
                .strokeBorder(
                    LinearGradient(
                        colors: [Color.white.opacity(0.22), Color.white.opacity(0.04)],
                        startPoint: .top,
                        endPoint: .bottom
                    ),
                    lineWidth: 0.5
                )
                .padding(0.5)
        )
        .overlay(
            RoundedRectangle(cornerRadius: ThornRadius.panel)
                .strokeBorder(Color.primary.opacity(0.10), lineWidth: 0.5)
        )
        .overlay(alignment: .topTrailing) {
            if hasContent {
                pinButton.padding(ThornSpace.sm + ThornSpace.hair)
            }
        }
        .overlay(alignment: .bottomTrailing) {
            // Dedicated resize grip: the borderless window's system resize
            // border is only ~4px and hard to grab.
            if hasContent {
                Image(systemName: "line.3.horizontal.decrease")
                    .font(ThornType.ui(ThornType.micro))
                    .foregroundStyle(.tertiary)
                    .rotationEffect(.degrees(-45))
                    .frame(width: 20, height: 20, alignment: .bottomTrailing)
                    .padding(ThornSpace.xs)
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

    private var hasContent: Bool {
        switch state.status {
        case .result, .word: return true
        default: return false
        }
    }

    /// Word results are compact; forcing the sentence panel's 400/460pt
    /// footprint leaves a sea of empty glass to the right of the blocks.
    private var minPanelWidth: CGFloat {
        state.wordMode ? 220 : 400
    }

    /// Word cards take their natural content width (the flow layout caps
    /// monster words at 560pt internally); sentences keep the fixed ideal.
    private var idealPanelWidth: CGFloat? {
        state.wordMode ? nil : 460
    }

    private var pinButton: some View {
        Button {
            state.pinned.toggle()
        } label: {
            Image(systemName: state.pinned ? "pin.fill" : "pin")
                .font(ThornType.ui(ThornType.small))
                .foregroundStyle(state.pinned
                    ? ThornPalette.predicate.color
                    : Color.secondary.opacity(0.55))
                // Pinning tilts the pin upright: the state change is felt,
                // not just seen.
                .rotationEffect(.degrees(state.pinned ? 0 : 32))
                .animation(ThornMotion.hover, value: state.pinned)
        }
        .buttonStyle(.plain)
        .help(state.pinned ? "取消固定" : "固定：点击外部不再关闭")
    }

    private var loadingView: some View {
        HStack(spacing: ThornSpace.sm) {
            ProgressView().controlSize(.small)
            Text("拆解中…")
                .font(ThornType.ui(ThornType.body))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, ThornSpace.lg)
        .padding(.vertical, ThornSpace.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func errorView(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: ThornSpace.sm) {
            Label("拆解失败", systemImage: "exclamationmark.triangle")
                .font(ThornType.ui(ThornType.body, .semibold))
                .foregroundStyle(ThornPalette.predicate.color)
            Text(message)
                .font(ThornType.ui(ThornType.small))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(ThornSpace.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func resultView(_ result: ParseResult) -> some View {
        let chunks = headerChunks(result)
        // The parsed sentence, not state.sentence: normalization runs again
        // inside ParseService, so only the result knows the exact string its
        // chunks were cut from.
        let layout = ChunkSpanResolver.layout(for: chunks, in: result.sentence)
        let spans = layout.spans

        return VStack(alignment: .leading, spacing: 0) {
            // Sentence flows like the original text: trunk bold and dark,
            // modifiers in their role color — sense groups read by shade.
            Text(attributedSentence(chunks, layout: layout))
                .lineSpacing(5)
                .lineLimit(12) // monster sentences: cap by lines, not by a greedy frame
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
                .animation(ThornMotion.hover, value: state.hoveredHighlight?.range)
                .padding(.leading, ThornSpace.lg)
                .padding(.trailing, ThornSpace.pinInset + ThornSpace.xs)
                .padding(.top, ThornSpace.lg)
                .padding(.bottom, ThornSpace.md)

            Divider().padding(.horizontal, ThornSpace.md)

            // Chunk cards; children nest under their parent with a guide line.
            // Same descent as the header: skip a single all-covering wrapper.
            // Deep trees scroll so the translation stays visible.
            let cards = VStack(alignment: .leading, spacing: ThornSpace.hair) {
                ForEach(chunks) { chunk in
                    chunkTree(chunk, depth: 0, spans: spans)
                }
            }
            .padding(.horizontal, ThornSpace.sm + ThornSpace.hair)
            .padding(.vertical, ThornSpace.sm)

            // Always a ScrollView: it absorbs extra height when the user
            // enlarges the panel and compresses when they shrink it.
            ScrollView(.vertical, showsIndicators: true) {
                cards
            }
            .frame(minHeight: 80,
                   idealHeight: estimatedCardsHeight(result),
                   maxHeight: .infinity)

            Divider().padding(.horizontal, ThornSpace.md)

            // Full translation (arrives last while streaming)
            Group {
                if result.translation.isEmpty {
                    HStack(spacing: ThornSpace.sm) {
                        ProgressView().controlSize(.small)
                        Text("整句翻译中…")
                            .font(ThornType.ui(ThornType.small))
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Text(result.translation)
                        .font(ThornType.ui(ThornType.body))
                        .foregroundStyle(.primary.opacity(0.85))
                        .textSelection(.enabled)
                        // Rigid: the min-height clamp must count every line,
                        // or the window shrinks under it and clips.
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        // The translation lands seconds after the tree; fading
                        // it in marks the arrival instead of a silent swap.
                        .transition(.opacity)
                }
            }
            .animation(ThornMotion.reveal, value: result.translation.isEmpty)
            .padding(.horizontal, ThornSpace.lg)
            .padding(.vertical, ThornSpace.md)
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

    /// Descend through neutral all-covering wrappers only. A wrapper carrying
    /// an explicit construction form is itself a teaching result and must
    /// remain visible as a card even when it covers the whole selection.
    private func headerChunks(_ result: ParseResult) -> [Chunk] {
        var chunks = result.chunks
        while chunks.count == 1,
              !chunks[0].preservesTeachingWrapper,
              let kids = chunks[0].children,
              !kids.isEmpty {
            chunks = kids
        }
        return chunks
    }

    /// Three tiers: S/V/O bold + emphatic; complement medium; modifiers in
    /// their role color (not washed-out primary gray). Same hues as the cards.
    ///
    /// Coloring keys off the *leaf* nodes and their pre-resolved character
    /// spans, so a wrapper card (a coordinated clause block, an appositive
    /// list) never repaints its whole span one flat color — the backbone keeps
    /// its per-role hues at any nesting depth.
    private func attributedSentence(_ chunks: [Chunk], layout: ChunkTextLayout) -> AttributedString {
        var out = AttributedString(layout.text)
        // Glue between leaves (spaces, semicolons, stray determiners) reads as
        // quiet connective tissue.
        out.font = ThornType.english(ThornType.reading, .medium)
        out.foregroundColor = Color.primary.opacity(0.5)

        func apply(_ range: Range<Int>, weight: Font.Weight, color: Color) {
            let characters = out.characters
            guard range.lowerBound >= 0, range.upperBound <= characters.count else { return }
            let lower = characters.index(characters.startIndex, offsetBy: range.lowerBound)
            let upper = characters.index(characters.startIndex, offsetBy: range.upperBound)
            out[lower..<upper].font = ThornType.english(ThornType.reading, weight)
            out[lower..<upper].foregroundColor = color
        }

        func colorLeaves(_ nodes: [Chunk]) {
            for node in nodes {
                if let kids = node.children, !kids.isEmpty {
                    colorLeaves(kids)
                    continue
                }
                guard let range = layout.spans[node.id] else { continue }
                let displayRole = node.displayRole
                switch displayRole {
                case .subject, .verb, .object:
                    apply(range, weight: .bold, color: displayRole.emphaticColor)
                case .complement:
                    apply(range, weight: .semibold, color: displayRole.emphaticColor)
                default:
                    apply(range, weight: .medium, color: displayRole.color)
                }
            }
        }
        colorLeaves(chunks)

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
                out[lower..<upper].backgroundColor = highlight.color.opacity(0.20)
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
            VStack(alignment: .leading, spacing: ThornSpace.hair) {
                chunkRow(chunk, depth: depth, span: spans[chunk.id])
                    .contentShape(Rectangle())
                    .onTapGesture {
                        guard chunk.children != nil else { return }
                        // The window is resized first (the observer on
                        // `expanded` fires synchronously on the main queue and
                        // grows the panel before shrinking), so the subtree
                        // animates inside a frame that is already big enough.
                        withAnimation(ThornMotion.reveal) {
                            if state.expanded.contains(chunk.id) {
                                state.expanded.remove(chunk.id)
                            } else {
                                state.expanded.insert(chunk.id)
                            }
                        }
                    }
                if let kids = chunk.children, state.expanded.contains(chunk.id) {
                    VStack(alignment: .leading, spacing: ThornSpace.hair) {
                        ForEach(kids) { chunkTree($0, depth: depth + 1, spans: spans) }
                    }
                    .padding(.leading, ThornSpace.lg)
                    .overlay(alignment: .leading) {
                        // The guide line grows out of the parent row rather
                        // than blinking in at full length.
                        RoundedRectangle(cornerRadius: 1)
                            .fill(chunk.displayRole.ink.opacity(0.28))
                            .frame(width: 2)
                            .padding(.leading, 7)
                            .padding(.vertical, 3)
                            .transition(.scale(scale: 0.01, anchor: .top))
                    }
                    // Fade + a 6pt settle. Deliberately not `.move(edge: .top)`:
                    // an unclipped VStack lets a moving subtree overdraw the
                    // parent row it is sliding out of.
                    .transition(.opacity.combined(with: .offset(y: -6)))
                }
            }
        )
    }

    private func chunkRow(
        _ chunk: Chunk,
        depth: Int = 0,
        span: Range<Int>?
    ) -> some View {
        let displayRole = chunk.displayRole
        let expanded = state.expanded.contains(chunk.id)
        return HStack(alignment: .firstTextBaseline, spacing: ThornSpace.sm) {
            RoundedRectangle(cornerRadius: ThornRadius.bar)
                .fill(displayRole.ink.opacity(depth > 0 ? 0.55 : 1))
                .frame(width: 3, height: 14)
                .offset(y: 1)

            if chunk.children != nil {
                // One glyph that turns, not two that swap: the rotation is
                // what tells the eye the row opened.
                Image(systemName: "chevron.right")
                    .font(ThornType.ui(ThornType.micro, .semibold))
                    .foregroundStyle(.tertiary)
                    .rotationEffect(.degrees(expanded ? 90 : 0))
                    .animation(ThornMotion.reveal, value: expanded)
                    .frame(width: 10)
            }

            // Cards show clean phrases: sentence punctuation the data layer
            // must keep (header reassembly + span math) is trimmed here only.
            Text(chunk.text.trimmingCharacters(
                in: CharacterSet(charactersIn: ",.;:!?-—–― ")
            ))
                .font(ThornType.english(depth > 0 ? ThornType.small : ThornType.body))
                // Keep English readable; only slightly dim expandable parents.
                .foregroundStyle(.primary.opacity(chunk.children != nil ? 0.72 : (depth > 0 ? 0.88 : 0.95)))
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let detail = chunk.secondaryLabel {
                Text(detail)
                    .font(ThornType.ui(ThornType.micro))
                    .foregroundStyle(.secondary)
                    .fixedSize()
            }

            Text(chunk.primaryLabel)
                .font(ThornType.ui(ThornType.small, .medium))
                .foregroundStyle(displayRole.color)
                .padding(.horizontal, ThornSpace.sm - ThornSpace.hair)
                .padding(.vertical, ThornSpace.hair)
                .background(displayRole.badgeFill, in: Capsule())
                // The fill alone is too faint to hold an edge at the low
                // saturations the subordinate tiers use.
                .overlay(Capsule().strokeBorder(displayRole.badgeStroke, lineWidth: 0.5))
                .fixedSize()

            // Local pipeline delivers no per-chunk glosses; don't reserve a
            // blank 130pt column for them.
            if !chunk.gloss.isEmpty {
                Text(chunk.gloss)
                    .font(ThornType.ui(depth > 0 ? ThornType.small : ThornType.body))
                    .foregroundStyle(.primary.opacity(0.72))
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(minWidth: 130, maxWidth: 260, alignment: .leading)
            }
        }
        .padding(.horizontal, ThornSpace.sm - ThornSpace.hair)
        .padding(.vertical, ThornSpace.xs)
        .background(
            RoundedRectangle(cornerRadius: ThornRadius.row)
                .fill(state.hoveredChunkID == chunk.id ? displayRole.ink.opacity(0.13) : Color.clear)
        )
        .animation(ThornMotion.hover, value: state.hoveredChunkID == chunk.id)
        .onHover { hovering in
            if hovering {
                state.hoveredChunkID = chunk.id
                state.hoveredHighlight = span.map { ($0, displayRole.color) }
            } else if state.hoveredChunkID == chunk.id {
                state.hoveredChunkID = nil
                state.hoveredHighlight = nil
            }
        }
    }

    // MARK: - Single-word phonics view

    private func wordView(_ result: PhonicsResult) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: ThornSpace.sm) {
                // Wrap at syllable boundaries; long words must not force a
                // panel wider than the screen.
                PhonicsFlowLayout(spacing: ThornSpace.sm) {
                    ForEach(Array(result.syllables.enumerated()), id: \.offset) { index, syllable in
                        syllableBlock(
                            syllable,
                            ink: ThornPalette.syllable(index),
                            trailingDot: index < result.syllables.count - 1
                        )
                    }
                }
                .contentShape(Rectangle())
                .onTapGesture { WordSpeaker.speak(result.word) }
                .help("点击朗读")

                HStack(spacing: ThornSpace.sm) {
                    if let ipa = result.ipa {
                        Text("/\(ipa)/")
                            .font(ThornType.english(ThornType.body))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                    }
                    Button {
                        WordSpeaker.speak(result.word)
                    } label: {
                        Image(systemName: "speaker.wave.2")
                            .font(ThornType.ui(ThornType.small))
                            .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                    .help("朗读（本机系统语音）")
                }

                if result.approximate {
                    // Same ink as the parse-failure label: one caution colour
                    // across the app instead of a stray system orange.
                    Label("近似拆分（词典未收录，不含发音）",
                          systemImage: "questionmark.circle")
                        .font(ThornType.ui(ThornType.small))
                        .foregroundStyle(ThornPalette.predicate.opacity(0.9))
                }
            }
            .padding(.leading, ThornSpace.lg)
            .padding(.trailing, ThornSpace.pinInset) // room for the pin in the corner
            .padding(.top, ThornSpace.md)
            .padding(.bottom, ThornSpace.sm)

            Divider().padding(.horizontal, ThornSpace.md)

            // Chinese meaning (arrives after the blocks, like the sentence
            // translation).
            Group {
                if result.meaning.isEmpty {
                    HStack(spacing: ThornSpace.sm) {
                        ProgressView().controlSize(.small)
                        Text("查询中文词义…")
                            .font(ThornType.ui(ThornType.small))
                            .foregroundStyle(.secondary)
                    }
                } else {
                    // The meaning is the card's payload. Same point size as
                    // the graphemes, but Han glyphs fill their em far more
                    // than a serif Latin one, so it still reads as the answer.
                    Text(result.meaning)
                        .font(ThornType.ui(ThornType.display, .medium))
                        .foregroundStyle(.primary.opacity(0.9))
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .transition(.opacity)
                }
            }
            .animation(ThornMotion.reveal, value: result.meaning.isEmpty)
            .padding(.horizontal, ThornSpace.lg)
            .padding(.vertical, ThornSpace.md)
        }
    }

    /// One syllable, dictionary-card style: colored graphemes over a thin
    /// underline that visually binds each chunk, IPA in small type below.
    /// No boxes — light and compact.
    private func syllableBlock(
        _ syllable: PhonicsSyllable,
        ink: ThornInk,
        trailingDot: Bool
    ) -> some View {
        HStack(alignment: .top, spacing: ThornSpace.xs) {
            if syllable.stress != .none {
                Text(syllable.stress.mark)
                    .font(ThornType.english(ThornType.body, .bold))
                    .foregroundStyle(ink.color)
                    .padding(.top, ThornSpace.hair)
            }
            ForEach(Array(syllable.chunks.enumerated()), id: \.offset) { _, chunk in
                VStack(spacing: ThornSpace.hair) {
                    Text(chunk.grapheme)
                        .font(ThornType.english(
                            ThornType.display,
                            syllable.stress == .primary ? .bold : .semibold
                        ))
                        .foregroundStyle(ink.color)
                        .padding(.horizontal, 1)
                    Capsule()
                        .fill(ink.opacity(syllable.stress == .primary ? 0.55 : 0.35))
                        .frame(height: 2)
                    // Reserve the row even without IPA so graphemes of
                    // approximate splits still baseline-align.
                    Text(chunk.ipa ?? " ")
                        .font(ThornType.ui(ThornType.micro))
                        .foregroundStyle(.secondary)
                }
            }
            if trailingDot {
                // Vertically centered against the grapheme line, not floating
                // at the top of the block like a stray speck.
                Text("·")
                    .font(ThornType.ui(ThornType.reading, .semibold))
                    .foregroundStyle(.tertiary)
                    .frame(height: 26, alignment: .center)
            }
        }
        .fixedSize()
    }
}

/// Minimal left-to-right wrapping layout: rows break when the next item
/// exceeds the proposed width. Used for syllable blocks of long words.
struct PhonicsFlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(proposal: proposal, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize,
                       subviews: Subviews, cache: inout ()) {
        for (subview, position) in zip(subviews, arrange(proposal: proposal, subviews: subviews).positions) {
            subview.place(
                at: CGPoint(x: bounds.minX + position.x, y: bounds.minY + position.y),
                proposal: .unspecified
            )
        }
    }

    private func arrange(proposal: ProposedViewSize,
                         subviews: Subviews) -> (size: CGSize, positions: [CGPoint]) {
        // Cap even the unproposed ideal: the panel hugs this natural width,
        // and a monster word must wrap instead of spanning the screen.
        let maxWidth = min(proposal.width ?? 560, 560)
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalWidth: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > maxWidth {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            totalWidth = max(totalWidth, x - spacing)
        }
        return (CGSize(width: totalWidth, height: y + rowHeight), positions)
    }
}
