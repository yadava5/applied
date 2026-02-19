import Foundation

final class BackendAPIClient {
    static let shared = BackendAPIClient()

    // Adjust if you change backend host/port
    private let baseURL = URL(string: "http://127.0.0.1:8000")!
    private let maxBackendPageSize = 100
    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    // MARK: - Core request helpers

    private func decodeResponse<T: Decodable>(
        _ type: T.Type,
        from data: Data,
        response: URLResponse
    ) throws -> T {
        guard let http = response as? HTTPURLResponse else {
            throw NSError(
                domain: "BackendAPIClient",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Invalid server response"]
            )
        }

        guard (200...299).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? "Unknown backend error"
            throw NSError(
                domain: "BackendAPIClient",
                code: http.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode): \(body)"]
            )
        }

        let decoder = JSONDecoder()
        return try decoder.decode(type, from: data)
    }

    private func decodeEmptySuccess(response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw NSError(
                domain: "BackendAPIClient",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Invalid server response"]
            )
        }

        guard (200...299).contains(http.statusCode) else {
            throw NSError(
                domain: "BackendAPIClient",
                code: http.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "HTTP \(http.statusCode)"]
            )
        }
    }

    // MARK: - Applications

    func fetchApplications(
        page: Int = 1,
        pageSize: Int = 50,
        status: String? = nil,
        company: String? = nil,
        search: String? = nil
    ) async throws -> ApplicationListResponse {
        let safePageSize = min(max(pageSize, 1), maxBackendPageSize)
        var components = URLComponents(
            url: baseURL.appendingPathComponent("/applications"),
            resolvingAgainstBaseURL: false
        )!

        var queryItems = [
            URLQueryItem(name: "page", value: String(page)),
            URLQueryItem(name: "page_size", value: String(safePageSize))
        ]
        if let status, !status.isEmpty {
            queryItems.append(URLQueryItem(name: "status", value: status))
        }
        if let company, !company.isEmpty {
            queryItems.append(URLQueryItem(name: "company", value: company))
        }
        if let search, !search.isEmpty {
            queryItems.append(URLQueryItem(name: "search", value: search))
        }
        components.queryItems = queryItems

        let (data, response) = try await session.data(from: components.url!)
        return try decodeResponse(ApplicationListResponse.self, from: data, response: response)
    }

    func fetchApplicationDetail(id: Int) async throws -> ApplicationDetail {
        let url = baseURL.appendingPathComponent("/applications/\(id)")
        let (data, response) = try await session.data(from: url)
        return try decodeResponse(ApplicationDetail.self, from: data, response: response)
    }

    func updateApplicationStatus(id: Int, status: String) async throws -> ApplicationSummary {
        struct UpdatePayload: Encodable {
            let status: String
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("/applications/\(id)"))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(UpdatePayload(status: status))

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(ApplicationSummary.self, from: data, response: response)
    }

    func updateApplicationNotes(id: Int, notes: String) async throws -> ApplicationSummary {
        struct UpdatePayload: Encodable {
            let notes: String
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("/applications/\(id)"))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(UpdatePayload(notes: notes))

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(ApplicationSummary.self, from: data, response: response)
    }

    func deleteApplication(id: Int) async throws {
        var request = URLRequest(url: baseURL.appendingPathComponent("/applications/\(id)"))
        request.httpMethod = "DELETE"

        let (_, response) = try await session.data(for: request)
        try decodeEmptySuccess(response: response)
    }

    func markApplicationNotJobPosting(id: Int) async throws -> MarkNotJobResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("/applications/\(id)/mark-not-job"))
        request.httpMethod = "POST"

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(MarkNotJobResponse.self, from: data, response: response)
    }

    func fetchApplicationsOverview() async throws -> ApplicationsOverviewResponse {
        let url = baseURL.appendingPathComponent("/applications/stats/overview")
        let (data, response) = try await session.data(from: url)
        return try decodeResponse(ApplicationsOverviewResponse.self, from: data, response: response)
    }

    // MARK: - Health / auth / sync

    func fetchHealth() async throws -> HealthResponse {
        let url = baseURL.appendingPathComponent("/health")
        let (data, response) = try await session.data(from: url)
        return try decodeResponse(HealthResponse.self, from: data, response: response)
    }

    func fetchAuthStatus() async throws -> AuthStatusResponse {
        let url = baseURL.appendingPathComponent("/auth/status")
        let (data, response) = try await session.data(from: url)
        return try decodeResponse(AuthStatusResponse.self, from: data, response: response)
    }

    func triggerSync(
        accounts: [String]? = nil,
        sinceDate: Date? = nil,
        fullSync: Bool = false
    ) async throws -> SyncResultResponse {
        struct SyncRequest: Encodable {
            let accounts: [String]?
            let sinceDate: String?
            let fullSync: Bool

            enum CodingKeys: String, CodingKey {
                case accounts
                case sinceDate = "since_date"
                case fullSync = "full_sync"
            }
        }

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]

        let payload = SyncRequest(
            accounts: accounts,
            sinceDate: sinceDate.map { formatter.string(from: $0) },
            fullSync: fullSync
        )

        var request = URLRequest(url: baseURL.appendingPathComponent("/sync"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(SyncResultResponse.self, from: data, response: response)
    }

    // MARK: - Analytics

    func fetchAnalyticsOverview() async throws -> AnalyticsOverviewResponse {
        let url = baseURL.appendingPathComponent("/analytics/overview")
        let (data, response) = try await session.data(from: url)
        return try decodeResponse(AnalyticsOverviewResponse.self, from: data, response: response)
    }

    func fetchAnalyticsTrends(period: String = "weekly", months: Int = 3) async throws -> AnalyticsTrendsResponse {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("/analytics/trends"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [
            URLQueryItem(name: "period", value: period),
            URLQueryItem(name: "months", value: String(months))
        ]

        let (data, response) = try await session.data(from: components.url!)
        return try decodeResponse(AnalyticsTrendsResponse.self, from: data, response: response)
    }

    // MARK: - Account authentication management

    func setGmailClientSecret(_ jsonText: String) async throws -> GmailClientSecretResponse {
        struct Payload: Encodable {
            let clientSecret: [String: AnyCodable]

            enum CodingKeys: String, CodingKey {
                case clientSecret = "client_secret"
            }
        }

        guard
            let data = jsonText.data(using: .utf8),
            let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            throw NSError(
                domain: "BackendAPIClient",
                code: -1,
                userInfo: [NSLocalizedDescriptionKey: "Client secret JSON is invalid."]
            )
        }

        let wrapped = object.mapValues { AnyCodable($0) }
        let payload = Payload(clientSecret: wrapped)

        var request = URLRequest(url: baseURL.appendingPathComponent("/auth/gmail/client-secret"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)

        let (responseData, response) = try await session.data(for: request)
        return try decodeResponse(GmailClientSecretResponse.self, from: responseData, response: response)
    }

    func authenticateGmail() async throws -> GmailAuthenticateResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("/auth/gmail/authenticate"))
        request.httpMethod = "POST"

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(GmailAuthenticateResponse.self, from: data, response: response)
    }

    func disconnectGmail(deleteEmails: Bool = false) async throws -> CorrectionResponse {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("/auth/gmail"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [URLQueryItem(name: "delete_emails", value: deleteEmails ? "true" : "false")]

        var request = URLRequest(url: components.url!)
        request.httpMethod = "DELETE"

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(CorrectionResponse.self, from: data, response: response)
    }

    func connectICloud(email: String, appPassword: String) async throws -> ICloudAuthenticateResponse {
        struct Payload: Encodable {
            let email: String
            let appPassword: String

            enum CodingKeys: String, CodingKey {
                case email
                case appPassword = "app_password"
            }
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("/auth/icloud"))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(Payload(email: email, appPassword: appPassword))

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(ICloudAuthenticateResponse.self, from: data, response: response)
    }

    func disconnectICloud(deleteEmails: Bool = false) async throws -> CorrectionResponse {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("/auth/icloud"),
            resolvingAgainstBaseURL: false
        )!
        components.queryItems = [URLQueryItem(name: "delete_emails", value: deleteEmails ? "true" : "false")]

        var request = URLRequest(url: components.url!)
        request.httpMethod = "DELETE"

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(CorrectionResponse.self, from: data, response: response)
    }

    // MARK: - Review queue / classification

    func fetchNeedsReview(limit: Int = 50, offset: Int = 0) async throws -> NeedsReviewResponse {
        var components = URLComponents(
            url: baseURL.appendingPathComponent("/classify/needs-review"),
            resolvingAgainstBaseURL: false
        )!

        components.queryItems = [
            URLQueryItem(name: "limit", value: String(limit)),
            URLQueryItem(name: "offset", value: String(offset))
        ]

        let (data, response) = try await session.data(from: components.url!)
        return try decodeResponse(NeedsReviewResponse.self, from: data, response: response)
    }

    func fetchEmails(
        page: Int = 1,
        pageSize: Int = 50,
        source: String? = nil,
        classification: String? = nil,
        unreviewedOnly: Bool = false,
        search: String? = nil
    ) async throws -> InboxEmailListResponse {
        let safePageSize = min(max(pageSize, 1), maxBackendPageSize)
        var components = URLComponents(
            url: baseURL.appendingPathComponent("/emails"),
            resolvingAgainstBaseURL: false
        )!

        var queryItems = [
            URLQueryItem(name: "page", value: String(page)),
            URLQueryItem(name: "page_size", value: String(safePageSize)),
            URLQueryItem(name: "unreviewed_only", value: unreviewedOnly ? "true" : "false"),
        ]
        if let source, !source.isEmpty {
            queryItems.append(URLQueryItem(name: "source", value: source))
        }
        if let classification, !classification.isEmpty {
            queryItems.append(URLQueryItem(name: "classification", value: classification))
        }
        if let search, !search.isEmpty {
            queryItems.append(URLQueryItem(name: "search", value: search))
        }
        components.queryItems = queryItems

        let (data, response) = try await session.data(from: components.url!)
        return try decodeResponse(InboxEmailListResponse.self, from: data, response: response)
    }

    func fetchEmailDetail(id: Int) async throws -> InboxEmailDetail {
        let url = baseURL.appendingPathComponent("/emails/\(id)")
        let (data, response) = try await session.data(from: url)
        return try decodeResponse(InboxEmailDetail.self, from: data, response: response)
    }

    func correctEmailClassification(emailID: Int, category: String) async throws -> CorrectionResponse {
        struct CorrectionRequest: Encodable {
            let category: String
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("/classify/email/\(emailID)/correct"))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(CorrectionRequest(category: category))

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(CorrectionResponse.self, from: data, response: response)
    }

    func approveEmailClassification(emailID: Int) async throws -> CorrectionResponse {
        var request = URLRequest(url: baseURL.appendingPathComponent("/classify/needs-review/\(emailID)/approve"))
        request.httpMethod = "POST"

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(CorrectionResponse.self, from: data, response: response)
    }

    func fetchLiteModeState() async throws -> LiteModeStateResponse {
        let url = baseURL.appendingPathComponent("/classify/lite-mode")
        let (data, response) = try await session.data(from: url)
        return try decodeResponse(LiteModeStateResponse.self, from: data, response: response)
    }

    func setLiteMode(enabled: Bool) async throws -> LiteModeStateResponse {
        struct LiteModeRequest: Encodable {
            let enabled: Bool
        }

        var request = URLRequest(url: baseURL.appendingPathComponent("/classify/lite-mode"))
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(LiteModeRequest(enabled: enabled))

        let (data, response) = try await session.data(for: request)
        return try decodeResponse(LiteModeStateResponse.self, from: data, response: response)
    }
}

// MARK: - AnyCodable helper for arbitrary JSON payloads

private struct AnyCodable: Encodable {
    private let value: Any

    init(_ value: Any) {
        self.value = value
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()

        switch value {
        case let intValue as Int:
            try container.encode(intValue)
        case let doubleValue as Double:
            try container.encode(doubleValue)
        case let boolValue as Bool:
            try container.encode(boolValue)
        case let stringValue as String:
            try container.encode(stringValue)
        case let arrayValue as [Any]:
            try container.encode(arrayValue.map { AnyCodable($0) })
        case let dictionaryValue as [String: Any]:
            try container.encode(dictionaryValue.mapValues { AnyCodable($0) })
        default:
            try container.encodeNil()
        }
    }
}
