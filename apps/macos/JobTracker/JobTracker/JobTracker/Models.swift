import Foundation

// MARK: - Applications list models

struct ApplicationSummary: Identifiable, Decodable {
    let id: Int
    let company: String
    let position: String
    let status: String
    let appliedDate: String?
    let emailCount: Int

    private enum CodingKeys: String, CodingKey {
        case id
        case company
        case position
        case status
        case appliedDate = "applied_date"
        case emailCount = "email_count"
    }
}

struct ApplicationListResponse: Decodable {
    let applications: [ApplicationSummary]
    let total: Int
    let page: Int
    let pageSize: Int

    private enum CodingKeys: String, CodingKey {
        case applications
        case total
        case page
        case pageSize = "page_size"
    }
}

struct ApplicationsOverviewResponse: Decodable {
    let totalApplications: Int
    let byStatus: [String: Int]
    let emailsLinked: Int
    let emailsUnlinked: Int

    private enum CodingKeys: String, CodingKey {
        case totalApplications = "total_applications"
        case byStatus = "by_status"
        case emailsLinked = "emails_linked"
        case emailsUnlinked = "emails_unlinked"
    }
}

// MARK: - Application detail models

struct ApplicationEmail: Identifiable, Decodable {
    let id: Int
    let subject: String?
    let sender: String?
    let receivedAt: String?
    let classification: String?
    let confidence: Double?
    let bodySnippet: String?
    let bodyText: String?
    let bodyHtml: String?

    private enum CodingKeys: String, CodingKey {
        case id, subject, sender, classification, confidence
        case receivedAt = "received_at"
        case bodySnippet = "body_snippet"
        case bodyText = "body_text"
        case bodyHtml = "body_html"
    }
}

struct ApplicationDetail: Decodable {
    let id: Int
    let company: String
    let position: String
    let status: String
    let appliedDate: String?
    let source: String?
    let url: String?
    let notes: String?
    let createdAt: String
    let updatedAt: String?
    let emailCount: Int
    let emails: [ApplicationEmail]

    private enum CodingKeys: String, CodingKey {
        case id, company, position, status, source, url, notes, emails
        case appliedDate = "applied_date"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case emailCount = "email_count"
    }
}

// MARK: - Health / system models

struct ClassifierStatus: Decodable {
    let activeLayers: [String]
    let setfitTrained: Bool

    private enum CodingKeys: String, CodingKey {
        case activeLayers = "active_layers"
        case setfitTrained = "setfit_trained"
    }
}

struct HealthResponse: Decodable {
    let status: String
    let version: String
    let environment: String
    let dbConnected: Bool
    let gmailConnected: Bool
    let icloudConnected: Bool
    let lastSync: String?
    let classifierStatus: ClassifierStatus

    private enum CodingKeys: String, CodingKey {
        case status
        case version
        case environment
        case dbConnected = "db_connected"
        case gmailConnected = "gmail_connected"
        case icloudConnected = "icloud_connected"
        case lastSync = "last_sync"
        case classifierStatus = "classifier_status"
    }
}

// MARK: - Review queue models

struct ReviewEmail: Identifiable, Decodable {
    let id: Int
    let subject: String?
    let senderEmail: String?
    let senderName: String?
    let snippet: String?
    let bodyText: String?
    let bodyHtml: String?
    let currentCategory: String
    let confidence: Double
    let receivedAt: String?

    private enum CodingKeys: String, CodingKey {
        case id, subject, snippet, confidence
        case senderEmail = "sender_email"
        case senderName = "sender_name"
        case bodyText = "body_text"
        case bodyHtml = "body_html"
        case currentCategory = "current_category"
        case receivedAt = "received_at"
    }
}

struct NeedsReviewResponse: Decodable {
    let emails: [ReviewEmail]
    let totalCount: Int

    private enum CodingKeys: String, CodingKey {
        case emails
        case totalCount = "total_count"
    }
}

// MARK: - Inbox models

struct InboxEmailSummary: Identifiable, Decodable {
    let id: Int
    let applicationID: Int?
    let sourceAccount: String
    let messageID: String
    let threadID: String?
    let subject: String
    let senderName: String?
    let senderEmail: String
    let receivedAt: String
    let bodySnippet: String
    let classifiedAs: String?
    let classificationConfidence: Double?
    let classificationMethod: String?
    let userCorrected: Bool
    let isReviewed: Bool
    let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id, subject
        case applicationID = "application_id"
        case sourceAccount = "source_account"
        case messageID = "message_id"
        case threadID = "thread_id"
        case senderName = "sender_name"
        case senderEmail = "sender_email"
        case receivedAt = "received_at"
        case bodySnippet = "body_snippet"
        case classifiedAs = "classified_as"
        case classificationConfidence = "classification_confidence"
        case classificationMethod = "classification_method"
        case userCorrected = "user_corrected"
        case isReviewed = "is_reviewed"
        case createdAt = "created_at"
    }
}

struct InboxEmailListResponse: Decodable {
    let emails: [InboxEmailSummary]
    let total: Int
    let page: Int
    let pageSize: Int
    let hasMore: Bool

    private enum CodingKeys: String, CodingKey {
        case emails, total, page
        case pageSize = "page_size"
        case hasMore = "has_more"
    }
}

struct InboxEmailDetail: Identifiable, Decodable {
    let id: Int
    let applicationID: Int?
    let sourceAccount: String
    let messageID: String
    let threadID: String?
    let subject: String
    let senderName: String?
    let senderEmail: String
    let receivedAt: String
    let bodyText: String
    let bodyHtml: String?
    let bodySnippet: String
    let classifiedAs: String?
    let classificationConfidence: Double?
    let classificationMethod: String?
    let userCorrected: Bool
    let isReviewed: Bool
    let createdAt: String

    private enum CodingKeys: String, CodingKey {
        case id, subject
        case applicationID = "application_id"
        case sourceAccount = "source_account"
        case messageID = "message_id"
        case threadID = "thread_id"
        case senderName = "sender_name"
        case senderEmail = "sender_email"
        case receivedAt = "received_at"
        case bodyText = "body_text"
        case bodyHtml = "body_html"
        case bodySnippet = "body_snippet"
        case classifiedAs = "classified_as"
        case classificationConfidence = "classification_confidence"
        case classificationMethod = "classification_method"
        case userCorrected = "user_corrected"
        case isReviewed = "is_reviewed"
        case createdAt = "created_at"
    }
}

// MARK: - Auth / sync models

struct AccountStatus: Decodable {
    let connected: Bool
    let email: String?
}

struct AuthStatusResponse: Decodable {
    let gmail: AccountStatus
    let icloud: AccountStatus
}

struct SyncResultResponse: Decodable {
    let success: Bool
    let accountsSynced: [String]
    let emailsFetched: Int
    let emailsSaved: Int
    let emailsSkipped: Int
    let errors: [String]
    let durationSeconds: Double

    private enum CodingKeys: String, CodingKey {
        case success
        case accountsSynced = "accounts_synced"
        case emailsFetched = "emails_fetched"
        case emailsSaved = "emails_saved"
        case emailsSkipped = "emails_skipped"
        case errors
        case durationSeconds = "duration_seconds"
    }
}

struct LiteModeStateResponse: Decodable {
    let enabled: Bool
    let setfitAvailable: Bool
    let disabledByLiteMode: Bool

    private enum CodingKeys: String, CodingKey {
        case enabled
        case setfitAvailable = "setfit_available"
        case disabledByLiteMode = "disabled_by_lite_mode"
    }
}

struct CorrectionResponse: Decodable {
    let success: Bool
    let message: String
    let category: String?
}

struct MarkNotJobResponse: Decodable {
    let success: Bool
    let applicationID: Int
    let emailsReclassified: Int
    let message: String

    private enum CodingKeys: String, CodingKey {
        case success
        case message
        case applicationID = "application_id"
        case emailsReclassified = "emails_reclassified"
    }
}

// MARK: - Analytics models

struct AnalyticsOverviewResponse: Decodable {
    struct WeekSummary: Decodable {
        let applied: Int
        let responsesReceived: Int
        let interviewsScheduled: Int

        private enum CodingKeys: String, CodingKey {
            case applied
            case responsesReceived = "responses_received"
            case interviewsScheduled = "interviews_scheduled"
        }
    }

    let totalApplications: Int
    let byStatus: [String: Int]
    let responseRate: Double
    let avgResponseDays: Double?
    let thisWeek: WeekSummary

    private enum CodingKeys: String, CodingKey {
        case totalApplications = "total_applications"
        case byStatus = "by_status"
        case responseRate = "response_rate"
        case avgResponseDays = "avg_response_days"
        case thisWeek = "this_week"
    }
}

struct AnalyticsTrendPoint: Decodable, Identifiable {
    var id: String { periodStart }

    let periodStart: String
    let applied: Int
    let rejected: Int
    let interviews: Int
    let offers: Int

    private enum CodingKeys: String, CodingKey {
        case periodStart = "period_start"
        case applied
        case rejected
        case interviews
        case offers
    }
}

struct AnalyticsTrendsResponse: Decodable {
    let period: String
    let months: Int
    let data: [AnalyticsTrendPoint]
}

// MARK: - Auth flow models

struct GmailClientSecretResponse: Decodable {
    let success: Bool
    let message: String
}

struct GmailAuthenticateResponse: Decodable {
    let success: Bool
    let email: String?
    let message: String
}

struct ICloudAuthenticateResponse: Decodable {
    let success: Bool
    let email: String?
    let message: String
}
