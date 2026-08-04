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

    /// The ⌥X compose path, running the same model backwards. Phrased to
    /// mirror `sentencePrompt` rather than to be clever: the two directions
    /// wording the same constraint two different ways is how they drift.
    static func englishPrompt(source: String) -> String {
        """
        Translate the following Simplified Chinese sentence faithfully into English. Preserve every clause and produce one natural, grammatical English sentence. Do not omit or paraphrase away information, and do not add commentary. Output only the translation:
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
