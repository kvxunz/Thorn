import AppKit
import SwiftUI

/// Role -> ink. The mapping is the only place that decides what counts as
/// backbone and what counts as subordinate material; the actual colour
/// values live in `ThornPalette`.
extension ChunkRole {
    var ink: ThornInk {
        switch self {
        // 主干：三个强调色相，一眼能分开
        // A contraction card is still the head of its clause, so it keeps
        // the subject's ink: the eye needs the spine to start somewhere.
        case .subject, .subjectVerb: return ThornPalette.subject
        case .verb: return ThornPalette.predicate
        case .object: return ThornPalette.object
        case .complement: return ThornPalette.complement

        // 从句层：渐进披露的主角，从属族里最强的一档
        case .clauseRelative, .clauseAdverbial, .clauseNoun, .clause:
            return ThornPalette.subordinate(.clause)

        // 短语层
        case .prepPhrase, .adverbial, .appositive, .absolute, .insertion:
            return ThornPalette.subordinate(.phrase)

        // 虚词与未分类
        case .conjunction, .relative, .other:
            return ThornPalette.subordinate(.function)
        }
    }

    var color: Color { ink.color }

    /// Header backbone: the spine gets a touch more punch than its card bar,
    /// so the sentence resolves into S-V-O before the eye reaches the tree.
    var emphaticColor: Color {
        switch self {
        case .subject, .subjectVerb:
            return ThornInk(hue: 0.58, lightSat: 0.86, lightBri: 0.41,
                            darkSat: 0.60, darkBri: 0.91).color
        case .verb:
            return ThornInk(hue: 0.03, lightSat: 0.90, lightBri: 0.50,
                            darkSat: 0.70, darkBri: 0.93).color
        case .object:
            return ThornInk(hue: 0.36, lightSat: 0.80, lightBri: 0.37,
                            darkSat: 0.58, darkBri: 0.84).color
        default:
            return color
        }
    }

    /// Pill fill and its hairline. The stroke is what keeps a low-saturation
    /// subordinate pill from dissolving into the material behind it.
    var badgeFill: Color { ink.opacity(0.16) }
    var badgeStroke: Color { ink.opacity(0.22) }
}
