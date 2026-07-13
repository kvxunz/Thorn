import Foundation

enum ChunkRole: String, Codable, CaseIterable {
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
    case adverbial
    case other

    /// Trunk roles form the sentence backbone; everything else is a modifier.
    var isTrunk: Bool {
        switch self {
        case .subject, .verb, .object, .complement: return true
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
        case .adverbial: return "状语"
        case .other: return "其他"
        }
    }
}

struct Chunk: Codable, Identifiable, Equatable {
    let text: String
    let role: ChunkRole
    let gloss: String

    var id: String { text + role.rawValue }

    enum CodingKeys: String, CodingKey {
        case text, role, gloss
    }

    init(text: String, role: ChunkRole, gloss: String) {
        self.text = text
        self.role = role
        self.gloss = gloss
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = try c.decode(String.self, forKey: .text)
        gloss = try c.decode(String.self, forKey: .gloss)
        let raw = try c.decode(String.self, forKey: .role)
        role = ChunkRole(rawValue: raw) ?? .other
    }
}

struct ParseResult: Codable, Equatable {
    let chunks: [Chunk]
    let translation: String
}
