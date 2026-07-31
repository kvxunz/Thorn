import AppKit
import SwiftUI
import XCTest
@testable import Thorn

/// The palette's job is discriminability, and that is a numeric property —
/// the old sixteen-hue palette looked reasonable in source and put two blues
/// 0.02 apart on screen. These tests fail if that regresses.
final class DesignSystemTests: XCTestCase {

    private func hue(_ color: NSColor) -> CGFloat {
        let rgb = color.usingColorSpace(.sRGB) ?? color
        var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        rgb.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
        return h
    }

    /// Circular distance on the hue wheel, in turns (0…0.5).
    private func hueGap(_ a: ThornInk, _ b: ThornInk) -> CGFloat {
        let d = abs(hue(a.light) - hue(b.light))
        return min(d, 1 - d)
    }

    func testTrunkHuesAreDiscriminable() {
        let trunk: [(String, ThornInk)] = [
            ("subject", ThornPalette.subject),
            ("predicate", ThornPalette.predicate),
            ("object", ThornPalette.object),
        ]
        for i in trunk.indices {
            for j in trunk.indices where j > i {
                let gap = hueGap(trunk[i].1, trunk[j].1)
                XCTAssertGreaterThan(
                    gap, 0.12,
                    "\(trunk[i].0) vs \(trunk[j].0): hues only \(gap) apart"
                )
            }
        }
    }

    /// Subordinate material must not compete with the trunk: one hue, three
    /// saturations. If a tier ever grows its own hue, the "where is the
    /// backbone?" reading collapses.
    func testSubordinateTiersShareTheBrandHueAndSeparateBySaturation() {
        let tiers: [ThornPalette.Tier] = [.clause, .phrase, .function]
        var saturations: [CGFloat] = []
        for tier in tiers {
            let ink = ThornPalette.subordinate(tier)
            let rgb = ink.light.usingColorSpace(.sRGB)!
            var h: CGFloat = 0, s: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
            rgb.getHue(&h, saturation: &s, brightness: &b, alpha: &a)
            XCTAssertEqual(h, ThornPalette.brandHue, accuracy: 0.01, "\(tier)")
            saturations.append(s)
        }
        // Strictly decreasing, with a gap wide enough to see.
        for i in 1..<saturations.count {
            XCTAssertGreaterThan(saturations[i - 1] - saturations[i], 0.05,
                                 "tier \(i) is not visibly fainter than \(i - 1)")
        }
    }

    /// Every role resolves to an ink, and the trunk roles never collide with
    /// subordinate ones — the switch in `ChunkRole.ink` is exhaustive but a
    /// wrong arm would silently paint a subject like a preposition.
    func testTrunkRolesDoNotShareInkWithSubordinateRoles() {
        let trunkInks = [ChunkRole.subject, .verb, .object].map(\.ink)
        let subordinate: [ChunkRole] = [
            .clauseRelative, .clauseAdverbial, .clauseNoun, .clause,
            .prepPhrase, .adverbial, .appositive, .absolute, .insertion,
            .conjunction, .relative, .other,
        ]
        for role in subordinate {
            XCTAssertFalse(trunkInks.contains(role.ink), "\(role) reuses a trunk ink")
        }
    }

    /// The syllable ring is decorative, but adjacent syllables must contrast
    /// or the word stops splitting visually.
    func testAdjacentSyllableInksDiffer() {
        for index in 0..<8 {
            XCTAssertGreaterThan(
                hueGap(ThornPalette.syllable(index), ThornPalette.syllable(index + 1)),
                0.10,
                "syllables \(index)/\(index + 1) do not contrast"
            )
        }
    }

    func testTypeScaleIsMonotonic() {
        let scale = [ThornType.micro, ThornType.small, ThornType.body,
                     ThornType.reading, ThornType.display]
        XCTAssertEqual(scale, scale.sorted(), "type scale steps are out of order")
        XCTAssertEqual(Set(scale).count, scale.count, "type scale has duplicate steps")
    }
}
