import XCTest
@testable import Thorn

/// ⌥X: typed Chinese -> English -> the ordinary parse pipeline.
///
/// The network call itself belongs to the live suite; what is checked here is
/// every decision made around it, because those are the ones that decide
/// whether an English parser is handed English.
final class ComposeServiceTests: XCTestCase {
    func testRejectsEmptyInputBeforeReachingTheModel() async {
        for blank in ["", "   ", "\n\t "] {
            do {
                _ = try await ComposeService.englishSentence(from: blank)
                XCTFail("blank input reached the model: \(blank.debugDescription)")
            } catch let failure as ComposeService.Failure {
                XCTAssertEqual(failure, .empty)
            } catch {
                XCTFail("wrong error for blank input: \(error)")
            }
        }
    }

    func testRejectsInputLongerThanTheParserDownstreamCanTake() async {
        let long = String(repeating: "句", count: ComposeService.inputLimit + 1)
        do {
            _ = try await ComposeService.englishSentence(from: long)
            XCTFail("oversized input reached the model")
        } catch let failure as ComposeService.Failure {
            XCTAssertEqual(failure, .tooLong(ComposeService.inputLimit))
        } catch {
            XCTFail("wrong error for oversized input: \(error)")
        }
    }

    /// The failure this guard exists for: a translation model asked for
    /// English can answer in Chinese, and a Chinese "translation" fed to an
    /// English parser produces a confident tree of nonsense, not an error.
    func testChineseRepliesAreNotAcceptedAsAnEnglishTranslation() {
        XCTAssertFalse(ComposeService.looksEnglish("我昨天本来该把那封信寄出去的。"))
        XCTAssertFalse(ComposeService.looksEnglish(""))
        XCTAssertFalse(ComposeService.looksEnglish("。，！"))
        // Punctuation and digits are shared between the scripts: counting them
        // would let a Chinese reply pass on its commas.
        XCTAssertFalse(ComposeService.looksEnglish("好的，2026 年 8 月 4 日，一共 12 个。"))
    }

    func testEnglishRepliesSurviveTheirOwnPunctuationAndLoanwords() {
        XCTAssertTrue(
            ComposeService.looksEnglish("I should have mailed that letter yesterday.")
        )
        // A stray Chinese name or quotation inside an English sentence must
        // not tip the whole reply over.
        XCTAssertTrue(
            ComposeService.looksEnglish("He kept saying 加油 to everyone at the finish line.")
        )
    }

    /// A Chinese selection routes to compose instead of erroring. The guard
    /// that decides this must not be `!looksEnglish`: that would drag every
    /// other script onto a path that only speaks Chinese.
    func testChineseCapturesAreRoutedToComposeAndOtherScriptsAreNot() {
        XCTAssertTrue(ComposeService.looksChinese("我昨天本来该把那封信寄出去的。"))
        // A Chinese sentence quoting an English term is still Chinese.
        XCTAssertTrue(ComposeService.looksChinese("这个功能叫做 progressive disclosure，很好用。"))

        XCTAssertFalse(ComposeService.looksChinese("I should have mailed that letter."))
        XCTAssertFalse(ComposeService.looksChinese(""))
        XCTAssertFalse(ComposeService.looksChinese("。，！2026"))
        // Scripts Thorn cannot help with must keep their error, not be sent
        // to a Chinese-to-English translator.
        XCTAssertFalse(ComposeService.looksChinese("Съешь же ещё этих мягких булок."))
        XCTAssertFalse(ComposeService.looksChinese("すもももももももものうち"))
        // Kanji cannot carry the decision on its own: this is Japanese, and
        // half its letters are Han.
        XCTAssertFalse(ComposeService.looksChinese("私は学生で、毎日図書館に行きます。"))
        // A lone CJK glyph inside another script is not a Chinese sentence.
        XCTAssertFalse(ComposeService.looksChinese("한국어 문장 中 하나"))
    }

    /// The route is only reachable where an English sentence could not be
    /// found, so bilingual study material must still yield its English.
    func testBilingualMaterialIsNotMistakenForAChineseCapture() {
        let mixed = "【翻译技巧】the big seven industrial economies 是指西方七大工业国。"
            + "15．Economists have been particularly surprised by favorable inflation "
            + "figures in Britain and the United States."
        XCTAssertFalse(ComposeService.looksChinese(mixed))
        XCTAssertFalse(
            ParseService.extractEnglish(ParseService.normalizedInput(mixed)).isEmpty,
            "sanity: this is the path that must keep winning"
        )
    }

    func testComposePromptAsksForOneEnglishSentenceAndNothingElse() {
        let source = "我昨天本来该把那封信寄出去的。"
        let prompt = HYMT2TranslationPolicy.englishPrompt(source: source)

        XCTAssertTrue(prompt.contains("into English"))
        XCTAssertTrue(prompt.contains("Preserve every clause"))
        XCTAssertTrue(prompt.contains("Output only the translation"))
        XCTAssertTrue(prompt.hasSuffix(source))
        // The two directions must not be the same string with a word swapped
        // by accident; each has to name its own target language.
        XCTAssertFalse(prompt.contains("into Simplified Chinese"))
    }

    /// The Chinese in a compose result is the user's own sentence, so the
    /// second model call the reading path makes must not happen at all.
    func testKnownTranslationReplacesTheModelCallEntirely() async throws {
        let typed = "我昨天本来该把那封信寄出去的。"
        let structure = SidecarStructure(
            chunks: [Chunk(text: "I", role: .subject, gloss: "")],
            sourceTokens: ["I"]
        )
        let translateCalled = LockedFlag()

        let result = try await ParseService.completeAfterStructure(
            sentence: "I should have mailed that letter yesterday.",
            structure: structure,
            translate: {
                translateCalled.set()
                return "一段模型自己写的中文"
            }
        )
        XCTAssertTrue(translateCalled.value, "sanity: this helper does call translate")
        XCTAssertEqual(result.translation, "一段模型自己写的中文")

        // Compose passes the typed Chinese through the same closure slot, so
        // the model is never reached and the panel shows what was written.
        let composed = try await ParseService.completeAfterStructure(
            sentence: "I should have mailed that letter yesterday.",
            structure: structure,
            translate: { typed }
        )
        XCTAssertEqual(composed.translation, typed)
    }

    /// ⌥Z after a compose must replay the Chinese, not the English: replaying
    /// the English would run it through the reading path and answer with a
    /// machine paraphrase of the user's own sentence.
    @MainActor
    func testRecallHasSomethingToReplayBeforeTheEnglishExists() {
        let state = PanelState()
        XCTAssertFalse(state.hasSubject, "a fresh panel has nothing to recall")

        state.mode = .compose
        state.sentence = ""
        XCTAssertFalse(state.hasSubject)

        state.start(chinese: "我昨天本来该把那封信寄出去的。")
        XCTAssertTrue(
            state.hasSubject,
            "compose has a subject from the moment it is typed, not from when the model answers"
        )
        state.cancel()
    }
}

private final class LockedFlag: @unchecked Sendable {
    private let lock = NSLock()
    private var flag = false

    func set() {
        lock.lock()
        flag = true
        lock.unlock()
    }

    var value: Bool {
        lock.lock()
        defer { lock.unlock() }
        return flag
    }
}
