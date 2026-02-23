# API Specification

Base URL: `http://127.0.0.1:8000`

All endpoints return JSON.

## Health

### `GET /health`

Returns backend, DB, account, and classifier status.

## Auth

### `GET /auth/status`

Returns Gmail/iCloud connected flags and account email values.

### `POST /auth/gmail/client-secret`

Store Google OAuth desktop client secret.

Request body:

```json
{
  "client_secret": {
    "installed": {
      "client_id": "...",
      "client_secret": "...",
      "auth_uri": "https://accounts.google.com/o/oauth2/auth",
      "token_uri": "https://oauth2.googleapis.com/token"
    }
  }
}
```

### `POST /auth/gmail/authenticate`

Starts Gmail OAuth flow.

### `DELETE /auth/gmail?delete_emails=false`

Disconnect Gmail credentials. Optional email cleanup with `delete_emails=true`.

### `POST /auth/icloud`

Connect iCloud using app-specific password.

Request body:

```json
{
  "email": "user@icloud.com",
  "app_password": "xxxx-xxxx-xxxx-xxxx"
}
```

### `DELETE /auth/icloud?delete_emails=false`

Disconnect iCloud credentials. Optional email cleanup with `delete_emails=true`.

## Sync

### `POST /sync`

Trigger sync.

Request body:

```json
{
  "accounts": ["gmail", "icloud"],
  "since_date": "2026-02-01T00:00:00Z",
  "full_sync": false
}
```

Notes:

- `accounts` can be omitted to sync all connected accounts.
- `since_date` can be omitted.
- `full_sync=true` ignores last incremental position.

### `GET /sync/status`

Returns latest Gmail/iCloud sync state and `last_sync`.

## Emails

### `GET /emails`

Query params:

- `page` (default `1`)
- `page_size` (default `50`, max `100`)
- `source` (`gmail` | `icloud`)
- `classification` (category string)
- `unreviewed_only` (`true` | `false`)
- `unlinked_only` (`true` | `false`)
- `search` (full-text + fallback search)

Compatibility aliases accepted (hidden from schema):

- `unreviewed`
- `unlinked`

Response includes pagination metadata and each email includes `application_id` for linkage-aware UI filtering.

### `GET /emails/stats`

Returns totals by source/category and unreviewed count.

### `GET /emails/{email_id}`

Returns full email body and metadata.

### `PUT /emails/{email_id}/review`

Marks an email as reviewed.

### `DELETE /emails/{email_id}`

Deletes one email from local JobTracker DB.

### `DELETE /emails`

Bulk delete with filters.

Query params:

- `source`
- `sender_email`
- `before_date`
- `after_date`
- `confirm`

Safety behavior:

- If `confirm=false` (default), endpoint returns preview count only.

## Classification and Review

### `POST /classify`

Classifies arbitrary text payload (testing/debug endpoint).

### `POST /classify/email/{email_id}`

Classifies and updates one stored email.

### `PUT /classify/email/{email_id}/correct`

Applies user correction, marks reviewed, and appends training data.

Request body:

```json
{
  "category": "pending_application"
}
```

### `POST /classify/batch`

Batch-classifies emails.

Query params:

- `limit` (default `100`)
- `unclassified_only` (default `true`)
- `force_reclassify` (default `false`)

### `GET /classify/status`

Classifier layer status (rules, embeddings, setfit).

### `GET /classify/lite-mode`

Current lite-mode state.

### `PUT /classify/lite-mode`

Enable/disable lite mode (`setfit` disabled when enabled).

### `POST /classify/retrain`

Triggers SetFit retraining in background.

### `POST /classify/seed-training-data`

Seeds training data from high-confidence rule classifications.

### `GET /classify/needs-review`

Returns low-confidence job-related emails and explicit `needs_review` items.

Query params:

- `limit`
- `offset`

### `GET /classify/needs-review/count`

Returns review queue count.

### `POST /classify/needs-review/{email_id}/approve`

Approves current category and feeds confirmed example into training data.

## Applications

### `GET /applications`

List applications.

Query params:

- `page` (default `1`)
- `page_size` (default `20`, max `100`)
- `status`
- `company`
- `search`

### `GET /applications/{application_id}`

Get single application with linked email list.

### `POST /applications`

Create application.

### `PUT /applications/{application_id}`

Update fields (`company`, `position`, `status`, `applied_date`, `source`, `url`, `notes`).

### `DELETE /applications/{application_id}`

Delete application and unlink emails.

### `POST /applications/{application_id}/status`

Transition status with payload:

```json
{
  "new_status": "interviewing"
}
```

### `POST /applications/{application_id}/mark-not-job`

Reclassifies linked emails to `other`, unlinks them, deletes the application.

### `GET /applications/link/preview/{email_id}`

Preview extraction/matching for email linking.

### `POST /applications/link/email/{email_id}`

Link a single email. Optional query param `application_id`.

### `POST /applications/link/batch`

Auto-link unlinked job-related emails. Optional query param `limit`.

### `GET /applications/stats/overview`

Pipeline totals and linked/unlinked job-email counts.

### `GET /applications/insights/follow-up-reminders`

Follow-up reminder suggestions.

Query params:

- `stale_days`
- `ghosted_days`
- `limit`

## WebSocket

### `WS /ws/sync-status`

Server emits sync lifecycle messages:

- `connected`
- `started`
- `progress`
- `completed`
- `error`
- `heartbeat`
- `pong` (reply to client `ping`)

## Optional Analytics (Feature Flag)

When `JOBTRACKER_ANALYTICS_ENABLED=true`:

- `GET /analytics/overview`
- `GET /analytics/trends`
