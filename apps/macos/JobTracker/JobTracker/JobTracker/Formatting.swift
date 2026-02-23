import AppKit
import Foundation
import SwiftUI

extension String {
    var humanizedFromSnakeCase: String {
        self
            .split(separator: "_")
            .map { part in part.capitalized }
            .joined(separator: " ")
    }

    var asEasternTimestamp: String {
        guard let date = TimestampParsers.parseISO8601(self) else {
            return self
        }
        return TimestampParsers.easternOutputFormatter.string(from: date)
    }
}

private enum TimestampParsers {
    static let isoWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    static let isoBasic: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    static let naiveDateTime: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return formatter
    }()

    static let naiveDateTimeFractional: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        return formatter
    }()

    static let easternOutputFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "America/New_York")
        formatter.dateFormat = "MMM d, yyyy h:mm a zzz"
        return formatter
    }()

    static func parseISO8601(_ value: String) -> Date? {
        if let withFractional = isoWithFractionalSeconds.date(from: value) {
            return withFractional
        }
        if let basic = isoBasic.date(from: value) {
            return basic
        }
        if let fractionalNaive = naiveDateTimeFractional.date(from: value) {
            return fractionalNaive
        }
        return naiveDateTime.date(from: value)
    }
}

struct EmailBodyView: View {
    let plainText: String?
    let html: String?

    @State private var showPlainText = false

    private var normalizedPlainText: String {
        let value = (plainText ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return cleanPlainTextForDisplay(value)
    }

    private var normalizedHTML: String? {
        let value = (html ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? nil : value
    }

    private var inferredHTMLFromPlainText: String? {
        guard normalizedHTML == nil else { return nil }
        let value = normalizedPlainText
        guard !value.isEmpty else { return nil }

        let lowered = value.lowercased()
        let htmlIndicators = ["<html", "<body", "<div", "<table", "<p", "<span", "<img"]
        if htmlIndicators.contains(where: { lowered.contains($0) }) {
            return value
        }
        return nil
    }

    private var effectiveHTML: String? {
        normalizedHTML ?? inferredHTMLFromPlainText
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let html = effectiveHTML, !showPlainText {
                EmailHTMLView(html: wrappedHTMLDocument(html))
                    .frame(minHeight: 320, maxHeight: 700)

                HStack(spacing: 8) {
                    Button("Show Plain Text") {
                        showPlainText = true
                    }
                    .buttonStyle(.bordered)

                    Button("Open in Browser") {
                        openHTMLInBrowser(html)
                    }
                    .buttonStyle(.bordered)
                }
            } else if !normalizedPlainText.isEmpty {
                Text(verbatim: normalizedPlainText)
                    .font(.body)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)

                if effectiveHTML != nil {
                    HStack(spacing: 8) {
                        Button("Show Rich Content") {
                            showPlainText = false
                        }
                        .buttonStyle(.bordered)

                        if let html = effectiveHTML {
                            Button("Open in Browser") {
                                openHTMLInBrowser(html)
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }
            } else {
                if effectiveHTML != nil {
                    Text("No readable content is available in this format.")
                        .foregroundStyle(.secondary)
                    Button("Open in Browser") {
                        openHTMLInBrowser(effectiveHTML ?? "")
                    }
                    .buttonStyle(.bordered)
                } else {
                    Text("No readable email content found.")
                        .foregroundStyle(.secondary)
                }
            }
        }
    }

    private func cleanPlainTextForDisplay(_ raw: String) -> String {
        var text = raw
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: "\u{00A0}", with: " ")
            .replacingOccurrences(of: "\u{200B}", with: "")
            .replacingOccurrences(of: "\u{200C}", with: "")
            .replacingOccurrences(of: "\u{200D}", with: "")
            .replacingOccurrences(of: "\u{FEFF}", with: "")

        // LinkedIn plain-text bodies sometimes include duplicated full sections.
        text = trimDuplicatedLinkedInBlock(text)
        text = simplifyTrackedURLs(in: text)

        // Keep paragraph structure while collapsing pathological whitespace.
        text = text.replacingOccurrences(
            of: "[ \\t]{2,}",
            with: " ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: "\\n{3,}",
            with: "\n\n",
            options: .regularExpression
        )
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func trimDuplicatedLinkedInBlock(_ text: String) -> String {
        let marker = "your application was sent to"
        let lowered = text.lowercased()
        guard let firstRange = lowered.range(of: marker) else {
            return text
        }

        let afterFirst = lowered[firstRange.upperBound...]
        guard let secondRelative = afterFirst.range(of: marker) else {
            return text
        }
        let secondLowerIndex = secondRelative.lowerBound

        // Keep only first block if the second copy appears much later.
        let firstOffset = lowered.distance(from: lowered.startIndex, to: firstRange.lowerBound)
        let secondOffset = lowered.distance(from: lowered.startIndex, to: secondLowerIndex)
        guard secondOffset - firstOffset > 800 else {
            return text
        }

        let cutoff = text.index(text.startIndex, offsetBy: secondOffset)
        return String(text[..<cutoff]).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func simplifyTrackedURLs(in text: String) -> String {
        guard let regex = try? NSRegularExpression(pattern: #"https?://\S+"#, options: []) else {
            return text
        }

        let nsRange = NSRange(text.startIndex..., in: text)
        let matches = regex.matches(in: text, options: [], range: nsRange)
        guard !matches.isEmpty else { return text }

        var output = text
        for match in matches.reversed() {
            guard let range = Range(match.range, in: output) else { continue }
            var candidate = String(output[range])
            candidate = candidate.trimmingCharacters(in: CharacterSet(charactersIn: ".,);]>\"'"))

            guard var components = URLComponents(string: candidate) else { continue }
            components.query = nil
            components.fragment = nil
            guard let simplified = components.url?.absoluteString else { continue }

            output.replaceSubrange(range, with: simplified)
        }

        return output
    }

    private func openHTMLInBrowser(_ htmlBody: String) {
        let filename = "jobtracker-email-\(UUID().uuidString).html"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)

        do {
            try wrappedHTMLDocument(htmlBody).write(to: url, atomically: true, encoding: .utf8)
            NSWorkspace.shared.open(url)
        } catch {
            // Keep the in-app reader resilient even if temp write/open fails.
        }
    }

    private func wrappedHTMLDocument(_ htmlBody: String) -> String {
        """
        <!doctype html>
        <html>
        <head>
            <meta charset=\"utf-8\">
            <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
            <style>
                :root { color-scheme: light dark; }
                body {
                    margin: 0;
                    font-family: -apple-system, BlinkMacSystemFont, \"SF Pro Text\", sans-serif;
                    font-size: 15px;
                    line-height: 1.45;
                    padding: 12px;
                    word-wrap: break-word;
                }
                img, table { max-width: 100%; height: auto; }
                pre, code { white-space: pre-wrap; }
            </style>
        </head>
        <body>
        \(htmlBody)
        </body>
        </html>
        """
    }
}

private struct EmailHTMLView: NSViewRepresentable {
    let html: String

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSScrollView()
        scrollView.drawsBackground = false
        scrollView.borderType = .noBorder
        scrollView.hasVerticalScroller = true

        let textView = NSTextView()
        textView.isEditable = false
        textView.isSelectable = true
        textView.isRichText = true
        textView.drawsBackground = false
        textView.textContainerInset = NSSize(width: 0, height: 0)
        textView.textContainer?.lineFragmentPadding = 0
        textView.textContainer?.widthTracksTextView = true
        textView.delegate = context.coordinator
        textView.linkTextAttributes = [.foregroundColor: NSColor.linkColor]

        scrollView.documentView = textView
        return scrollView
    }

    func updateNSView(_ nsView: NSScrollView, context: Context) {
        guard let textView = nsView.documentView as? NSTextView else {
            return
        }
        let shouldReload = context.coordinator.lastLoadedHTML != html
        guard shouldReload else {
            return
        }

        context.coordinator.lastLoadedHTML = html
        context.coordinator.scheduleRender(html: html, into: textView)
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var lastLoadedHTML: String?
        private var pendingRender: DispatchWorkItem?
        private var lastAppliedHTML: String?

        deinit {
            pendingRender?.cancel()
        }

        func scheduleRender(html: String, into textView: NSTextView) {
            pendingRender?.cancel()

            let work = DispatchWorkItem { [weak self, weak textView] in
                guard let self, let textView else { return }
                guard self.lastLoadedHTML == html else { return }
                guard self.lastAppliedHTML != html else { return }

                if let attributed = self.makeAttributed(from: html) {
                    textView.textStorage?.setAttributedString(attributed)
                } else {
                    textView.string = "This rich email format could not be rendered inline."
                }
                self.lastAppliedHTML = html
            }

            pendingRender = work
            DispatchQueue.main.async(execute: work)
        }

        func makeAttributed(from html: String) -> NSAttributedString? {
            guard let data = html.data(using: .utf8) else {
                return nil
            }

            let options: [NSAttributedString.DocumentReadingOptionKey: Any] = [
                .documentType: NSAttributedString.DocumentType.html,
                .characterEncoding: String.Encoding.utf8.rawValue,
            ]

            guard
                let attributed = try? NSMutableAttributedString(
                    data: data,
                    options: options,
                    documentAttributes: nil
                )
            else {
                return nil
            }

            let fullRange = NSRange(location: 0, length: attributed.length)
            attributed.addAttributes(
                [
                    .font: NSFont.systemFont(ofSize: 14),
                    .foregroundColor: NSColor.labelColor,
                ],
                range: fullRange
            )

            return attributed
        }

        func textView(_ textView: NSTextView, clickedOnLink link: Any, at charIndex: Int) -> Bool {
            if let url = link as? URL {
                NSWorkspace.shared.open(url)
                return true
            }
            if let urlString = link as? String, let url = URL(string: urlString) {
                NSWorkspace.shared.open(url)
                return true
            }
            return false
        }
    }
}


struct JTThemePalette {
    let backgroundTop: Color
    let backgroundBottom: Color
    let surfaceTop: Color
    let surfaceBottom: Color
    let surfaceStroke: Color
    let accentPrimary: Color
    let accentSecondary: Color
    let success: Color
    let warning: Color
    let danger: Color
    let backgroundImageName: String?
    let backgroundImageOpacity: Double
    let backgroundImageSaturation: Double
}

enum JTThemePreset: String, CaseIterable, Identifiable {
    case oceanGlass
    case sunriseGlow
    case forestMist
    case graphiteSky
    case auroraBorealis
    case desertBloom
    case midnightNeon

    static let defaultsKey = "appearance.theme.preset"

    static var persistedDefault: JTThemePreset {
        guard
            let rawValue = UserDefaults.standard.string(forKey: defaultsKey),
            let preset = JTThemePreset(rawValue: rawValue)
        else {
            return .oceanGlass
        }
        return preset
    }

    var id: String { rawValue }

    var title: String {
        switch self {
        case .oceanGlass:
            return "Ocean Glass"
        case .sunriseGlow:
            return "Sunrise Glow"
        case .forestMist:
            return "Forest Mist"
        case .graphiteSky:
            return "Graphite Sky"
        case .auroraBorealis:
            return "Aurora Borealis"
        case .desertBloom:
            return "Desert Bloom"
        case .midnightNeon:
            return "Midnight Neon"
        }
    }

    var subtitle: String {
        switch self {
        case .oceanGlass:
            return "Cool blue-teal with wave backdrop"
        case .sunriseGlow:
            return "Warm amber-coral with sunrise hills"
        case .forestMist:
            return "Earthy greens with canopy texture"
        case .graphiteSky:
            return "Neutral slate palette for minimalists"
        case .auroraBorealis:
            return "Northern light vibes with soft ribbons"
        case .desertBloom:
            return "Sand dunes and warm late-evening tones"
        case .midnightNeon:
            return "Dark city neon accents with depth"
        }
    }

    var palette: JTThemePalette {
        switch self {
        case .oceanGlass:
            return JTThemePalette(
                backgroundTop: Color(red: 0.06, green: 0.10, blue: 0.18),
                backgroundBottom: Color(red: 0.02, green: 0.05, blue: 0.10),
                surfaceTop: Color(red: 0.21, green: 0.31, blue: 0.47).opacity(0.24),
                surfaceBottom: Color(red: 0.10, green: 0.17, blue: 0.30).opacity(0.18),
                surfaceStroke: Color(red: 0.66, green: 0.82, blue: 0.95).opacity(0.42),
                accentPrimary: Color(red: 0.21, green: 0.79, blue: 0.71),
                accentSecondary: Color(red: 0.97, green: 0.73, blue: 0.33),
                success: Color(red: 0.54, green: 0.90, blue: 0.55),
                warning: Color(red: 0.99, green: 0.72, blue: 0.31),
                danger: Color(red: 0.98, green: 0.42, blue: 0.46),
                backgroundImageName: "ThemeOceanWaves",
                backgroundImageOpacity: 0.28,
                backgroundImageSaturation: 1.05
            )
        case .sunriseGlow:
            return JTThemePalette(
                backgroundTop: Color(red: 0.24, green: 0.11, blue: 0.10),
                backgroundBottom: Color(red: 0.10, green: 0.05, blue: 0.08),
                surfaceTop: Color(red: 0.49, green: 0.29, blue: 0.25).opacity(0.24),
                surfaceBottom: Color(red: 0.29, green: 0.15, blue: 0.18).opacity(0.20),
                surfaceStroke: Color(red: 0.98, green: 0.79, blue: 0.67).opacity(0.42),
                accentPrimary: Color(red: 0.98, green: 0.56, blue: 0.38),
                accentSecondary: Color(red: 0.98, green: 0.78, blue: 0.37),
                success: Color(red: 0.58, green: 0.86, blue: 0.53),
                warning: Color(red: 0.99, green: 0.71, blue: 0.32),
                danger: Color(red: 0.96, green: 0.39, blue: 0.42),
                backgroundImageName: "ThemeSunriseHills",
                backgroundImageOpacity: 0.27,
                backgroundImageSaturation: 1.08
            )
        case .forestMist:
            return JTThemePalette(
                backgroundTop: Color(red: 0.06, green: 0.14, blue: 0.12),
                backgroundBottom: Color(red: 0.03, green: 0.08, blue: 0.08),
                surfaceTop: Color(red: 0.20, green: 0.35, blue: 0.30).opacity(0.24),
                surfaceBottom: Color(red: 0.10, green: 0.21, blue: 0.19).opacity(0.20),
                surfaceStroke: Color(red: 0.69, green: 0.88, blue: 0.80).opacity(0.40),
                accentPrimary: Color(red: 0.31, green: 0.81, blue: 0.63),
                accentSecondary: Color(red: 0.71, green: 0.86, blue: 0.46),
                success: Color(red: 0.60, green: 0.90, blue: 0.56),
                warning: Color(red: 0.95, green: 0.76, blue: 0.34),
                danger: Color(red: 0.90, green: 0.42, blue: 0.46),
                backgroundImageName: "ThemeForestCanopy",
                backgroundImageOpacity: 0.25,
                backgroundImageSaturation: 1.12
            )
        case .graphiteSky:
            return JTThemePalette(
                backgroundTop: Color(red: 0.11, green: 0.13, blue: 0.18),
                backgroundBottom: Color(red: 0.05, green: 0.06, blue: 0.09),
                surfaceTop: Color(red: 0.24, green: 0.27, blue: 0.36).opacity(0.24),
                surfaceBottom: Color(red: 0.14, green: 0.16, blue: 0.24).opacity(0.20),
                surfaceStroke: Color(red: 0.74, green: 0.79, blue: 0.88).opacity(0.38),
                accentPrimary: Color(red: 0.42, green: 0.70, blue: 0.96),
                accentSecondary: Color(red: 0.78, green: 0.69, blue: 0.95),
                success: Color(red: 0.56, green: 0.86, blue: 0.58),
                warning: Color(red: 0.95, green: 0.71, blue: 0.35),
                danger: Color(red: 0.92, green: 0.43, blue: 0.46),
                backgroundImageName: "ThemeGraphiteGrid",
                backgroundImageOpacity: 0.20,
                backgroundImageSaturation: 0.86
            )
        case .auroraBorealis:
            return JTThemePalette(
                backgroundTop: Color(red: 0.02, green: 0.11, blue: 0.16),
                backgroundBottom: Color(red: 0.01, green: 0.04, blue: 0.09),
                surfaceTop: Color(red: 0.16, green: 0.32, blue: 0.35).opacity(0.26),
                surfaceBottom: Color(red: 0.07, green: 0.18, blue: 0.24).opacity(0.20),
                surfaceStroke: Color(red: 0.64, green: 0.92, blue: 0.88).opacity(0.44),
                accentPrimary: Color(red: 0.23, green: 0.88, blue: 0.74),
                accentSecondary: Color(red: 0.45, green: 0.72, blue: 0.98),
                success: Color(red: 0.58, green: 0.93, blue: 0.64),
                warning: Color(red: 0.97, green: 0.78, blue: 0.36),
                danger: Color(red: 0.95, green: 0.45, blue: 0.49),
                backgroundImageName: "ThemeAuroraVeil",
                backgroundImageOpacity: 0.30,
                backgroundImageSaturation: 1.18
            )
        case .desertBloom:
            return JTThemePalette(
                backgroundTop: Color(red: 0.23, green: 0.12, blue: 0.08),
                backgroundBottom: Color(red: 0.11, green: 0.06, blue: 0.05),
                surfaceTop: Color(red: 0.46, green: 0.28, blue: 0.20).opacity(0.24),
                surfaceBottom: Color(red: 0.24, green: 0.15, blue: 0.12).opacity(0.20),
                surfaceStroke: Color(red: 0.98, green: 0.82, blue: 0.62).opacity(0.42),
                accentPrimary: Color(red: 0.97, green: 0.62, blue: 0.37),
                accentSecondary: Color(red: 0.97, green: 0.81, blue: 0.43),
                success: Color(red: 0.62, green: 0.88, blue: 0.54),
                warning: Color(red: 0.98, green: 0.73, blue: 0.33),
                danger: Color(red: 0.94, green: 0.44, blue: 0.38),
                backgroundImageName: "ThemeDesertDunes",
                backgroundImageOpacity: 0.27,
                backgroundImageSaturation: 1.06
            )
        case .midnightNeon:
            return JTThemePalette(
                backgroundTop: Color(red: 0.06, green: 0.05, blue: 0.14),
                backgroundBottom: Color(red: 0.02, green: 0.02, blue: 0.08),
                surfaceTop: Color(red: 0.20, green: 0.16, blue: 0.34).opacity(0.26),
                surfaceBottom: Color(red: 0.10, green: 0.09, blue: 0.20).opacity(0.20),
                surfaceStroke: Color(red: 0.78, green: 0.73, blue: 0.98).opacity(0.42),
                accentPrimary: Color(red: 0.47, green: 0.78, blue: 0.99),
                accentSecondary: Color(red: 0.95, green: 0.45, blue: 0.73),
                success: Color(red: 0.58, green: 0.87, blue: 0.63),
                warning: Color(red: 0.95, green: 0.72, blue: 0.33),
                danger: Color(red: 0.96, green: 0.42, blue: 0.50),
                backgroundImageName: "ThemeMidnightNeon",
                backgroundImageOpacity: 0.24,
                backgroundImageSaturation: 1.2
            )
        }
    }
}

enum JTTheme {
    private static var activePreset: JTThemePreset = .oceanGlass

    static func apply(_ preset: JTThemePreset) {
        activePreset = preset
    }

    static var currentPreset: JTThemePreset {
        activePreset
    }

    private static var palette: JTThemePalette {
        activePreset.palette
    }

    static var backgroundTop: Color { palette.backgroundTop }
    static var backgroundBottom: Color { palette.backgroundBottom }
    static var surfaceTop: Color { palette.surfaceTop }
    static var surfaceBottom: Color { palette.surfaceBottom }
    static var surfaceStroke: Color { palette.surfaceStroke }
    static var accentPrimary: Color { palette.accentPrimary }
    static var accentSecondary: Color { palette.accentSecondary }
    static var success: Color { palette.success }
    static var warning: Color { palette.warning }
    static var danger: Color { palette.danger }
    static var backgroundImageName: String? { palette.backgroundImageName }
    static var backgroundImageOpacity: Double { palette.backgroundImageOpacity }
    static var backgroundImageSaturation: Double { palette.backgroundImageSaturation }
}

struct JTBackdropView: View {
    var body: some View {
        ZStack {
            LinearGradient(
                colors: [JTTheme.backgroundTop, JTTheme.backgroundBottom],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            if let backgroundImageName = JTTheme.backgroundImageName {
                Image(backgroundImageName)
                    .resizable()
                    .scaledToFill()
                    .ignoresSafeArea()
                    .opacity(JTTheme.backgroundImageOpacity)
                    .saturation(JTTheme.backgroundImageSaturation)
                    .overlay {
                        LinearGradient(
                            colors: [
                                Color.black.opacity(0.22),
                                Color.clear,
                                Color.black.opacity(0.30),
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    }
            }

            Circle()
                .fill(
                    RadialGradient(
                        colors: [JTTheme.accentPrimary.opacity(0.32), .clear],
                        center: .center,
                        startRadius: 10,
                        endRadius: 360
                    )
                )
                .frame(width: 520, height: 520)
                .offset(x: -260, y: -240)

            Circle()
                .fill(
                    RadialGradient(
                        colors: [JTTheme.accentSecondary.opacity(0.22), .clear],
                        center: .center,
                        startRadius: 10,
                        endRadius: 420
                    )
                )
                .frame(width: 640, height: 640)
                .offset(x: 300, y: 260)
        }
    }
}
private struct JTPageBackdropModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background {
                JTBackdropView()
                    .ignoresSafeArea()
            }
    }
}

private struct JTCardModifier: ViewModifier {
    let cornerRadius: CGFloat
    let contentPadding: CGFloat

    func body(content: Content) -> some View {
        content
            .padding(contentPadding)
            .background {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(.ultraThinMaterial)
            }
            .background {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(0.14),
                                JTTheme.surfaceTop,
                                JTTheme.surfaceBottom
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
            }
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(JTTheme.surfaceStroke, lineWidth: 1)
            )
            .overlay(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color.white.opacity(0.26), lineWidth: 0.8)
                    .blur(radius: 0.3)
                    .mask(
                        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [Color.white, Color.white.opacity(0)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    )
            }
            .shadow(color: .black.opacity(0.16), radius: 10, x: 0, y: 6)
    }
}

struct JTPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(.body, design: .rounded).weight(.semibold))
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(.thinMaterial)
            }
            .background {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [
                                JTTheme.accentPrimary.opacity(configuration.isPressed ? 0.45 : 0.62),
                                JTTheme.accentSecondary.opacity(configuration.isPressed ? 0.38 : 0.58),
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
            }
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(Color.white.opacity(0.35), lineWidth: 0.8)
            )
            .foregroundStyle(.white)
            .scaleEffect(configuration.isPressed ? 0.98 : 1.0)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

struct JTSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(.body, design: .rounded).weight(.medium))
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(.thinMaterial)
            }
            .background {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Color.white.opacity(configuration.isPressed ? 0.08 : 0.12))
            }
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .stroke(JTTheme.surfaceStroke.opacity(configuration.isPressed ? 0.45 : 0.65), lineWidth: 1)
            )
            .foregroundStyle(.primary)
            .scaleEffect(configuration.isPressed ? 0.985 : 1.0)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

extension View {
    func jtPageBackdrop() -> some View {
        modifier(JTPageBackdropModifier())
    }

    func jtCard(cornerRadius: CGFloat = 16, contentPadding: CGFloat = 14) -> some View {
        modifier(JTCardModifier(cornerRadius: cornerRadius, contentPadding: contentPadding))
    }
}
