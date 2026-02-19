import Foundation
import GRDB
import GRDBQuery

@MainActor
final class LocalDatabaseProvider {
    let databaseContext: DatabaseContext
    let databasePath: String

    init() {
        let resolvedPath = ("~/Library/Application Support/JobTracker/jobtracker.db" as NSString)
            .expandingTildeInPath
        databasePath = resolvedPath
        databaseContext = .readWrite {
            var configuration = Configuration()
            configuration.readonly = false
            return try DatabaseQueue(path: resolvedPath, configuration: configuration)
        }
    }
}

struct LocalApplicationsCountRequest: ValueObservationQueryable {
    static var defaultValue: Int { 0 }

    func fetch(_ db: Database) throws -> Int {
        try Int.fetchOne(db, sql: "SELECT COUNT(*) FROM applications") ?? 0
    }
}

struct LocalNeedsReviewCountRequest: ValueObservationQueryable {
    static var defaultValue: Int { 0 }

    func fetch(_ db: Database) throws -> Int {
        try Int.fetchOne(
            db,
            sql: """
            SELECT COUNT(*) FROM emails
            WHERE UPPER(classified_as) = 'NEEDS_REVIEW'
               OR (
                    UPPER(classified_as) IN ('APPLIED', 'INTERVIEW', 'REJECTION', 'OFFER', 'ASSESSMENT', 'FOLLOW_UP')
                    AND classification_confidence IS NOT NULL
                    AND classification_confidence < 0.70
                    AND user_corrected = 0
               )
            """
        ) ?? 0
    }
}
