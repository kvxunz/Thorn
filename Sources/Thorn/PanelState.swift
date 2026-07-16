import Foundation
import SwiftUI

@MainActor
final class PanelState: ObservableObject {
    enum Status: Equatable {
        case loading
        case result(ParseResult)
        case error(String)
    }

    @Published var sentence: String = ""
    @Published var status: Status = .loading
    @Published var hoveredChunkID: UUID?
    /// Exact character span + color to light up in the header sentence.
    @Published var hoveredHighlight: (range: Range<Int>, color: Color)?
    /// Chunks whose children are currently shown; everything starts collapsed.
    @Published var expanded: Set<UUID> = []
    @Published var activeProvider: Provider = .ollama
    @Published var pinned = false

    var usingCloud: Bool { activeProvider == .custom }

    private var task: Task<Void, Never>?
    private var activeRunID: UUID?

    func start(sentence: String) {
        self.sentence = sentence
        self.activeProvider = SettingsStore.shared.provider
        self.pinned = false
        self.expanded = []
        self.hoveredHighlight = nil
        run(provider: activeProvider, force: false)
    }

    /// Standalone message without any parse (e.g. selection too long).
    func presentError(_ message: String) {
        task?.cancel()
        activeRunID = nil
        sentence = ""
        pinned = false
        status = .error(message)
    }

    /// Toggle between engines and re-run the live pipeline for the current sentence.
    func switchEngine(to provider: Provider) {
        guard provider != activeProvider else { return }
        activeProvider = provider
        run(provider: provider, force: false)
    }

    private func run(provider: Provider?, force: Bool) {
        task?.cancel()
        let runID = UUID()
        activeRunID = runID
        status = .loading
        hoveredChunkID = nil
        let sentence = self.sentence
        task = Task {
            do {
                let result = try await ParseService.parse(sentence: sentence, provider: provider, force: force) { partial in
                    Task { @MainActor in
                        guard self.activeRunID == runID else { return }
                        // Empty partial = stream fell back to a retry: show loading again.
                        self.status = partial.chunks.isEmpty ? .loading : .result(partial)
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
                ThornLog.info("parse error: \(error.localizedDescription)")
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
        } else if case .loading = status {
            status = .error("已取消")
        }
    }
}
