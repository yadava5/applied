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
        if let attributed = context.coordinator.makeAttributed(from: html) {
            textView.textStorage?.setAttributedString(attributed)
        } else {
            textView.string = "This rich email format could not be rendered inline."
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var lastLoadedHTML: String?

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
