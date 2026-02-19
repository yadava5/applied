import Foundation
import Observation

struct SyncSocketEvent: Identifiable {
    let id = UUID()
    let event: String
    let timestamp: String?
    let message: String?
    let account: String?
    let emailsSaved: Int?
    let emailsFetched: Int?
}

@MainActor
@Observable
final class SyncWebSocketClient {
    enum ConnectionState: String {
        case disconnected
        case connecting
        case connected
        case error
    }

    private(set) var state: ConnectionState = .disconnected
    private(set) var lastEvent: SyncSocketEvent?
    private(set) var lastErrorMessage: String?

    var onEvent: ((SyncSocketEvent) -> Void)?

    @ObservationIgnored private var socketTask: URLSessionWebSocketTask?
    @ObservationIgnored private let session: URLSession
    @ObservationIgnored private let websocketURL = URL(string: "ws://127.0.0.1:8000/ws/sync-status")!
    @ObservationIgnored private var reconnectTask: Task<Void, Never>?
    @ObservationIgnored private var reconnectAttempt = 0
    @ObservationIgnored private var shouldReconnect = false

    @ObservationIgnored private let maxReconnectDelay: TimeInterval = 30
    @ObservationIgnored private let baseReconnectDelay: TimeInterval = 1

    init() {
        session = URLSession(configuration: .default)
    }

    func connect() {
        shouldReconnect = true
        reconnectTask?.cancel()
        reconnectTask = nil
        reconnectAttempt = 0
        openSocketIfNeeded()
    }

    func disconnect() {
        shouldReconnect = false
        reconnectTask?.cancel()
        reconnectTask = nil
        closeSocket(with: .normalClosure)
        state = .disconnected
    }

    func sendPing() {
        guard let socketTask else { return }

        socketTask.send(.string("ping")) { [weak self] error in
            guard let self else { return }
            guard let error else { return }
            Task { @MainActor in
                self.handleSocketFailure(error)
            }
        }
    }

    private func openSocketIfNeeded() {
        guard socketTask == nil else { return }

        state = .connecting
        lastErrorMessage = nil

        let task = session.webSocketTask(with: websocketURL)
        socketTask = task
        task.resume()
        state = .connected
        receiveLoop()
    }

    private func closeSocket(with code: URLSessionWebSocketTask.CloseCode) {
        socketTask?.cancel(with: code, reason: nil)
        socketTask = nil
    }

    private func receiveLoop() {
        guard let socketTask else { return }

        socketTask.receive { [weak self] result in
            guard let self else { return }

            switch result {
            case .failure(let error):
                Task { @MainActor in
                    self.handleSocketFailure(error)
                }
            case .success(let message):
                Task { @MainActor in
                    self.handle(message: message)
                    self.receiveLoop()
                }
            }
        }
    }

    private func handleSocketFailure(_ error: Error) {
        lastErrorMessage = error.localizedDescription
        state = .error
        closeSocket(with: .goingAway)

        scheduleReconnectIfNeeded()
    }

    private func scheduleReconnectIfNeeded() {
        guard shouldReconnect else { return }

        reconnectTask?.cancel()

        let exponential = baseReconnectDelay * pow(2.0, Double(reconnectAttempt))
        let capped = min(exponential, maxReconnectDelay)
        let jitter = Double.random(in: 0.0...0.6)
        let delay = capped + jitter

        reconnectAttempt = min(reconnectAttempt + 1, 8)

        reconnectTask = Task { [weak self] in
            guard let self else { return }

            let ns = UInt64(delay * 1_000_000_000)
            try? await Task.sleep(nanoseconds: ns)

            guard !Task.isCancelled else { return }
            await MainActor.run {
                guard self.shouldReconnect else { return }
                self.openSocketIfNeeded()
            }
        }
    }

    private func resetReconnectBackoff() {
        reconnectAttempt = 0
        reconnectTask?.cancel()
        reconnectTask = nil
    }

    private func handle(message: URLSessionWebSocketTask.Message) {
        let data: Data?
        switch message {
        case .string(let text):
            data = text.data(using: .utf8)
        case .data(let payload):
            data = payload
        @unknown default:
            data = nil
        }

        guard
            let data,
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return
        }

        let event = SyncSocketEvent(
            event: json["event"] as? String ?? "unknown",
            timestamp: json["timestamp"] as? String,
            message: json["message"] as? String,
            account: json["account"] as? String,
            emailsSaved: json["emails_saved"] as? Int,
            emailsFetched: json["emails_fetched"] as? Int
        )

        if event.event == "connected" || event.event == "heartbeat" || event.event == "started" {
            resetReconnectBackoff()
            state = .connected
            lastErrorMessage = nil
        }

        lastEvent = event
        onEvent?(event)
    }
}
