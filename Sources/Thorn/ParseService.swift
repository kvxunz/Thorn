import Foundation

enum ParseService {
    private enum LocalPipelineError: LocalizedError {
        case structureUnavailable
        case noEnglishSentence

        var errorDescription: String? {
            switch self {
            case .structureUnavailable:
                return "本地句法引擎暂不可用；HY-MT2 只负责翻译，不能代替句法拆分"
            case .noEnglishSentence:
                return "选中内容主要是中文注释，没有找到可拆解的英文句子"
            }
        }
    }

    /// Local pipeline: deterministic structure from the sidecar, HY-MT2 only
    /// translates the whole sentence. No per-chunk glosses: chunks carry only
    /// the syntax-derived glosses the parser itself produces
    /// (relative-pronoun referents).
    /// `onPartial` receives the bare structure as soon as the sidecar returns,
    /// before the translation lands.
    static func parse(sentence: String,
                      onPartial: (@Sendable (ParseResult) -> Void)? = nil) async throws -> ParseResult {
        let ep = SettingsStore.shared.endpoint()
        guard !ep.model.isEmpty else {
            throw LLMError.notConfigured
        }
        // Mixed bilingual selections keep only their English sentences; the
        // hotkey path pre-extracts too, so this is a backstop for direct calls.
        let normalized = extractEnglish(normalizedInput(sentence))
        guard !normalized.isEmpty else {
            throw LocalPipelineError.noEnglishSentence
        }

        let client = LLMClient(baseURL: ep.baseURL, model: ep.model)

        // Parsing and whole-sentence translation are independent and run
        // concurrently.
        async let translated = translateOnly(sentence: normalized, client: client)
        guard let structure = await Sidecar.shared.structure(for: normalized) else {
            throw LocalPipelineError.structureUnavailable
        }
        try Task.checkCancellation()
        let bare = ParseResult(chunks: structure.chunks, translation: "")
        onPartial?(bare) // tree on screen immediately, translation pending
        do {
            let translation = try await translated
            try Task.checkCancellation()
            return ParseResult(chunks: structure.chunks, translation: translation)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            ThornLog.info("local translation failed: \(error.localizedDescription)")
            // Structure alone still beats nothing — but fill the translation
            // slot so the panel doesn't spin forever waiting for one.
            return ParseResult(chunks: structure.chunks,
                               translation: "（中文释义暂缺：本地模型未响应，结构来自句法引擎）")
        }
    }

    /// Text copied from bilingual reading material often carries CJK fullwidth
    /// punctuation ("troubles，or so") and invisible control/format characters
    /// (zero-width spaces, bidi marks) wedged between words. spaCy's English
    /// models misattach dependencies around the former and render the latter as
    /// tofu boxes in the header, so clean both before parsing. Curly
    /// quotes/apostrophes are normal English typography and stay as-is.
    /// Exposed internally for unit tests.
    static func normalizedInput(_ sentence: String) -> String {
        let cjkPunctuation: [Character: String] = [
            "，": ", ", "。": ". ", "、": ", ", "；": "; ", "：": ": ",
            "？": "? ", "！": "! ", "（": " (", "）": ") ", "\u{3000}": " ",
            "．": ". ", // fullwidth dot: bilingual books number sentences "15．"
        ]
        var mapped = ""
        mapped.reserveCapacity(sentence.count)
        for character in sentence {
            if let replacement = cjkPunctuation[character] {
                mapped += replacement
            } else if character.unicodeScalars.allSatisfy({
                // Strip Unicode control (Cc) and format (Cf) characters — e.g.
                // U+200B zero-width space, U+FEFF BOM, U+200E LRM. Keep the
                // whitespace we normalize below (space/tab/newline are Cc).
                ($0.properties.generalCategory == .control
                    || $0.properties.generalCategory == .format)
                    && !$0.properties.isWhitespace
            }) {
                continue
            } else {
                mapped.append(character)
            }
        }
        return mapped.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
    }

    /// Bilingual study material interleaves the English sentence with Chinese
    /// annotations ("close to 是靠近的意思." / "【翻译技巧】…"). The English-only
    /// syntax engine produces garbage on such text, so keep only segments that
    /// read as English sentences: split at sentence-final punctuation, drop any
    /// segment containing CJK and any fragment shorter than three words
    /// (vocabulary glosses, list numbers). Text without CJK passes untouched.
    /// Returns "" when nothing sentence-like survives. Exposed for unit tests.
    static func extractEnglish(_ text: String) -> String {
        guard text.unicodeScalars.contains(where: isCJKScalar) else { return text }

        var segments: [String] = []
        var current = ""
        var afterTerminator = false
        for character in text {
            if afterTerminator, character.isWhitespace {
                segments.append(current)
                current = ""
                afterTerminator = false
                continue
            }
            if ".!?;".contains(character) {
                afterTerminator = true
            } else if !character.isWhitespace {
                afterTerminator = false
            }
            if !(character.isWhitespace && current.isEmpty) {
                current.append(character)
            }
        }
        if !current.isEmpty { segments.append(current) }

        return segments
            .filter { segment in
                !segment.unicodeScalars.contains(where: isCJKScalar)
                    && segment.split(whereSeparator: \.isWhitespace)
                        .filter { $0.contains(where: \.isLetter) }.count >= 3
            }
            .joined(separator: " ")
    }

    private static func isCJKScalar(_ scalar: Unicode.Scalar) -> Bool {
        scalar.properties.isIdeographic
            || (0x3000...0x303F).contains(scalar.value) // CJK punctuation 【】、
            || (0x3040...0x30FF).contains(scalar.value) // kana
            || (0xFF00...0xFFEF).contains(scalar.value) // fullwidth forms
    }

    // MARK: - Translation

    private static func translateOnly(sentence: String, client: LLMClient) async throws -> String {
        let raw = try await client.chat(
            system: "",
            user: HYMT2TranslationPolicy.sentencePrompt(source: sentence),
            temperature: HYMT2TranslationPolicy.temperature
        )
        let cleaned = cleanTranslationOutput(raw)
        guard !cleaned.isEmpty else { throw LLMError.emptyResponse }
        return cleaned
    }

    /// Remove common wrappers a local translation model may add despite an
    /// output-only instruction. Exposed internally for unit tests.
    static func cleanTranslationOutput(_ raw: String) -> String {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        text = text
            .replacingOccurrences(
                of: "^```(?:text|markdown)?\\s*",
                with: "",
                options: [.regularExpression, .caseInsensitive]
            )
            .replacingOccurrences(of: "```\\s*$", with: "", options: .regularExpression)
            .replacingOccurrences(
                of: "^\\s*<(?:target|translation)>\\s*",
                with: "",
                options: [.regularExpression, .caseInsensitive]
            )
            .replacingOccurrences(
                of: "\\s*</(?:target|translation)>\\s*$",
                with: "",
                options: [.regularExpression, .caseInsensitive]
            )
            .replacingOccurrences(
                of: "^\\s*(?:translation|chinese translation|译文|翻译)\\s*[:：]\\s*",
                with: "",
                options: [.regularExpression, .caseInsensitive]
            )
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
