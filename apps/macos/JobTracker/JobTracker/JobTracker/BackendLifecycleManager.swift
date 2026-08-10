import AppKit
import Darwin
import Foundation
import Observation
import ServiceManagement

@MainActor
@Observable
final class BackendLifecycleManager {
    private(set) var autoStartEnabled = false
    private(set) var serviceStatusText = "Unknown"
    private(set) var serviceHintText = ""
    private(set) var requiresSystemApproval = false
    private(set) var autoStartSupported = true
    private(set) var lastErrorMessage: String?

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
            serviceHintText =
                "Start Backend at Login is disabled for debug runs. The app still attempts development backend auto-launch on startup."
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
        if await isBackendHealthy(retries: 2, delaySeconds: 0.2) {
            return
        }

        await startBackendProcessForDevelopment()
    }

    func waitForBackendReady(maxAttempts: Int = 40, delaySeconds: Double = 0.5) async -> Bool {
        for _ in 0..<max(1, maxAttempts) {
            if Task.isCancelled {
                return false
            }
            if lastErrorMessage != nil {
                return false
            }

            if isLocalPortReachable(backendPort),
               await isBackendHealthy(retries: 1, delaySeconds: 0)
            {
                return true
            }

            if delaySeconds > 0 {
                try? await Task.sleep(nanoseconds: UInt64(delaySeconds * 1_000_000_000))
            }
        }

        return false
    }

    private func startBackendProcessForDevelopment() async {
        if let process = devBackendProcess, process.isRunning {
            return
        }

        if !isPortAvailable(backendPort) {
            if await isBackendHealthy(retries: 6, delaySeconds: 0.25) {
                lastErrorMessage = nil
                return
            }
            lastErrorMessage =
                "Cannot auto-start backend: port \(backendPort) is already in use. Stop the conflicting service and retry."
            return
        }

        ensureBackendLogDirectoryExists()

        guard let projectRoot = resolveProjectRootForDevelopment() else {
            lastErrorMessage = """
            Could not locate project root for development backend startup. \
            Set JOBTRACKER_PROJECT_ROOT to your repo path and retry.
            """
            return
        }

        let backendPath = URL(fileURLWithPath: projectRoot)
            .appendingPathComponent("backend")
            .path
        let launcherPath = URL(fileURLWithPath: projectRoot)
            .appendingPathComponent("scripts/start_backend.sh")
            .path
        let process = Process()
        let environment = developmentEnvironment(projectRoot: projectRoot)
        if FileManager.default.isExecutableFile(atPath: launcherPath) {
            process.currentDirectoryURL = URL(fileURLWithPath: projectRoot)
            process.executableURL = URL(fileURLWithPath: "/bin/bash")
            process.arguments = [
                launcherPath,
                "--host",
                "127.0.0.1",
                "--port",
                String(backendPort),
            ]
        } else {
            let pythonPath = preferredPythonPath(in: backendPath)
            process.currentDirectoryURL = URL(fileURLWithPath: backendPath)
            process.executableURL = URL(fileURLWithPath: pythonPath)
            process.arguments = [
                "-m",
                "uvicorn",
                "jobtracker.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                String(backendPort),
            ]
        }

        process.environment = environment

        let stdoutURL = backendLogURL(fileName: "backend-dev.log")
        let stderrURL = backendLogURL(fileName: "backend-dev-error.log")
        let stdoutHandle = makeAppendFileHandle(at: stdoutURL) ?? FileHandle.nullDevice
        let stderrHandle = makeAppendFileHandle(at: stderrURL) ?? FileHandle.nullDevice
        process.standardOutput = stdoutHandle
        process.standardError = stderrHandle
        process.terminationHandler = { [weak self] finishedProcess in
            try? stdoutHandle.close()
            try? stderrHandle.close()

            let stderrTail = BackendLifecycleManager.readLogTail(from: stderrURL, maxBytes: 4096)
            Task { @MainActor [weak self] in
                guard let self else { return }
                if self.devBackendProcess === finishedProcess {
                    self.devBackendProcess = nil
                }
                guard finishedProcess.terminationStatus != 0 else {
                    return
                }

                if stderrTail.localizedCaseInsensitiveContains("address already in use") {
                    self.lastErrorMessage =
                        "Backend failed to start because port \(self.backendPort) is already in use."
                } else if stderrTail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    self.lastErrorMessage =
                        "Backend exited with status \(finishedProcess.terminationStatus). See \(stderrURL.path)"
                } else {
                    self.lastErrorMessage =
                        "Backend exited with status \(finishedProcess.terminationStatus): \(stderrTail)"
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

    private func isBackendHealthy(retries: Int = 1, delaySeconds: Double = 0.3) async -> Bool {
        for _ in 0..<max(1, retries) {
            if let health = try? await BackendAPIClient.shared.fetchHealth(),
               health.status == "ok"
            {
                return true
            }

            if delaySeconds > 0 {
                try? await Task.sleep(nanoseconds: UInt64(delaySeconds * 1_000_000_000))
            }
        }
        return false
    }

    private func resolveProjectRootForDevelopment() -> String? {
        let fileManager = FileManager.default
        let environment = ProcessInfo.processInfo.environment

        var candidates: [String] = []
        if let fromEnv = environment["JOBTRACKER_PROJECT_ROOT"], !fromEnv.isEmpty {
            candidates.append((fromEnv as NSString).expandingTildeInPath)
        }

        let defaultProjectsPath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/Projects/applied")
            .path
        candidates.append(defaultProjectsPath)
        candidates.append(fileManager.currentDirectoryPath)
        candidates.append((fileManager.currentDirectoryPath as NSString).deletingLastPathComponent)

        for candidate in candidates {
            let marker = URL(fileURLWithPath: candidate)
                .appendingPathComponent("backend/jobtracker/main.py")
                .path
            if fileManager.fileExists(atPath: marker) {
                return candidate
            }
        }

        return nil
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
        let directory = backendLogDirectoryURL()

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

    private func backendLogDirectoryURL() -> URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/JobTracker", isDirectory: true)
    }

    private func backendLogURL(fileName: String) -> URL {
        backendLogDirectoryURL().appendingPathComponent(fileName)
    }

    private func makeAppendFileHandle(at url: URL) -> FileHandle? {
        do {
            try FileManager.default.createDirectory(
                at: backendLogDirectoryURL(),
                withIntermediateDirectories: true
            )
            if !FileManager.default.fileExists(atPath: url.path) {
                FileManager.default.createFile(atPath: url.path, contents: nil)
            }

            let handle = try FileHandle(forWritingTo: url)
            try handle.seekToEnd()
            return handle
        } catch {
            return nil
        }
    }

    private func developmentEnvironment(projectRoot: String) -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        let currentPATH = env["PATH"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if currentPATH.isEmpty {
            env["PATH"] = developmentPATH
        } else if !currentPATH.contains("/opt/homebrew/bin") {
            env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:\(currentPATH)"
        }

        env["JOBTRACKER_PROJECT_ROOT"] = projectRoot
        env["JOBTRACKER_AUTO_BOOTSTRAP"] = "1"
        return env
    }

    private func preferredPythonPath(in backendPath: String) -> String {
        let candidates = [
            "\(backendPath)/.venv311/bin/python",
            "\(backendPath)/.venv/bin/python",
            "/usr/bin/python3",
        ]

        for candidate in candidates where FileManager.default.isExecutableFile(atPath: candidate) {
            return candidate
        }

        return "/usr/bin/python3"
    }

    private var developmentPATH: String {
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }

    nonisolated private static func readLogTail(from url: URL, maxBytes: Int) -> String {
        guard let data = try? Data(contentsOf: url), !data.isEmpty else {
            return ""
        }

        let slice: Data
        if data.count > maxBytes {
            slice = data.subdata(in: (data.count - maxBytes)..<data.count)
        } else {
            slice = data
        }
        return String(data: slice, encoding: .utf8) ?? ""
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

    private func isLocalPortReachable(_ port: UInt16) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        if fd == -1 {
            return false
        }
        defer { close(fd) }

        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.stride)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = port.bigEndian
        addr.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        let connectResult = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPtr in
                Darwin.connect(fd, sockaddrPtr, socklen_t(MemoryLayout<sockaddr_in>.stride))
            }
        }

        return connectResult == 0
    }
}
