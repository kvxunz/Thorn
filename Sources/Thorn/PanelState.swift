import Foundation

@MainActor
final class PanelState: ObservableObject {
    enum Status: Equatable {
        case loading
        case result(ParseResult)
        case error(String)
    }

    @Published var sentence: String = ""
    @Published var status: Status = .loading
    @Published var hoveredChunkID: String?
    @Published var usingCloud = false

    private var task: Task<Void, Never>?

    func start(sentence: String) {
        self.sentence = sentence
        self.usingCloud = false
        run(provider: nil, force: false)
    }

    func reparseWithCloud() {
        usingCloud = true
        run(provider: .custom, force: true)
    }

    private func run(provider: Provider?, force: Bool) {
        task?.cancel()
        status = .loading
        hoveredChunkID = nil
        let sentence = self.sentence
        task = Task {
            do {
                let result = try await ParseService.parse(sentence: sentence, provider: provider, force: force)
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
