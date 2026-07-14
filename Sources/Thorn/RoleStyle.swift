import SwiftUI
import AppKit

/// Appearance-adaptive color: deep tones for light mode, bright for dark.
private func adaptive(light: NSColor, dark: NSColor) -> Color {
    Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
    })
}

/// Role color tuned per appearance: muted deep tones on light backgrounds,
/// lifted brightness / eased saturation on dark ones.
private func roleColor(_ hue: CGFloat, _ sat: CGFloat, _ bri: CGFloat) -> Color {
    adaptive(light: NSColor(hue: hue, saturation: sat, brightness: bri, alpha: 1),
             dark: NSColor(hue: hue, saturation: max(0.22, sat * 0.75),
                           brightness: min(0.95, bri + 0.24), alpha: 1))
}

/// Muted, learner-friendly palette. Trunk roles saturated; modifiers softer.
extension ChunkRole {
    var color: Color {
        switch self {
        case .subject: return roleColor(0.58, 0.55, 0.72)
        case .verb: return roleColor(0.02, 0.58, 0.78)
        case .object: return roleColor(0.38, 0.50, 0.62)
        case .complement: return roleColor(0.47, 0.52, 0.62)
        case .clauseRelative: return roleColor(0.75, 0.35, 0.70)
        case .clauseAdverbial: return roleColor(0.68, 0.35, 0.70)
        case .clauseNoun: return roleColor(0.82, 0.32, 0.70)
        case .prepPhrase: return roleColor(0.09, 0.42, 0.68)
        case .insertion: return roleColor(0.60, 0.10, 0.58)
        case .conjunction: return roleColor(0.13, 0.45, 0.62)
        case .relative: return roleColor(0.78, 0.30, 0.66)
        case .adverbial: return roleColor(0.53, 0.38, 0.62)
        case .other: return roleColor(0.60, 0.06, 0.55)
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
