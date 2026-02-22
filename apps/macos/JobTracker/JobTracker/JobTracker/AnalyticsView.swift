import Charts
import SwiftUI

struct AnalyticsView: View {
    @Environment(AppModel.self) private var appModel
    private struct ChartPoint: Identifiable {
        let id: String
        let date: Date
        let applied: Int
        let rejected: Int
        let interviews: Int
        let offers: Int
    }

    @State private var overview: AnalyticsOverviewResponse?
    @State private var trends: AnalyticsTrendsResponse?
    @State private var period = "weekly"
    @State private var months = 3
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                controls

                if let errorMessage {
                    Text(errorMessage)
                        .font(.subheadline)
                        .foregroundStyle(JTTheme.danger)
                }

                if isLoading && overview == nil {
                    ProgressView("Loading analytics...")
                } else {
                    overviewCards
                    statusBreakdown
                    trendsChart
                }
            }
            .padding(20)
        }
        .navigationTitle("Analytics")
        .jtPageBackdrop()
        .toolbar {
            ToolbarItem(placement: .automatic) {
                Button("Refresh") {
                    Task { await reloadAnalytics() }
                }
                .buttonStyle(.bordered)
            }
        }
        .task {
            await reloadAnalytics()
        }
    }

    private var chartPoints: [ChartPoint] {
        guard let points = trends?.data else { return [] }
        return points
            .compactMap { point in
                guard let parsedDate = parsePeriodStart(point.periodStart) else { return nil }
                return ChartPoint(
                    id: point.periodStart,
                    date: parsedDate,
                    applied: point.applied,
                    rejected: point.rejected,
                    interviews: point.interviews,
                    offers: point.offers
                )
            }
            .sorted { $0.date < $1.date }
    }

    private var controls: some View {
        HStack(spacing: 12) {
            Picker("Period", selection: $period) {
                Text("Weekly").tag("weekly")
                Text("Monthly").tag("monthly")
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 240)

            Stepper("Months: \(months)", value: $months, in: 1...12)
                .frame(maxWidth: 200)

            Button("Apply") {
                Task { await reloadAnalytics() }
            }
            .buttonStyle(JTPrimaryButtonStyle())
        }
        .jtCard()
    }

    private var overviewCards: some View {
        let total = overview?.totalApplications ?? 0
        let responseRate = Int((overview?.responseRate ?? 0.0) * 100)
        let avgResponse = overview?.avgResponseDays.map { String(format: "%.1f", $0) } ?? "—"

        return LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 12)], spacing: 12) {
            StatCard(title: "Total Applications", value: "\(total)", subtitle: "All tracked")
            StatCard(title: "Response Rate", value: "\(responseRate)%", subtitle: "Apps with replies")
            StatCard(title: "Avg Response Time", value: "\(avgResponse) days", subtitle: "Time to first response")
        }
    }

    private var statusBreakdown: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Status Breakdown")
                .font(.headline)

            if let byStatus = overview?.byStatus {
                ForEach(byStatus.keys.sorted(), id: \.self) { key in
                    HStack {
                        Text(key.humanizedFromSnakeCase)
                        Spacer()
                        Text("\(byStatus[key] ?? 0)")
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Text("No status data.")
                    .foregroundStyle(.secondary)
            }
        }
        .jtCard()
    }

    private var trendsChart: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Trends")
                .font(.headline)

            if !chartPoints.isEmpty {
                Chart(chartPoints) { point in
                    LineMark(
                        x: .value("Period", point.date),
                        y: .value("Applied", point.applied)
                    )
                    .foregroundStyle(JTTheme.accentPrimary)
                    .interpolationMethod(.catmullRom)

                    LineMark(
                        x: .value("Period", point.date),
                        y: .value("Interviews", point.interviews)
                    )
                    .foregroundStyle(JTTheme.success)
                    .interpolationMethod(.catmullRom)

                    LineMark(
                        x: .value("Period", point.date),
                        y: .value("Rejected", point.rejected)
                    )
                    .foregroundStyle(JTTheme.danger)
                    .interpolationMethod(.catmullRom)

                    LineMark(
                        x: .value("Period", point.date),
                        y: .value("Offers", point.offers)
                    )
                    .foregroundStyle(JTTheme.accentSecondary)
                    .interpolationMethod(.catmullRom)
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 6)) { _ in
                        AxisGridLine()
                        AxisTick()
                        if period == "weekly" {
                            AxisValueLabel(format: .dateTime.month(.abbreviated).day())
                        } else {
                            AxisValueLabel(format: .dateTime.month(.abbreviated).year())
                        }
                    }
                }
                .chartLegend(position: .bottom, spacing: 16)
                .frame(height: 260)
            } else {
                Text("No trend points yet.")
                    .foregroundStyle(.secondary)
            }
        }
        .jtCard()
    }

    private func reloadAnalytics() async {
        guard await appModel.awaitBackendReady(maxWaitSeconds: 20) else {
            errorMessage = appModel.backendStartupError ?? "Backend is unavailable."
            return
        }
        isLoading = true
        errorMessage = nil
        do {
            async let overviewRequest = BackendAPIClient.shared.fetchAnalyticsOverview()
            async let trendsRequest = BackendAPIClient.shared.fetchAnalyticsTrends(
                period: period,
                months: months
            )

            overview = try await overviewRequest
            trends = try await trendsRequest
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func parsePeriodStart(_ value: String) -> Date? {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .iso8601)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.date(from: value)
    }
}
