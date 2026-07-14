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
    /// Text span + color to light up in the header sentence (any depth).
    @Published var hoveredHighlight: (text: String, color: Color)?
    /// Chunks whose children are currently shown; everything starts collapsed.
    @Published var expanded: Set<UUID> = []
    @Published var activeProvider: Provider = .ollama
    @Published var pinned = false

    var usingCloud: Bool { activeProvider == .custom }

    private var task: Task<Void, Never>?

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
        sentence = ""
        pinned = false
        status = .error(message)
    }

    /// Toggle between engines; results are cached per model, so flipping back is instant.
    func switchEngine(to provider: Provider) {
        guard provider != activeProvider else { return }
        activeProvider = provider
        run(provider: provider, force: false)
    }

    private func run(provider: Provider?, force: Bool) {
        task?.cancel()
        status = .loading
        hoveredChunkID = nil
        let sentence = self.sentence
        task = Task {
            do {
                let result = try await ParseService.parse(sentence: sentence, provider: provider, force: force) { partial in
                    Task { @MainActor in
                        guard self.task?.isCancelled == false else { return }
                        // Empty partial = stream fell back to a retry: show loading again.
                        self.status = partial.chunks.isEmpty ? .loading : .result(partial)
                    }
                }
                guard !Task.isCancelled else { return }
                ThornLog.info("parse ok, \(result.chunks.count) chunks")
                self.status = .result(result)
            } catch {
                guard !Task.isCancelled else { return }
                ThornLog.info("parse error: \(error.localizedDescription)")
                self.status = .error(error.localizedDescription)
            }
        }
    }

    func cancel() {
        task?.cancel()
    }
}
