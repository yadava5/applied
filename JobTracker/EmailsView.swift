import SwiftUI
import WebKit

private enum EmailsPanel: String, CaseIterable, Identifiable {
    case inbox
    case review

    var id: String { rawValue }

    var title: String {
        switch self {
        case .inbox:
            return "Inbox"
        case .review:
            return "Review Queue"
        }
    }
}

private enum EmailSourceFilter: String, CaseIterable, Identifiable {
    case all
    case gmail
    case icloud

    var id: String { rawValue }
    var title: String { rawValue == "all" ? "All Sources" : rawValue.uppercased() }
    var queryValue: String? { self == .all ? nil : rawValue }
}

private enum EmailClassificationFilter: String, CaseIterable, Identifiable {
    case all
    case applied
    case interview
    case rejection
    case offer
    case assessment
    case followUp = "follow_up"
    case other

    var id: String { rawValue }
    var title: String { self == .all ? "All Categories" : rawValue.humanizedFromSnakeCase }
    var queryValue: String? { self == .all ? nil : rawValue }
}

struct EmailsView: View {
    @State private var panel: EmailsPanel = .inbox

    var body: some View {
        VStack(spacing: 0) {
            Picker("Email View", selection: $panel) {
                ForEach(EmailsPanel.allCases) { view in
                    Text(view.title).tag(view)
                }
            }
            .pickerStyle(.segmented)
            .padding([.horizontal, .top], 16)

            Group {
                switch panel {
                case .inbox:
                    EmailInboxView()
                case .review:
                    ReviewQueueView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .navigationTitle("Emails")
    }
}

private struct EmailInboxView: View {
    @State private var emails: [InboxEmailSummary] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var searchText = ""
    @State private var sourceFilter: EmailSourceFilter = .all
    @State private var classificationFilter: EmailClassificationFilter = .all
    @State private var unreviewedOnly = false
    @State private var currentPage = 1
    @State private var hasMore = false
    @State private var total = 0
    @State private var emailSheetSelection: InboxEmailSheetSelection?

    private let pageSize = 50

    var body: some View {
        List {
            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .foregroundStyle(.red)
                }
            }

            Section("Inbox (\(total))") {
                if isLoading && emails.isEmpty {
                    ProgressView("Loading emails...")
                        .frame(maxWidth: .infinity, alignment: .center)
                } else if emails.isEmpty {
                    Text("No emails matched your filters.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(emails) { email in
                        Button {
                            emailSheetSelection = InboxEmailSheetSelection(id: email.id)
                        } label: {
                            EmailInboxRow(email: email)
                        }
                        .buttonStyle(.plain)
                    }

                    if hasMore {
                        Button("Load More") {
                            Task { await loadPage(reset: false) }
                        }
                        .frame(maxWidth: .infinity, alignment: .center)
                        .disabled(isLoading)
                    }
                }
            }
        }
        .navigationTitle("Inbox")
        .searchable(text: $searchText, prompt: "Search subject or sender")
        .onSubmit(of: .search) {
            Task { await loadPage(reset: true) }
        }
        .toolbar {
            ToolbarItemGroup(placement: .automatic) {
                Menu("Filter") {
                    Picker("Source", selection: $sourceFilter) {
                        ForEach(EmailSourceFilter.allCases) { source in
                            Text(source.title).tag(source)
                        }
                    }
                    Picker("Category", selection: $classificationFilter) {
                        ForEach(EmailClassificationFilter.allCases) { category in
                            Text(category.title).tag(category)
                        }
                    }
                    Toggle("Unreviewed Only", isOn: $unreviewedOnly)
                }

                Button("Apply") {
                    Task { await loadPage(reset: true) }
                }
                .disabled(isLoading)

                Button("Refresh") {
                    Task { await loadPage(reset: true) }
                }
                .disabled(isLoading)
            }
        }
        .task {
            await loadPage(reset: true)
        }
        .sheet(item: $emailSheetSelection) { selection in
            NavigationStack {
                EmailDetailView(emailID: selection.id, showsCloseButton: true)
            }
            .frame(minWidth: 760, minHeight: 620)
        }
    }

    private func loadPage(reset: Bool) async {
        if isLoading {
            return
        }
        isLoading = true
        errorMessage = nil

        let page = reset ? 1 : (currentPage + 1)
        let trimmedSearch = searchText.trimmingCharacters(in: .whitespacesAndNewlines)

        do {
            let response = try await BackendAPIClient.shared.fetchEmails(
                page: page,
                pageSize: pageSize,
                source: sourceFilter.queryValue,
                classification: classificationFilter.queryValue,
                unreviewedOnly: unreviewedOnly,
                search: trimmedSearch.isEmpty ? nil : trimmedSearch
            )

            if reset {
                emails = response.emails
            } else {
                emails.append(contentsOf: response.emails)
            }
            currentPage = response.page
            hasMore = response.hasMore
            total = response.total
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }
}

private struct InboxEmailSheetSelection: Identifiable {
    let id: Int
}

private struct EmailInboxRow: View {
    let email: InboxEmailSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 10) {
                VStack(alignment: .leading, spacing: 3) {
                    Text(email.subject.isEmpty ? "(No subject)" : email.subject)
                        .font(.headline)
                    Text(email.senderName ?? email.senderEmail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 3) {
                    if let category = email.classifiedAs {
                        Text(category.humanizedFromSnakeCase)
                            .font(.caption2)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 3)
                            .background(.thinMaterial, in: Capsule())
                    }
                    Text(email.receivedAt.asEasternTimestamp)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }

            if !email.bodySnippet.isEmpty {
                Text(email.bodySnippet)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
        .padding(.vertical, 4)
    }
}

struct EmailDetailView: View {
    let emailID: Int
    let showsCloseButton: Bool

    @Environment(\.dismiss) private var dismiss

    @State private var email: InboxEmailDetail?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var browserLoadError: String?

    init(emailID: Int, showsCloseButton: Bool = false) {
        self.emailID = emailID
        self.showsCloseButton = showsCloseButton
    }

    var body: some View {
        Group {
            if isLoading {
                ProgressView("Loading email…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let errorMessage {
                VStack(spacing: 10) {
                    Text("Could not load email")
                        .font(.headline)
                    Text(errorMessage)
                        .font(.subheadline)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.red)
                }
                .padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let email {
                VStack(spacing: 0) {
                    emailHeader(email)

                    Divider()

                    if let html = normalizedHTMLBody(from: email) {
                        EmailInAppBrowserView(
                            htmlDocument: wrappedHTMLDocument(html),
                            loadError: $browserLoadError
                        )
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        ScrollView {
                            Text(verbatim: normalizedPlainText(from: email))
                                .font(.body)
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(16)
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                Text("No email loaded.")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .navigationTitle("Email")
        .toolbar {
            if let email, let html = normalizedHTMLBody(from: email) {
                ToolbarItem(placement: .automatic) {
                    Button("Open in Browser") {
                        openInDefaultBrowser(html)
                    }
                }
            }
            if showsCloseButton {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        dismiss()
                    }
                    .keyboardShortcut(.cancelAction)
                }
            }
        }
        .task(id: emailID) {
            await loadEmail()
        }
    }

    @ViewBuilder
    private func emailHeader(_ email: InboxEmailDetail) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(email.subject.isEmpty ? "(No subject)" : email.subject)
                .font(.title3.weight(.semibold))
                .textSelection(.enabled)

            HStack(spacing: 8) {
                headerTag("From: \(email.senderName ?? email.senderEmail)")
                headerTag("Received: \(email.receivedAt.asEasternTimestamp)")
                if let category = email.classifiedAs {
                    headerTag("Category: \(category.humanizedFromSnakeCase)")
                }
            }

            if let browserLoadError, !browserLoadError.isEmpty {
                Text(browserLoadError)
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .lineLimit(2)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.thinMaterial)
    }

    @ViewBuilder
    private func headerTag(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.thinMaterial, in: Capsule())
            .overlay(
                Capsule().stroke(Color.secondary.opacity(0.2))
            )
    }

    private func loadEmail() async {
        isLoading = true
        errorMessage = nil
        browserLoadError = nil
        do {
            email = try await BackendAPIClient.shared.fetchEmailDetail(id: emailID)
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func normalizedHTMLBody(from email: InboxEmailDetail) -> String? {
        let html = (email.bodyHtml ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return html.isEmpty ? nil : html
    }

    private func normalizedPlainText(from email: InboxEmailDetail) -> String {
        let fallback = email.bodyText.isEmpty ? email.bodySnippet : email.bodyText
        let value = fallback.trimmingCharacters(in: .whitespacesAndNewlines)
        return value.isEmpty ? "No text content available." : value
    }

    private func openInDefaultBrowser(_ htmlBody: String) {
        let filename = "jobtracker-email-\(UUID().uuidString).html"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        do {
            try wrappedHTMLDocument(htmlBody).write(to: url, atomically: true, encoding: .utf8)
            NSWorkspace.shared.open(url)
        } catch {
            browserLoadError = "Could not open the default browser."
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

private struct EmailInAppBrowserView: NSViewRepresentable {
    let htmlDocument: String
    @Binding var loadError: String?

    func makeCoordinator() -> Coordinator {
        Coordinator(loadError: $loadError)
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.websiteDataStore = .nonPersistent()

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {
        guard context.coordinator.lastLoadedHTML != htmlDocument else {
            return
        }
        context.coordinator.lastLoadedHTML = htmlDocument
        context.coordinator.load(htmlDocument, in: nsView)
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        @Binding private var loadError: String?
        var lastLoadedHTML: String?
        private var temporaryHTMLURL: URL?

        init(loadError: Binding<String?>) {
            _loadError = loadError
        }

        func load(_ htmlDocument: String, in webView: WKWebView) {
            updateLoadError(nil)

            do {
                let url = try persist(htmlDocument: htmlDocument)
                webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
            } catch {
                webView.loadHTMLString(htmlDocument, baseURL: nil)
                updateLoadError("Using fallback renderer for this message.")
            }
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard
                navigationAction.targetFrame == nil,
                let url = navigationAction.request.url
            else {
                decisionHandler(.allow)
                return
            }

            webView.load(URLRequest(url: url))
            decisionHandler(.cancel)
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            updateLoadError(nil)
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            updateLoadError("In-app browser could not finish loading this email.")
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            updateLoadError("In-app browser failed to start loading this email.")
        }

        private func persist(htmlDocument: String) throws -> URL {
            if let temporaryHTMLURL {
                try? FileManager.default.removeItem(at: temporaryHTMLURL)
            }

            let filename = "jobtracker-inline-\(UUID().uuidString).html"
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
            try htmlDocument.write(to: url, atomically: true, encoding: .utf8)
            temporaryHTMLURL = url
            return url
        }

        private func updateLoadError(_ message: String?) {
            DispatchQueue.main.async {
                self.loadError = message
            }
        }
    }
}
