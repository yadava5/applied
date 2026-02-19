import AppKit
import GRDBQuery
import SwiftUI

@main
struct JobTrackerApp: App {
    @StateObject private var appModel = AppModel()

    var body: some Scene {
        WindowGroup("JobTracker", id: "main") {
            AppShellView()
                .environmentObject(appModel)
                .databaseContext(appModel.localDatabase.databaseContext)
                .task {
                    appModel.start()
                }
        }
        .databaseContext(appModel.localDatabase.databaseContext)

        MenuBarExtra("JobTracker", systemImage: appModel.menuBarSymbol) {
            VStack(alignment: .leading, spacing: 10) {
                Text("JobTracker")
                    .font(.headline)

                if let health = appModel.health {
                    Text("Backend: \(health.status.capitalized)")
                        .font(.caption)
                        .foregroundStyle(health.status == "ok" ? .green : .red)
                } else {
                    Text("Backend: Unknown")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Text("Needs review: \(appModel.needsReviewCount)")
                    .font(.caption)

                if let summary = appModel.lastSyncSummary {
                    Text(summary)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }

                Divider()

                Button(appModel.isSyncing ? "Syncing..." : "Sync Now") {
                    appModel.syncNow()
                }
                .disabled(appModel.isSyncing)

                Button("Refresh Status") {
                    Task { await appModel.refreshAllStatus() }
                }

                Button("Open App") {
                    NSApp.activate(ignoringOtherApps: true)
                }

                Button("Quit") {
                    NSApplication.shared.terminate(nil)
                }
            }
            .padding(8)
            .frame(minWidth: 240)
        }
        .menuBarExtraStyle(.window)
    }
}
