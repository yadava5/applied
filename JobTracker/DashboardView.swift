import GRDBQuery
import SwiftUI

struct DashboardView: View {
    @Query(LocalApplicationsCountRequest()) private var localApplicationsCount: Int
    @Query(LocalNeedsReviewCountRequest()) private var localNeedsReviewCount: Int

    @State private var health: HealthResponse?
    @State private var overview: ApplicationsOverviewResponse?
    @State private var isLoading = false
    @State private var errorMessage: String?
    @State private var syncMessage: String?

    private let orderedStatuses = [
        "applied",
        "interviewing",
        "offered",
        "rejected",
        "accepted",
        "withdrawn",
        "ghosted"
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let errorMessage {
                    Text(errorMessage)
                        .font(.subheadline)
                        .foregroundStyle(.red)
                }

                if let syncMessage {
                    Text(syncMessage)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                if isLoading && health == nil && overview == nil {
                    ProgressView("Loading dashboard...")
                } else {
                    summaryCards
                    systemStatusSection
                    pipelineSection
                }
            }
            .padding(20)
        }
        .navigationTitle("Dashboard")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button("Sync Now") {
                    Task { await syncNow() }
                }
            }
            ToolbarItem(placement: .automatic) {
                Button("Refresh") {
                    Task { await reload() }
                }
            }
        }
        .task {
            await reload()
        }
    }

    private var summaryCards: some View {
        let total = overview?.totalApplications ?? 0
        let linked = overview?.emailsLinked ?? 0
        let unlinked = overview?.emailsUnlinked ?? 0

        return LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 12)], spacing: 12) {
            StatCard(title: "Applications", value: "\(total)", subtitle: "Tracked jobs")
            StatCard(title: "Local DB Apps", value: "\(localApplicationsCount)", subtitle: "Reactive (GRDBQuery)")
            StatCard(title: "Emails Linked", value: "\(linked)", subtitle: "Mapped to applications")
            StatCard(title: "Emails Unlinked", value: "\(unlinked)", subtitle: "Need linking")
            StatCard(title: "Needs Review", value: "\(localNeedsReviewCount)", subtitle: "Reactive queue size")
        }
    }

    private var systemStatusSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("System Status")
                .font(.headline)

            if let health {
                HStack(spacing: 16) {
                    StatusPill(title: "API", isOn: health.status == "ok")
                    StatusPill(title: "Database", isOn: health.dbConnected)
                    StatusPill(title: "Gmail", isOn: health.gmailConnected)
                    StatusPill(title: "iCloud", isOn: health.icloudConnected)
                }

                if let lastSync = health.lastSync, !lastSync.isEmpty {
                    Text("Last sync: \(lastSync)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                Text("No health data yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var pipelineSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Pipeline")
                .font(.headline)

            if let byStatus = overview?.byStatus, !byStatus.isEmpty {
                ForEach(orderedStatuses, id: \.self) { status in
                    let count = byStatus[status] ?? 0
                    HStack {
                        Text(status.humanizedFromSnakeCase)
                            .foregroundStyle(.primary)
                        Spacer()
                        Text("\(count)")
                            .font(.body.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Text("No applications yet.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private func reload() async {
        isLoading = true
        errorMessage = nil

        do {
            async let healthRequest = BackendAPIClient.shared.fetchHealth()
            async let overviewRequest = BackendAPIClient.shared.fetchApplicationsOverview()
            health = try await healthRequest
            overview = try await overviewRequest
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    private func syncNow() async {
        syncMessage = nil
        do {
            let result = try await BackendAPIClient.shared.triggerSync()
            syncMessage = "Synced \(result.emailsSaved) emails from \(result.accountsSynced.joined(separator: ", "))."
            await reload()
        } catch {
            syncMessage = "Sync failed: \(error.localizedDescription)"
        }
    }
}

struct StatCard: View {
    let title: String
    let value: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.system(size: 28, weight: .semibold, design: .rounded))
            Text(subtitle)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

private struct StatusPill: View {
    let title: String
    let isOn: Bool

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(isOn ? Color.green : Color.red)
                .frame(width: 8, height: 8)
            Text(title)
                .font(.caption)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(.ultraThinMaterial, in: Capsule())
    }
}
