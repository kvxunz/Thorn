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

    @Published var sentence: String = ""
    /// The last capture was a single word (phonics path), not a sentence.
    /// Internal setter for measurement tests only.
    var wordMode = false
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
        self.sentence = sentence
        self.wordMode = false
        self.pinned = false
        self.expanded = []
        self.hoveredHighlight = nil
        run()
    }

    func start(word: String) {
        self.sentence = word // recall (⌥Z) replays whatever is stored here
        self.wordMode = true
        self.pinned = false
        self.expanded = []
        self.hoveredHighlight = nil
        runWord()
    }

    /// Re-run the last capture through whichever pipeline produced it.
    func restart() {
        if wordMode {
            start(word: sentence)
        } else {
            start(sentence: sentence)
        }
    }

    /// Standalone message without any parse (e.g. selection too long).
    func presentError(_ message: String) {
        task?.cancel()
        activeRunID = nil
        sentence = ""
        pinned = false
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
                    Task { @MainActor in
                        guard self.activeRunID == runID else { return }
                        // Bare structure from the sidecar: tree now, translation later.
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
