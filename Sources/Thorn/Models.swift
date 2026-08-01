import Foundation

enum ChunkRole: String, Decodable, CaseIterable, Sendable {
    case subject
    case verb
    case object
    case complement
    case clauseRelative = "clause-relative"
    case clauseAdverbial = "clause-adverbial"
    case clauseNoun = "clause-noun"
    case clause
    case prepPhrase = "prep-phrase"
    case insertion
    case appositive
    case absolute
    case conjunction
    case relative
    case adverbial
    case other

    var label: String {
        switch self {
        case .subject: return "主语"
        case .verb: return "谓语"
        case .object: return "宾语"
        case .complement: return "补语"
        case .clauseRelative: return "定语从句"
        case .clauseAdverbial: return "状语从句"
        case .clauseNoun: return "名词性从句"
        case .clause: return "分句"
        case .prepPhrase: return "介词短语"
        case .insertion: return "插入语"
        case .appositive: return "同位语"
        case .absolute: return "独立主格"
        case .conjunction: return "连词"
        case .relative: return "关系词"
        case .adverbial: return "状语"
        case .other: return "其他"
        }
    }
}

enum ChunkFunction: String, Decodable, Sendable {
    case subject
    case predicate
    case object
    case complement
    case adverbial
    case modifier
    case connector
    case logicalSubject = "logical-subject"
    case content

    var label: String {
        switch self {
        case .subject: return "主语"
        case .predicate: return "谓语"
        case .object: return "宾语"
        case .complement: return "补语"
        case .adverbial: return "状语"
        case .modifier: return "定语"
        case .connector: return "连接成分"
        case .logicalSubject: return "逻辑主语"
        case .content: return "引语内容"
        }
    }

    var displayRole: ChunkRole {
        switch self {
        case .subject, .logicalSubject: return .subject
        case .predicate: return .verb
        case .object: return .object
        case .complement: return .complement
        case .adverbial: return .adverbial
        case .modifier: return .clauseRelative
        case .connector: return .conjunction
        case .content: return .clauseNoun
        }
    }
}

enum ChunkForm: String, Decodable, Sendable {
    case prepositionalPhrase = "prepositional-phrase"
    case relativeClause = "relative-clause"
    case appositiveClause = "appositive-clause"
    case adverbialClause = "adverbial-clause"
    case nominalClause = "nominal-clause"
    case absoluteConstruction = "absolute-construction"
    case whInfinitive = "wh-infinitive"
    case whWord = "wh-word"
    case infinitivePredicate = "infinitive-predicate"
    case withComplex = "with-complex"
    case preposition
    case participialClause = "participial-clause"
    case presentParticiple = "present-participle"
    case pastParticiple = "past-participle"
    case reducedRelative = "reduced-relative"
    case directQuotation = "direct-quotation"

    var label: String {
        switch self {
        case .prepositionalPhrase: return "介词短语"
        case .relativeClause: return "关系从句"
        case .appositiveClause: return "同位语从句"
        case .adverbialClause: return "状语从句"
        case .nominalClause: return "名词性从句"
        case .absoluteConstruction: return "独立主格"
        case .whInfinitive: return "疑问词不定式"
        case .whWord: return "疑问词"
        case .infinitivePredicate: return "不定式"
        case .withComplex: return "with 复合结构"
        case .preposition: return "介词"
        case .participialClause: return "分词小句"
        case .presentParticiple: return "现在分词"
        case .pastParticiple: return "过去分词"
        case .reducedRelative: return "分词后置结构"
        case .directQuotation: return "直接引语"
        }
    }
}

struct Chunk: Decodable, Identifiable, Equatable, Sendable {
    let text: String
    let role: ChunkRole
    let gloss: String
    /// Recursive decomposition: clause chunks carry their internal components.
    let children: [Chunk]?
    /// Stable sidecar identity and exact spaCy source-token range. These are
    /// used by the v3 alignment protocol; UI identity remains instance-local.
    let nodeKey: String?
    let sourceStart: Int?
    let sourceEnd: Int?
    /// Orthogonal teaching metadata: function answers "what does it do?",
    /// while form answers "what construction is it?".
    let function: ChunkFunction?
    let form: ChunkForm?

    // Identity must be unique per instance: the same text+role can appear
    // twice in one sentence, and duplicate ForEach IDs break hover highlight.
    private let uid = UUID()
    var id: UUID { uid }

    enum CodingKeys: String, CodingKey {
        case text, role, gloss, children, function, form
        case nodeKey = "id"
        case sourceStart = "s"
        case sourceEnd = "e"
    }

    static func == (lhs: Chunk, rhs: Chunk) -> Bool {
        lhs.text == rhs.text && lhs.role == rhs.role && lhs.gloss == rhs.gloss
            && lhs.children == rhs.children && lhs.nodeKey == rhs.nodeKey
            && lhs.sourceStart == rhs.sourceStart && lhs.sourceEnd == rhs.sourceEnd
            && lhs.function == rhs.function && lhs.form == rhs.form
    }

    init(text: String, role: ChunkRole, gloss: String, children: [Chunk]? = nil,
         nodeKey: String? = nil, sourceStart: Int? = nil, sourceEnd: Int? = nil,
         function: ChunkFunction? = nil, form: ChunkForm? = nil) {
        self.text = text
        self.role = role
        self.gloss = gloss
        self.children = children
        self.nodeKey = nodeKey
        self.sourceStart = sourceStart
        self.sourceEnd = sourceEnd
        self.function = function
        self.form = form
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = try c.decode(String.self, forKey: .text)
        gloss = try c.decode(String.self, forKey: .gloss)
        let raw = try c.decode(String.self, forKey: .role)
        role = ChunkRole(rawValue: raw) ?? .other
        let kids = try c.decodeIfPresent([Chunk].self, forKey: .children)
        children = (kids?.isEmpty == false) ? kids : nil
        nodeKey = try c.decodeIfPresent(String.self, forKey: .nodeKey)
        sourceStart = try c.decodeIfPresent(Int.self, forKey: .sourceStart)
        sourceEnd = try c.decodeIfPresent(Int.self, forKey: .sourceEnd)
        function = try c.decodeIfPresent(String.self, forKey: .function)
            .flatMap { ChunkFunction(rawValue: $0) }
        form = try c.decodeIfPresent(String.self, forKey: .form)
            .flatMap { ChunkForm(rawValue: $0) }
    }

    var displayRole: ChunkRole {
        function?.displayRole ?? role
    }

    var primaryLabel: String {
        function?.label ?? form?.label ?? role.label
    }

    var secondaryLabel: String? {
        guard let formLabel = form?.label, formLabel != primaryLabel else {
            return nil
        }
        return formLabel
    }

    var preservesTeachingWrapper: Bool {
        form != nil
    }
}

struct ParseResult: Equatable, Sendable {
    /// The exact string the chunks were produced from — already normalized and
    /// English-extracted. The header renders this rather than gluing chunk text
    /// back together, which cannot restore spacing around detached tokens.
    let sentence: String
    let chunks: [Chunk]
    let translation: String
}

// MARK: - Phonics (single-word input path)

enum PhonicsStress: Equatable, Sendable {
    case none
    case primary
    case secondary

    var mark: String {
        switch self {
        case .none: return ""
        case .primary: return "ˈ"
        case .secondary: return "ˌ"
        }
    }
}

/// One phonics block: a grapheme (letter group) and the IPA it spells.
/// `ipa` is nil for heuristic splits, where the pronunciation is unknown.
struct PhonicsChunk: Equatable, Sendable {
    let grapheme: String
    let ipa: String?
}

struct PhonicsSyllable: Equatable, Sendable {
    let chunks: [PhonicsChunk]
    let stress: PhonicsStress
}

/// Phonics decomposition of a single word. `approximate` marks the
/// rule-based fallback used when the word is not in the bundled dictionary.
struct PhonicsResult: Equatable, Sendable {
    let word: String
    let ipa: String?
    let syllables: [PhonicsSyllable]
    let approximate: Bool
    let meaning: String

    func withMeaning(_ text: String) -> PhonicsResult {
        PhonicsResult(word: word, ipa: ipa, syllables: syllables,
                      approximate: approximate, meaning: text)
    }
}
