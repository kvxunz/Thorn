import Foundation

enum ParseService {
    private static let systemPrompt = """
    You are an English sentence-structure analyzer for Chinese learners doing intensive reading.

    Given English text (one sentence, or a few consecutive sentences), split it into sense groups (意群) in original order and translate. If there are several sentences, chunk each sentence in turn within the same "chunks" array.

    Output STRICT JSON only, no markdown, no commentary:
    {
      "chunks": [
        {"text": "<exact substring>", "role": "<role>", "gloss": "<自然的中文释义>",
         "children": [ ...same shape, only when this chunk contains a clause... ]}
      ],
      "translation": "<流畅的中文翻译>"
    }

    Roles: subject, verb, object, complement, clause-relative, clause-adverbial, clause-noun, prep-phrase, insertion, conjunction, relative, adverbial, other

    Chunking:
    - Backbone components each get their OWN chunk: subject / verb / object / complement — never merge the subject or object into the verb chunk. The verb chunk keeps its auxiliaries and fixed particles ("have to get used to", "benefit from" are each ONE verb chunk).
    - Linking verbs (be/become/seem/remain...) take a predicative with role "complement", never an object; verb and predicative are separate chunks. Infinitive complements ("to purchase assets") are "complement", never "other".
    - Modifiers are separate chunks: prep-phrases, subordinate clauses, adverbials. Participial phrases ("Standing at the door,") are "adverbial"; appositives ("John, a local farmer,") are "insertion".
    - Coordinate clauses (and/but/or/so, often after a dash or semicolon) are MAIN clauses: decompose each into its own backbone. The joining conjunction ("—but", "or at least") is its own "conjunction" chunk, never glued to a neighbor.
    - Keep original word order. One exception: in questions, the inverted aux+subject+verb group ("must we master") stays ONE verb chunk and the question word (Why/How...) is "adverbial". In declarative clauses the subject ALWAYS stands alone.
    - Never make a punctuation-only chunk: attach punctuation to the preceding chunk (a clause-introducing dash stays with its conjunction: "—but").

    Clauses and recursion:
    - clause-* roles ONLY for subordinate clauses containing their own subject and verb. Prep-phrases and V-ing phrases without their own subject ("in other places", "making a decision") are NOT clauses.
    - Every clause-* chunk MUST have "children" decomposing it into its own components (split out its internal prep-phrases and adverbials too), recursively if a child is itself a clause.
    - Inside a clause the introducing word gets its true role: relative pronouns (which/who/that referring to a noun) are "relative", glossed by their referent ("指代前述委员会"); subordinating conjunctions (when/if/because, noun-clause "that") are "conjunction".
    - A non-clause chunk has "children" ONLY when a clause is embedded in it ("everyone who attended" -> "everyone" + the who-clause).

    Invariants:
    - Top-level chunk texts concatenated in order = the WHOLE input, word for word. A parent's text = its children's texts concatenated.
    - "gloss": concise Chinese for that chunk in context. "translation": fluent Chinese covering ALL input sentences, not a concatenation of glosses.

    Example, for "In other places, people have to get used to the rain and cold when autumn comes.":
    {"chunks":[
      {"text":"In other places,","role":"prep-phrase","gloss":"在其他地方"},
      {"text":"people","role":"subject","gloss":"人们"},
      {"text":"have to get used to","role":"verb","gloss":"不得不习惯"},
      {"text":"the rain and cold","role":"object","gloss":"雨水和寒冷"},
      {"text":"when autumn comes.","role":"clause-adverbial","gloss":"当秋天到来时","children":[
        {"text":"when","role":"conjunction","gloss":"当…时"},
        {"text":"autumn","role":"subject","gloss":"秋天"},
        {"text":"comes.","role":"verb","gloss":"到来"}
      ]}
    ],"translation":"在其他地方，秋天来临时人们不得不习惯雨水和寒冷。"}

    Example with coordinate clauses, for "The committee praised the ambitious proposal—but in the end they rejected it unanimously.":
    {"chunks":[
      {"text":"The committee","role":"subject","gloss":"委员会"},
      {"text":"praised","role":"verb","gloss":"称赞了"},
      {"text":"the ambitious proposal","role":"object","gloss":"这份雄心勃勃的提案"},
      {"text":"—but","role":"conjunction","gloss":"但是"},
      {"text":"in the end","role":"adverbial","gloss":"最终"},
      {"text":"they","role":"subject","gloss":"他们"},
      {"text":"rejected","role":"verb","gloss":"否决了"},
      {"text":"it","role":"object","gloss":"它"},
      {"text":"unanimously.","role":"adverbial","gloss":"一致地"}
    ],"translation":"委员会称赞了这份雄心勃勃的提案——但最终他们一致否决了它。"}

    Copy chunk text EXACTLY from the input sentence, word for word. Never drop or alter words. Do not reuse wording from the examples.
    """

    /// Parse via given provider; cache hit returns instantly. Retries once on malformed JSON.
    /// `onPartial` receives progressively growing results while the model streams
    /// (Chat Completions wire only; Responses gateways deliver in one piece).
    static func parse(sentence: String, provider: Provider? = nil, force: Bool = false,
                      onPartial: (@Sendable (ParseResult) -> Void)? = nil) async throws -> ParseResult {
        let ep = SettingsStore.shared.endpoint(for: provider)
        guard !ep.baseURL.isEmpty, !ep.model.isEmpty else {
            throw LLMError.notConfigured
        }
        let normalized = sentence.trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)

        if !force, let cached = ParseCache.get(model: ep.model, sentence: normalized) {
            return cached
        }

        let client = LLMClient(baseURL: ep.baseURL, model: ep.model, apiKey: ep.apiKey, wireAPI: ep.wireAPI)

        // Local engine: deterministic structure from the sidecar, LLM only
        // fills glosses + translation. Falls through to direct LLM parsing
        // when the sidecar is unavailable.
        if (provider ?? SettingsStore.shared.provider) == .ollama,
           let structure = await Sidecar.shared.structure(for: normalized) {
            let bare = ParseResult(chunks: structure, translation: "")
            onPartial?(bare) // tree on screen immediately, glosses pending
            do {
                let result = try await fillGlosses(structure: structure, sentence: normalized, client: client)
                ParseCache.set(model: ep.model, sentence: normalized, result: result)
                return result
            } catch {
                ThornLog.info("gloss fill failed: \(error.localizedDescription)")
                // Structure alone still beats nothing — but fill the translation
                // slot so the panel doesn't spin forever waiting for one.
                return ParseResult(chunks: structure,
                                   translation: "（中文释义暂缺：本地模型未响应，结构来自句法引擎）")
            }
        }

        if let onPartial, client.supportsStreaming {
            do {
                let raw = try await streamRaw(client: client, sentence: normalized, onPartial: onPartial)
                ThornLog.info("model \(ep.model) streamed output: \(raw.prefix(4000))")
                let result = try decode(raw)
                ParseCache.set(model: ep.model, sentence: normalized, result: result)
                return result
            } catch let error as LLMError {
                switch error {
                case .badJSON, .emptyResponse:
                    // Falling back to a non-streaming retry: clear the stale
                    // partial from the panel (empty result = reset signal).
                    onPartial(ParseResult(chunks: [], translation: ""))
                default:
                    throw error
                }
            }
        }

        var lastError: Error = LLMError.emptyResponse
        for _ in 0..<2 {
            do {
                let raw = try await client.chat(system: systemPrompt, user: normalized, jsonMode: true)
                ThornLog.info("model \(ep.model) raw output: \(raw.prefix(4000))")
                let result = try decode(raw)
                ParseCache.set(model: ep.model, sentence: normalized, result: result)
                return result
            } catch let error as LLMError {
                switch error {
                case .badJSON, .emptyResponse:
                    lastError = error // model hiccup: retry
                default:
                    throw error // network/HTTP errors won't fix themselves
                }
            }
        }
        throw lastError
    }

    // MARK: - Gloss filling (pipeline path)

    private static let glossPrompt = """
    You annotate English sense-groups for Chinese learners. Given a sentence and its numbered chunks, output STRICT JSON only:
    {"glosses": [{"n": 1, "g": "<中文释义>"}, ...], "translation": "<整句流畅中文翻译>"}
    - One entry per chunk, "n" copied from the input chunk's "n". Do not skip, merge, or add entries.
    - Gloss each chunk by its meaning IN THIS sentence. Idiom parts stay idiomatic: for "raised eyebrows", the object chunk "eyebrows" is glossed 表示惊讶/非议 (习语成分), never the literal 眉毛.
    - For role "relative", state what it refers to in THIS sentence: "指代前述" + the actual noun from the sentence. Never copy nouns that are not in the sentence.
    - translation: fluent Chinese of the whole input, not a gloss concatenation.
    """

    private static func fillGlosses(structure: [Chunk], sentence: String, client: LLMClient) async throws -> ParseResult {
        struct Node: Encodable {
            let n: Int
            let text: String
            let role: String
        }
        // Number every node in DFS order, but only send the ones the sidecar
        // didn't already gloss deterministically (e.g. relative referents).
        var nodes: [Node] = []
        var totalCount = 0
        func collect(_ chunks: [Chunk]) {
            for c in chunks {
                totalCount += 1
                if c.gloss.isEmpty {
                    nodes.append(Node(n: totalCount, text: c.text, role: c.role.rawValue))
                }
                collect(c.children ?? [])
            }
        }
        collect(structure)

        struct Payload: Encodable {
            let sentence: String
            let chunks: [Node]
        }
        let payload = String(data: try JSONEncoder().encode(Payload(sentence: sentence, chunks: nodes)),
                             encoding: .utf8) ?? sentence
        let raw = try await client.chat(system: glossPrompt, user: payload, jsonMode: true)

        // Tolerant decoding: entries keyed by "n" so one miscount doesn't
        // sink the whole batch; a plain string array is accepted as fallback.
        struct Entry: Decodable {
            let n: Int
            let g: String
        }
        struct GlossResponse: Decodable {
            let glosses: [Entry]?
            let translation: String?
        }
        struct LegacyResponse: Decodable {
            let glosses: [String]?
            let translation: String?
        }
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("```") {
            text = text
                .replacingOccurrences(of: "^```(json)?\\s*", with: "", options: .regularExpression)
                .replacingOccurrences(of: "```\\s*$", with: "", options: .regularExpression)
        }
        guard let data = text.data(using: .utf8) else { throw LLMError.badJSON(raw) }

        var byIndex: [Int: String] = [:]
        var translation = ""
        if let decoded = try? JSONDecoder().decode(GlossResponse.self, from: data), decoded.glosses != nil {
            for e in decoded.glosses ?? [] { byIndex[e.n] = e.g }
            translation = decoded.translation ?? ""
        } else if let legacy = try? JSONDecoder().decode(LegacyResponse.self, from: data) {
            for (i, g) in (legacy.glosses ?? []).enumerated() { byIndex[i + 1] = g }
            translation = legacy.translation ?? ""
        }
        // Require the translation and at least half the glosses to call it a success.
        guard !translation.isEmpty, byIndex.count * 2 >= nodes.count else {
            throw LLMError.badJSON(raw)
        }

        var index = 0
        func attach(_ chunks: [Chunk]) -> [Chunk] {
            chunks.map { c in
                index += 1
                let gloss = c.gloss.isEmpty ? (byIndex[index] ?? "") : c.gloss
                return Chunk(text: c.text, role: c.role, gloss: gloss,
                             children: c.children.map(attach))
            }
        }
        let glossed = attach(structure)
        return ParseResult(chunks: glossed, translation: translation)
    }

    // MARK: - Streaming

    private static func streamRaw(client: LLMClient, sentence: String,
                                  onPartial: @Sendable (ParseResult) -> Void) async throws -> String {
        var buffer = ""
        var sinceParse = 0
        for try await delta in try await client.chatStream(system: systemPrompt, user: sentence, jsonMode: true) {
            buffer += delta
            sinceParse += delta.count
            // Attempt a partial parse every ~60 chars; cheap enough, feels live.
            if sinceParse >= 60 {
                sinceParse = 0
                if let partial = partialResult(from: buffer), !partial.chunks.isEmpty {
                    onPartial(partial)
                }
            }
        }
        return buffer
    }

    /// Lenient mirror of the schema: everything optional, so a truncated tail
    /// doesn't sink the fields that already arrived.
    private struct LenientChunk: Decodable {
        let text: String?
        let role: String?
        let gloss: String?
        let children: [LenientChunk]?
    }
    private struct LenientResult: Decodable {
        let chunks: [LenientChunk]?
        let translation: String?
    }

    private static func partialResult(from buffer: String) -> ParseResult? {
        guard let data = completeJSON(buffer).data(using: .utf8),
              let lenient = try? JSONDecoder().decode(LenientResult.self, from: data),
              let rawChunks = lenient.chunks else { return nil }
        let chunks = rawChunks.compactMap(materialize)
        guard !chunks.isEmpty else { return nil }
        return ParseResult(chunks: repair(sanitize(chunks)), translation: lenient.translation ?? "")
    }

    private static func materialize(_ lenient: LenientChunk) -> Chunk? {
        guard let text = lenient.text, !text.isEmpty,
              let role = lenient.role, let gloss = lenient.gloss else { return nil }
        let kids = lenient.children?.compactMap(materialize)
        return Chunk(text: text, role: ChunkRole(rawValue: role) ?? .other, gloss: gloss,
                     children: (kids?.isEmpty == false) ? kids : nil)
    }

    /// Close whatever is dangling (open strings, braces, brackets) so a
    /// mid-generation buffer becomes decodable JSON.
    private static func completeJSON(_ s: String) -> String {
        var stack: [Character] = []
        var inString = false
        var escaped = false
        for ch in s {
            if inString {
                if escaped { escaped = false }
                else if ch == "\\" { escaped = true }
                else if ch == "\"" { inString = false }
            } else {
                switch ch {
                case "\"": inString = true
                case "{", "[": stack.append(ch)
                case "}", "]": if !stack.isEmpty { stack.removeLast() }
                default: break
                }
            }
        }
        var out = s
        if escaped { out.removeLast() }
        if inString { out += "\"" }
        while let last = out.last, last == "," || last.isWhitespace { out.removeLast() }
        if out.last == ":" { out += "null" }
        for opener in stack.reversed() {
            out.append(opener == "{" ? "}" : "]")
        }
        return out
    }

    private static func decode(_ raw: String) throws -> ParseResult {
        // Strip markdown fences some models add despite instructions.
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("```") {
            text = text
                .replacingOccurrences(of: "^```(json)?\\s*", with: "", options: .regularExpression)
                .replacingOccurrences(of: "```\\s*$", with: "", options: .regularExpression)
        }
        guard let data = text.data(using: .utf8),
              let result = try? JSONDecoder().decode(ParseResult.self, from: data),
              !result.chunks.isEmpty, !result.translation.isEmpty else {
            throw LLMError.badJSON(raw)
        }
        return sanitize(result)
    }

    /// Merge punctuation-only chunks into their neighbor so they never render as
    /// cards: into the previous chunk, or ahead into the next if they lead.
    /// Applied recursively to clause children.
    private static func sanitize(_ result: ParseResult) -> ParseResult {
        ParseResult(chunks: repair(sanitize(result.chunks)), translation: result.translation)
    }

    private static func normalized(_ s: String) -> String {
        s.filter { !$0.isWhitespace }
    }

    /// Enforce tree invariants the model can't be trusted with:
    /// 1. Children the parent's text doesn't contain get hoisted to siblings.
    /// 2. Chunks with no clause involved lose their children (noise like "a"+"decision").
    /// 3. If kept children still don't reassemble the parent text, drop them —
    ///    better no tree than a lying tree.
    private static func repair(_ chunks: [Chunk]) -> [Chunk] {
        var out: [Chunk] = []
        for chunk in chunks {
            // Children were already cleaned by sanitize's own recursion.
            var kids = repair(chunk.children ?? [])

            // Asymmetric keep-criterion:
            // - a clause chunk's decomposition is real only if it contains a
            //   predicate (kills "capable of" + complement-chain junk);
            // - a non-clause chunk keeps children only when one embeds a
            //   clause (kills aux-verb chains like can / get / out of whack).
            let hasVerb = kids.contains { $0.role == .verb }
            let hasClauseChild = kids.contains { $0.role.isClause }
            let keep = kids.count >= 2 && (chunk.role.isClause ? (hasVerb || hasClauseChild) : hasClauseChild)
            if !keep { kids = [] }

            guard !kids.isEmpty else {
                out.append(Chunk(text: chunk.text, role: chunk.role, gloss: chunk.gloss))
                continue
            }

            let parent = normalized(chunk.text)
            if normalized(kids.map(\.text).joined()) == parent {
                out.append(Chunk(text: chunk.text, role: chunk.role, gloss: chunk.gloss, children: kids))
                continue
            }

            let kept = kids.filter { parent.contains(normalized($0.text)) }
            let hoisted = kids.filter { !parent.contains(normalized($0.text)) }
            let keptValid = normalized(kept.map(\.text).joined()) == parent
            out.append(Chunk(text: chunk.text, role: chunk.role, gloss: chunk.gloss,
                             children: keptValid ? kept : nil))
            out.append(contentsOf: hoisted)
        }
        return out
    }

    private static func sanitize(_ chunks: [Chunk]) -> [Chunk] {
        var merged: [Chunk] = []
        var pendingPrefix = ""
        for chunk in chunks {
            let children = chunk.children.map(sanitize)
            let hasContent = chunk.text.rangeOfCharacter(from: .alphanumerics) != nil
            if !hasContent {
                if merged.isEmpty {
                    pendingPrefix += chunk.text
                } else {
                    let last = merged[merged.count - 1]
                    merged[merged.count - 1] = Chunk(
                        text: last.text + chunk.text,
                        role: last.role,
                        gloss: last.gloss,
                        children: last.children
                    )
                }
            } else {
                let text = pendingPrefix + chunk.text
                pendingPrefix = ""
                merged.append(Chunk(text: text, role: chunk.role, gloss: chunk.gloss, children: children))
            }
        }
        return merged
    }
}
