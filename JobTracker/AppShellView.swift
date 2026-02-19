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
    @State private var selection: AppSection? = .dashboard

    var body: some View {
        NavigationSplitView {
            List(AppSection.allCases, selection: $selection) { section in
                Label(section.title, systemImage: section.systemImage)
                    .tag(section)
            }
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
}
