import Foundation

/// The ⌥X compose path: Chinese in, English out, then the English goes
/// through the ordinary parse pipeline.
///
/// This is the same HY-MT2 the reading path uses, run in the other direction.
/// It stays a separate entry point rather than a flag on `ParseService`
/// because the failure it has to catch is its own: a translation model asked
/// for English can answer in Chinese, and a Chinese "translation" would then
/// be handed to an English parser, which would produce a confident tree of
/// nonsense instead of an error.
enum ComposeService {
    enum Failure: LocalizedError, Equatable {
        case empty
        case tooLong(Int)
        case notEnglish(String)
        case modelNotConfigured

        var errorDescription: String? {
            switch self {
            case .empty:
                return "没有输入内容。"
            case .tooLong(let limit):
                return "输入过长（超过 \(limit) 字）。请只写一句或一小段。"
            case .notEnglish(let got):
                return "本地模型没有给出英文译文，返回的是：\(got.prefix(60))"
            case .modelNotConfigured:
                return "本地翻译模型未配置，请在设置里选择 Ollama 模型"
            }
        }
    }

    /// Long enough for a paragraph someone would actually want to say, short
    /// enough that the sentence parser downstream stays inside its own
    /// 1200-character ceiling once the text expands into English.
    static let inputLimit = 400

    static func englishSentence(from chinese: String) async throws -> String {
        let source = chinese.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !source.isEmpty else { throw Failure.empty }
        guard source.count <= inputLimit else { throw Failure.tooLong(inputLimit) }
        let model = await MainActor.run { SettingsStore.shared.translationModel }
        guard !model.isEmpty else { throw Failure.modelNotConfigured }

        let raw = try await OllamaCoordinator.shared.chat(
            model: model,
            messages: [OllamaMessage(
                role: "user",
                content: HYMT2TranslationPolicy.englishPrompt(source: source)
            )],
            temperature: HYMT2TranslationPolicy.temperature,
            contextWindow: 8_192,
            maximumOutputTokens: 1_024,
            thinking: false,
            timeout: 120
        )
        // The wrapper-stripping is direction-agnostic (fences, <target>, a
        // "Translation:" label), so both directions share one cleanup.
        let cleaned = ParseService.cleanTranslationOutput(raw)
        guard !cleaned.isEmpty else { throw OllamaError.emptyResponse }
        guard looksEnglish(cleaned) else { throw Failure.notEnglish(cleaned) }
        return cleaned
    }

    /// Whether a model reply is English enough to hand to an English parser.
    ///
    /// Measured on letters, not on characters: punctuation and digits are
    /// shared between the two scripts, so counting them lets a mostly-Chinese
    /// reply pass on its commas. Exposed internally for unit tests.
    static func looksEnglish(_ text: String) -> Bool {
        let letters = text.unicodeScalars.filter { CharacterSet.letters.contains($0) }
        guard !letters.isEmpty else { return false }
        let ascii = letters.filter(\.isASCII).count
        return Double(ascii) / Double(letters.count) > 0.5
    }

    /// Whether a *capture* is Chinese, and so belongs on the compose path
    /// rather than in an error.
    ///
    /// Not `!looksEnglish`: that returns true for Japanese, Russian and every
    /// other script Thorn cannot help with, and those must keep erroring.
    /// Han characters are the only positive evidence.
    ///
    /// The bar is deliberately low rather than a majority. This is only ever
    /// asked *after* the English extractor failed to find a sentence, so the
    /// question is "is there Chinese here worth translating", not "is Chinese
    /// the dominant script" — and a Chinese sentence quoting a long English
    /// term is outnumbered by its own quotation on a per-letter count.
    ///
    /// Kana veto Japanese outright: kanji alone cannot tell the two apart,
    /// and a Japanese sentence sent to a Chinese-to-English model is a wrong
    /// answer dressed as a right one.
    static func looksChinese(_ text: String) -> Bool {
        let letters = text.unicodeScalars.filter { CharacterSet.letters.contains($0) }
        guard !letters.isEmpty else { return false }
        let hasKana = letters.contains { (0x3040...0x30FF).contains($0.value) }
        guard !hasKana else { return false }
        let han = letters.filter { scalar in
            (0x4E00...0x9FFF).contains(scalar.value)        // CJK Unified Ideographs
                || (0x3400...0x4DBF).contains(scalar.value) // Extension A
                || (0xF900...0xFAFF).contains(scalar.value) // Compatibility
        }.count
        // Two characters is a word; one is a stray glyph in someone else's
        // script, and hanja in Korean text must not drag it onto this path.
        return han >= 2 && Double(han) / Double(letters.count) > 0.2
    }
}
