import Foundation

enum ParseService {
    private enum LocalPipelineError: LocalizedError {
        case structureUnavailable(String)
        case sidecarScriptMissing(String)
        case noEnglishSentence
        case modelNotConfigured

        var errorDescription: String? {
            switch self {
            case .structureUnavailable(let installCommand):
                return "本地句法引擎暂不可用。若尚未安装 Benepar 模型，请执行：\n"
                    + "\(installCommand)\n"
                    + "启动应用不会自动下载模型。"
            case .sidecarScriptMissing(let path):
                return "句法引擎脚本不存在：\(path)\n仓库被移动或删除？可执行 "
                    + "defaults write com.xvz.thorn sidecarScript /新路径/server.py 指定新位置。"
            case .noEnglishSentence:
                return "选中内容主要是中文注释，没有找到可拆解的英文句子"
            case .modelNotConfigured:
                return "本地翻译模型未配置，请在设置里选择 Ollama 模型"
            }
        }
    }

    /// Local two-stage pipeline:
    /// 1. Sidecar `/parse` — deterministic teaching chunk tree (no LLM)
    /// 2. HY-MT2 whole-sentence translation only (no per-chunk glosses)
    ///
    /// `onPartial` receives and presents the bare structure before HY-MT2 is
    /// started, so translation can never delay the first useful result.
    ///
    /// `knownTranslation` is the ⌥X compose path: the Chinese there is what
    /// the user typed, so the sentence already has a meaning attached and
    /// asking the model to translate it back would both cost a second load and
    /// answer with a paraphrase of the user's own words.
    static func parse(sentence: String,
                      knownTranslation: String? = nil,
                      onPartial: (@Sendable (ParseResult) async -> Void)? = nil) async throws -> ParseResult {
        let model = await MainActor.run { SettingsStore.shared.translationModel }
        guard !model.isEmpty || knownTranslation != nil else {
            throw LocalPipelineError.modelNotConfigured
        }
        // Mixed bilingual selections keep only their English sentences; the
        // hotkey path pre-extracts too, so this is a backstop for direct calls.
        let normalized = extractEnglish(normalizedInput(sentence))
        guard !normalized.isEmpty else {
            throw LocalPipelineError.noEnglishSentence
        }

        let structure: SidecarStructure
        do {
            structure = try await Sidecar.shared.structure(for: normalized)
        } catch SidecarFailure.unavailable {
            if let missing = await Sidecar.shared.missingScriptPath() {
                throw LocalPipelineError.sidecarScriptMissing(missing)
            }
            throw LocalPipelineError.structureUnavailable(
                await Sidecar.shared.modelInstallCommand()
            )
        } catch {
            throw error
        }

        return try await completeAfterStructure(
            sentence: normalized,
            structure: structure,
            onPartial: onPartial
        ) {
            if let knownTranslation { return knownTranslation }
            return try await translateOnly(sentence: normalized, model: model)
        }
    }

    /// The ordering boundary between the fast deterministic result and the
    /// slower local translation. Kept as a small helper so the contract can be
    /// tested without launching either model.
    static func completeAfterStructure(
        sentence: String,
        structure: SidecarStructure,
        onPartial: (@Sendable (ParseResult) async -> Void)? = nil,
        translate: @Sendable () async throws -> String
    ) async throws -> ParseResult {
        try Task.checkCancellation()
        let bare = ParseResult(sentence: sentence, chunks: structure.chunks, translation: "")
        await onPartial?(bare)
        do {
            let translation = try await translate()
            try Task.checkCancellation()
            return ParseResult(sentence: sentence, chunks: structure.chunks, translation: translation)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            ThornLog.info("local translation failed: \(error.localizedDescription)")
            // Structure alone still beats nothing — fill the translation slot
            // so the panel doesn't spin forever waiting for one.
            return ParseResult(
                sentence: sentence,
                chunks: structure.chunks,
                translation: "（中文释义暂缺：本地模型未响应，结构来自句法引擎）"
            )
        }
    }

    /// Text copied from bilingual reading material often carries CJK fullwidth
    /// punctuation ("troubles，or so") and invisible control/format characters
    /// (zero-width spaces, bidi marks) wedged between words. spaCy's English
    /// models misattach dependencies around the former and render the latter as
    /// tofu boxes in the header, so clean both before parsing.
    /// Exposed internally for unit tests.
    static func normalizedInput(_ sentence: String) -> String {
        let cjkPunctuation: [Character: String] = [
            "，": ", ", "。": ". ", "、": ", ", "；": "; ", "：": ": ",
            "？": "? ", "！": "! ", "（": " (", "）": ") ", "\u{3000}": " ",
            "．": ". ", // fullwidth dot: bilingual books number sentences "15．"
            // Curly quotes were left alone for years as "normal English
            // typography", which is true of the text and false of the parser.
            // Measured on "It’s all deliciously ironic ...": with U+2019,
            // spaCy tags `all` PRON/dep — its no-label-fits fallback, which no
            // chunk rule claims, so the card reads 其他. Swap in an ASCII
            // apostrophe and the same sentence gives ADV/advmod, i.e. 状语.
            // Everything copied out of a web page or an ebook arrives this
            // way, so this was the common case degrading, not an edge one.
            "\u{2018}": "'", "\u{2019}": "'", "\u{02BC}": "'",
            "\u{201C}": "\"", "\u{201D}": "\"",
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
            } else if character.unicodeScalars.allSatisfy({
                $0.properties.generalCategory == .privateUse
                    || $0.value == 0xFFFC // object replacement character
                    || $0.value == 0xFFFD // leaked decode replacement
            }) {
                // Preserve a word boundary: deleting an inline attachment
                // marker could fuse "Security" and "with".
                mapped.append(" ")
            } else {
                mapped.append(character)
            }
        }
        // PDF / OCR junk: footnote-like [tObj] [cObj] glued to words, exotic
        // spaces, soft hyphens, and line-wrapped hyphenated words. Dash runs
        // stay byte-for-byte intact here: the sidecar creates its own
        // parser-only spaced view while retaining source offsets.
        var text = mapped
            .replacingOccurrences(
                of: "[\u{00A0}\u{1680}\u{2000}-\u{200A}\u{202F}\u{205F}]",
                with: " ",
                options: .regularExpression
            )
            .replacingOccurrences(of: "\u{00AD}", with: "") // soft hyphen
            .replacingOccurrences(of: "\u{2060}", with: "") // word joiner
            .replacingOccurrences(
                of: "\\[[A-Za-z0-9]{1,8}\\]",
                with: "",
                options: .regularExpression
            )
            .replacingOccurrences(
                // Conservative dehyphenation: only join a letter + hyphen at
                // a line break to a lowercase continuation.
                of: "([A-Za-z])-\\s+(?=[a-z])",
                with: "$1-",
                options: .regularExpression
            )
            .replacingOccurrences(
                // A missing space after strong ASCII punctuation is a safe
                // copy/PDF repair. Do not guess inside words ("orall").
                of: "([,;:!?])(?=[A-Za-z])",
                with: "$1 ",
                options: .regularExpression
            )
        text = text.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
        return text
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

    /// A capture that is one English word — letters with optional internal
    /// apostrophe/hyphen — once surrounding punctuation is stripped. Such
    /// input goes to the phonics path instead of the sentence parser.
    /// Returns the cleaned word, or nil for anything sentence-like.
    static func singleWord(in text: String) -> String? {
        let surrounding = CharacterSet(charactersIn: "\"“”„«»‘’'()[]{}<>.,;:!?¡¿…·•*_—–- \t\n")
        let trimmed = text.trimmingCharacters(in: surrounding)
        guard !trimmed.isEmpty, !trimmed.contains(where: \.isWhitespace) else { return nil }
        let normalized = trimmed.replacingOccurrences(of: "’", with: "'")
        guard normalized.range(
            of: "^[A-Za-z][A-Za-z'\\-]*$",
            options: .regularExpression
        ) != nil else { return nil }
        return normalized
    }

    private static func isCJKScalar(_ scalar: Unicode.Scalar) -> Bool {
        scalar.properties.isIdeographic
            || (0x3000...0x303F).contains(scalar.value) // CJK punctuation 【】、
            || (0x3040...0x30FF).contains(scalar.value) // kana
            || (0xFF00...0xFFEF).contains(scalar.value) // fullwidth forms
    }

    // MARK: - Translation

    private static func translateOnly(sentence: String, model: String) async throws -> String {
        let raw = try await OllamaCoordinator.shared.chat(
            model: model,
            messages: [OllamaMessage(
                role: "user",
                content: HYMT2TranslationPolicy.sentencePrompt(source: sentence)
            )],
            temperature: HYMT2TranslationPolicy.temperature,
            contextWindow: 8_192,
            maximumOutputTokens: 1_024,
            thinking: false,
            timeout: 120
        )
        let cleaned = cleanTranslationOutput(raw)
        guard !cleaned.isEmpty else { throw OllamaError.emptyResponse }
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
