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
}
