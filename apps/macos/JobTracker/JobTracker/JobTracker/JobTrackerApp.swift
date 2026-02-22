import AppKit
import GRDBQuery
import SwiftUI

@main
struct JobTrackerApp: App {
    @State private var appModel = AppModel()
    private let fixedWindowSize = CGSize(width: 1360, height: 760)

    var body: some Scene {
        WindowGroup("JobTracker", id: "main") {
            AppShellView()
                .frame(width: fixedWindowSize.width, height: fixedWindowSize.height)
                .background(
                    FixedWindowConfiguratorView(size: fixedWindowSize)
                )
                .environment(appModel)
                .databaseContext(appModel.localDatabase.databaseContext)
                .tint(JTTheme.accentPrimary)
                .fontDesign(.rounded)
                .task {
                    appModel.start()
                }
        }
        .windowResizability(.contentSize)
        .defaultSize(width: fixedWindowSize.width, height: fixedWindowSize.height)
        .databaseContext(appModel.localDatabase.databaseContext)

#if !DEBUG
        MenuBarExtra("JobTracker", image: "MenuBarIcon") {
            VStack(alignment: .leading, spacing: 10) {
                Text("JobTracker")
                    .font(.headline)

                if let health = appModel.health {
                    HStack(spacing: 6) {
                        Image(systemName: appModel.menuBarStatusSymbol)
                            .foregroundStyle(health.status == "ok" ? JTTheme.success : JTTheme.warning)
                        Text("Backend: \(health.status.capitalized) · \(appModel.menuBarStatusText)")
                            .font(.caption)
                    }
                } else {
                    HStack(spacing: 6) {
                        Image(systemName: appModel.menuBarStatusSymbol)
                            .foregroundStyle(.secondary)
                        Text("Backend: Unknown")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
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
        .menuBarExtraStyle(.menu)
#endif
    }
}

private struct FixedWindowConfiguratorView: NSViewRepresentable {
    let size: CGSize

    func makeNSView(context: Context) -> NSView {
        let view = NSView(frame: .zero)
        DispatchQueue.main.async {
            configureWindow(for: view)
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        DispatchQueue.main.async {
            configureWindow(for: nsView)
        }
    }

    private func configureWindow(for view: NSView) {
        guard let window = view.window else { return }
        let fixedSize = NSSize(width: size.width, height: size.height)

        if window.minSize != fixedSize || window.maxSize != fixedSize {
            window.setContentSize(fixedSize)
            window.minSize = fixedSize
            window.maxSize = fixedSize
        }

        if window.styleMask.contains(.resizable) {
            window.styleMask.remove(.resizable)
        }
        window.collectionBehavior.remove(.fullScreenPrimary)
        window.collectionBehavior.remove(.fullScreenAuxiliary)

        if let zoomButton = window.standardWindowButton(.zoomButton) {
            zoomButton.isEnabled = false
        }
    }
}
