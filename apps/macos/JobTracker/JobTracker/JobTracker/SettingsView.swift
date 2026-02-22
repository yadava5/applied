import SwiftUI

private enum SyncAccountChoice: String, CaseIterable, Identifiable {
    case all
    case gmail
    case icloud

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all:
            return "All Accounts"
        case .gmail:
            return "Gmail"
        case .icloud:
            return "iCloud"
        }
    }

    var payload: [String]? {
        switch self {
        case .all:
            return nil
        case .gmail:
            return ["gmail"]
        case .icloud:
            return ["icloud"]
        }
    }
}

struct SettingsView: View {
    @Environment(AppModel.self) private var appModel

    @State private var authStatus: AuthStatusResponse?
    @State private var overview: ApplicationsOverviewResponse?
    @State private var isLoadingStatus = false
    @State private var isLoadingOverview = false
    @State private var errorMessage: String?
    @State private var syncMessage: String?
    @State private var isSyncing = false
    @State private var authActionMessage: String?
    @State private var liteModeEnabled = false
    @State private var liteModeSetFitAvailable = false
    @State private var isUpdatingLiteMode = false

    @State private var accountChoice: SyncAccountChoice = .all
    @State private var fullSync = false
    @State private var useSinceDate = false
    @State private var sinceDate = Date().addingTimeInterval(-30 * 24 * 60 * 60)

    @State private var gmailClientSecret = ""
    @State private var deleteEmailsOnDisconnect = false

    @State private var icloudEmail = ""
    @State private var icloudAppPassword = ""

    private let orderedStatuses = [
        "applied",
        "interviewing",
        "offered",
        "rejected",
        "accepted",
        "withdrawn",
        "ghosted"
    ]

    private var linkedCount: Int { overview?.emailsLinked ?? 0 }
    private var unlinkedCount: Int { overview?.emailsUnlinked ?? 0 }
    private var linkedPercentText: String {
        let total = linkedCount + unlinkedCount
        guard total > 0 else { return "0%" }
        let value = Int((Double(linkedCount) / Double(total) * 100).rounded())
        return "\(value)%"
    }

    private var classifierLayerSummary: String {
        guard let layers = appModel.health?.classifierStatus.activeLayers, !layers.isEmpty else {
            return "Initializing"
        }
        return layers
            .map { $0.replacingOccurrences(of: "_", with: " ").capitalized }
            .joined(separator: " + ")
    }

    var body: some View {
        Form {
            Section("Backend + Real-Time") {
                Text("WebSocket: \(appModel.websocketClient.state.rawValue.capitalized)")
                    .foregroundStyle(.secondary)
                Text("Auto-start service: \(appModel.backendLifecycle.serviceStatusText)")
                    .foregroundStyle(.secondary)
                Text(appModel.backendLifecycle.serviceHintText)
                    .font(.caption)
                    .foregroundStyle(.secondary)

                Toggle(
                    "Start Backend at Login",
                    isOn: Binding(
                        get: { appModel.backendLifecycle.autoStartEnabled },
                        set: { appModel.backendLifecycle.setAutoStart(enabled: $0) }
                    )
                )
                .disabled(!appModel.backendLifecycle.autoStartSupported)

                if let lifecycleError = appModel.backendLifecycle.lastErrorMessage {
                    Text(lifecycleError)
                        .font(.caption)
                        .foregroundStyle(JTTheme.danger)
                }

                if appModel.backendLifecycle.requiresSystemApproval {
                    Button("Open Login Items Settings") {
                        appModel.backendLifecycle.openLoginItemsSettings()
                    }
                    .buttonStyle(JTSecondaryButtonStyle())
                }
            }

            Section("Classifier") {
                Toggle(
                    "Lite Mode (Disable SetFit Layer)",
                    isOn: Binding(
                        get: { liteModeEnabled },
                        set: { newValue in
                            liteModeEnabled = newValue
                            Task { await updateLiteMode(enabled: newValue) }
                        }
                    )
                )
                .disabled(isUpdatingLiteMode)

                Text(
                    liteModeSetFitAvailable
                        ? "SetFit is currently active."
                        : "SetFit is disabled (lite mode or model unavailable)."
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }

            Section("Pipeline Overview") {
                if isLoadingOverview && overview == nil {
                    ProgressView("Loading pipeline metrics...")
                } else {
                    HStack(spacing: 18) {
                        metricsTile(title: "Linked", value: "\(linkedCount)", subtitle: linkedPercentText)
                        metricsTile(title: "Unlinked", value: "\(unlinkedCount)", subtitle: "Need linking")
                        metricsTile(
                            title: "Needs Review",
                            value: "\(appModel.needsReviewCount)",
                            subtitle: "Action queue"
                        )
                    }
                    .padding(.vertical, 2)

                    if let overview {
                        ForEach(orderedStatuses, id: \.self) { status in
                            HStack {
                                Text(status.humanizedFromSnakeCase)
                                    .foregroundStyle(.primary)
                                Spacer()
                                Text("\(overview.byStatus[status] ?? 0)")
                                    .font(.body.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                        }
                    } else {
                        Text("No pipeline data available yet.")
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section("System Status") {
                if let health = appModel.health {
                    HStack(spacing: 10) {
                        statusChip("API", isOn: health.status == "ok")
                        statusChip("Database", isOn: health.dbConnected)
                        statusChip("Gmail", isOn: health.gmailConnected)
                        statusChip("iCloud", isOn: health.icloudConnected)
                    }

                    Text("Classifier: \(classifierLayerSummary)")
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    if let lastSync = health.lastSync, !lastSync.isEmpty {
                        Text("Last sync: \(lastSync.asEasternTimestamp)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                } else {
                    Text("No system status yet.")
                        .foregroundStyle(.secondary)
                }

                Button("Refresh Pipeline + System Status") {
                    Task { await loadOverviewAndHealth() }
                }
                .buttonStyle(JTSecondaryButtonStyle())
                .disabled(isLoadingOverview)
            }

            Section("Connected Accounts") {
                if isLoadingStatus && authStatus == nil {
                    ProgressView("Checking status...")
                } else {
                    accountRow("Gmail", status: authStatus?.gmail)
                    accountRow("iCloud", status: authStatus?.icloud)
                }

                Button("Refresh Account Status") {
                    Task { await loadAuthStatus() }
                }
                .buttonStyle(JTSecondaryButtonStyle())
            }

            Section("Gmail Auth") {
                TextEditor(text: $gmailClientSecret)
                    .font(.system(.caption, design: .monospaced))
                    .frame(minHeight: 120)
                    .padding(8)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color.white.opacity(0.08))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 10)
                            .stroke(JTTheme.surfaceStroke, lineWidth: 1)
                    )

                HStack {
                    Button("Save Client Secret") {
                        Task { await saveGmailClientSecret() }
                    }
                    .buttonStyle(JTSecondaryButtonStyle())

                    Button("Authenticate Gmail") {
                        Task { await authenticateGmail() }
                    }
                    .buttonStyle(JTPrimaryButtonStyle())

                    Button("Disconnect Gmail") {
                        Task { await disconnectGmail() }
                    }
                    .buttonStyle(JTSecondaryButtonStyle())
                }
            }

            Section("iCloud Auth") {
                TextField("iCloud Email", text: $icloudEmail)

                SecureField("App-Specific Password", text: $icloudAppPassword)

                HStack {
                    Button("Connect iCloud") {
                        Task { await connectICloud() }
                    }
                    .buttonStyle(JTPrimaryButtonStyle())

                    Button("Disconnect iCloud") {
                        Task { await disconnectICloud() }
                    }
                    .buttonStyle(JTSecondaryButtonStyle())
                }
            }

            Section("Disconnect Options") {
                Toggle("Delete account emails on disconnect", isOn: $deleteEmailsOnDisconnect)
            }

            Section("Sync Controls") {
                Picker("Account", selection: $accountChoice) {
                    ForEach(SyncAccountChoice.allCases) { choice in
                        Text(choice.title).tag(choice)
                    }
                }

                Toggle("Full Sync", isOn: $fullSync)
                Toggle("Use Since Date", isOn: $useSinceDate)

                if useSinceDate {
                    DatePicker(
                        "Since",
                        selection: $sinceDate,
                        displayedComponents: .date
                    )
                }

                Button {
                    Task { await runSync() }
                } label: {
                    if isSyncing {
                        HStack {
                            ProgressView()
                                .controlSize(.small)
                            Text("Syncing...")
                        }
                    } else {
                        Text("Run Sync Now")
                    }
                }
                .disabled(isSyncing)
                .buttonStyle(JTPrimaryButtonStyle())
            }

            if let authActionMessage {
                Section("Auth Result") {
                    Text(authActionMessage)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            if let syncMessage {
                Section("Sync Result") {
                    Text(syncMessage)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }

            if let errorMessage {
                Section("Error") {
                    Text(errorMessage)
                        .font(.subheadline)
                        .foregroundStyle(JTTheme.danger)
                }
            }
        }
        .navigationTitle("Settings")
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
        .background(Color.clear)
        .jtPageBackdrop()
        .task {
            appModel.backendLifecycle.refreshServiceStatus()
            await loadAuthStatus()
            await loadLiteModeState()
            await loadOverviewAndHealth()
        }
    }

    @ViewBuilder
    private func metricsTile(title: String, value: String, subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(value)
                .font(.title3.monospacedDigit().weight(.bold))
            Text(subtitle)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func statusChip(_ title: String, isOn: Bool) -> some View {
        HStack(spacing: 6) {
            Circle()
                .fill(isOn ? JTTheme.success : JTTheme.danger)
                .frame(width: 8, height: 8)
            Text(title)
                .font(.caption.weight(.medium))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.ultraThinMaterial, in: Capsule())
        .overlay(Capsule().stroke(JTTheme.surfaceStroke.opacity(0.7), lineWidth: 1))
    }

    @ViewBuilder
    private func accountRow(_ title: String, status: AccountStatus?) -> some View {
        HStack {
            Text(title)
            Spacer()
            if let status {
                if status.connected {
                    Text(status.email ?? "Connected")
                        .foregroundStyle(JTTheme.success)
                } else {
                    Text("Not connected")
                    .foregroundStyle(.secondary)
                }
            } else {
                Text("Unknown")
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func loadAuthStatus() async {
        guard await ensureBackendReady() else { return }
        isLoadingStatus = true
        errorMessage = nil
        do {
            authStatus = try await BackendAPIClient.shared.fetchAuthStatus()
            appModel.authStatus = authStatus
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoadingStatus = false
    }

    private func runSync() async {
        guard await ensureBackendReady() else { return }
        isSyncing = true
        errorMessage = nil
        syncMessage = nil

        do {
            let result = try await BackendAPIClient.shared.triggerSync(
                accounts: accountChoice.payload,
                sinceDate: useSinceDate ? sinceDate : nil,
                fullSync: fullSync
            )

            let accountLabel = result.accountsSynced.isEmpty
                ? "none"
                : result.accountsSynced.joined(separator: ", ")
            if result.success {
                syncMessage = "Synced \(result.emailsSaved) emails (\(result.emailsSkipped) skipped) for: \(accountLabel)."
            } else {
                syncMessage = "Sync finished with errors: \(result.errors.joined(separator: "; "))"
            }
            await appModel.refreshAllStatus()
            await loadOverviewAndHealth()
        } catch {
            errorMessage = error.localizedDescription
        }

        isSyncing = false
    }

    private func loadLiteModeState() async {
        guard await ensureBackendReady() else { return }
        do {
            let state = try await BackendAPIClient.shared.fetchLiteModeState()
            liteModeEnabled = state.enabled
            liteModeSetFitAvailable = state.setfitAvailable
        } catch {
            // Do not fail settings screen over optional classifier metadata.
        }
    }

    private func updateLiteMode(enabled: Bool) async {
        guard await ensureBackendReady() else {
            liteModeEnabled.toggle()
            return
        }
        isUpdatingLiteMode = true
        defer { isUpdatingLiteMode = false }

        do {
            let state = try await BackendAPIClient.shared.setLiteMode(enabled: enabled)
            liteModeEnabled = state.enabled
            liteModeSetFitAvailable = state.setfitAvailable
            authActionMessage = state.enabled
                ? "Lite mode enabled (rules + embeddings only)."
                : "Lite mode disabled (SetFit re-enabled when available)."
        } catch {
            liteModeEnabled.toggle()
            errorMessage = error.localizedDescription
        }
    }

    private func saveGmailClientSecret() async {
        guard await ensureBackendReady() else { return }
        errorMessage = nil
        authActionMessage = nil

        do {
            let response = try await BackendAPIClient.shared.setGmailClientSecret(gmailClientSecret)
            authActionMessage = response.message
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func authenticateGmail() async {
        guard await ensureBackendReady() else { return }
        errorMessage = nil
        authActionMessage = nil
        do {
            let response = try await BackendAPIClient.shared.authenticateGmail()
            authActionMessage = response.message
            await loadAuthStatus()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func disconnectGmail() async {
        guard await ensureBackendReady() else { return }
        errorMessage = nil
        authActionMessage = nil
        do {
            let response = try await BackendAPIClient.shared.disconnectGmail(
                deleteEmails: deleteEmailsOnDisconnect
            )
            authActionMessage = response.message
            await loadAuthStatus()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func connectICloud() async {
        guard await ensureBackendReady() else { return }
        errorMessage = nil
        authActionMessage = nil
        do {
            let response = try await BackendAPIClient.shared.connectICloud(
                email: icloudEmail,
                appPassword: icloudAppPassword
            )
            authActionMessage = response.message
            await loadAuthStatus()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func disconnectICloud() async {
        guard await ensureBackendReady() else { return }
        errorMessage = nil
        authActionMessage = nil
        do {
            let response = try await BackendAPIClient.shared.disconnectICloud(
                deleteEmails: deleteEmailsOnDisconnect
            )
            authActionMessage = response.message
            await loadAuthStatus()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func ensureBackendReady() async -> Bool {
        if await appModel.awaitBackendReady(maxWaitSeconds: 20) {
            return true
        }
        errorMessage = appModel.backendStartupError ?? "Backend is unavailable."
        return false
    }

    private func loadOverviewAndHealth() async {
        guard await ensureBackendReady() else { return }
        isLoadingOverview = true
        defer { isLoadingOverview = false }

        do {
            async let healthRequest = BackendAPIClient.shared.fetchHealth()
            async let overviewRequest = BackendAPIClient.shared.fetchApplicationsOverview()
            appModel.health = try await healthRequest
            overview = try await overviewRequest
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
