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
    @EnvironmentObject private var appModel: AppModel

    @State private var authStatus: AuthStatusResponse?
    @State private var isLoadingStatus = false
    @State private var errorMessage: String?
    @State private var syncMessage: String?
    @State private var isSyncing = false
    @State private var authActionMessage: String?

    @State private var accountChoice: SyncAccountChoice = .all
    @State private var fullSync = false
    @State private var useSinceDate = false
    @State private var sinceDate = Date().addingTimeInterval(-30 * 24 * 60 * 60)

    @State private var gmailClientSecret = ""
    @State private var deleteEmailsOnDisconnect = false

    @State private var icloudEmail = ""
    @State private var icloudAppPassword = ""

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
                        .foregroundStyle(.red)
                }

                if appModel.backendLifecycle.requiresSystemApproval {
                    Button("Open Login Items Settings") {
                        appModel.backendLifecycle.openLoginItemsSettings()
                    }
                    .buttonStyle(.bordered)
                }
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
            }

            Section("Gmail Auth") {
                TextEditor(text: $gmailClientSecret)
                    .font(.system(.caption, design: .monospaced))
                    .frame(minHeight: 120)
                    .border(Color.secondary.opacity(0.2))

                HStack {
                    Button("Save Client Secret") {
                        Task { await saveGmailClientSecret() }
                    }
                    .buttonStyle(.bordered)

                    Button("Authenticate Gmail") {
                        Task { await authenticateGmail() }
                    }
                    .buttonStyle(.borderedProminent)

                    Button("Disconnect Gmail") {
                        Task { await disconnectGmail() }
                    }
                    .buttonStyle(.bordered)
                }
            }

            Section("iCloud Auth") {
                TextField("iCloud Email", text: $icloudEmail)

                SecureField("App-Specific Password", text: $icloudAppPassword)

                HStack {
                    Button("Connect iCloud") {
                        Task { await connectICloud() }
                    }
                    .buttonStyle(.borderedProminent)

                    Button("Disconnect iCloud") {
                        Task { await disconnectICloud() }
                    }
                    .buttonStyle(.bordered)
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
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("Settings")
        .task {
            appModel.backendLifecycle.refreshServiceStatus()
            await loadAuthStatus()
        }
    }

    @ViewBuilder
    private func accountRow(_ title: String, status: AccountStatus?) -> some View {
        HStack {
            Text(title)
            Spacer()
            if let status {
                if status.connected {
                    Text(status.email ?? "Connected")
                        .foregroundStyle(.green)
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
        } catch {
            errorMessage = error.localizedDescription
        }

        isSyncing = false
    }

    private func saveGmailClientSecret() async {
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
}
