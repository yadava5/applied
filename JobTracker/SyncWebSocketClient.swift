import Combine
import Foundation

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
final class SyncWebSocketClient: ObservableObject {
    enum ConnectionState: String {
        case disconnected
        case connecting
        case connected
        case error
    }

    @Published private(set) var state: ConnectionState = .disconnected
    @Published private(set) var lastEvent: SyncSocketEvent?
    @Published private(set) var lastErrorMessage: String?

    var onEvent: ((SyncSocketEvent) -> Void)?

    private var socketTask: URLSessionWebSocketTask?
    private let session: URLSession
    private let websocketURL = URL(string: "ws://127.0.0.1:8000/ws/sync-status")!

    init() {
        session = URLSession(configuration: .default)
    }

    func connect() {
        guard socketTask == nil else { return }

        state = .connecting
        let task = session.webSocketTask(with: websocketURL)
        socketTask = task
        task.resume()
        state = .connected
        receiveLoop()
    }

    func disconnect() {
        socketTask?.cancel(with: .normalClosure, reason: nil)
        socketTask = nil
        state = .disconnected
    }

    func sendPing() {
        guard let socketTask else { return }
        socketTask.send(.string("ping")) { [weak self] error in
            guard let self else { return }
            if let error {
                Task { @MainActor in
                    self.state = .error
                    self.lastErrorMessage = error.localizedDescription
                }
            }
        }
    }

    private func receiveLoop() {
        guard let socketTask else { return }
        socketTask.receive { [weak self] result in
            guard let self else { return }

            switch result {
            case .failure(let error):
                Task { @MainActor in
                    self.state = .error
                    self.lastErrorMessage = error.localizedDescription
                    self.socketTask = nil
                }
            case .success(let message):
                Task { @MainActor in
                    self.handle(message: message)
                    self.receiveLoop()
                }
            }
        }
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
        lastEvent = event
        onEvent?(event)
    }
}
