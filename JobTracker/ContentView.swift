import SwiftUI

private enum ApplicationsStatusFilter: String, CaseIterable, Identifiable {
    case all
    case applied
    case interviewing
    case offered
    case rejected
    case accepted
    case withdrawn
    case ghosted

    var id: String { rawValue }
    var title: String { self == .all ? "All Statuses" : rawValue.humanizedFromSnakeCase }
    var apiValue: String? { self == .all ? nil : rawValue }
}

private enum ApplicationsSortOption: String, CaseIterable, Identifiable {
    case newestFirst
    case companyAZ
    case companyZA
    case status
    case emailCountDesc

    var id: String { rawValue }
    var title: String {
        switch self {
        case .newestFirst:
            return "Newest First"
        case .companyAZ:
            return "Company A-Z"
        case .companyZA:
            return "Company Z-A"
        case .status:
            return "Status"
        case .emailCountDesc:
            return "Most Emails"
        }
    }
}

private struct ApplicationSheetSelection: Identifiable {
    let id: Int
}

// MARK: - Applications List

struct ApplicationsView: View {
    @State private var applications: [ApplicationSummary] = []
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var searchText = ""
    @State private var statusFilter: ApplicationsStatusFilter = .all
    @State private var sortOption: ApplicationsSortOption = .newestFirst
    @State private var applicationSheetSelection: ApplicationSheetSelection?

    private var displayedApplications: [ApplicationSummary] {
        var items = applications

        switch sortOption {
        case .newestFirst:
            // Backend already returns newest-first.
            break
        case .companyAZ:
            items.sort { $0.company.localizedCaseInsensitiveCompare($1.company) == .orderedAscending }
        case .companyZA:
            items.sort { $0.company.localizedCaseInsensitiveCompare($1.company) == .orderedDescending }
        case .status:
            items.sort { $0.status.localizedCaseInsensitiveCompare($1.status) == .orderedAscending }
        case .emailCountDesc:
            items.sort {
                if $0.emailCount == $1.emailCount {
                    return $0.company.localizedCaseInsensitiveCompare($1.company) == .orderedAscending
                }
                return $0.emailCount > $1.emailCount
            }
        }

        return items
    }

    var body: some View {
        Group {
            if isLoading && applications.isEmpty {
                ProgressView("Loading applications…")
            } else if let errorMessage {
                VStack(spacing: 8) {
                    Text("Error")
                        .font(.headline)
                    Text(errorMessage)
                        .font(.subheadline)
                        .multilineTextAlignment(.center)
                    Button("Retry") {
                        Task { await loadApplications() }
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding()
            } else if displayedApplications.isEmpty {
                Text("No applications matched your filters.")
                    .foregroundStyle(.secondary)
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(displayedApplications) { app in
                            Button {
                                applicationSheetSelection = ApplicationSheetSelection(id: app.id)
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(app.company)
                                            .font(.headline)
                                        Text(app.position)
                                            .font(.subheadline)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    VStack(alignment: .trailing, spacing: 4) {
                                        Text(app.status.humanizedFromSnakeCase)
                                            .font(.caption)
                                            .padding(.horizontal, 8)
                                            .padding(.vertical, 4)
                                            .background(.thinMaterial, in: Capsule())
                                        Text("\(app.emailCount) emails")
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                .padding(.vertical, 10)
                                .padding(.horizontal, 12)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)

                            Divider()
                                .padding(.leading, 12)
                        }
                    }
                }
            }
        }
        .navigationTitle("Applications")
        .toolbar {
            ToolbarItemGroup(placement: .automatic) {
                Menu("Filter") {
                    Picker("Status", selection: $statusFilter) {
                        ForEach(ApplicationsStatusFilter.allCases) { status in
                            Text(status.title).tag(status)
                        }
                    }
                    Picker("Sort", selection: $sortOption) {
                        ForEach(ApplicationsSortOption.allCases) { option in
                            Text(option.title).tag(option)
                        }
                    }
                }

                Button("Apply") {
                    Task { await loadApplications() }
                }
                .disabled(isLoading)

                Button("Refresh") {
                    Task { await loadApplications() }
                }
                .disabled(isLoading)

                TextField("Search company or role", text: $searchText)
                    .textFieldStyle(.roundedBorder)
                    .frame(minWidth: 220, idealWidth: 260)
                    .onSubmit {
                        Task { await loadApplications() }
                    }
                    .disabled(isLoading)
            }
        }
        .onAppear {
            guard applications.isEmpty, !isLoading else { return }
            Task { await loadApplications() }
        }
        .sheet(item: $applicationSheetSelection) { selection in
            NavigationStack {
                ApplicationDetailView(applicationId: selection.id)
                    .toolbar {
                        ToolbarItem(placement: .cancellationAction) {
                            Button("Close") {
                                applicationSheetSelection = nil
                            }
                            .keyboardShortcut(.cancelAction)
                        }
                    }
            }
            .frame(minWidth: 760, minHeight: 620)
        }
    }

    private func loadApplications() async {
        if isLoading {
            return
        }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }

        let trimmedSearch = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        let maxAttempts = 4

        for attempt in 1...maxAttempts {
            do {
                let response = try await BackendAPIClient.shared.fetchApplications(
                    page: 1,
                    pageSize: 100,
                    status: statusFilter.apiValue,
                    search: trimmedSearch.isEmpty ? nil : trimmedSearch
                )
                applications = response.applications
                errorMessage = nil
                return
            } catch {
                if isCancellationError(error) {
                    if attempt < maxAttempts {
                        try? await Task.sleep(nanoseconds: 120_000_000)
                    }
                    continue
                }

                if attempt == maxAttempts || !isTransientBackendError(error) {
                    errorMessage = error.localizedDescription
                    return
                }
                try? await Task.sleep(nanoseconds: 250_000_000)
            }
        }
    }

    private func isCancellationError(_ error: Error) -> Bool {
        if error is CancellationError {
            return true
        }
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled {
            return true
        }
        return nsError.localizedDescription.lowercased() == "cancelled"
    }

    private func isTransientBackendError(_ error: Error) -> Bool {
        if let urlError = error as? URLError {
            switch urlError.code {
            case .cannotFindHost, .cannotConnectToHost, .networkConnectionLost, .timedOut, .notConnectedToInternet:
                return true
            default:
                break
            }
        }

        let description = error.localizedDescription.lowercased()
        return description.contains("could not connect") || description.contains("connection refused")
    }
}

// MARK: - Application Detail
private struct EmailSheetSelection: Identifiable {
    let id: Int
}

struct ApplicationDetailView: View {
    let applicationId: Int

    @Environment(\.dismiss) private var dismiss
    @State private var detail: ApplicationDetail?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var selectedStatus = "applied"
    @State private var notesDraft = ""
    @State private var isSavingStatus = false
    @State private var isSavingNotes = false
    @State private var isMarkingNotJob = false
    @State private var statusMessage: String?
    @State private var actionError: String?
    @State private var emailSheetSelection: EmailSheetSelection?

    private let statusOptions = [
        "applied",
        "interviewing",
        "offered",
        "rejected",
        "accepted",
        "withdrawn",
        "ghosted",
    ]

    private var uniqueContacts: [String] {
        guard let detail else { return [] }
        let contacts = detail.emails.compactMap { email -> String? in
            guard let sender = email.sender, !sender.isEmpty else { return nil }
            return sender
        }
        return Array(Set(contacts)).sorted()
    }

    private var timelineEmails: [ApplicationEmail] {
        guard let detail else { return [] }
        return detail.emails.sorted { lhs, rhs in
            guard
                let leftDate = parseISODate(lhs.receivedAt),
                let rightDate = parseISODate(rhs.receivedAt)
            else {
                return (lhs.receivedAt ?? "") < (rhs.receivedAt ?? "")
            }
            return leftDate < rightDate
        }
    }

    var body: some View {
        Group {
            if isLoading {
                ProgressView("Loading…")
            } else if let errorMessage {
                Text(errorMessage)
                    .foregroundStyle(.red)
                    .padding()
            } else if let detail {
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        sectionCard("Application") {
                            Text(detail.company)
                                .font(.headline)
                            Text(detail.position)
                                .font(.subheadline)
                                .foregroundStyle(.secondary)

                            Picker("Status", selection: $selectedStatus) {
                                ForEach(statusOptions, id: \.self) { status in
                                    Text(status.humanizedFromSnakeCase).tag(status)
                                }
                            }
                            .pickerStyle(.menu)

                            Button {
                                Task { await updateStatus() }
                            } label: {
                                if isSavingStatus {
                                    ProgressView()
                                } else {
                                    Text("Save Status")
                                }
                            }
                            .disabled(isSavingStatus || selectedStatus == detail.status)

                            VStack(alignment: .leading, spacing: 6) {
                                Text("Notes")
                                    .font(.subheadline.weight(.medium))
                                TextField("Add notes...", text: $notesDraft, axis: .vertical)
                                    .lineLimit(4...12)
                                    .textFieldStyle(.plain)
                                    .padding(8)
                                    .background(
                                        RoundedRectangle(cornerRadius: 8)
                                            .fill(.thinMaterial)
                                    )
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 8)
                                            .stroke(Color.secondary.opacity(0.25))
                                    )

                                Button {
                                    Task { await saveNotes() }
                                } label: {
                                    if isSavingNotes {
                                        ProgressView()
                                    } else {
                                        Text("Save Notes")
                                    }
                                }
                                .disabled(isSavingNotes || notesDraft == (detail.notes ?? ""))
                            }

                            if let statusMessage {
                                Text(statusMessage)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }

                            if let applied = detail.appliedDate {
                                Text("Applied: \(applied)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }

                        if !uniqueContacts.isEmpty {
                            sectionCard("Contacts") {
                                ForEach(uniqueContacts, id: \.self) { contact in
                                    Text(contact)
                                        .font(.subheadline)
                                }
                            }
                        }

                        if !timelineEmails.isEmpty {
                            sectionCard("Timeline") {
                                ForEach(timelineEmails) { email in
                                    Button {
                                        emailSheetSelection = EmailSheetSelection(id: email.id)
                                    } label: {
                                        VStack(alignment: .leading, spacing: 4) {
                                            Text(email.receivedAt?.asEasternTimestamp ?? "Unknown time")
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                            Text(email.classification?.humanizedFromSnakeCase ?? "Unclassified")
                                                .font(.caption2)
                                                .padding(.horizontal, 6)
                                                .padding(.vertical, 2)
                                                .background(.thinMaterial, in: Capsule())
                                            Text(email.subject ?? "(No subject)")
                                                .font(.subheadline)

                                            Label("View Full Email", systemImage: "envelope.open")
                                                .font(.caption)
                                                .foregroundStyle(.blue)
                                        }
                                        .padding(.vertical, 2)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }

                        sectionCard("Emails (\(detail.emailCount))") {
                            Text("Each email row can open the full rich email (HTML + images when available).")
                                .font(.caption)
                                .foregroundStyle(.secondary)

                            ForEach(detail.emails) { email in
                                Button {
                                    emailSheetSelection = EmailSheetSelection(id: email.id)
                                } label: {
                                    VStack(alignment: .leading, spacing: 8) {
                                        Text(email.subject ?? "(No subject)")
                                            .font(.subheadline)
                                        if let sender = email.sender {
                                            Text(sender)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                        if let receivedAt = email.receivedAt {
                                            Text(receivedAt.asEasternTimestamp)
                                                .font(.caption2)
                                                .foregroundStyle(.secondary)
                                        }
                                        HStack(spacing: 8) {
                                            if let classification = email.classification {
                                                Text(classification.humanizedFromSnakeCase)
                                                    .font(.caption2)
                                                    .padding(.horizontal, 6)
                                                    .padding(.vertical, 2)
                                                    .background(.thinMaterial, in: Capsule())
                                            }
                                            if let confidence = email.confidence {
                                                Text("\(Int(confidence * 100))%")
                                                    .font(.caption2)
                                                    .foregroundStyle(.secondary)
                                            }
                                            Label("View Full Email", systemImage: "envelope.open")
                                                .font(.caption2)
                                                .foregroundStyle(.blue)
                                        }

                                        if let snippet = email.bodySnippet, !snippet.isEmpty {
                                            Text(snippet)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                                .lineLimit(4)
                                        }
                                    }
                                    .padding(.vertical, 4)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                .buttonStyle(.plain)
                            }
                        }

                        sectionCard("Actions") {
                            if let actionError {
                                Text(actionError)
                                    .font(.caption)
                                    .foregroundStyle(.red)
                            }

                            Button(role: .destructive) {
                                Task { await markNotJobPosting() }
                            } label: {
                                if isMarkingNotJob {
                                    ProgressView()
                                } else {
                                    Text("Mark as Not Job Posting")
                                }
                            }
                            .disabled(isMarkingNotJob)
                        }
                    }
                    .padding(16)
                }
            } else {
                Text("No data")
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle("Details")
        .task {
            await loadDetail()
        }
        .sheet(item: $emailSheetSelection) { selection in
            NavigationStack {
                EmailDetailView(emailID: selection.id, showsCloseButton: true)
            }
            .frame(minWidth: 760, minHeight: 620)
        }
    }

    private func loadDetail() async {
        isLoading = true
        errorMessage = nil
        actionError = nil
        do {
            let loaded = try await BackendAPIClient.shared.fetchApplicationDetail(id: applicationId)
            detail = loaded
            selectedStatus = loaded.status
            notesDraft = loaded.notes ?? ""
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func updateStatus() async {
        guard let detail, !isSavingStatus else { return }
        guard selectedStatus != detail.status else { return }

        isSavingStatus = true
        actionError = nil
        statusMessage = nil

        do {
            _ = try await BackendAPIClient.shared.updateApplicationStatus(
                id: applicationId,
                status: selectedStatus
            )
            statusMessage = "Status updated to \(selectedStatus.humanizedFromSnakeCase)."
            await loadDetail()
        } catch {
            actionError = error.localizedDescription
        }

        isSavingStatus = false
    }

    private func saveNotes() async {
        guard let detail, !isSavingNotes else { return }
        guard notesDraft != (detail.notes ?? "") else { return }

        isSavingNotes = true
        actionError = nil
        statusMessage = nil

        do {
            _ = try await BackendAPIClient.shared.updateApplicationNotes(
                id: applicationId,
                notes: notesDraft
            )
            statusMessage = "Notes saved."
            await loadDetail()
        } catch {
            actionError = error.localizedDescription
        }

        isSavingNotes = false
    }

    private func markNotJobPosting() async {
        guard !isMarkingNotJob else { return }
        isMarkingNotJob = true
        actionError = nil
        statusMessage = nil

        do {
            _ = try await BackendAPIClient.shared.markApplicationNotJobPosting(id: applicationId)
            await MainActor.run {
                dismiss()
            }
        } catch {
            actionError = error.localizedDescription
        }

        isMarkingNotJob = false
    }

    private func parseISODate(_ value: String?) -> Date? {
        guard let value else { return nil }

        let formatterWithFractional = ISO8601DateFormatter()
        formatterWithFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = formatterWithFractional.date(from: value) {
            return parsed
        }

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }

    @ViewBuilder
    private func sectionCard<Content: View>(
        _ title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.headline)
            content()
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(.thinMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.secondary.opacity(0.15))
        )
    }
}
