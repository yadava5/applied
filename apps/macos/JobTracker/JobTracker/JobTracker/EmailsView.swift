import SwiftUI

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
    case pendingApplication = "pending_application"
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
        VStack(spacing: 12) {
            Picker("Email View", selection: $panel) {
                ForEach(EmailsPanel.allCases) { view in
                    Text(view.title).tag(view)
                }
            }
            .pickerStyle(.segmented)
            .padding(12)
            .jtCard(cornerRadius: 14, contentPadding: 8)
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
        .jtPageBackdrop()
    }
}

private struct EmailInboxView: View {
    @Environment(AppModel.self) private var appModel
    @State private var emails: [InboxEmailSummary] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var searchText = ""
    @State private var sourceFilter: EmailSourceFilter = .all
    @State private var classificationFilter: EmailClassificationFilter = .all
    @State private var unreviewedOnly = false
    @State private var unlinkedOnly = false
    @State private var currentPage = 1
    @State private var hasMore = false
    @State private var total = 0
    @State private var emailSheetSelection: InboxEmailSheetSelection?

    private let pageSize = 50

    private var hasActiveFilters: Bool {
        !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || sourceFilter != .all
            || classificationFilter != .all
            || unreviewedOnly
            || unlinkedOnly
    }

    var body: some View {
        List {
            Section {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        TextField("Search subject or sender", text: $searchText)
                            .textFieldStyle(.roundedBorder)
                            .onSubmit {
                                Task { await loadPage(reset: true) }
                            }

                        Button("Search") {
                            Task { await loadPage(reset: true) }
                        }
                        .buttonStyle(.bordered)
                        .disabled(isLoading)

                        if !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            Button("Clear") {
                                searchText = ""
                                Task { await loadPage(reset: true) }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isLoading)
                        }
                    }

                    HStack(spacing: 8) {
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
                            Toggle("Unlinked Job Emails Only", isOn: $unlinkedOnly)
                        }
                        .buttonStyle(.bordered)

                        Button("Apply") {
                            Task { await loadPage(reset: true) }
                        }
                        .disabled(isLoading)
                        .buttonStyle(.bordered)

                        Button("Refresh") {
                            Task { await loadPage(reset: true) }
                        }
                        .disabled(isLoading)
                        .buttonStyle(.bordered)
                    }
                }
                .padding(.vertical, 2)
            }

            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .foregroundStyle(JTTheme.danger)
                }
            }

            Section("Inbox (\(total))") {
                if isLoading && emails.isEmpty {
                    ProgressView("Loading emails...")
                        .frame(maxWidth: .infinity, alignment: .center)
                } else if emails.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(hasActiveFilters ? "No emails matched your filters." : "No synced emails yet.")
                            .font(.subheadline.weight(.semibold))
                        Text(
                            hasActiveFilters
                                ? "Try clearing filters or broadening your search."
                                : "Run your first sync from Dashboard or Settings after connecting Gmail/iCloud."
                        )
                        .font(.caption)
                        .foregroundStyle(.secondary)

                        if hasActiveFilters {
                            Button("Clear Filters") {
                                sourceFilter = .all
                                classificationFilter = .all
                                unreviewedOnly = false
                                unlinkedOnly = false
                                searchText = ""
                                Task { await loadPage(reset: true) }
                            }
                            .buttonStyle(JTSecondaryButtonStyle())
                        }
                    }
                    .padding(.vertical, 6)
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
                        .buttonStyle(JTSecondaryButtonStyle())
                    }
                }
            }
        }
        .navigationTitle("Inbox")
        .listStyle(.inset)
        .scrollContentBackground(.hidden)
        .background(Color.clear)
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
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            errorMessage = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
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
                unlinkedOnly: unlinkedOnly,
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
                            .background(Color.white.opacity(0.12), in: Capsule())
                            .overlay(Capsule().stroke(JTTheme.surfaceStroke, lineWidth: 1))
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
    @Environment(AppModel.self) private var appModel
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
                        .foregroundStyle(JTTheme.danger)
                }
                .padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let email {
                let htmlBody = normalizedHTMLBody(from: email)
                VStack(spacing: 0) {
                    emailHeader(email, htmlBody: htmlBody)

                    Divider()

                    ScrollView {
                        EmailBodyView(
                            plainText: normalizedPlainText(from: email),
                            html: htmlBody
                        )
                        .padding(16)
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
        .background(Color.clear)
        .task(id: emailID) {
            await loadEmail()
        }
    }

    @ViewBuilder
    private func emailHeader(_ email: InboxEmailDetail, htmlBody: String?) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                Text(email.subject.isEmpty ? "(No subject)" : email.subject)
                    .font(.title3.weight(.semibold))
                    .textSelection(.enabled)

                Spacer(minLength: 8)

                HStack(spacing: 8) {
                    if let htmlBody {
                        Button("Open in Browser") {
                            openInDefaultBrowser(htmlBody)
                        }
                        .buttonStyle(.bordered)
                    }

                    if showsCloseButton {
                        Button("Close") {
                            dismiss()
                        }
                        .buttonStyle(.bordered)
                        .keyboardShortcut(.cancelAction)
                    }
                }
            }

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
        .background(
            LinearGradient(
                colors: [JTTheme.surfaceTop, JTTheme.surfaceBottom],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
        )
    }

    @ViewBuilder
    private func headerTag(_ text: String) -> some View {
        Text(text)
            .font(.caption)
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color.white.opacity(0.12), in: Capsule())
            .overlay(
                Capsule().stroke(JTTheme.surfaceStroke, lineWidth: 1)
            )
    }

    private func loadEmail() async {
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            errorMessage = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
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
        guard !html.isEmpty else { return nil }
        return sanitizeHTMLForInAppBrowser(html)
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

    private func sanitizeHTMLForInAppBrowser(_ html: String) -> String {
        var sanitized = html

        let replacements: [(pattern: String, template: String)] = [
            // Remove active script payloads.
            ("<script\\b[^>]*>[\\s\\S]*?<\\/script>", ""),
            // Remove inline event handlers (onclick, onload, ...).
            ("\\son[a-zA-Z]+\\s*=\\s*\"[^\"]*\"", ""),
            ("\\son[a-zA-Z]+\\s*=\\s*'[^']*'", ""),
            ("\\son[a-zA-Z]+\\s*=\\s*[^\\s>]+", ""),
            // Remove javascript: URLs.
            ("(?i)(href|src)\\s*=\\s*\"\\s*javascript:[^\"]*\"", ""),
            ("(?i)(href|src)\\s*=\\s*'\\s*javascript:[^']*'", ""),
        ]

        for rule in replacements {
            sanitized = replacingRegex(
                in: sanitized,
                pattern: rule.pattern,
                template: rule.template
            )
        }

        return sanitized
    }

    private func replacingRegex(
        in input: String,
        pattern: String,
        template: String
    ) -> String {
        guard let regex = try? NSRegularExpression(
            pattern: pattern,
            options: [.caseInsensitive]
        ) else {
            return input
        }

        let range = NSRange(input.startIndex..<input.endIndex, in: input)
        return regex.stringByReplacingMatches(in: input, options: [], range: range, withTemplate: template)
    }
}
