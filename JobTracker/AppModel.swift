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

    let notifications = AppNotificationManager()
    let backendLifecycle = BackendLifecycleManager()
    let websocketClient = SyncWebSocketClient()
    let localDatabase = LocalDatabaseProvider()

    init() {
        websocketClient.onEvent = { [weak self] event in
            guard let self else { return }
            self.handleWebSocketEvent(event)
        }
    }

    func start() {
        backendLifecycle.refreshServiceStatus()

        Task {
            await notifications.requestAuthorizationIfNeeded()
            await backendLifecycle.ensureBackendRunningIfNeeded()
            if await waitForBackendReady() {
                websocketClient.connect()
            }
            await refreshAllStatus()
        }
    }

    func stop() {
        websocketClient.disconnect()
    }

    func refreshAllStatus() async {
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
        guard !isSyncing else { return }
        isSyncing = true

        Task {
            defer { isSyncing = false }
            do {
                let result = try await BackendAPIClient.shared.triggerSync()
                lastSyncSummary = "Synced \(result.emailsSaved) emails."
                await refreshAllStatus()
            } catch {
                lastSyncSummary = "Sync failed: \(error.localizedDescription)"
            }
        }
    }

    var menuBarSymbol: String {
        switch websocketClient.state {
        case .connected:
            return isSyncing ? "arrow.triangle.2.circlepath.circle.fill" : "tray.full.fill"
        case .connecting:
            return "arrow.triangle.2.circlepath.circle"
        case .error:
            return "exclamationmark.triangle.fill"
        case .disconnected:
            return "tray"
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

    private func waitForBackendReady(maxAttempts: Int = 20, delay: TimeInterval = 0.3) async -> Bool {
        for _ in 0..<maxAttempts {
            if let health = try? await BackendAPIClient.shared.fetchHealth(), health.status == "ok" {
                return true
            }
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
        }
        return false
    }
}
