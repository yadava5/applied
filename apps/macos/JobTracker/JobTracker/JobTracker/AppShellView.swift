import SwiftUI

private enum AppSection: String, CaseIterable, Hashable, Identifiable {
    case dashboard
    case applications
    case emails
    case settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .dashboard:
            return "Dashboard"
        case .applications:
            return "Applications"
        case .emails:
            return "Emails"
        case .settings:
            return "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .dashboard:
            return "rectangle.grid.2x2"
        case .applications:
            return "briefcase"
        case .emails:
            return "envelope"
        case .settings:
            return "gearshape"
        }
    }
}

struct AppShellView: View {
    @Environment(AppModel.self) private var appModel
    @AppStorage("onboarding.completed.v1") private var onboardingCompleted = false

    @State private var selection: AppSection? = .dashboard
    @State private var showOnboarding = false

    var body: some View {
        ZStack {
            JTBackdropView()
                .ignoresSafeArea()

            NavigationSplitView {
                List(AppSection.allCases, selection: $selection) { section in
                    let isSelected = selection == section

                    HStack(spacing: 10) {
                        Image(systemName: section.systemImage)
                            .font(.system(size: 14, weight: .semibold))
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(isSelected ? .white : JTTheme.accentPrimary)
                            .frame(width: 18)

                        Text(section.title)
                            .font(.system(.body, design: .rounded).weight(.semibold))
                            .foregroundStyle(isSelected ? .white : .primary)

                        Spacer(minLength: 6)

                        if isSelected {
                            Image(systemName: "chevron.right")
                                .font(.caption2.weight(.bold))
                                .foregroundStyle(.white.opacity(0.85))
                        }
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(isSelected ? AnyShapeStyle(.thinMaterial) : AnyShapeStyle(Color.clear))
                    }
                    .background {
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(
                                isSelected
                                    ? AnyShapeStyle(
                                        LinearGradient(
                                            colors: [
                                                JTTheme.accentPrimary.opacity(0.45),
                                                JTTheme.accentSecondary.opacity(0.35)
                                            ],
                                            startPoint: .topLeading,
                                            endPoint: .bottomTrailing
                                        )
                                    )
                                    : AnyShapeStyle(Color.clear)
                            )
                    }
                    .overlay(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .stroke(
                                isSelected ? Color.white.opacity(0.38) : JTTheme.surfaceStroke.opacity(0.24),
                                lineWidth: 1
                            )
                    )
                    .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .tag(section)
                    .listRowInsets(EdgeInsets(top: 3, leading: 8, bottom: 3, trailing: 8))
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
                }
                .listStyle(.sidebar)
                .scrollContentBackground(.hidden)
                .background(Color.clear)
                .navigationTitle("JobTracker")
            } detail: {
                switch selection ?? .dashboard {
                case .dashboard:
                    DashboardView()
                case .applications:
                    ApplicationsView()
                case .emails:
                    EmailsView()
                case .settings:
                    SettingsView()
                }
            }
        }
        .task {
            await appModel.refreshAllStatus()
            syncOnboardingPresentation()
        }
        .onChange(of: appModel.health?.lastSync) { _, _ in
            syncOnboardingPresentation()
        }
        .onChange(of: appModel.authStatus?.gmail.connected ?? false) { _, _ in
            syncOnboardingPresentation()
        }
        .onChange(of: appModel.authStatus?.icloud.connected ?? false) { _, _ in
            syncOnboardingPresentation()
        }
        .sheet(isPresented: $showOnboarding) {
            OnboardingFlowView(
                selection: $selection,
                isOnboardingCompleted: $onboardingCompleted
            )
            .environment(appModel)
            .presentationBackground(.clear)
        }
    }

    private func syncOnboardingPresentation() {
        if appModel.hasCompletedFirstSync {
            onboardingCompleted = true
            showOnboarding = false
            return
        }

        if onboardingCompleted {
            showOnboarding = false
            return
        }

        showOnboarding = true
    }
}

private enum OnboardingStep: Int, CaseIterable {
    case welcome
    case connectAccounts
    case firstSync
}

private struct OnboardingFlowView: View {
    @Environment(AppModel.self) private var appModel
    @Environment(\.dismiss) private var dismiss

    @Binding var selection: AppSection?
    @Binding var isOnboardingCompleted: Bool

    @State private var step: OnboardingStep = .welcome
    @State private var isRunningFirstSync = false
    @State private var stepMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Welcome to JobTracker")
                .font(.system(size: 30, weight: .bold, design: .rounded))

            Text("Set up your accounts, run your first sync, and JobTracker will start building your application pipeline.")
                .font(.subheadline)
                .foregroundStyle(.secondary)

            Divider()

            Group {
                switch step {
                case .welcome:
                    welcomeStep
                case .connectAccounts:
                    connectAccountsStep
                case .firstSync:
                    firstSyncStep
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

            if let stepMessage {
                Text(stepMessage)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Divider()

            HStack {
                switch step {
                case .welcome:
                    Button("Skip for Now") {
                        dismiss()
                    }
                    .buttonStyle(JTSecondaryButtonStyle())
                case .connectAccounts, .firstSync:
                    Button("Back") {
                        goBack()
                    }
                    .buttonStyle(JTSecondaryButtonStyle())
                }

                Spacer()

                Button(primaryActionTitle) {
                    handlePrimaryAction()
                }
                .buttonStyle(JTPrimaryButtonStyle())
                .disabled(primaryActionDisabled)
            }
        }
        .padding(24)
        .frame(width: 640, height: 430)
        .jtCard(cornerRadius: 22, contentPadding: 24)
        .padding(16)
        .jtPageBackdrop()
        .task {
            await appModel.refreshAllStatus()
        }
    }

    private var welcomeStep: some View {
        VStack(alignment: .leading, spacing: 12) {
            onboardingBullet("Connect Gmail and/or iCloud in Settings.")
            onboardingBullet("Run your first sync to import job emails.")
            onboardingBullet("Review and correct classifications as needed.")
        }
    }

    private var connectAccountsStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Step 1: Connect Accounts")
                .font(.headline)

            accountStatusRow(title: "Gmail", isConnected: appModel.authStatus?.gmail.connected ?? false)
            accountStatusRow(title: "iCloud", isConnected: appModel.authStatus?.icloud.connected ?? false)

            Text("Tip: open Settings, connect at least one account, then come back here.")
                .font(.caption)
                .foregroundStyle(.secondary)

            HStack {
                Button("Open Settings") {
                    selection = .settings
                    stepMessage = "Settings opened. Connect an account, then continue."
                }
                .buttonStyle(JTSecondaryButtonStyle())

                Button("Refresh Status") {
                    Task {
                        await appModel.refreshAllStatus()
                    }
                }
                .buttonStyle(JTSecondaryButtonStyle())
            }
        }
    }

    private var firstSyncStep: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Step 2: Run First Sync")
                .font(.headline)

            if appModel.hasCompletedFirstSync {
                Label("First sync completed.", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            } else {
                Text("Run your first sync now to populate Applications and Emails.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            HStack {
                Button {
                    runFirstSync()
                } label: {
                    if isRunningFirstSync || appModel.isSyncing {
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Syncing...")
                        }
                    } else {
                        Text("Run First Sync")
                    }
                }
                .buttonStyle(JTPrimaryButtonStyle())
                .disabled(isRunningFirstSync || appModel.isSyncing || !appModel.hasConnectedAccount)

                Button("Open Settings") {
                    selection = .settings
                }
                .buttonStyle(JTSecondaryButtonStyle())
            }
        }
    }

    private var primaryActionTitle: String {
        switch step {
        case .welcome:
            return "Get Started"
        case .connectAccounts:
            return appModel.hasConnectedAccount ? "Continue" : "Connect an Account"
        case .firstSync:
            return appModel.hasCompletedFirstSync ? "Finish" : "Finish Later"
        }
    }

    private var primaryActionDisabled: Bool {
        switch step {
        case .welcome:
            return false
        case .connectAccounts:
            return !appModel.hasConnectedAccount
        case .firstSync:
            return false
        }
    }

    private func handlePrimaryAction() {
        switch step {
        case .welcome:
            step = .connectAccounts
        case .connectAccounts:
            if appModel.hasConnectedAccount {
                step = .firstSync
                stepMessage = nil
            } else {
                selection = .settings
            }
        case .firstSync:
            if appModel.hasCompletedFirstSync {
                isOnboardingCompleted = true
            }
            dismiss()
        }
    }

    private func goBack() {
        switch step {
        case .welcome:
            break
        case .connectAccounts:
            step = .welcome
        case .firstSync:
            step = .connectAccounts
        }
    }

    private func runFirstSync() {
        guard !isRunningFirstSync else { return }
        isRunningFirstSync = true
        stepMessage = nil

        Task { @MainActor in
            let success = await appModel.syncNowAndWait()
            isRunningFirstSync = false

            if success && appModel.hasCompletedFirstSync {
                stepMessage = "First sync completed. You can finish onboarding."
                isOnboardingCompleted = true
            } else {
                stepMessage = appModel.lastSyncSummary ?? "Sync did not complete. Please retry."
            }
        }
    }

    @ViewBuilder
    private func onboardingBullet(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "checkmark.seal")
                .foregroundStyle(.secondary)
            Text(text)
                .font(.body)
        }
    }

    @ViewBuilder
    private func accountStatusRow(title: String, isConnected: Bool) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text(isConnected ? "Connected" : "Not Connected")
                .font(.caption.weight(.medium))
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(.thinMaterial, in: Capsule())
                .foregroundStyle(isConnected ? .green : .secondary)
        }
    }
}
