// Generates AppIcon.icns: warm paper squircle with three lines of
// chunked sense-group bars in the app's role colors.
// Run: swift scripts/makeicon.swift && iconutil -c icns build/AppIcon.iconset -o Resources/AppIcon.icns
import AppKit

let canvas: CGFloat = 1024

func draw(into size: Int, to url: URL) {
    let s = CGFloat(size) / canvas
    guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0
    ) else { fatalError("rep") }
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

    // Squircle background: warm paper with a faint top-light gradient
    let inset: CGFloat = 96 * s
    let rect = NSRect(x: inset, y: inset, width: CGFloat(size) - inset * 2, height: CGFloat(size) - inset * 2)
    let radius = 186 * s
    let squircle = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
    NSGradient(
        starting: NSColor(calibratedRed: 0.988, green: 0.973, blue: 0.937, alpha: 1),
        ending: NSColor(calibratedRed: 0.949, green: 0.925, blue: 0.871, alpha: 1)
    )?.draw(in: squircle, angle: -90)

    // Hairline edge so it reads on white backgrounds
    NSColor(calibratedWhite: 0.35, alpha: 0.12).setStroke()
    squircle.lineWidth = max(2 * s, 0.5)
    squircle.stroke()

    // Role colors (match RoleStyle.swift hues)
    let subject = NSColor(calibratedHue: 0.58, saturation: 0.55, brightness: 0.72, alpha: 1)
    let verb = NSColor(calibratedHue: 0.02, saturation: 0.58, brightness: 0.78, alpha: 1)
    let object = NSColor(calibratedHue: 0.38, saturation: 0.50, brightness: 0.62, alpha: 1)
    let clause = NSColor(calibratedHue: 0.75, saturation: 0.35, brightness: 0.70, alpha: 1)
    let faint = NSColor(calibratedHue: 0.60, saturation: 0.10, brightness: 0.58, alpha: 1)

    func bar(_ x0: CGFloat, _ x1: CGFloat, _ y: CGFloat, _ color: NSColor) {
        let h = 84 * s
        let r = NSRect(x: x0 * s, y: (y - 42) * s, width: (x1 - x0) * s, height: h)
        let path = NSBezierPath(roundedRect: r, xRadius: h / 2, yRadius: h / 2)
        color.setFill()
        path.fill()
    }

    // Three staggered lines of chunks
    bar(232, 468, 664, subject)
    bar(516, 792, 664, verb)
    bar(232, 384, 512, verb)
    bar(432, 700, 512, object)
    bar(232, 560, 360, clause)
    bar(608, 792, 360, faint)

    NSGraphicsContext.restoreGraphicsState()
    guard let png = rep.representation(using: .png, properties: [:]) else { fatalError("png") }
    try! png.write(to: url)
}

let iconsetURL = URL(fileURLWithPath: "build/AppIcon.iconset")
try? FileManager.default.createDirectory(at: iconsetURL, withIntermediateDirectories: true)
let entries: [(String, Int)] = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]
for (name, size) in entries {
    draw(into: size, to: iconsetURL.appendingPathComponent(name))
}
print("iconset written to \(iconsetURL.path)")
