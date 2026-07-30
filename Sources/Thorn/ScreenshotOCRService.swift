import AppKit
import CoreGraphics
import Vision

struct OCRTextLine: Equatable, Sendable {
    let text: String
    let boundingBox: CGRect
}

enum ScreenshotOCRFailure: LocalizedError, Sendable {
    case permissionDenied
    case captureFailed
    case imageUnreadable
    case recognitionFailed(String)
    case noText

    var errorDescription: String? {
        switch self {
        case .permissionDenied:
            return "框选识字需要“屏幕与系统音频录制”权限。请在系统设置 → 隐私与安全性中允许 Thorn，然后重试。"
        case .captureFailed:
            return "没有取得框选截图，请重新按 ⌥S 后拖动选择文字区域。"
        case .imageUnreadable:
            return "框选截图无法读取，请重新选择清晰一些的文字区域。"
        case .recognitionFailed(let detail):
            return "本地 OCR 识别失败：\(detail)"
        case .noText:
            return "框选区域内没有识别到可拆解的文字。"
        }
    }
}

/// Interactive region capture followed by Apple's on-device Vision OCR.
/// No screenshot or recognized text leaves the Mac.
enum ScreenshotOCRService {
    /// Returns nil when the user cancels the interactive selection.
    @MainActor
    static func captureText() async throws -> String? {
        // TCC permission prompts are UI and must be requested from the main
        // actor. The blocking capture/OCR work itself stays detached below.
        guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
            throw ScreenshotOCRFailure.permissionDenied
        }

        // `screencapture` refuses `/dev/fd/*` and `/dev/stdout` destinations
        // (it needs a seekable regular file), so pixels are written to a
        // per-capture file in a 0700 directory and unlinked the instant they
        // are read. They never reach the global pasteboard.
        return try await Task.detached(priority: .userInitiated) {
            guard let data = try captureImageDataSynchronously() else {
                return nil // Escape produces no PNG bytes.
            }
            guard let image = NSImage(data: data) else {
                throw ScreenshotOCRFailure.imageUnreadable
            }
            var proposedRect = CGRect(origin: .zero, size: image.size)
            guard let cgImage = image.cgImage(
                forProposedRect: &proposedRect,
                context: nil,
                hints: nil
            ) else {
                throw ScreenshotOCRFailure.imageUnreadable
            }
            return try recognizeText(in: cgImage)
        }.value
    }

    static func readingOrder(_ lines: [OCRTextLine]) -> [OCRTextLine] {
        // First use a strict total order, then form rows. A pairwise
        // "approximately same Y" comparator is non-transitive and can make
        // Swift's sort produce unstable reading order.
        let vertical = lines.sorted {
            if $0.boundingBox.midY != $1.boundingBox.midY {
                return $0.boundingBox.midY > $1.boundingBox.midY
            }
            return $0.boundingBox.minX < $1.boundingBox.minX
        }
        var rows: [[OCRTextLine]] = []
        for line in vertical {
            if let last = rows.indices.last {
                let referenceY = rows[last]
                    .map(\.boundingBox.midY)
                    .reduce(0, +) / CGFloat(rows[last].count)
                let referenceHeight = rows[last]
                    .map(\.boundingBox.height)
                    .max() ?? line.boundingBox.height
                let tolerance = max(referenceHeight, line.boundingBox.height) * 0.55
                if abs(referenceY - line.boundingBox.midY) <= tolerance {
                    rows[last].append(line)
                    continue
                }
            }
            rows.append([line])
        }
        return rows.flatMap { $0.sorted { $0.boundingBox.minX < $1.boundingBox.minX } }
    }

    private static func captureImageDataSynchronously() throws -> Data? {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("Thorn-ocr", isDirectory: true)
        try? FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let fileURL = directory.appendingPathComponent(UUID().uuidString + ".png")
        defer { try? FileManager.default.removeItem(at: fileURL) }

        let process = Process()
        let errorPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        process.arguments = ["-i", "-x", "-tpng", fileURL.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = errorPipe
        do {
            try process.run()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            try Task.checkCancellation()

            if let data = try? Data(contentsOf: fileURL), !data.isEmpty {
                return data
            }
            // No image on disk. A user cancel (Escape / empty selection) exits
            // quietly; a real failure prints to stderr. Only the former is a
            // silent no-op — surface the latter instead of swallowing it.
            let message = String(decoding: errorData, as: UTF8.self)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard message.isEmpty else {
                ThornLog.info("screencapture failed: \(message)")
                throw ScreenshotOCRFailure.captureFailed
            }
            return nil
        } catch is CancellationError {
            throw CancellationError()
        } catch let failure as ScreenshotOCRFailure {
            throw failure
        } catch {
            throw ScreenshotOCRFailure.captureFailed
        }
    }

    private static func recognizeText(in cgImage: CGImage) throws -> String {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.recognitionLanguages = ["en-US"]
        do {
            try VNImageRequestHandler(cgImage: cgImage, options: [:]).perform([request])
        } catch {
            throw ScreenshotOCRFailure.recognitionFailed(error.localizedDescription)
        }
        try Task.checkCancellation()

        let lines = (request.results ?? []).compactMap { observation -> OCRTextLine? in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? nil : OCRTextLine(text: text, boundingBox: observation.boundingBox)
        }
        let text = readingOrder(lines).map(\.text).joined(separator: " ")
        guard !text.isEmpty else { throw ScreenshotOCRFailure.noText }
        return text
    }
}
