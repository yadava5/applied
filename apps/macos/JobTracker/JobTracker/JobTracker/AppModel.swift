import Foundation
import Observation

@MainActor
@Observable
final class AppModel {
    var health: HealthResponse?
    var authStatus: AuthStatusResponse?
    var needsReviewCount: Int = 0
    var lastSyncSummary: String?
    var isSyncing: Bool = false
    var backendReady: Bool = false
    var backendStartupError: String?
    var themePreset: JTThemePreset = JTThemePreset.persistedDefault
    var themeRefreshID = UUID()

    let notifications = AppNotificationManager()
    let backendLifecycle = BackendLifecycleManager()
    let websocketClient = SyncWebSocketClient()
    let localDatabase = LocalDatabaseProvider()
    @ObservationIgnored private var startupTask: Task<Void, Never>?

    init() {
        let persistedTheme = JTThemePreset.persistedDefault
        themePreset = persistedTheme
        JTTheme.apply(persistedTheme)

        websocketClient.onEvent = { [weak self] event in
            guard let self else { return }
            self.handleWebSocketEvent(event)
        }
    }

    func start() {
        guard startupTask == nil else { return }
        backendLifecycle.refreshServiceStatus()
        backendReady = false
        backendStartupError = nil

        startupTask = Task { [weak self] in
            guard let self else { return }
            defer { self.startupTask = nil }
            await notifications.requestAuthorizationIfNeeded()
            await backendLifecycle.ensureBackendRunningIfNeeded()
            if Task.isCancelled { return }
            if await waitForBackendReady() {
                backendReady = true
                websocketClient.connect()
                await refreshAllStatus()
            } else {
                backendReady = false
                backendStartupError =
                    backendLifecycle.lastErrorMessage
                    ?? "Backend did not become ready on 127.0.0.1:8000."
                websocketClient.disconnect()
            }
        }
    }

    func stop() {
        startupTask?.cancel()
        startupTask = nil
        websocketClient.disconnect()
        backendReady = false
    }

    func setThemePreset(_ preset: JTThemePreset) {
        guard themePreset != preset else { return }
        themePreset = preset
        JTTheme.apply(preset)
        UserDefaults.standard.set(preset.rawValue, forKey: JTThemePreset.defaultsKey)
        themeRefreshID = UUID()
    }

    func refreshAllStatus() async {
        guard backendReady else { return }
        do {
            async let healthRequest = BackendAPIClient.shared.fetchHealth()
            async let authRequest = BackendAPIClient.shared.fetchAuthStatus()
            async let reviewRequest = BackendAPIClient.shared.fetchNeedsReview(limit: 1, offset: 0)

            health = try await healthRequest
            authStatus = try await authRequest
            let reviewResult = try await reviewRequest
            needsReviewCount = reviewResult.totalCount
        } catch {
            // Keep the model resilient. Individual views show their own errors.
        }
    }

    func syncNow() {
        Task {
            _ = await syncNowAndWait()
        }
    }

    @discardableResult
    func syncNowAndWait() async -> Bool {
        guard backendReady else {
            lastSyncSummary = backendStartupError ?? "Backend is unavailable."
            return false
        }
        guard !isSyncing else { return false }
        isSyncing = true
        defer { isSyncing = false }

        do {
            let result = try await BackendAPIClient.shared.triggerSync()
            lastSyncSummary = "Synced \(result.emailsSaved) emails."
            await refreshAllStatus()
            return result.success
        } catch {
            lastSyncSummary = "Sync failed: \(error.localizedDescription)"
            return false
        }
    }

    var hasConnectedAccount: Bool {
        (authStatus?.gmail.connected ?? false) || (authStatus?.icloud.connected ?? false)
    }

    var hasCompletedFirstSync: Bool {
        guard let lastSync = health?.lastSync else { return false }
        return !lastSync.isEmpty
    }

    var menuBarStatusSymbol: String {
        switch websocketClient.state {
        case .connected:
            return isSyncing ? "arrow.triangle.2.circlepath.circle.fill" : "checkmark.circle.fill"
        case .connecting:
            return "arrow.triangle.2.circlepath.circle"
        case .error:
            return "exclamationmark.triangle.fill"
        case .disconnected:
            return "bolt.horizontal.circle"
        }
    }

    var menuBarStatusText: String {
        switch websocketClient.state {
        case .connected:
            return isSyncing ? "Syncing" : "Connected"
        case .connecting:
            return "Connecting"
        case .error:
            return "Error"
        case .disconnected:
            return "Disconnected"
        }
    }

    private func handleWebSocketEvent(_ event: SyncSocketEvent) {
        switch event.event {
        case "started":
            isSyncing = true
            lastSyncSummary = "Sync started..."
        case "completed":
            isSyncing = false
            let fetched = event.emailsFetched ?? 0
            let saved = event.emailsSaved ?? 0
            lastSyncSummary = "Sync completed. Fetched \(fetched), saved \(saved)."
            notifications.notify(
                title: "JobTracker Sync Complete",
                body: "Fetched \(fetched) emails, saved \(saved)."
            )
            Task {
                await refreshAllStatus()
                if let overview = try? await BackendAPIClient.shared.fetchApplicationsOverview() {
                    let interviewing = overview.byStatus["interviewing"] ?? 0
                    if interviewing > 0 {
                        notifications.notify(
                            title: "Interview Pipeline Update",
                            body: "\(interviewing) applications are currently in interviewing status."
                        )
                    }
                    let offered = overview.byStatus["offered"] ?? 0
                    if offered > 0 {
                        notifications.notify(
                            title: "Offer Stage Reached",
                            body: "\(offered) application(s) are currently in offered status."
                        )
                    }
                }
            }
        case "error":
            isSyncing = false
            lastSyncSummary = event.message ?? "Sync error"
            notifications.notify(
                title: "JobTracker Sync Error",
                body: event.message ?? "An error occurred during sync."
            )
        default:
            break
        }
    }

    private func waitForBackendReady(maxAttempts: Int = 40, delay: TimeInterval = 0.5) async -> Bool {
        await backendLifecycle.waitForBackendReady(
            maxAttempts: maxAttempts,
            delaySeconds: delay
        )
    }

    func awaitBackendReady(
        maxWaitSeconds: TimeInterval = 35,
        pollInterval: TimeInterval = 0.25
    ) async -> Bool {
        if backendReady { return true }

        let deadline = Date().addingTimeInterval(maxWaitSeconds)
        while Date() < deadline {
            if backendReady { return true }
            if backendStartupError != nil { return false }
            try? await Task.sleep(nanoseconds: UInt64(pollInterval * 1_000_000_000))
        }

        return backendReady
    }
}
