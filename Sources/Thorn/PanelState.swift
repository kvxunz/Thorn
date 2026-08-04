import Foundation
import SwiftUI

@MainActor
final class PanelState: ObservableObject {
    enum Status: Equatable {
        case loading
        case result(ParseResult)
        case word(PhonicsResult)
        case error(String)
    }

    /// Which pipeline produced what is on screen. Was a `wordMode` Bool until
    /// ⌥X added a third; two Bools would have had a fourth, illegal state.
    enum Mode {
        /// ⌥A / ⌥S: captured English, parsed and translated into Chinese.
        case sentence
        /// ⌥A on a single word: phonics decomposition.
        case word
        /// ⌥X: typed Chinese, translated into English, then parsed.
        case compose
    }

    @Published var sentence: String = ""
    /// Internal setter for measurement tests only.
    var mode: Mode = .sentence
    /// Word cards are measured and sized differently everywhere; this is the
    /// distinction those call sites actually care about.
    var wordMode: Bool { mode == .word }
    /// The Chinese the user typed (⌥X). Kept so ⌥Z can replay the compose from
    /// its real source rather than from the English the model produced.
    private(set) var composeSource = ""

    /// Whether there is anything for ⌥Z to bring back. A compose that failed
    /// before the model answered has no English sentence yet but still has the
    /// Chinese that produced it, which is the thing worth retrying.
    var hasSubject: Bool { !sentence.isEmpty || !composeSource.isEmpty }
    @Published var status: Status = .loading
    @Published var hoveredChunkID: UUID?
    /// Exact character span + color to light up in the header sentence.
    @Published var hoveredHighlight: (range: Range<Int>, color: Color)?
    /// Chunks whose children are currently shown; everything starts collapsed.
    @Published var expanded: Set<UUID> = []
    @Published var pinned = false

    private var task: Task<Void, Never>?
    private var activeRunID: UUID?

    func start(sentence: String) {
        reset(mode: .sentence, subject: sentence)
        run()
    }

    func start(word: String) {
        reset(mode: .word, subject: word)
        runWord()
    }

    /// ⌥X: the subject is Chinese, and the English it becomes is not known
    /// until the model answers.
    func start(chinese: String) {
        reset(mode: .compose, subject: "")
        composeSource = chinese
        runCompose()
    }

    private func reset(mode: Mode, subject: String) {
        self.sentence = subject // recall (⌥Z) replays whatever is stored here
        self.mode = mode
        self.composeSource = ""
        self.pinned = false
        self.expanded = []
        self.hoveredHighlight = nil
    }

    /// Re-run the last capture through whichever pipeline produced it.
    func restart() {
        switch mode {
        case .sentence: start(sentence: sentence)
        case .word: start(word: sentence)
        case .compose: start(chinese: composeSource)
        }
    }

    /// Standalone message without any parse (e.g. selection too long).
    func presentError(_ message: String) {
        task?.cancel()
        activeRunID = nil
        reset(mode: .sentence, subject: "")
        status = .error(message)
    }

    private func run() {
        task?.cancel()
        let runID = UUID()
        activeRunID = runID
        status = .loading
        hoveredChunkID = nil
        let sentence = self.sentence
        task = Task {
            do {
                let result = try await ParseService.parse(sentence: sentence) { partial in
                    await MainActor.run {
                        guard self.activeRunID == runID else { return }
                        // This awaited handoff completes before HY-MT2 starts.
                        self.status = .result(partial)
                    }
                }
                guard self.activeRunID == runID else {
                    ThornLog.info("parse finished but run was superseded; dropping result")
                    return
                }
                // Even if the Task was cancelled mid-flight, surface a finished
                // result when this run is still the active one (hide ≠ cancel).
                ThornLog.info("parse ok, \(result.chunks.count) chunks, translation=\(result.translation.isEmpty ? "empty" : "ok")")
                self.status = .result(result)
            } catch is CancellationError {
                ThornLog.info("parse cancelled")
                guard self.activeRunID == runID else { return }
                if case .result(let partial) = self.status, partial.translation.isEmpty {
                    self.status = .result(ParseResult(
                        sentence: partial.sentence,
                        chunks: partial.chunks,
                        translation: "（已取消：整句翻译未完成）"
                    ))
                }
            } catch {
                guard self.activeRunID == runID else { return }
                ThornLog.info("parse error type: \(String(describing: type(of: error)))")
                self.status = .error(error.localizedDescription)
            }
        }
    }

    /// Compose runs two models back to back, so unlike the reading path there
    /// is nothing useful to show in between: the sidecar cannot start until
    /// HY-MT2 has produced the sentence it is meant to cut up.
    private func runCompose() {
        task?.cancel()
        let runID = UUID()
        activeRunID = runID
        status = .loading
        hoveredChunkID = nil
        let chinese = self.composeSource
        task = Task {
            do {
                let english = try await ComposeService.englishSentence(from: chinese)
                try Task.checkCancellation()
                guard self.activeRunID == runID else { return }
                // Publish the English before the parse so the header stops
                // saying "翻译成英文中…" the moment there is an English sentence.
                self.sentence = english
                let result = try await ParseService.parse(
                    sentence: english,
                    // The Chinese is the user's own; translating the English
                    // back would answer with a paraphrase of what they wrote.
                    knownTranslation: chinese
                ) { partial in
                    await MainActor.run {
                        guard self.activeRunID == runID else { return }
                        self.status = .result(partial)
                    }
                }
                guard self.activeRunID == runID else { return }
                ThornLog.info("compose ok, \(result.chunks.count) chunks")
                self.status = .result(result)
            } catch is CancellationError {
                guard self.activeRunID == runID else { return }
                if case .loading = self.status {
                    self.status = .error("已取消")
                }
            } catch {
                guard self.activeRunID == runID else { return }
                ThornLog.info("compose error: \(error.localizedDescription)")
                self.status = .error(error.localizedDescription)
            }
        }
    }

    private func runWord() {
        task?.cancel()
        let runID = UUID()
        activeRunID = runID
        status = .loading
        hoveredChunkID = nil
        let word = self.sentence
        task = Task {
            do {
                let result = try await PhonicsService.analyze(word: word) { partial in
                    Task { @MainActor in
                        guard self.activeRunID == runID else { return }
                        // Blocks on screen immediately, meaning pending.
                        self.status = .word(partial)
                    }
                }
                guard self.activeRunID == runID else { return }
                ThornLog.info("phonics ok, \(result.syllables.count) syllables, "
                    + "approximate=\(result.approximate)")
                self.status = .word(result)
            } catch is CancellationError {
                guard self.activeRunID == runID else { return }
                if case .word(let partial) = self.status, partial.meaning.isEmpty {
                    self.status = .word(partial.withMeaning("（已取消：中文词义未完成）"))
                }
            } catch {
                guard self.activeRunID == runID else { return }
                self.status = .error(error.localizedDescription)
            }
        }
    }

    func cancel() {
        task?.cancel()
        activeRunID = nil
        // Never leave the panel on a half-result spinner (structure without
        // translation) after an intentional cancel.
        if case .result(let result) = status, result.translation.isEmpty {
            status = .result(ParseResult(
                sentence: result.sentence,
                chunks: result.chunks,
                translation: "（已取消：整句翻译未完成）"
            ))
        } else if case .word(let result) = status, result.meaning.isEmpty {
            status = .word(result.withMeaning("（已取消：中文词义未完成）"))
        } else if case .loading = status {
            status = .error("已取消")
        }
    }
}
