import SwiftUI
import AppKit

/// Appearance-adaptive color: deep readable tones on light, bright on dark.
private func adaptive(light: NSColor, dark: NSColor) -> Color {
    Color(nsColor: NSColor(name: nil) { appearance in
        appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua ? dark : light
    })
}

/// Build a role hue that stays legible on both materials.
/// Light: deeper / mid-sat so it sits on pale glass.
/// Dark: higher brightness, moderate sat so it does not dissolve into gray.
private func roleColor(hue: CGFloat, lightSat: CGFloat, lightBri: CGFloat,
                       darkSat: CGFloat, darkBri: CGFloat) -> Color {
    adaptive(
        light: NSColor(hue: hue, saturation: lightSat, brightness: lightBri, alpha: 1),
        dark: NSColor(hue: hue, saturation: darkSat, brightness: darkBri, alpha: 1)
    )
}

/// Learner palette: **distinct hues**, not near-gray pastels.
/// Trunk (S/V/O) strongest; clauses purple family; prep warm; insertion cool-gray blue.
extension ChunkRole {
    var color: Color {
        switch self {
        // 蓝 — 主语
        case .subject:
            return roleColor(hue: 0.58, lightSat: 0.72, lightBri: 0.48,
                             darkSat: 0.55, darkBri: 0.82)
        // 红橙 — 谓语
        case .verb:
            return roleColor(hue: 0.02, lightSat: 0.78, lightBri: 0.55,
                             darkSat: 0.62, darkBri: 0.88)
        // 绿 — 宾语
        case .object:
            return roleColor(hue: 0.36, lightSat: 0.70, lightBri: 0.42,
                             darkSat: 0.55, darkBri: 0.78)
        // 青绿 — 补语（与宾语拉开）
        case .complement:
            return roleColor(hue: 0.48, lightSat: 0.65, lightBri: 0.42,
                             darkSat: 0.50, darkBri: 0.80)
        // 紫 — 定语从句
        case .clauseRelative:
            return roleColor(hue: 0.76, lightSat: 0.55, lightBri: 0.52,
                             darkSat: 0.48, darkBri: 0.86)
        // 靛紫 — 状语从句
        case .clauseAdverbial:
            return roleColor(hue: 0.70, lightSat: 0.52, lightBri: 0.50,
                             darkSat: 0.45, darkBri: 0.85)
        // 品红紫 — 名词性从句
        case .clauseNoun:
            return roleColor(hue: 0.88, lightSat: 0.50, lightBri: 0.52,
                             darkSat: 0.45, darkBri: 0.86)
        // 雾紫灰 — 分号并列分句容器（低饱和，不与内部成分抢色）
        case .clause:
            return roleColor(hue: 0.72, lightSat: 0.26, lightBri: 0.48,
                             darkSat: 0.20, darkBri: 0.80)
        // 琥珀 — 介词短语（与主语蓝明显分开）
        case .prepPhrase:
            return roleColor(hue: 0.10, lightSat: 0.75, lightBri: 0.52,
                             darkSat: 0.60, darkBri: 0.82)
        // 石板蓝灰 — 插入语（比纯灰有色相）
        case .insertion:
            return roleColor(hue: 0.62, lightSat: 0.28, lightBri: 0.45,
                             darkSat: 0.22, darkBri: 0.78)
        // 靛蓝 — 同位语（插入语的高饱和近亲，仍是名词性复指）
        case .appositive:
            return roleColor(hue: 0.66, lightSat: 0.52, lightBri: 0.50,
                             darkSat: 0.44, darkBri: 0.84)
        // 橄榄绿 — 独立主格（无动词伴随分句）
        case .absolute:
            return roleColor(hue: 0.24, lightSat: 0.55, lightBri: 0.44,
                             darkSat: 0.45, darkBri: 0.78)
        // 金棕 — 连词
        case .conjunction:
            return roleColor(hue: 0.12, lightSat: 0.70, lightBri: 0.48,
                             darkSat: 0.55, darkBri: 0.80)
        // 淡紫 — 关系词
        case .relative:
            return roleColor(hue: 0.78, lightSat: 0.48, lightBri: 0.50,
                             darkSat: 0.42, darkBri: 0.84)
        // 天蓝 — 状语（非从句）
        case .adverbial:
            return roleColor(hue: 0.55, lightSat: 0.55, lightBri: 0.48,
                             darkSat: 0.45, darkBri: 0.82)
        // 中性灰褐 — 其他
        case .other:
            return roleColor(hue: 0.08, lightSat: 0.12, lightBri: 0.42,
                             darkSat: 0.10, darkBri: 0.72)
        }
    }

    /// Header backbone: S/V/O extra punch so the main spine jumps out first.
    var emphaticColor: Color {
        switch self {
        case .subject:
            return adaptive(
                light: NSColor(hue: 0.58, saturation: 0.82, brightness: 0.42, alpha: 1),
                dark: NSColor(hue: 0.58, saturation: 0.58, brightness: 0.90, alpha: 1)
            )
        case .verb:
            return adaptive(
                light: NSColor(hue: 0.04, saturation: 0.88, brightness: 0.52, alpha: 1),
                dark: NSColor(hue: 0.06, saturation: 0.72, brightness: 0.93, alpha: 1)
            )
        case .object:
            return adaptive(
                light: NSColor(hue: 0.36, saturation: 0.78, brightness: 0.38, alpha: 1),
                dark: NSColor(hue: 0.36, saturation: 0.55, brightness: 0.85, alpha: 1)
            )
        case .complement:
            // Header used to paint complements as muddy primary gray — use role hue.
            return color
        default:
            return color
        }
    }

    /// Pill / bar fill: a touch stronger than plain color.opacity(0.12).
    var badgeFill: Color { color.opacity(0.18) }
}
