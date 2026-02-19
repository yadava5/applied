import AppKit
import Combine
import Darwin
import Foundation
import ServiceManagement

@MainActor
final class BackendLifecycleManager: ObservableObject {
    @Published private(set) var autoStartEnabled = false
    @Published private(set) var serviceStatusText = "Unknown"
    @Published private(set) var serviceHintText = ""
    @Published private(set) var requiresSystemApproval = false
    @Published private(set) var autoStartSupported = true
    @Published private(set) var lastErrorMessage: String?

    private let launchAgentPlistName = "com.jobtracker.backend.plist"
    private let backendPort: UInt16 = 8000
    private var devBackendProcess: Process?
    private var autoStartFeatureEnabled: Bool {
#if DEBUG
        false
#else
        true
#endif
    }

    func refreshServiceStatus() {
        guard autoStartFeatureEnabled else {
            autoStartEnabled = false
            requiresSystemApproval = false
            autoStartSupported = false
            serviceStatusText = "Disabled in Debug"
            serviceHintText = "Start Backend at Login is disabled for debug runs."
            return
        }

        guard bundledLaunchAgentURL != nil else {
            autoStartEnabled = false
            requiresSystemApproval = false
            autoStartSupported = false
            serviceStatusText = "Launch Agent Missing"
            serviceHintText = "Rebuild the app so \(launchAgentPlistName) is embedded."
            return
        }

        if let signingIssue = codeSigningIssueMessage() {
            autoStartEnabled = false
            requiresSystemApproval = false
            autoStartSupported = false
            serviceStatusText = "Unavailable in Debug Build"
            serviceHintText = signingIssue
            return
        }

        if #available(macOS 13.0, *) {
            let service = SMAppService.agent(plistName: launchAgentPlistName)
            autoStartSupported = true
            switch service.status {
            case .enabled:
                autoStartEnabled = true
                requiresSystemApproval = false
                serviceStatusText = "Enabled"
                serviceHintText = "Backend auto-start is active."
            case .requiresApproval:
                autoStartEnabled = false
                requiresSystemApproval = true
                serviceStatusText = "Requires Approval"
                serviceHintText =
                    "Allow JobTracker in System Settings > General > Login Items."
            case .notRegistered:
                autoStartEnabled = false
                requiresSystemApproval = false
                serviceStatusText = "Not Registered"
                serviceHintText = "Enable Start Backend at Login to register the launch agent."
            case .notFound:
                autoStartEnabled = false
                requiresSystemApproval = false
                serviceStatusText = "Launch Agent Missing"
                serviceHintText = "Could not find \(launchAgentPlistName) in the app bundle."
            @unknown default:
                autoStartEnabled = false
                requiresSystemApproval = false
                serviceStatusText = "Unknown"
                serviceHintText = "Service status could not be determined."
            }
        } else {
            autoStartEnabled = false
            requiresSystemApproval = false
            autoStartSupported = false
            serviceStatusText = "Unsupported on this macOS version"
            serviceHintText = "SMAppService requires macOS 13+."
        }
    }

    func setAutoStart(enabled: Bool) {
        guard autoStartFeatureEnabled else {
            lastErrorMessage = "Start Backend at Login is only available in signed Release builds."
            refreshServiceStatus()
            return
        }

        guard #available(macOS 13.0, *) else {
            lastErrorMessage = "SMAppService requires macOS 13+."
            return
        }

        guard bundledLaunchAgentURL != nil else {
            lastErrorMessage =
                "Cannot configure auto-start because \(launchAgentPlistName) is not bundled."
            refreshServiceStatus()
            return
        }

        if let signingIssue = codeSigningIssueMessage() {
            lastErrorMessage = signingIssue
            refreshServiceStatus()
            return
        }

        ensureBackendLogDirectoryExists()

        do {
            let service = SMAppService.agent(plistName: launchAgentPlistName)
            if enabled {
                try service.register()
            } else {
                try service.unregister()
            }
            lastErrorMessage = nil
        } catch {
            lastErrorMessage = """
            Failed to update backend auto-start: \(error.localizedDescription). \
            If macOS asks for approval, allow JobTracker in System Settings > General > Login Items.
            """
        }

        refreshServiceStatus()
    }

    func openLoginItemsSettings() {
        guard
            let settingsURL = URL(
                string: "x-apple.systempreferences:com.apple.LoginItems-Settings.extension"
            )
        else {
            return
        }

        NSWorkspace.shared.open(settingsURL)
    }

    func ensureBackendRunningIfNeeded() async {
        do {
            let health = try await BackendAPIClient.shared.fetchHealth()
            if health.status == "ok" {
                return
            }
        } catch {
            // Backend likely not up; we'll attempt local start for development.
        }

        startBackendProcessForDevelopment()
    }

    private func startBackendProcessForDevelopment() {
        if let process = devBackendProcess, process.isRunning {
            return
        }

        if !isPortAvailable(backendPort) {
            lastErrorMessage =
                "Cannot auto-start backend: port \(backendPort) is already in use. Stop the conflicting service and retry."
            return
        }

        ensureBackendLogDirectoryExists()

        let backendPath = ("/Users/ayush/Documents/Projects/jobtracker/backend" as NSString)
            .expandingTildeInPath
        let process = Process()
        process.currentDirectoryURL = URL(fileURLWithPath: backendPath)
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [
            "python3",
            "-m",
            "uvicorn",
            "jobtracker.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            String(backendPort),
        ]
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        process.terminationHandler = { [weak self] finishedProcess in
            let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let stderr = String(data: stderrData, encoding: .utf8) ?? ""
            Task { @MainActor [weak self] in
                guard let self else { return }
                if self.devBackendProcess === finishedProcess {
                    self.devBackendProcess = nil
                }
                guard finishedProcess.terminationStatus != 0 else {
                    return
                }

                if stderr.localizedCaseInsensitiveContains("address already in use") {
                    self.lastErrorMessage =
                        "Backend failed to start because port \(self.backendPort) is already in use."
                } else if stderr.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    self.lastErrorMessage =
                        "Backend exited with status \(finishedProcess.terminationStatus)."
                } else {
                    self.lastErrorMessage =
                        "Backend exited with status \(finishedProcess.terminationStatus): \(stderr)"
                }
            }
        }

        do {
            try process.run()
            devBackendProcess = process
            lastErrorMessage = nil
        } catch {
            lastErrorMessage = "Failed to start backend: \(error.localizedDescription)"
        }
    }

    private var bundledLaunchAgentURL: URL? {
        let launchAgentURL = Bundle.main.bundleURL
            .appendingPathComponent("Contents/Library/LaunchAgents")
            .appendingPathComponent(launchAgentPlistName)

        guard FileManager.default.fileExists(atPath: launchAgentURL.path) else {
            return nil
        }

        return launchAgentURL
    }

    private func codeSigningIssueMessage() -> String? {
        let appPath = Bundle.main.bundleURL.path
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        process.arguments = ["--verify", "--strict", "--deep", appPath]

        let stderrPipe = Pipe()
        process.standardError = stderrPipe
        process.standardOutput = Pipe()

        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return "Unable to verify app signature: \(error.localizedDescription)"
        }

        guard process.terminationStatus != 0 else {
            return nil
        }

        let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
        let stderrText = String(data: stderrData, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

        if stderrText.contains("code has no resources but signature indicates they must be present") {
            return """
            Start at Login requires a signed app build. In Xcode, use \
            Signing "Sign to Run Locally" or your Apple Development team, \
            then Clean Build Folder and run again.
            """
        }

        if stderrText.isEmpty {
            return "Start at Login requires a valid signed app build."
        }

        return "Start at Login unavailable: \(stderrText)"
    }

    private func ensureBackendLogDirectoryExists() {
        let directory = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/JobTracker", isDirectory: true)

        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true
            )
        } catch {
            lastErrorMessage =
                "Failed to create backend log directory at \(directory.path): \(error.localizedDescription)"
        }
    }

    private func isPortAvailable(_ port: UInt16) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        if fd == -1 {
            return false
        }
        defer { close(fd) }

        var reuse: Int32 = 1
        let socketOptionResult = withUnsafePointer(to: &reuse) { pointer in
            setsockopt(
                fd,
                SOL_SOCKET,
                SO_REUSEADDR,
                pointer,
                socklen_t(MemoryLayout<Int32>.size)
            )
        }
        if socketOptionResult == -1 {
            return false
        }

        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.stride)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        addr.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        let bindResult = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPtr in
                Darwin.bind(fd, sockaddrPtr, socklen_t(MemoryLayout<sockaddr_in>.stride))
            }
        }

        return bindResult == 0
    }
}
