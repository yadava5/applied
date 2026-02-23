import GRDBQuery
import SwiftUI

struct DashboardView: View {
    @Environment(AppModel.self) private var appModel
    @Query(LocalNeedsReviewCountRequest()) private var localNeedsReviewCount: Int

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

    private var linkedCount: Int { overview?.emailsLinked ?? 0 }
    private var unlinkedCount: Int { overview?.emailsUnlinked ?? 0 }
    private var totalApplicationsCount: Int { overview?.totalApplications ?? 0 }
    private var totalEmailCount: Int { linkedCount + unlinkedCount }

    private var linkedRatio: Double {
        guard totalEmailCount > 0 else { return 0 }
        return Double(linkedCount) / Double(totalEmailCount)
    }

    private var connectedAccountsRatio: Double {
        Double(connectedAccountsCount) / 2.0
    }

    private var connectedAccountsCount: Int {
        var count = 0
        if appModel.authStatus?.gmail.connected == true { count += 1 }
        if appModel.authStatus?.icloud.connected == true { count += 1 }
        return count
    }

    private var backendStateLabel: String {
        appModel.backendReady ? "Ready" : "Unavailable"
    }

    private var syncStateLabel: String {
        if appModel.isSyncing { return "Syncing" }
        return appModel.menuBarStatusText
    }

    private var lastActivitySummary: String {
        if let summary = appModel.lastSyncSummary, !summary.isEmpty {
            return summary
        }
        if let lastSync = appModel.health?.lastSync, !lastSync.isEmpty {
            return "Last sync: \(lastSync)"
        }
        return "No recent sync activity."
    }

    private var activePipelineStages: Int {
        guard let byStatus = overview?.byStatus else { return 0 }
        return orderedStatuses.filter { (byStatus[$0] ?? 0) > 0 }.count
    }

    private struct DashboardLayoutMetrics {
        let availableWidth: CGFloat
        let shouldScroll: Bool
        let isCompactHeight: Bool
        let metricRailMinimumWidth: CGFloat
    }

    private func layoutMetrics(for size: CGSize) -> DashboardLayoutMetrics {
        let availableWidth = max(size.width - 32, 320)
        let availableHeight = max(size.height - 32, 320)
        let isCompactHeight = availableHeight < 690
        let shouldScroll = availableHeight < 620 || size.width < 900

        let metricRailMinimumWidth: CGFloat
        if availableWidth >= 1180 {
            metricRailMinimumWidth = max((availableWidth - 30) / 3, 220)
        } else if availableWidth >= 560 {
            metricRailMinimumWidth = max((availableWidth - 14) / 2, 220)
        } else {
            metricRailMinimumWidth = max(availableWidth - 4, 220)
        }

        return DashboardLayoutMetrics(
            availableWidth: availableWidth,
            shouldScroll: shouldScroll,
            isCompactHeight: isCompactHeight,
            metricRailMinimumWidth: metricRailMinimumWidth
        )
    }

    var body: some View {
        GeometryReader { proxy in
            let metrics = layoutMetrics(for: proxy.size)
            Group {
                if metrics.shouldScroll {
                    ScrollView {
                        dashboardContent(metrics: metrics)
                            .frame(width: metrics.availableWidth, alignment: .leading)
                            .padding(.bottom, 6)
                    }
                } else {
                    dashboardContent(metrics: metrics)
                        .frame(width: metrics.availableWidth, alignment: .leading)
                        .frame(maxHeight: .infinity, alignment: .top)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .navigationTitle("Dashboard")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await syncNow() }
                } label: {
                    Label("Sync Now", systemImage: "arrow.triangle.2.circlepath.circle.fill")
                }
                .buttonStyle(.borderedProminent)
            }
            ToolbarItem(placement: .automatic) {
                Button {
                    Task { await reload() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }
                .buttonStyle(.bordered)
            }
        }
        .task {
            await reload()
        }
    }

    @ViewBuilder
    private func dashboardContent(metrics: DashboardLayoutMetrics) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if let errorMessage {
                Text(errorMessage)
                    .font(.subheadline)
                    .foregroundStyle(JTTheme.danger)
            }

            if let syncMessage {
                Text(syncMessage)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if isLoading && overview == nil {
                ProgressView("Loading dashboard...")
            } else {
                responsiveLayout(metrics: metrics)
            }
        }
    }

    private func responsiveLayout(metrics: DashboardLayoutMetrics) -> some View {
        VStack(alignment: .leading, spacing: metrics.isCompactHeight ? 8 : 10) {
            snapshotSection(minimumRailWidth: metrics.metricRailMinimumWidth)

            if metrics.availableWidth >= 980 {
                HStack(alignment: .top, spacing: 10) {
                    pipelineOverviewSection
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                    runtimeSection
                        .frame(
                            width: max(300, min(metrics.availableWidth * 0.34, 420)),
                            alignment: .topLeading
                        )
                }
            } else {
                pipelineOverviewSection
                runtimeSection
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func snapshotSection(minimumRailWidth: CGFloat) -> some View {
        let topBaseline = max(totalApplicationsCount, totalEmailCount, 1)
        let snapshotItems = [
            MetricRailItem(
                title: "Applications",
                value: totalApplicationsCount,
                subtitle: "Tracked jobs",
                symbol: "briefcase.fill",
                tone: JTTheme.accentPrimary,
                progress: Double(totalApplicationsCount) / Double(topBaseline)
            ),
            MetricRailItem(
                title: "Emails Unlinked",
                value: unlinkedCount,
                subtitle: "Needs linking",
                symbol: "link",
                tone: JTTheme.warning,
                progress: totalEmailCount > 0 ? Double(unlinkedCount) / Double(totalEmailCount) : 0
            ),
            MetricRailItem(
                title: "Needs Review",
                value: localNeedsReviewCount,
                subtitle: "Queue",
                symbol: "checklist.unchecked",
                tone: JTTheme.danger,
                progress: totalEmailCount > 0 ? Double(localNeedsReviewCount) / Double(totalEmailCount) : 0
            ),
            MetricRailItem(
                title: "Active Stages",
                value: activePipelineStages,
                subtitle: "Pipeline movement",
                symbol: "point.topleft.down.curvedto.point.bottomright.up.fill",
                tone: JTTheme.accentPrimary,
                progress: Double(activePipelineStages) / Double(max(orderedStatuses.count, 1))
            )
        ]

        let columns = [
            GridItem(.adaptive(minimum: minimumRailWidth), spacing: 10)
        ]

        return VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 18) {
                QueueDial(
                    title: "Linked",
                    symbol: "link.circle.fill",
                    valueText: "\(Int((linkedRatio * 100).rounded()))%",
                    progress: linkedRatio,
                    tone: JTTheme.success
                )
                QueueDial(
                    title: "Accounts",
                    symbol: "person.2.fill",
                    valueText: "\(connectedAccountsCount)/2",
                    progress: min(max(connectedAccountsRatio, 0), 1),
                    tone: JTTheme.accentSecondary
                )
                Rectangle()
                    .fill(
                        LinearGradient(
                            colors: [Color.white.opacity(0.25), Color.white.opacity(0.05)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .frame(width: 1, height: 70)
                VStack(alignment: .leading, spacing: 6) {
                    Text("Snapshot")
                        .font(.subheadline.weight(.semibold))
                    Text("Single-view metrics: no duplicated counters on this screen.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
            }

            LazyVGrid(columns: columns, spacing: 8) {
                ForEach(snapshotItems) { rail in
                    MetricRail(item: rail)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .jtCard(cornerRadius: 18, contentPadding: 14)
    }

    private var pipelineOverviewSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("Pipeline Stages", systemImage: "chart.bar.xaxis")
                .font(.headline)
                .symbolRenderingMode(.hierarchical)

            if let byStatus = overview?.byStatus, !byStatus.isEmpty {
                PipelineNodeTrack(
                    statuses: orderedStatuses.map(\.humanizedFromSnakeCase),
                    counts: orderedStatuses.map { byStatus[$0] ?? 0 },
                    symbols: orderedStatuses.map(iconForStatus)
                )

                HStack(spacing: 10) {
                    Label("\(activePipelineStages) active", systemImage: "point.topleft.down.curvedto.point.bottomright.up.fill")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Label("\(orderedStatuses.count - activePipelineStages) idle", systemImage: "circle.dotted")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("No applications yet.")
                        .font(.subheadline.weight(.semibold))
                    Text("Run sync to populate pipeline stages.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .jtCard(cornerRadius: 18, contentPadding: 14)
    }

    private var runtimeSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Runtime", systemImage: "dot.radiowaves.left.and.right")
                .font(.headline)
                .symbolRenderingMode(.hierarchical)

            RuntimeInfoRow(
                title: "Backend",
                value: backendStateLabel,
                symbol: "server.rack",
                tone: appModel.backendReady ? JTTheme.success : JTTheme.danger
            )
            RuntimeInfoRow(
                title: "WebSocket",
                value: appModel.websocketClient.state.rawValue.capitalized,
                symbol: "wave.3.right.circle",
                tone: appModel.websocketClient.state == .connected ? JTTheme.success : JTTheme.warning
            )
            RuntimeInfoRow(
                title: "Sync",
                value: syncStateLabel,
                symbol: "arrow.triangle.2.circlepath",
                tone: appModel.isSyncing ? JTTheme.warning : JTTheme.accentPrimary
            )
            RuntimeInfoRow(
                title: "Connected Accounts",
                value: "\(connectedAccountsCount) / 2",
                symbol: "person.2.fill",
                tone: connectedAccountsCount > 0 ? JTTheme.success : JTTheme.warning
            )

            Text(lastActivitySummary)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(3)
                .fixedSize(horizontal: false, vertical: true)

            if appModel.isSyncing {
                ProgressView()
                    .controlSize(.small)
            }
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .jtCard(cornerRadius: 18, contentPadding: 14)
    }

    private func iconForStatus(_ status: String) -> String {
        switch status {
        case "applied":
            return "paperplane.fill"
        case "interviewing":
            return "person.2.fill"
        case "offered":
            return "gift.fill"
        case "rejected":
            return "xmark.octagon.fill"
        case "accepted":
            return "checkmark.seal.fill"
        case "withdrawn":
            return "arrow.uturn.backward.circle.fill"
        case "ghosted":
            return "moon.stars.fill"
        default:
            return "circle.fill"
        }
    }

    private func reload() async {
        isLoading = true
        errorMessage = nil
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            errorMessage = appModel.backendStartupError ?? "Backend is unavailable."
            isLoading = false
            return
        }

        do {
            async let overviewRequest = BackendAPIClient.shared.fetchApplicationsOverview()
            async let statusRefresh: Void = appModel.refreshAllStatus()
            overview = try await overviewRequest
            _ = await statusRefresh
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }

    private func syncNow() async {
        syncMessage = nil
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            syncMessage = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
        do {
            let result = try await BackendAPIClient.shared.triggerSync()
            syncMessage = "Synced \(result.emailsSaved) emails from \(result.accountsSynced.joined(separator: ", "))."
            await reload()
        } catch {
            syncMessage = "Sync failed: \(error.localizedDescription)"
        }
    }
}

private struct MetricRailItem: Identifiable {
    let id = UUID()
    let title: String
    let value: Int
    let subtitle: String
    let symbol: String
    let tone: Color
    let progress: Double
}

private struct MetricRail: View {
    let item: MetricRailItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: item.symbol)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(item.tone)
                    .symbolRenderingMode(.hierarchical)
                Text(item.title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 6)
                Text("\(item.value)")
                    .font(.subheadline.monospacedDigit().weight(.bold))
            }

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.white.opacity(0.08))
                    .frame(height: 7)
                Capsule()
                    .fill(
                        LinearGradient(
                            colors: [item.tone.opacity(0.42), item.tone],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: max(CGFloat(min(max(item.progress, 0), 1)) * 180, 16), height: 7)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Text(item.subtitle)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 11)
        .padding(.vertical, 9)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(JTTheme.surfaceStroke.opacity(0.55), lineWidth: 1)
        )
    }
}

private struct QueueDial: View {
    let title: String
    let symbol: String
    let valueText: String
    let progress: Double
    let tone: Color

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle()
                    .stroke(Color.white.opacity(0.12), lineWidth: 7)

                Circle()
                    .trim(from: 0, to: min(max(progress, 0), 1))
                    .stroke(
                        AngularGradient(
                            colors: [tone.opacity(0.3), tone],
                            center: .center
                        ),
                        style: StrokeStyle(lineWidth: 7, lineCap: .round)
                    )
                    .rotationEffect(.degrees(-90))

                VStack(spacing: 1) {
                    Image(systemName: symbol)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(tone)
                        .symbolRenderingMode(.hierarchical)
                    Text(valueText)
                        .font(.headline.monospacedDigit().weight(.bold))
                }
            }
            .frame(width: 74, height: 74)

            Text(title)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }
}

private struct PipelineNodeTrack: View {
    let statuses: [String]
    let counts: [Int]
    let symbols: [String]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Array(statuses.enumerated()), id: \.offset) { index, title in
                let count = counts[safe: index] ?? 0
                let symbol = symbols[safe: index] ?? "circle.fill"
                let isActive = count > 0

                VStack(spacing: 6) {
                    ZStack {
                        Circle()
                            .fill((isActive ? JTTheme.accentPrimary : Color.white.opacity(0.18)).opacity(0.22))
                        Image(systemName: symbol)
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(isActive ? JTTheme.accentPrimary : Color.white.opacity(0.55))
                            .symbolRenderingMode(.hierarchical)
                    }
                    .frame(width: 26, height: 26)

                    Text("\(count)")
                        .font(.caption.monospacedDigit().weight(.bold))
                        .foregroundStyle(isActive ? .primary : .secondary)

                    Text(title)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .frame(minWidth: 0, maxWidth: .infinity)

                if index < statuses.count - 1 {
                    Capsule()
                        .fill(
                            LinearGradient(
                                colors: [
                                    isActive ? JTTheme.accentPrimary.opacity(0.65) : Color.white.opacity(0.15),
                                    (counts[safe: index + 1] ?? 0) > 0
                                        ? JTTheme.accentPrimary.opacity(0.45)
                                        : Color.white.opacity(0.1)
                                ],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(height: 2)
                        .padding(.horizontal, 4)
                        .offset(y: -13)
                }
            }
        }
        .padding(.horizontal, 6)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(JTTheme.surfaceStroke.opacity(0.45), lineWidth: 1)
        )
    }
}

struct StatCard: View {
    let title: String
    let value: String
    let subtitle: String
    let icon: String?
    let tone: Color

    init(
        title: String,
        value: String,
        subtitle: String,
        icon: String? = nil,
        tone: Color = JTTheme.accentPrimary
    ) {
        self.title = title
        self.value = value
        self.subtitle = subtitle
        self.icon = icon
        self.tone = tone
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.system(size: 24, weight: .bold, design: .rounded))
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer(minLength: 8)

            if let icon {
                ZStack {
                    Circle()
                        .fill(tone.opacity(0.18))
                    Image(systemName: icon)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(tone)
                        .symbolRenderingMode(.hierarchical)
                }
                .frame(width: 34, height: 34)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .jtCard(cornerRadius: 16, contentPadding: 12)
    }
}

private struct RuntimeInfoRow: View {
    let title: String
    let value: String
    let symbol: String
    let tone: Color

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: symbol)
                .font(.caption.weight(.semibold))
                .foregroundStyle(tone)
                .symbolRenderingMode(.hierarchical)
                .frame(width: 17)

            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            Spacer(minLength: 8)

            Text(value)
                .font(.caption.monospacedDigit().weight(.bold))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(.thinMaterial, in: Capsule())
        .overlay(Capsule().stroke(JTTheme.surfaceStroke.opacity(0.55), lineWidth: 1))
    }
}

private extension Collection {
    subscript(safe index: Index) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
