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

    Rules:
    - "role" must be one of: subject, verb, object, complement, clause-relative, clause-adverbial, clause-noun, prep-phrase, insertion, conjunction, relative, adverbial, other
    - Split the MAIN clause backbone into separate chunks: subject / verb / object / complement each gets its own chunk. The verb chunk includes auxiliaries ("have to get used to" is ONE verb chunk).
    - Linking verbs (be/become/seem/look/remain...) take a PREDICATIVE, not an object: "are" is the verb chunk, "volatile quantities" is a separate chunk with role "complement" — never merge them and never call the predicative an object.
    - Each modifier (prepositional phrase, subordinate clause, insertion) is its own chunk.
    - Use clause-* roles ONLY for real SUBORDINATE clauses containing their own subject and verb. "In other places" has no verb: it is prep-phrase, not a clause.
    - COORDINATE clauses (joined by and/but/or/so, often after a dash or semicolon) are MAIN clauses, never clause-*. Decompose EACH coordinate clause into its own subject/verb/object/complement chunks.
    - A coordinating conjunction joining two clauses ("or", "but", "—or at least", "and yet") is its own chunk with role "conjunction". Never glue it to the preceding object or the following subject.
    - NEVER reorder words: chunks in array order must read exactly like the original. ONLY in questions where the auxiliary comes BEFORE the subject ("Why must we master...") keep the inverted group "must we master" as ONE verb chunk; the question word (Why/How/What...) is its own chunk with role "adverbial".
    - In every DECLARATIVE clause the subject is ALWAYS its own separate chunk, and the object is separate from the verb. "they would have hedged their bets" is THREE chunks (they / would have hedged / their bets), never one.
    - An infinitive complement ("to purchase assets") belongs with its verb chain or gets role "complement" — never "other".
    - COVERAGE INVARIANT: top-level chunk texts concatenated in order must equal the WHOLE input. And whenever a chunk has children, that chunk's own text must equal its children's texts concatenated. So a subject with an attached relative clause has text "The committee, which had been deliberating for weeks," and children ["The committee," + the which-clause] — the parent text is never shorter than its children.
    - NEVER make a chunk that is only punctuation. Attach punctuation (: , ; ?) to the end of the preceding chunk; a dash introducing a new clause stays with the conjunction chunk ("—or at least").
    - RECURSIVE EXPANSION: every clause-* chunk MUST carry a "children" array that decomposes the clause into its OWN components. Inside the clause, split out prep-phrases and adverbials too ("had been deliberating" verb + "for weeks" prep-phrase). If a child is itself a clause, give it children the same way, recursively. Children texts concatenated must equal the parent chunk text.
    - Inside a clause, the introducing word gets its true role: a relative pronoun (which/who/that referring back to a noun) is role "relative" — it often IS the clause's subject or object, so gloss it as what it refers to (e.g. which -> "指代前述委员会"). A pure subordinating conjunction (when/because/if/although, or "that" introducing a noun clause) is role "conjunction".
    - A non-clause chunk gets "children" ONLY when it embeds a clause inside it (e.g. object "everyone who attended" -> children: "everyone" + the who-clause). Plain phrases never have children.
    - Participial phrases ("Standing at the door," / "encouraged by the news,") are role "adverbial"; appositives ("John, a local farmer,") are role "insertion".
    - "gloss" is a concise Chinese rendering of that chunk in context.
    - "translation" is fluent natural Chinese covering ALL input sentences, not a concatenation of glosses.

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
                    break // fall through to the non-streaming retry below
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
            var kids = repair(sanitize(chunk.children ?? []))

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
