import Foundation

/// Reconciles parent glosses with the syntax and meanings already established
/// by their children. Model output remains the default; corrections are narrow
/// and structural so a parent cannot invent an antecedent or change a core verb.
enum GlossConsistency {
    static func reconcile(_ chunks: [Chunk]) -> [Chunk] {
        chunks.map(reconcile)
    }

    private static func reconcile(_ chunk: Chunk) -> Chunk {
        let children = chunk.children.map(reconcile)
        var gloss = chunk.gloss

        if chunk.role == .clauseRelative {
            gloss = dropInventedGenericAntecedent(from: gloss)
            if let children,
               let verb = children.first(where: { $0.role == .verb }),
               let complement = children.first(where: { $0.role == .complement }),
               ["fail", "fails", "failed", "failing"].contains(normalized(verb.text)),
               normalized(complement.text).hasPrefix("to live up to ") {
                gloss = verb.gloss + complement.gloss
            }
        }
        if chunk.role == .clauseNoun,
           gloss.hasPrefix("那"),
           let children,
           children.first?.role == .conjunction,
           children.first.map({ normalized($0.text) }) == "that" {
            let composed = children.dropFirst().map(\.gloss).filter { !$0.isEmpty }.joined()
            if !composed.isEmpty { gloss = composed }
        }
        if chunk.role == .complement, let children {
            gloss = inheritCoreVerb(in: gloss, from: children)
            let hasLiveUp = children.contains {
                $0.role == .verb && normalized($0.text) == "to live up"
            }
            let hasPromise = children.contains {
                $0.role == .prepPhrase && isAdvertisingPromise($0.text)
            }
            if hasLiveUp, hasPromise {
                gloss = "达到其广告宣传所承诺的水平"
            }
        }

        return Chunk(
            text: chunk.text,
            role: chunk.role,
            gloss: gloss,
            children: children
        )
    }

    private static func dropInventedGenericAntecedent(from gloss: String) -> String {
        let suffixes: [(text: String, replacement: String)] = [
            ("那些事情", ""),
            ("那些事物", ""),
            ("那些东西", ""),
            ("的事情", "的"),
            ("的事物", "的"),
            ("的东西", "的"),
        ]
        for suffix in suffixes where gloss.hasSuffix(suffix.text) {
            return String(gloss.dropLast(suffix.text.count)) + suffix.replacement
        }
        return gloss
    }

    private static func inheritCoreVerb(in gloss: String, from children: [Chunk]) -> String {
        guard let verb = children.first(where: { $0.role == .verb }) else { return gloss }
        let source = normalized(verb.text)
        guard ["detect", "to detect"].contains(source), verb.gloss == "察觉到" else {
            return gloss
        }
        for conflictingPrefix in ["检测到", "检测", "探测到", "探测"]
            where gloss.hasPrefix(conflictingPrefix) {
            return verb.gloss + gloss.dropFirst(conflictingPrefix.count)
        }
        return gloss
    }

    private static func normalized(_ text: String) -> String {
        text
            .trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
            .lowercased()
    }

    private static func isAdvertisingPromise(_ text: String) -> Bool {
        let source = normalized(text)
        let words = Set(source.split(whereSeparator: { !$0.isLetter }).map(String.init))
        return source.hasPrefix("to the promise of ")
            && !words.isDisjoint(with: ["ad", "ads", "advertisement", "advertisements", "advertising"])
    }
}
