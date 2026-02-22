#!/bin/bash
# =============================================================================
# Generate README Preview Images
# =============================================================================
# Creates static preview images for README in docs/screenshots.
#
# Usage:
#   ./scripts/generate_readme_screenshots.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$PROJECT_ROOT/docs/screenshots"
TMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$OUT_DIR"

cat > "$TMP_DIR/render_previews.swift" <<'SWIFT'
import AppKit
import Foundation

func makeBitmap(width: Int, height: Int, draw: () -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: width,
        pixelsHigh: height,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    )!
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = ctx
    draw()
    ctx.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

func savePNG(_ rep: NSBitmapImageRep, path: String) throws {
    guard let data = rep.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "preview-render", code: 1)
    }
    try data.write(to: URL(fileURLWithPath: path))
}

func drawCard(_ rect: NSRect, title: String, subtitle: String) {
    let path = NSBezierPath(roundedRect: rect, xRadius: 16, yRadius: 16)
    NSColor(calibratedWhite: 1, alpha: 0.10).setFill()
    path.fill()

    let titleAttrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 22, weight: .semibold),
        .foregroundColor: NSColor.white,
    ]
    let subtitleAttrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: 15, weight: .regular),
        .foregroundColor: NSColor(calibratedWhite: 0.9, alpha: 0.95),
    ]

    NSString(string: title).draw(
        at: NSPoint(x: rect.minX + 22, y: rect.maxY - 42),
        withAttributes: titleAttrs
    )
    NSString(string: subtitle).draw(
        at: NSPoint(x: rect.minX + 22, y: rect.maxY - 72),
        withAttributes: subtitleAttrs
    )
}

func renderPreview(path: String, heading: String, cards: [(String, String)]) throws {
    let width = 1440
    let height = 900

    let rep = makeBitmap(width: width, height: height) {
        let canvas = NSRect(x: 0, y: 0, width: width, height: height)
        NSColor(calibratedRed: 0.08, green: 0.09, blue: 0.15, alpha: 1).setFill()
        canvas.fill()

        let gradient = NSGradient(colors: [
            NSColor(calibratedRed: 0.18, green: 0.20, blue: 0.35, alpha: 1),
            NSColor(calibratedRed: 0.09, green: 0.11, blue: 0.20, alpha: 1)
        ])!
        gradient.draw(in: canvas, angle: 245)

        let headerAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 44, weight: .bold),
            .foregroundColor: NSColor.white,
        ]
        NSString(string: heading).draw(
            at: NSPoint(x: 70, y: 808),
            withAttributes: headerAttrs
        )

        let cardWidth = 1300.0
        var top = 700.0
        for (title, subtitle) in cards {
            drawCard(
                NSRect(x: 70, y: top, width: cardWidth, height: 140),
                title: title,
                subtitle: subtitle
            )
            top -= 170
        }
    }

    try savePNG(rep, path: path)
}

let outDir = CommandLine.arguments[1]
try renderPreview(
    path: "\(outDir)/dashboard.png",
    heading: "JobTracker Dashboard",
    cards: [
        ("Pipeline Overview", "Applied, Interviewing, Offered, Rejected at a glance"),
        ("Live Sync Status", "WebSocket-driven sync progress and health"),
        ("Review Queue", "Low-confidence emails that need quick confirmation")
    ]
)
try renderPreview(
    path: "\(outDir)/applications.png",
    heading: "Applications View",
    cards: [
        ("Search + Filters", "Filter by status and sort by latest activity"),
        ("Application Timeline", "Linked email history, contacts, and notes"),
        ("Manual Overrides", "Update status and correct false-positive links")
    ]
)
try renderPreview(
    path: "\(outDir)/emails.png",
    heading: "Inbox + Review Queue",
    cards: [
        ("Unified Inbox", "Gmail + iCloud messages in one place"),
        ("Classification Badges", "Rules + embeddings + SetFit confidence signals"),
        ("One-Click Correction", "Feed training data directly from review actions")
    ]
)
SWIFT

swift "$TMP_DIR/render_previews.swift" "$OUT_DIR"
echo "Generated README preview images in $OUT_DIR"
