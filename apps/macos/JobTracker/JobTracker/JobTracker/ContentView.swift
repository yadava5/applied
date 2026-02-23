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

private enum ApplicationsLayoutOption: String, CaseIterable, Identifiable {
    case featureCards
    case compactRows
    case statusBoard

    static let defaultsKey = "applications.layout.option"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .featureCards:
            return "Feature Cards"
        case .compactRows:
            return "Compact Rows"
        case .statusBoard:
            return "Status Board"
        }
    }

    static var persistedDefault: ApplicationsLayoutOption {
        guard
            let rawValue = UserDefaults.standard.string(forKey: defaultsKey),
            let value = ApplicationsLayoutOption(rawValue: rawValue)
        else {
            return .featureCards
        }
        return value
    }
}

private struct ApplicationSheetSelection: Identifiable {
    let id: Int
}

// MARK: - Applications List

struct ApplicationsView: View {
    @Environment(AppModel.self) private var appModel
    @State private var applications: [ApplicationSummary] = []
    @State private var displayedApplications: [ApplicationSummary] = []
    @State private var boardApplicationsByStatus: [String: [ApplicationSummary]] = [:]
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var searchText = ""
    @State private var statusFilter: ApplicationsStatusFilter = .all
    @State private var sortOption: ApplicationsSortOption = .newestFirst
    @State private var layoutOption: ApplicationsLayoutOption = .persistedDefault
    @State private var applicationSheetSelection: ApplicationSheetSelection?

    private let boardStatuses = [
        "applied",
        "interviewing",
        "offered",
        "rejected",
        "accepted",
        "withdrawn",
        "ghosted",
    ]

    private var hasActiveFilters: Bool {
        !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || statusFilter != .all
    }

    var body: some View {
        Group {
            if isLoading && applications.isEmpty {
                ProgressView("Loading applications…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let errorMessage {
                VStack(spacing: 8) {
                    Text("Error")
                        .font(.headline)
                    Text(errorMessage)
                        .font(.subheadline)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(JTTheme.danger)
                    Button("Retry") {
                        Task { await loadApplications() }
                    }
                    .buttonStyle(JTPrimaryButtonStyle())
                }
                .padding()
                .jtCard()
            } else if displayedApplications.isEmpty {
                VStack(spacing: 8) {
                    Text(hasActiveFilters ? "No applications matched your filters." : "No applications yet.")
                        .font(.headline)
                    Text(
                        hasActiveFilters
                            ? "Try clearing filters or changing the search term."
                            : "Connect an account in Settings, run sync, and applications will appear here."
                    )
                    .font(.subheadline)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)

                    if hasActiveFilters {
                        Button("Clear Filters") {
                            searchText = ""
                            statusFilter = .all
                            Task { await loadApplications() }
                        }
                        .buttonStyle(JTSecondaryButtonStyle())
                    }
                }
                .padding()
                .jtCard()
            } else {
                switch layoutOption {
                case .featureCards:
                    featureCardsLayout
                case .compactRows:
                    compactRowsLayout
                case .statusBoard:
                    statusBoardLayout
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

                Menu("Layout") {
                    ForEach(ApplicationsLayoutOption.allCases) { option in
                        Button {
                            layoutOption = option
                        } label: {
                            if option == layoutOption {
                                Label(option.title, systemImage: "checkmark")
                            } else {
                                Text(option.title)
                            }
                        }
                    }
                }

                Button("Apply") {
                    Task { await loadApplications() }
                }
                .disabled(isLoading)
                .buttonStyle(.bordered)

                Button("Refresh") {
                    Task { await loadApplications() }
                }
                .disabled(isLoading)
                .buttonStyle(.bordered)

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
            if displayedApplications.isEmpty, !applications.isEmpty {
                rebuildDisplayIndex(for: applications)
            }
            guard applications.isEmpty, !isLoading else { return }
            Task { await loadApplications() }
        }
        .onChange(of: layoutOption) { _, newValue in
            UserDefaults.standard.set(newValue.rawValue, forKey: ApplicationsLayoutOption.defaultsKey)
        }
        .onChange(of: sortOption) { _, _ in
            rebuildDisplayIndex(for: applications)
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

    private var featureCardsLayout: some View {
        ScrollView {
            LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 12)], spacing: 12) {
                ForEach(displayedApplications) { app in
                    Button {
                        applicationSheetSelection = ApplicationSheetSelection(id: app.id)
                    } label: {
                        VStack(alignment: .leading, spacing: 10) {
                            HStack(spacing: 10) {
                                Image(systemName: statusIcon(for: app.status))
                                    .font(.title3)
                                    .foregroundStyle(statusTone(for: app.status))
                                    .frame(width: 28)

                                VStack(alignment: .leading, spacing: 2) {
                                    Text(app.company)
                                        .font(.headline)
                                        .lineLimit(1)
                                    Text(app.position)
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(2)
                                }

                                Spacer(minLength: 0)
                            }

                            HStack(spacing: 8) {
                                Text(app.status.humanizedFromSnakeCase)
                                    .font(.caption.weight(.semibold))
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 5)
                                    .background(statusTone(for: app.status).opacity(0.18), in: Capsule())
                                    .overlay(
                                        Capsule().stroke(statusTone(for: app.status).opacity(0.55), lineWidth: 1)
                                    )
                                Spacer()
                                Label("\(app.emailCount)", systemImage: "envelope.fill")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(14)
                        .background(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .fill(
                                    LinearGradient(
                                        colors: [
                                            statusTone(for: app.status).opacity(0.14),
                                            Color.white.opacity(0.035),
                                        ],
                                        startPoint: .topLeading,
                                        endPoint: .bottomTrailing
                                    )
                                )
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .stroke(JTTheme.surfaceStroke.opacity(0.45), lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
    }

    private var compactRowsLayout: some View {
        ScrollView {
            LazyVStack(spacing: 8) {
                ForEach(displayedApplications) { app in
                    Button {
                        applicationSheetSelection = ApplicationSheetSelection(id: app.id)
                    } label: {
                        HStack(spacing: 12) {
                            Circle()
                                .fill(statusTone(for: app.status).opacity(0.85))
                                .frame(width: 10, height: 10)

                            VStack(alignment: .leading, spacing: 2) {
                                Text(app.company)
                                    .font(.subheadline.weight(.semibold))
                                Text(app.position)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }

                            Spacer(minLength: 8)

                            Text(app.status.humanizedFromSnakeCase)
                                .font(.caption2)
                                .foregroundStyle(.secondary)

                            Text("\(app.emailCount)")
                                .font(.caption.monospacedDigit())
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(Color.white.opacity(0.09), in: Capsule())
                                .overlay(Capsule().stroke(JTTheme.surfaceStroke, lineWidth: 1))
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 10)
                        .padding(.horizontal, 12)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(Color.white.opacity(0.065))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .stroke(JTTheme.surfaceStroke.opacity(0.42), lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
    }

    private var statusBoardLayout: some View {
        ScrollView(.horizontal) {
            HStack(alignment: .top, spacing: 12) {
                ForEach(boardStatuses, id: \.self) { status in
                    statusColumn(status: status)
                        .frame(width: 280)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
        }
    }

    @ViewBuilder
    private func statusColumn(status: String) -> some View {
        let items = boardApplicationsByStatus[status] ?? []
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label(status.humanizedFromSnakeCase, systemImage: statusIcon(for: status))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(statusTone(for: status))
                Spacer()
                Text("\(items.count)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }

            if items.isEmpty {
                Text("No applications")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(items) { app in
                    Button {
                        applicationSheetSelection = ApplicationSheetSelection(id: app.id)
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(app.company)
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                            Text(app.position)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                            HStack {
                                Spacer()
                                Label("\(app.emailCount)", systemImage: "envelope")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                        .background(
                            RoundedRectangle(cornerRadius: 10)
                                .fill(statusTone(for: status).opacity(0.12))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 10)
                                .stroke(statusTone(for: status).opacity(0.32), lineWidth: 1)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.white.opacity(0.055))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(JTTheme.surfaceStroke.opacity(0.38), lineWidth: 1)
        )
    }

    private func sortedApplications(from items: [ApplicationSummary]) -> [ApplicationSummary] {
        var sorted = items

        switch sortOption {
        case .newestFirst:
            // Backend already returns newest-first.
            break
        case .companyAZ:
            sorted.sort { $0.company.localizedCaseInsensitiveCompare($1.company) == .orderedAscending }
        case .companyZA:
            sorted.sort { $0.company.localizedCaseInsensitiveCompare($1.company) == .orderedDescending }
        case .status:
            sorted.sort {
                if $0.status == $1.status {
                    return $0.company.localizedCaseInsensitiveCompare($1.company) == .orderedAscending
                }
                return $0.status.localizedCaseInsensitiveCompare($1.status) == .orderedAscending
            }
        case .emailCountDesc:
            sorted.sort {
                if $0.emailCount == $1.emailCount {
                    return $0.company.localizedCaseInsensitiveCompare($1.company) == .orderedAscending
                }
                return $0.emailCount > $1.emailCount
            }
        }

        return sorted
    }

    private func rebuildDisplayIndex(for items: [ApplicationSummary]) {
        let sorted = sortedApplications(from: items)
        displayedApplications = sorted
        boardApplicationsByStatus = Dictionary(grouping: sorted, by: \.status)
    }

    private func statusIcon(for status: String) -> String {
        switch status {
        case "applied":
            return "paperplane.fill"
        case "interviewing":
            return "person.2.fill"
        case "offered":
            return "sparkles"
        case "rejected":
            return "xmark.octagon.fill"
        case "accepted":
            return "checkmark.seal.fill"
        case "withdrawn":
            return "arrow.uturn.backward.circle.fill"
        case "ghosted":
            return "moon.stars.fill"
        default:
            return "briefcase.fill"
        }
    }

    private func statusTone(for status: String) -> Color {
        switch status {
        case "applied":
            return JTTheme.accentPrimary
        case "interviewing":
            return JTTheme.warning
        case "offered":
            return JTTheme.success
        case "rejected":
            return JTTheme.danger
        case "accepted":
            return JTTheme.success
        case "withdrawn":
            return JTTheme.accentSecondary
        case "ghosted":
            return Color.gray
        default:
            return JTTheme.accentPrimary
        }
    }

    private func loadApplications() async {
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            errorMessage = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
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
                rebuildDisplayIndex(for: response.applications)
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
    @Environment(AppModel.self) private var appModel
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
                    .foregroundStyle(JTTheme.danger)
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
                            .buttonStyle(JTSecondaryButtonStyle())
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
                                .buttonStyle(JTSecondaryButtonStyle())
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
                                                .background(Color.white.opacity(0.12), in: Capsule())
                                                .overlay(Capsule().stroke(JTTheme.surfaceStroke, lineWidth: 1))
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
                                                    .background(Color.white.opacity(0.12), in: Capsule())
                                                    .overlay(Capsule().stroke(JTTheme.surfaceStroke, lineWidth: 1))
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
                                    .foregroundStyle(JTTheme.danger)
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
        .jtPageBackdrop()
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
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            errorMessage = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
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
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            actionError = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
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
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            actionError = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
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
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            actionError = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
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
        .jtCard(cornerRadius: 14, contentPadding: 12)
    }
}
