import AVFoundation
import Foundation

/// Local pronunciation via the system speech synthesizer — offline, no
/// audio leaves the machine. Kept as a singleton: a deallocated synthesizer
/// stops mid-utterance.
@MainActor
enum WordSpeaker {
    private static let synthesizer = AVSpeechSynthesizer()

    static func speak(_ word: String) {
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: word)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = 0.42 // a touch slower than default: learner pace
        synthesizer.speak(utterance)
    }
}

/// Single-word phonics pipeline: deterministic grapheme-phoneme blocks from
/// the bundled aligned dictionary (built offline by
/// scripts/build_phonics_dict.py), with a rule-based approximate split for
/// out-of-dictionary words. The Chinese meaning comes from the local Ollama
/// model, concurrently — structure never waits for it, mirroring the
/// sentence pipeline's structure/translation split.
enum PhonicsService {

    // MARK: - Public pipeline

    /// `onPartial` receives the bare decomposition immediately; the meaning
    /// slot fills in when the local model answers.
    static func analyze(word: String,
                        onPartial: (@Sendable (PhonicsResult) -> Void)? = nil) async throws -> PhonicsResult {
        let structure = decompose(word: word)
        onPartial?(structure)

        let model = SettingsStore.shared.translationModel
        guard !model.isEmpty else {
            return structure.withMeaning("（中文词义暂缺：请在设置里选择 Ollama 模型）")
        }
        do {
            let raw = try await OllamaCoordinator.shared.chat(
                model: model,
                messages: [OllamaMessage(
                    role: "user",
                    content: HYMT2TranslationPolicy.wordPrompt(source: structure.word)
                )],
                temperature: HYMT2TranslationPolicy.temperature,
                contextWindow: 2_048,
                maximumOutputTokens: 256,
                thinking: false,
                timeout: 120
            )
            try Task.checkCancellation()
            let meaning = ParseService.cleanTranslationOutput(raw)
            guard !meaning.isEmpty else { throw OllamaError.emptyResponse }
            return structure.withMeaning(meaning)
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            ThornLog.info("word meaning failed: \(error.localizedDescription)")
            return structure.withMeaning("（中文词义暂缺：本地模型未响应）")
        }
    }

    /// Dictionary blocks when the word is known, approximate rule split
    /// otherwise. Always succeeds for a word made of letters.
    static func decompose(word: String) -> PhonicsResult {
        // The dictionary is all-lowercase with ASCII apostrophes.
        let canonical = word.lowercased().replacingOccurrences(of: "’", with: "'")
        if let line = lookupLine(canonical), let entry = parseEntry(line: line) {
            return entry
        }
        return heuristicSplit(word: canonical)
    }

    // MARK: - Bundled dictionary lookup

    /// Memory-mapped sorted TSV; binary search over byte offsets, never
    /// loaded as a whole. nil when the resource is missing.
    private static let dictionary: Data? = {
        for path in candidatePaths() where FileManager.default.fileExists(atPath: path) {
            if let data = try? Data(contentsOf: URL(fileURLWithPath: path),
                                    options: .mappedIfSafe) {
                ThornLog.info("phonics dictionary: \(path), \(data.count) bytes")
                return data
            }
        }
        ThornLog.info("phonics dictionary missing (tried bundle + repo)")
        return nil
    }()

    private static func candidatePaths() -> [String] {
        var paths: [String] = []
        if let custom = UserDefaults.standard.string(forKey: "phonicsDict") {
            paths.append(custom)
        }
        if let bundled = Bundle.main.path(forResource: "phonics-en", ofType: "tsv") {
            paths.append(bundled)
        }
        // Development layout, same convention as the sidecar script default.
        paths.append(NSString(
            string: "~/xznm/code/Thorn/Resources/phonics-en.tsv"
        ).expandingTildeInPath)
        return paths
    }

    /// Exact-match lookup of a lowercase word; returns the full TSV line.
    static func lookupLine(_ word: String) -> String? {
        guard let data = dictionary, !data.isEmpty else { return nil }
        return lookupLine(word, in: data)
    }

    /// Binary search over a sorted "word<TAB>..." byte buffer (look(1)-style):
    /// probe an offset, snap to the containing line, byte-compare the key.
    /// Exposed with an explicit buffer for unit tests.
    static func lookupLine(_ word: String, in data: Data) -> String? {
        let key = Array(word.utf8) + [0x09] // word + tab, unambiguous prefix
        guard key.count > 1 else { return nil }

        func startOfLine(containing offset: Int) -> Int {
            var i = offset
            while i > 0 && data[i - 1] != 0x0A { i -= 1 }
            return i
        }
        func startOfNextLine(after lineStart: Int) -> Int {
            var i = lineStart
            while i < data.count && data[i] != 0x0A { i += 1 }
            return i + 1
        }
        // -1 line < key, 0 line starts with key, 1 line > key
        func compare(lineAt start: Int) -> Int {
            for (k, expected) in key.enumerated() {
                let index = start + k
                if index >= data.count { return -1 }
                let byte = data[index]
                if byte == 0x0A { return -1 } // line ended before the key did
                if byte != expected { return byte < expected ? -1 : 1 }
            }
            return 0
        }
        func line(at start: Int) -> String? {
            var end = start
            while end < data.count && data[end] != 0x0A { end += 1 }
            return String(data: data.subdata(in: start..<end), encoding: .utf8)
        }

        var low = 0
        var high = data.count
        while low < high {
            let mid = low + (high - low) / 2
            let start = startOfLine(containing: mid)
            switch compare(lineAt: start) {
            case 0:
                return line(at: start)
            case ..<0:
                low = startOfNextLine(after: start) // > mid, loop shrinks
            default:
                high = start
            }
        }
        return nil
    }

    // MARK: - TSV entry parsing

    /// `word<TAB>ipa<TAB>[g:ipa|g:ipa].ˈ[g:ipa]` (see build_phonics_dict.py).
    /// Malformed lines return nil — a wrong split is worse than fallback.
    static func parseEntry(line: String) -> PhonicsResult? {
        let fields = line.split(separator: "\t", omittingEmptySubsequences: false)
        guard fields.count == 3, !fields[0].isEmpty, !fields[1].isEmpty else { return nil }
        let word = String(fields[0])

        var syllables: [PhonicsSyllable] = []
        for part in fields[2].split(separator: ".") {
            var body = Substring(part)
            var stress = PhonicsStress.none
            if body.hasPrefix("ˈ") { stress = .primary; body = body.dropFirst() }
            else if body.hasPrefix("ˌ") { stress = .secondary; body = body.dropFirst() }
            guard body.hasPrefix("["), body.hasSuffix("]") else { return nil }
            body = body.dropFirst().dropLast()

            var chunks: [PhonicsChunk] = []
            for piece in body.split(separator: "|", omittingEmptySubsequences: false) {
                guard let colon = piece.firstIndex(of: ":") else { return nil }
                let grapheme = String(piece[..<colon])
                let ipa = String(piece[piece.index(after: colon)...])
                guard !grapheme.isEmpty else { return nil }
                chunks.append(PhonicsChunk(grapheme: grapheme,
                                           ipa: ipa.isEmpty ? nil : ipa))
            }
            guard !chunks.isEmpty else { return nil }
            syllables.append(PhonicsSyllable(chunks: chunks, stress: stress))
        }
        guard !syllables.isEmpty else { return nil }

        // Same invariant the generator enforces; distrust the file anyway.
        let rebuilt = syllables.flatMap(\.chunks).map(\.grapheme).joined()
        guard rebuilt == word else { return nil }

        return PhonicsResult(word: word, ipa: String(fields[1]),
                             syllables: syllables, approximate: false, meaning: "")
    }

    // MARK: - Heuristic fallback (out-of-dictionary words)

    /// Multi-letter graphemes recognized by the approximate splitter,
    /// longest-first. Consonant blends (str, pl) stay as separate letters —
    /// phonics treats them as individual sounds.
    private static let multigraphs: [String] = [
        "eigh", "ough", "augh",
        "igh", "tch", "dge",
        "ch", "sh", "th", "ph", "wh", "ck", "ng", "qu", "kn", "wr", "gh",
        "ee", "ea", "ai", "ay", "oa", "ow", "ou", "oo", "oi", "oy",
        "au", "aw", "ue", "ew", "ie", "ei", "ey",
        "ar", "er", "ir", "or", "ur",
    ]

    private static func isVowelLetter(_ character: Character) -> Bool {
        "aeiou".contains(character)
    }

    /// Deterministic approximate split: greedy longest-match graphemes,
    /// magic-e attachment, and open-syllable grouping. No pronunciation is
    /// guessed — chunks carry no IPA and the result is flagged approximate.
    static func heuristicSplit(word: String) -> PhonicsResult {
        let letters = Array(word)
        var chunks: [(grapheme: String, nucleus: Bool)] = []
        var i = 0
        while i < letters.count {
            if !letters[i].isLetter { // apostrophe / hyphen rides along
                if chunks.isEmpty {
                    chunks.append((String(letters[i]), false))
                } else {
                    chunks[chunks.count - 1].grapheme.append(letters[i])
                }
                i += 1
                continue
            }
            var taken = 1
            for candidate in multigraphs where letters.count - i >= candidate.count {
                if String(letters[i..<i + candidate.count]) == candidate {
                    taken = candidate.count
                    break
                }
            }
            let grapheme = String(letters[i..<i + taken])
            // "y" acts as a vowel anywhere but the word-initial position.
            let nucleus = grapheme.contains(where: isVowelLetter)
                || (grapheme == "y" && i > 0)
            chunks.append((grapheme, nucleus))
            i += taken
        }

        // Magic-e: a trailing lone "e" after a single consonant joins it
        // (make -> m|a|ke) and stops counting as a syllable nucleus.
        if chunks.count >= 3,
           chunks[chunks.count - 1].grapheme == "e",
           chunks[chunks.count - 2].grapheme.count == 1,
           !chunks[chunks.count - 2].nucleus,
           chunks[0..<chunks.count - 2].contains(where: \.nucleus) {
            let consonant = chunks[chunks.count - 2].grapheme
            chunks.removeLast(2)
            chunks.append((consonant + "e", false))
        }

        // Open-syllable grouping: a lone consonant between nuclei starts the
        // next syllable; two or more split after the first.
        let nucleusIndices = chunks.indices.filter { chunks[$0].nucleus }
        var boundaries: [Int] = []
        for (current, next) in zip(nucleusIndices, nucleusIndices.dropFirst()) {
            let consonants = next - current - 1
            boundaries.append(consonants >= 2 ? current + 2 : next - consonants)
        }

        var syllables: [PhonicsSyllable] = []
        var start = 0
        for boundary in boundaries + [chunks.count] {
            let group = chunks[start..<boundary].map {
                PhonicsChunk(grapheme: $0.grapheme, ipa: nil)
            }
            if !group.isEmpty {
                syllables.append(PhonicsSyllable(chunks: group, stress: .none))
            }
            start = boundary
        }
        if syllables.isEmpty {
            syllables = [PhonicsSyllable(
                chunks: [PhonicsChunk(grapheme: word, ipa: nil)], stress: .none
            )]
        }
        return PhonicsResult(word: word, ipa: nil, syllables: syllables,
                             approximate: true, meaning: "")
    }
}
