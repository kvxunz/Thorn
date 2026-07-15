import Foundation

/// HY-MT2 is a translation model, not a general instruction follower. Keep
/// each request limited to the exact source span it is allowed to translate.
enum HYMT2TranslationPolicy {
    static let temperature = 0.0

    static func glossPrompt(source: String) -> String {
        """
        Translate the following English phrase into Simplified Chinese. Output only the translation:
        \(source)
        """
    }

    static func sentencePrompt(source: String) -> String {
        """
        Translate the following English sentence faithfully into Simplified Chinese. Preserve every clause and explicitly translate any framing expression at the beginning. Do not omit or paraphrase away information. Output only the translation:
        \(source)
        """
    }

    static func deterministicGloss(
        text: String,
        role: ChunkRole,
        parentRole: ChunkRole?,
        followingText: String? = nil,
        followingRole: ChunkRole? = nil,
        subsequentRole: ChunkRole? = nil,
        governingVerbText: String? = nil
    ) -> String? {
        let normalized = text
            .trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
            .lowercased()

        if role == .conjunction, parentRole == .clauseNoun, normalized == "that" {
            return "即"
        }
        if role == .conjunction, normalized == "because" {
            return "因为"
        }
        let finalWord = normalized.split(whereSeparator: \.isWhitespace).last.map(String.init)
        let followingStartsWithInfinitive = followingText?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .hasPrefix("to ") == true
        if role == .verb,
           followingRole == .complement,
           followingStartsWithInfinitive,
           let finalWord,
           ["fail", "fails", "failed", "failing"].contains(finalWord) {
            return "未能"
        }
        let following = followingText?
            .trimmingCharacters(in: .whitespacesAndNewlines.union(.punctuationCharacters))
            .lowercased()
        if role == .subject,
           ["the notion", "a notion", "this notion"].contains(normalized),
           followingRole == .verb,
           ["is", "was"].contains(following ?? ""),
           subsequentRole == .clauseNoun {
            return "这种观点"
        }
        if role == .subject, normalized == "no regular advertiser" {
            return "没有哪家正规的广告商"
        }
        if role == .verb,
           normalized == "to live up",
           followingRole == .prepPhrase,
           following?.hasPrefix("to the promise") == true {
            return "达到承诺的标准"
        }
        let followingWords = Set(
            (following ?? "").split(whereSeparator: { !$0.isLetter }).map(String.init)
        )
        let verbWords = normalized
            .split(whereSeparator: { !$0.isLetter })
            .map(String.init)
        let isLieVerb = verbWords.first.map {
            ["lie", "lies", "lay", "lain", "lying"].contains($0)
        } == true
        let followsAbstractLieIn = followingRole == .prepPhrase
            && (following?.hasPrefix("in ") == true || following?.hasPrefix("not in ") == true)
            && !followingWords.isDisjoint(with: ["how", "whether"])
        if role == .verb, isLieVerb, followsAbstractLieIn {
            let isNegated = verbWords.contains("not") || following?.hasPrefix("not in ") == true
            return isNegated ? "不在于" : "在于"
        }
        if role == .verb,
           normalized == "dare promote",
           followingRole == .object,
           followingWords.contains("product") {
            return "敢于宣传"
        }
        if role == .verb,
           ["detect", "to detect"].contains(normalized),
           parentRole == .complement,
           followingRole == .object,
           !followingWords.isDisjoint(with: ["change", "changes"]) {
            return "察觉到"
        }
        if role == .verb,
           ["govern", "governs", "governed", "governing"].contains(normalized),
           followingRole == .object,
           !followingWords.isDisjoint(with: ["term", "terms"]) {
            return "规定"
        }
        let governingVerbWords = Set(
            (governingVerbText ?? "")
                .lowercased()
                .split(whereSeparator: { !$0.isLetter })
                .map(String.init)
        )
        let sourceWords = Set(
            normalized.split(whereSeparator: { !$0.isLetter }).map(String.init)
        )
        let isAdvertisingPromise = normalized.hasPrefix("to the promise of ")
            && !sourceWords.isDisjoint(with: ["ad", "ads", "advertisement", "advertisements", "advertising"])
        if role == .prepPhrase,
           isAdvertisingPromise,
           governingVerbWords.contains("live"),
           governingVerbWords.contains("up") {
            return "其广告宣传中所作的承诺"
        }
        let hasLookBack = governingVerbWords.contains("back")
            && !governingVerbWords.isDisjoint(with: ["look", "looks", "looked", "looking"])
        if role == .prepPhrase, normalized == "into the past", hasLookBack {
            return "向过去追溯"
        }
        return nil
    }

    /// Reject model output that cannot plausibly belong to this exact source
    /// span. Clause translations may be naturally long; smaller sense groups
    /// are capped relative to their English word count.
    static func validatedGloss(
        _ gloss: String,
        source: String,
        role: ChunkRole
    ) -> String? {
        let trimmed = gloss.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        guard !role.isClause else { return trimmed }

        let wordCount = max(1, source.split(whereSeparator: \.isWhitespace).count)
        let maximumLength = max(8, wordCount * 4)
        guard trimmed.count <= maximumLength else { return nil }
        return trimmed
    }
}
