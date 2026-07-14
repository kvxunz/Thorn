import SwiftUI
import AppKit

/// Appearance-adaptive color: deep tones for light mode, bright for dark.
private func adaptive(light: NSColor, dark: NSColor) -> Color {
    Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
    })
}

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

    /// Saturated variants for the sentence header backbone (S/V/O):
    /// deep in light mode, brightened in dark mode for contrast.
    var emphaticColor: Color {
        switch self {
        case .subject:
            return adaptive(light: NSColor(hue: 0.58, saturation: 0.75, brightness: 0.52, alpha: 1),
                            dark: NSColor(hue: 0.58, saturation: 0.50, brightness: 0.88, alpha: 1))
        case .verb: // amber-yellow
            return adaptive(light: NSColor(hue: 0.10, saturation: 0.90, brightness: 0.60, alpha: 1),
                            dark: NSColor(hue: 0.11, saturation: 0.75, brightness: 0.92, alpha: 1))
        case .object:
            return adaptive(light: NSColor(hue: 0.38, saturation: 0.70, brightness: 0.45, alpha: 1),
                            dark: NSColor(hue: 0.38, saturation: 0.50, brightness: 0.82, alpha: 1))
        default:
            return color
        }
    }
}
