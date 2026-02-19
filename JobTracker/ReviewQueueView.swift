import SwiftUI

struct ReviewQueueView: View {
    @State private var emails: [ReviewEmail] = []
    @State private var totalCount = 0
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var infoMessage: String?
    @State private var processingIDs: Set<Int> = []
    @State private var expandedEmailIDs: Set<Int> = []
    @State private var emailSheetSelection: ReviewEmailSheetSelection?

    private let categories = [
        "applied",
        "interview",
        "rejection",
        "offer",
        "assessment",
        "follow_up",
        "other"
    ]

    var body: some View {
        List {
            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .font(.subheadline)
                        .foregroundStyle(.red)
                }
            }

            if let infoMessage {
                Section {
                    Text(infoMessage)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            Section("Needs Review (\(totalCount))") {
                if isLoading && emails.isEmpty {
                    ProgressView("Loading review queue...")
                        .frame(maxWidth: .infinity, alignment: .center)
                } else if emails.isEmpty {
                    Text("No emails need review right now.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(emails) { email in
                        reviewRow(email)
                    }
                }
            }
        }
        .navigationTitle("Review Queue")
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Button("Refresh") {
                    Task { await loadNeedsReview() }
                }
            }
        }
        .task {
            await loadNeedsReview()
        }
        .sheet(item: $emailSheetSelection) { selection in
            NavigationStack {
                EmailDetailView(emailID: selection.id, showsCloseButton: true)
            }
            .frame(minWidth: 760, minHeight: 620)
        }
    }

    private func reviewRow(_ email: ReviewEmail) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(email.subject?.isEmpty == false ? (email.subject ?? "(No subject)") : "(No subject)")
                        .font(.headline)
                    Text(email.senderEmail ?? email.senderName ?? "Unknown sender")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let receivedAt = email.receivedAt, !receivedAt.isEmpty {
                        Text(receivedAt.asEasternTimestamp)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Text(email.currentCategory.humanizedFromSnakeCase)
                        .font(.caption)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.thinMaterial, in: Capsule())
                    Text("\(Int(email.confidence * 100))%")
                        .font(.caption2)
                        .foregroundStyle(confidenceColor(email.confidence))
                }
            }

            if let snippet = email.snippet, !snippet.isEmpty {
                Text(snippet)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }

            HStack {
                Button(expandedEmailIDs.contains(email.id) ? "Hide Full Content" : "Show Full Content") {
                    toggleExpanded(email.id)
                }
                .buttonStyle(.bordered)

                Button("Open Full Email") {
                    emailSheetSelection = ReviewEmailSheetSelection(id: email.id)
                }
                .buttonStyle(.borderedProminent)

                Button("Approve") {
                    Task { await approve(emailID: email.id) }
                }
                .buttonStyle(.bordered)
                .disabled(processingIDs.contains(email.id))

                Menu("Correct") {
                    ForEach(categories, id: \.self) { category in
                        Button(category.humanizedFromSnakeCase) {
                            Task { await correct(emailID: email.id, category: category) }
                        }
                    }
                }
                .disabled(processingIDs.contains(email.id))

                if processingIDs.contains(email.id) {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            if expandedEmailIDs.contains(email.id) {
                EmailBodyView(
                    plainText: email.bodyText ?? email.snippet,
                    html: email.bodyHtml
                )
                .padding(10)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 10))
            }
        }
        .padding(.vertical, 6)
    }

    private func confidenceColor(_ confidence: Double) -> Color {
        if confidence >= 0.85 {
            return .green
        }
        if confidence >= 0.70 {
            return .orange
        }
        return .red
    }

    private func loadNeedsReview() async {
        isLoading = true
        errorMessage = nil

        do {
            let response = try await BackendAPIClient.shared.fetchNeedsReview(limit: 100, offset: 0)
            emails = response.emails
            totalCount = response.totalCount
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    private func approve(emailID: Int) async {
        processingIDs.insert(emailID)
        defer { processingIDs.remove(emailID) }

        do {
            let response = try await BackendAPIClient.shared.approveEmailClassification(emailID: emailID)
            infoMessage = response.message
            removeEmail(emailID)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func correct(emailID: Int, category: String) async {
        processingIDs.insert(emailID)
        defer { processingIDs.remove(emailID) }

        do {
            let response = try await BackendAPIClient.shared.correctEmailClassification(emailID: emailID, category: category)
            infoMessage = response.message
            removeEmail(emailID)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func removeEmail(_ emailID: Int) {
        emails.removeAll { $0.id == emailID }
        totalCount = max(0, totalCount - 1)
        expandedEmailIDs.remove(emailID)
    }

    private func toggleExpanded(_ emailID: Int) {
        if expandedEmailIDs.contains(emailID) {
            expandedEmailIDs.remove(emailID)
        } else {
            expandedEmailIDs.insert(emailID)
        }
    }
}

private struct ReviewEmailSheetSelection: Identifiable {
    let id: Int
}
