import Foundation

/// HY-MT2 translates the whole sentence once; that is the model's entire job
/// in the local pipeline. Per-chunk glossing was removed.
enum HYMT2TranslationPolicy {
    static let temperature = 0.0

    static func sentencePrompt(source: String) -> String {
        """
        Translate the following English sentence faithfully into Simplified Chinese. Preserve every clause and explicitly translate any framing expression at the beginning. Do not omit or paraphrase away information. Output only the translation:
        \(source)
        """
    }

    /// Single-word capture: a compact dictionary-style gloss, not a sentence
    /// translation. Kept to plain translation phrasing because HY-MT2 is a
    /// pure MT model.
    static func wordPrompt(source: String) -> String {
        """
        Translate the English word below into Simplified Chinese. Give its common meanings concisely (at most three senses, separated by "；"). Output only the Chinese meanings, nothing else:
        \(source)
        """
    }
}
