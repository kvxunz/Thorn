import Foundation

enum ChunkRole: String, Codable, CaseIterable, Sendable {
    case subject
    case verb
    case object
    case complement
    case clauseRelative = "clause-relative"
    case clauseAdverbial = "clause-adverbial"
    case clauseNoun = "clause-noun"
    case prepPhrase = "prep-phrase"
    case insertion
    case conjunction
    case relative
    case adverbial
    case other

    /// Trunk roles form the sentence backbone; everything else is a modifier.
    var isTrunk: Bool {
        switch self {
        case .subject, .verb, .object, .complement: return true
        default: return false
        }
    }

    var isClause: Bool {
        switch self {
        case .clauseRelative, .clauseAdverbial, .clauseNoun: return true
        default: return false
        }
    }

    var label: String {
        switch self {
        case .subject: return "主语"
        case .verb: return "谓语"
        case .object: return "宾语"
        case .complement: return "补语"
        case .clauseRelative: return "定语从句"
        case .clauseAdverbial: return "状语从句"
        case .clauseNoun: return "名词性从句"
        case .prepPhrase: return "介词短语"
        case .insertion: return "插入语"
        case .conjunction: return "连词"
        case .relative: return "关系词"
        case .adverbial: return "状语"
        case .other: return "其他"
        }
    }
}

struct Chunk: Codable, Identifiable, Equatable, Sendable {
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

    // Identity must be unique per instance: the same text+role can appear
    // twice in one sentence, and duplicate ForEach IDs break hover highlight.
    private let uid = UUID()
    var id: UUID { uid }

    enum CodingKeys: String, CodingKey {
        case text, role, gloss, children
        case nodeKey = "id"
        case sourceStart = "s"
        case sourceEnd = "e"
    }

    static func == (lhs: Chunk, rhs: Chunk) -> Bool {
        lhs.text == rhs.text && lhs.role == rhs.role && lhs.gloss == rhs.gloss
            && lhs.children == rhs.children && lhs.nodeKey == rhs.nodeKey
            && lhs.sourceStart == rhs.sourceStart && lhs.sourceEnd == rhs.sourceEnd
    }

    init(text: String, role: ChunkRole, gloss: String, children: [Chunk]? = nil,
         nodeKey: String? = nil, sourceStart: Int? = nil, sourceEnd: Int? = nil) {
        self.text = text
        self.role = role
        self.gloss = gloss
        self.children = children
        self.nodeKey = nodeKey
        self.sourceStart = sourceStart
        self.sourceEnd = sourceEnd
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
    }

    /// Explicit encode so sidecar metadata (`id`/`s`/`e`) survives re-encoding
    /// (custom decode alone can leave synthesis incomplete for the private `uid`).
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(text, forKey: .text)
        try c.encode(role.rawValue, forKey: .role)
        try c.encode(gloss, forKey: .gloss)
        try c.encodeIfPresent(children, forKey: .children)
        try c.encodeIfPresent(nodeKey, forKey: .nodeKey)
        try c.encodeIfPresent(sourceStart, forKey: .sourceStart)
        try c.encodeIfPresent(sourceEnd, forKey: .sourceEnd)
    }
}

struct ParseResult: Codable, Equatable, Sendable {
    let chunks: [Chunk]
    let translation: String
}
