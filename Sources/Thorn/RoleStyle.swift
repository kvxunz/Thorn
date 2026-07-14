import SwiftUI

/// Muted, learner-friendly palette. Trunk roles saturated; modifiers softer.
extension ChunkRole {
    var color: Color {
        switch self {
        case .subject: return Color(hue: 0.58, saturation: 0.55, brightness: 0.72)
        case .verb: return Color(hue: 0.02, saturation: 0.58, brightness: 0.78)
        case .object: return Color(hue: 0.38, saturation: 0.50, brightness: 0.62)
        case .complement: return Color(hue: 0.47, saturation: 0.52, brightness: 0.62)
        case .clauseRelative: return Color(hue: 0.75, saturation: 0.35, brightness: 0.70)
        case .clauseAdverbial: return Color(hue: 0.68, saturation: 0.35, brightness: 0.70)
        case .clauseNoun: return Color(hue: 0.82, saturation: 0.32, brightness: 0.70)
        case .prepPhrase: return Color(hue: 0.09, saturation: 0.42, brightness: 0.68)
        case .insertion: return Color(hue: 0.60, saturation: 0.10, brightness: 0.58)
        case .conjunction: return Color(hue: 0.13, saturation: 0.45, brightness: 0.62)
        case .relative: return Color(hue: 0.78, saturation: 0.30, brightness: 0.66)
        case .adverbial: return Color(hue: 0.53, saturation: 0.38, brightness: 0.62)
        case .other: return Color(hue: 0.60, saturation: 0.06, brightness: 0.55)
        }
    }

    /// Deeper, saturated variants for the sentence header backbone (S/V/O).
    var emphaticColor: Color {
        switch self {
        case .subject: return Color(hue: 0.58, saturation: 0.75, brightness: 0.52)
        case .verb: return Color(hue: 0.10, saturation: 0.90, brightness: 0.60) // deep amber-yellow

        case .object: return Color(hue: 0.38, saturation: 0.70, brightness: 0.45)
        default: return color
        }
    }
}
