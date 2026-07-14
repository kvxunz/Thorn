import Foundation

enum ParseService {
    private static let systemPrompt = """
    You are an English sentence-structure analyzer for Chinese learners doing intensive reading.

    Given one English sentence, split it into sense groups (意群) in original order and translate.

    Output STRICT JSON only, no markdown, no commentary:
    {
      "chunks": [
        {"text": "<exact substring from the sentence>", "role": "<role>", "gloss": "<自然的中文释义>"}
      ],
      "translation": "<整句流畅中文翻译>"
    }

    Rules:
    - "role" must be one of: subject, verb, object, complement, clause-relative, clause-adverbial, clause-noun, prep-phrase, insertion, conjunction, adverbial, other
    - Split the MAIN clause backbone into separate chunks: subject / verb / object / complement each gets its own chunk. The verb chunk includes auxiliaries ("have to get used to" is ONE verb chunk).
    - Each modifier (prepositional phrase, subordinate clause, insertion) is its own chunk.
    - Use clause-* roles ONLY for real SUBORDINATE clauses containing their own subject and verb. "In other places" has no verb: it is prep-phrase, not a clause.
    - COORDINATE clauses (joined by and/but/or/so, often after a dash or semicolon) are MAIN clauses, never clause-*. Decompose EACH coordinate clause into its own subject/verb/object/complement chunks.
    - A coordinating conjunction joining two clauses ("or", "but", "—or at least", "and yet") is its own chunk with role "conjunction". Never glue it to the preceding object or the following subject.
    - An infinitive complement ("to purchase assets") belongs with its verb chain or gets role "complement" — never "other".
    - Chunks concatenated in order must cover the whole sentence.
    - NEVER make a chunk that is only punctuation. Attach punctuation (: , ; ?) to the end of the preceding chunk; a dash introducing a new clause stays with the conjunction chunk ("—or at least").
    - "gloss" is a concise Chinese rendering of that chunk in context.
    - "translation" is one fluent Chinese sentence, not a concatenation of glosses.

    Example, for "In other places, people have to get used to the rain and cold when autumn comes.":
    {"chunks":[
      {"text":"In other places,","role":"prep-phrase","gloss":"在其他地方"},
      {"text":"people","role":"subject","gloss":"人们"},
      {"text":"have to get used to","role":"verb","gloss":"不得不习惯"},
      {"text":"the rain and cold","role":"object","gloss":"雨水和寒冷"},
      {"text":"when autumn comes.","role":"clause-adverbial","gloss":"当秋天到来时"}
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
    static func parse(sentence: String, provider: Provider? = nil, force: Bool = false) async throws -> ParseResult {
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

        var lastError: Error = LLMError.emptyResponse
        for _ in 0..<2 {
            do {
                let raw = try await client.chat(system: systemPrompt, user: normalized, jsonMode: true)
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
    private static func sanitize(_ result: ParseResult) -> ParseResult {
        var merged: [Chunk] = []
        var pendingPrefix = ""
        for chunk in result.chunks {
            let hasContent = chunk.text.rangeOfCharacter(from: .alphanumerics) != nil
            if !hasContent {
                if merged.isEmpty {
                    pendingPrefix += chunk.text
                } else {
                    let last = merged[merged.count - 1]
                    merged[merged.count - 1] = Chunk(
                        text: last.text + chunk.text,
                        role: last.role,
                        gloss: last.gloss
                    )
                }
            } else {
                let text = pendingPrefix + chunk.text
                pendingPrefix = ""
                merged.append(Chunk(text: text, role: chunk.role, gloss: chunk.gloss))
            }
        }
        return ParseResult(chunks: merged, translation: result.translation)
    }
}
