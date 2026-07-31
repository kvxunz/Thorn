import AppKit
import SwiftUI

// MARK: - Type

/// Five-step type scale (≈1.22 ratio). Every font size in the panel comes
/// from here: before this existed the views carried fourteen ad-hoc sizes
/// between 8 and 20pt, so nothing could be adjusted without hunting.
///
/// English under study is set in a serif face (New York) and Chinese chrome
/// in the system face — the two scripts stay visually separable even when
/// they share a line.
enum ThornType {
    /// IPA under a grapheme, the form sub-label.
    static let micro: CGFloat = 9.5
    /// Role pill, hints, nested gloss.
    static let small: CGFloat = 11
    /// Card text, secondary chrome.
    static let body: CGFloat = 12.5
    /// The header sentence and the translation — the two things being read.
    static let reading: CGFloat = 15
    /// Phonics graphemes and the word meaning.
    static let display: CGFloat = 19

    static func english(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .serif)
    }

    static func ui(_ size: CGFloat, _ weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight)
    }
}

// MARK: - Space

/// 4pt rhythm. Named by role rather than by number so a row's inner padding
/// and a section's outer padding cannot silently drift to the same value.
enum ThornSpace {
    static let hair: CGFloat = 2
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 12
    static let lg: CGFloat = 16
    /// Right inset that keeps text clear of the pin button in the corner.
    static let pinInset: CGFloat = 36
}

enum ThornRadius {
    static let panel: CGFloat = 14
    static let row: CGFloat = 7
    static let bar: CGFloat = 1.5
}

// MARK: - Motion

/// Ease-out-expo (the 0.16/1/0.3/1 curve): fast departure, long settle — it
/// reads as physical without the cartoon overshoot of a spring.
///
/// Only opacity and transform are animated. Panel geometry is deliberately
/// excluded: the window is resized to its final size up front (see
/// `ResultPanelController.fitToContent`), because an animated window height
/// racing an animated content height is exactly the clipping bug in
/// LEARNINGS #15.
enum ThornMotion {
    static let revealDuration: Double = 0.26
    static let reveal = Animation.timingCurve(0.16, 1, 0.3, 1, duration: revealDuration)
    static let hover = Animation.timingCurve(0.16, 1, 0.3, 1, duration: 0.14)
}

// MARK: - Color

/// One ink in both appearances. Held as `NSColor` rather than `Color` so the
/// palette's separation can be asserted numerically in tests; `color` is the
/// dynamic value the views actually use.
struct ThornInk: Equatable {
    let light: NSColor
    let dark: NSColor

    init(hue: CGFloat,
         lightSat: CGFloat, lightBri: CGFloat,
         darkSat: CGFloat, darkBri: CGFloat) {
        light = ThornInk.srgb(hue, lightSat, lightBri)
        dark = ThornInk.srgb(hue, darkSat, darkBri)
    }

    /// HSB -> sRGB by hand. `NSColor(hue:saturation:brightness:)` builds in the
    /// *calibrated* space, so the hue you asked for is not the hue that comes
    /// back out on a modern display — which quietly breaks both the palette's
    /// spacing and any test that measures it.
    private static func srgb(_ hue: CGFloat, _ sat: CGFloat, _ bri: CGFloat) -> NSColor {
        let h = hue.truncatingRemainder(dividingBy: 1).magnitude * 6
        let c = bri * sat
        let x = c * (1 - abs(h.truncatingRemainder(dividingBy: 2) - 1))
        let m = bri - c
        let rgb: (CGFloat, CGFloat, CGFloat)
        switch Int(h) {
        case 0: rgb = (c, x, 0)
        case 1: rgb = (x, c, 0)
        case 2: rgb = (0, c, x)
        case 3: rgb = (0, x, c)
        case 4: rgb = (x, 0, c)
        default: rgb = (c, 0, x)
        }
        return NSColor(srgbRed: rgb.0 + m, green: rgb.1 + m, blue: rgb.2 + m, alpha: 1)
    }

    var color: Color {
        Color(nsColor: NSColor(name: nil) { appearance in
            appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
        })
    }

    func opacity(_ value: Double) -> Color { color.opacity(value) }
}

/// The palette is deliberately **narrow**: three accent hues for the trunk
/// (subject / predicate / object) and a single brand hue for everything
/// subordinate, separated by three tiers of saturation instead of by hue.
///
/// The previous palette gave all sixteen roles their own hue, which put five
/// purples (0.70–0.88) and four blues (0.55–0.66) on screen at once — two of
/// them 0.02 apart, i.e. not discriminable at all. Colour now answers only
/// the question a learner asks first ("where is the backbone?"); the precise
/// role is named in words on the pill, where it can actually be read.
enum ThornPalette {
    /// Muted violet. Neutral chrome is tinted with it so the panel reads as
    /// one object rather than a tray of unrelated colours.
    static let brandHue: CGFloat = 0.72

    static let subject = ThornInk(hue: 0.58, lightSat: 0.78, lightBri: 0.46,
                                  darkSat: 0.56, darkBri: 0.86)
    static let predicate = ThornInk(hue: 0.02, lightSat: 0.80, lightBri: 0.53,
                                    darkSat: 0.62, darkBri: 0.88)
    static let object = ThornInk(hue: 0.36, lightSat: 0.72, lightBri: 0.40,
                                 darkSat: 0.54, darkBri: 0.78)
    /// A predicative is the object slot of a linking verb: same hue, softened,
    /// so it reads as family rather than as a fourth thing to memorise.
    static let complement = ThornInk(hue: 0.36, lightSat: 0.40, lightBri: 0.44,
                                     darkSat: 0.30, darkBri: 0.76)

    /// Subordinate material, strongest to faintest.
    enum Tier {
        /// Real clauses — the layer progressive disclosure is about.
        case clause
        /// Phrases: prepositional, adverbial, appositive, absolute.
        case phrase
        /// Function words and unclassified remainder.
        case function
    }

    static func subordinate(_ tier: Tier) -> ThornInk {
        switch tier {
        case .clause:
            return ThornInk(hue: brandHue, lightSat: 0.34, lightBri: 0.52,
                            darkSat: 0.28, darkBri: 0.86)
        case .phrase:
            return ThornInk(hue: brandHue, lightSat: 0.21, lightBri: 0.47,
                            darkSat: 0.17, darkBri: 0.78)
        case .function:
            return ThornInk(hue: brandHue, lightSat: 0.11, lightBri: 0.44,
                            darkSat: 0.09, darkBri: 0.70)
        }
    }

    /// Word-card syllables carry no meaning — they only need to differ from
    /// their neighbour. Cycling the same four inks the sentence panel uses
    /// keeps both screens in one colour family; four covers nearly every
    /// English word, and no role labels are on screen to be confused with.
    static func syllable(_ index: Int) -> ThornInk {
        let ring = [subject, predicate, object, subordinate(.clause)]
        return ring[index % ring.count]
    }
}
