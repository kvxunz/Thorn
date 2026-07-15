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
    static func layout(for chunks: [Chunk]) -> ChunkTextLayout {
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
