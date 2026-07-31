import Foundation

struct ChunkTextLayout {
    let text: String
    let spans: [UUID: Range<Int>]
}

/// Maps every visible tree node to its exact character span in the rendered
/// header. Child searches are constrained to their parent and advance from
/// left to right, so repeated text such as two separate "that" nodes remains
/// unambiguous.
enum ChunkSpanResolver {
    /// Locate the tree inside the sentence the user actually captured.
    ///
    /// Reassembling the header from chunk text cannot reproduce English
    /// spacing: spaCy splits `It's` into `It` + `'s`, so gluing the pieces
    /// back with spaces renders `It 's`. Clitics, and any other token the
    /// tokenizer detaches, are only correct in the original string — so the
    /// original string is what gets drawn, and the chunks are matched into it.
    static func layout(for chunks: [Chunk], in sentence: String) -> ChunkTextLayout {
        if !sentence.isEmpty {
            var spans: [UUID: Range<Int>] = [:]
            // Same parent-constrained, left-to-right walk used for children:
            // the sentence is simply the outermost parent.
            resolveChildren(chunks, within: sentence, parentStart: 0, into: &spans)
            // All or nothing. A partial match would leave some chunks with no
            // span, and an uncolored chunk is worse than uniform fallback.
            if chunks.allSatisfy({ spans[$0.id] != nil }) {
                return ChunkTextLayout(text: sentence, spans: spans)
            }
        }
        return reassembled(chunks)
    }

    /// Fallback for when the tree cannot be found in the sentence (normalized
    /// capture, a sidecar that rewrote a token). Spacing may be imperfect, but
    /// every chunk still gets a span.
    private static func reassembled(_ chunks: [Chunk]) -> ChunkTextLayout {
        var text = ""
        var spans: [UUID: Range<Int>] = [:]

        for (index, chunk) in chunks.enumerated() {
            let start = text.count
            text += chunk.text
            let end = text.count
            spans[chunk.id] = start..<end
            resolveChildren(
                chunk.children ?? [],
                within: chunk.text,
                parentStart: start,
                into: &spans
            )

            if index < chunks.count - 1, !chunk.text.hasSuffix(" ") {
                text += " "
            }
        }

        return ChunkTextLayout(text: text, spans: spans)
    }

    private static func resolveChildren(
        _ children: [Chunk],
        within parentText: String,
        parentStart: Int,
        into spans: inout [UUID: Range<Int>]
    ) {
        var cursor = parentText.startIndex

        for child in children {
            guard let range = parentText.range(
                of: child.text,
                range: cursor..<parentText.endIndex
            ) else {
                continue
            }

            let localStart = parentText.distance(from: parentText.startIndex, to: range.lowerBound)
            let localEnd = parentText.distance(from: parentText.startIndex, to: range.upperBound)
            let absoluteRange = (parentStart + localStart)..<(parentStart + localEnd)
            spans[child.id] = absoluteRange
            resolveChildren(
                child.children ?? [],
                within: child.text,
                parentStart: absoluteRange.lowerBound,
                into: &spans
            )
            cursor = range.upperBound
        }
    }
}
