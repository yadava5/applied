#!/bin/bash
# =============================================================================
# Generate JobTracker App + Menu Bar Icon Assets
# =============================================================================
# Produces:
# - App icon files in macOS AppIcon.appiconset
# - Menu bar template icon files in MenuBarIcon.imageset
# - Icon Composer source image in docs/branding
#
# Usage:
#   ./scripts/generate_icons.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ASSETS_DIR="$PROJECT_ROOT/apps/macos/JobTracker/JobTracker/JobTracker/Assets.xcassets"
APPICON_DIR="$ASSETS_DIR/AppIcon.appiconset"
MENUBAR_DIR="$ASSETS_DIR/MenuBarIcon.imageset"
BRANDING_DIR="$PROJECT_ROOT/docs/branding"
TMP_DIR="$(mktemp -d)"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

if ! command -v swift >/dev/null 2>&1; then
    echo "swift command not found."
    exit 1
fi

if ! command -v sips >/dev/null 2>&1; then
    echo "sips command not found."
    exit 1
fi

mkdir -p "$APPICON_DIR" "$MENUBAR_DIR" "$BRANDING_DIR"
rm -f "$APPICON_DIR/AppIcon-2048.png" "$MENUBAR_DIR/MenuBarIcon-64.png"

cat > "$TMP_DIR/render_icons.swift" <<'SWIFT'
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

    let context = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    draw()
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

func writePNG(rep: NSBitmapImageRep, to path: String) throws {
    guard let data = rep.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "icon-render", code: 1)
    }
    try data.write(to: URL(fileURLWithPath: path))
}

let outputDir = CommandLine.arguments[1]

let appRep = makeBitmap(width: 2048, height: 2048) {
    let canvas = NSRect(x: 0, y: 0, width: 2048, height: 2048)
    NSColor.clear.setFill()
    canvas.fill()

    let glow = NSBezierPath(ovalIn: NSRect(x: 170, y: 170, width: 1708, height: 1708))
    let glowGradient = NSGradient(colors: [
        NSColor(calibratedRed: 0.21, green: 0.79, blue: 0.71, alpha: 0.42),
        NSColor(calibratedRed: 0.11, green: 0.34, blue: 0.78, alpha: 0.22),
        NSColor(calibratedRed: 0.03, green: 0.08, blue: 0.20, alpha: 0.02)
    ])!
    glowGradient.draw(in: glow, relativeCenterPosition: NSPoint(x: 0, y: 0))

    let tileRect = NSRect(x: 230, y: 230, width: 1588, height: 1588)
    let tile = NSBezierPath(roundedRect: tileRect, xRadius: 350, yRadius: 350)
    let gradient = NSGradient(colors: [
        NSColor(calibratedRed: 0.19, green: 0.58, blue: 0.97, alpha: 0.88),
        NSColor(calibratedRed: 0.09, green: 0.84, blue: 0.81, alpha: 0.74),
        NSColor(calibratedRed: 0.08, green: 0.24, blue: 0.57, alpha: 0.70)
    ])!
    gradient.draw(in: tile, angle: 318)

    NSColor(calibratedWhite: 1, alpha: 0.30).setStroke()
    tile.lineWidth = 26
    tile.stroke()

    let highlight = NSBezierPath(ovalIn: NSRect(x: 360, y: 980, width: 1240, height: 650))
    NSColor(calibratedWhite: 1, alpha: 0.16).setFill()
    highlight.fill()

    let briefcaseRect = NSRect(x: 545, y: 700, width: 930, height: 650)
    let briefcase = NSBezierPath(roundedRect: briefcaseRect, xRadius: 150, yRadius: 150)
    NSColor(calibratedWhite: 1, alpha: 0.94).setFill()
    briefcase.fill()
    NSColor(calibratedWhite: 1, alpha: 0.46).setStroke()
    briefcase.lineWidth = 10
    briefcase.stroke()

    let handleOuterRect = NSRect(x: 790, y: 1220, width: 460, height: 190)
    let handleOuter = NSBezierPath(roundedRect: handleOuterRect, xRadius: 80, yRadius: 80)
    NSColor(calibratedWhite: 1, alpha: 0.92).setFill()
    handleOuter.fill()

    let handleInnerRect = NSRect(x: 885, y: 1270, width: 270, height: 90)
    let handleInner = NSBezierPath(roundedRect: handleInnerRect, xRadius: 35, yRadius: 35)
    NSColor(calibratedRed: 0.14, green: 0.56, blue: 0.88, alpha: 0.88).setFill()
    handleInner.fill()

    let lens = NSBezierPath(ovalIn: NSRect(x: 1010, y: 570, width: 420, height: 420))
    NSColor(calibratedRed: 0.08, green: 0.36, blue: 0.78, alpha: 0.98).setStroke()
    lens.lineWidth = 64
    lens.stroke()

    let magnifierHandle = NSBezierPath()
    magnifierHandle.move(to: NSPoint(x: 1330, y: 530))
    magnifierHandle.line(to: NSPoint(x: 1500, y: 360))
    magnifierHandle.lineWidth = 66
    magnifierHandle.lineCapStyle = .round
    NSColor(calibratedRed: 0.08, green: 0.36, blue: 0.78, alpha: 0.98).setStroke()
    magnifierHandle.stroke()
}

let menuRep = makeBitmap(width: 64, height: 64) {
    let canvas = NSRect(x: 0, y: 0, width: 64, height: 64)
    NSColor.clear.setFill()
    canvas.fill()

    if let symbol = NSImage(systemSymbolName: "briefcase.fill", accessibilityDescription: nil) {
        let config = NSImage.SymbolConfiguration(pointSize: 42, weight: .semibold)
        let configured = symbol.withSymbolConfiguration(config) ?? symbol
        NSColor.black.set()
        configured.draw(in: NSRect(x: 10, y: 8, width: 44, height: 44))
    }
}

try writePNG(rep: appRep, to: "\(outputDir)/AppIcon-2048.png")
try writePNG(rep: menuRep, to: "\(outputDir)/MenuBarIcon-64.png")
SWIFT

swift "$TMP_DIR/render_icons.swift" "$TMP_DIR"

for px in 16 32 64 128 256 512 1024; do
    sips -s format png -z "$px" "$px" "$TMP_DIR/AppIcon-2048.png" \
        --out "$APPICON_DIR/AppIcon-${px}.png" >/dev/null
done

sips -s format png -z 32 32 "$TMP_DIR/MenuBarIcon-64.png" \
    --out "$MENUBAR_DIR/MenuBarIcon-32.png" >/dev/null
sips -s format png -z 16 16 "$TMP_DIR/MenuBarIcon-64.png" \
    --out "$MENUBAR_DIR/MenuBarIcon-16.png" >/dev/null

cp "$TMP_DIR/AppIcon-2048.png" "$BRANDING_DIR/applied-icon-composer-source.png"

cat > "$APPICON_DIR/Contents.json" <<'JSON'
{
  "images" : [
    {
      "filename" : "AppIcon-16.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "16x16"
    },
    {
      "filename" : "AppIcon-32.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "16x16"
    },
    {
      "filename" : "AppIcon-32.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "32x32"
    },
    {
      "filename" : "AppIcon-64.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "32x32"
    },
    {
      "filename" : "AppIcon-128.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "128x128"
    },
    {
      "filename" : "AppIcon-256.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "128x128"
    },
    {
      "filename" : "AppIcon-256.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "256x256"
    },
    {
      "filename" : "AppIcon-512.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "256x256"
    },
    {
      "filename" : "AppIcon-512.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "512x512"
    },
    {
      "filename" : "AppIcon-1024.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "512x512"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
JSON

cat > "$MENUBAR_DIR/Contents.json" <<'JSON'
{
  "images" : [
    {
      "filename" : "MenuBarIcon-16.png",
      "idiom" : "mac",
      "scale" : "1x",
      "size" : "16x16"
    },
    {
      "filename" : "MenuBarIcon-32.png",
      "idiom" : "mac",
      "scale" : "2x",
      "size" : "16x16"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  },
  "properties" : {
    "template-rendering-intent" : "template"
  }
}
JSON

echo "Generated icon assets:"
echo "  - $APPICON_DIR"
echo "  - $MENUBAR_DIR"
echo "  - $BRANDING_DIR/applied-icon-composer-source.png"
