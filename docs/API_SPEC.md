# API Specification

**Base URL:** `http://127.0.0.1:8000`

All responses are JSON. All timestamps are ISO 8601 format (`2026-02-09T10:30:00Z`).

---

## System

### `GET /health`

Check if backend is running and connected.

**Response `200 OK`:**

```json
{
  "status": "ok",
  "version": "0.1.0",
  "db_connected": true,
  "gmail_connected": true,
  "icloud_connected": false,
  "last_sync": "2026-02-09T10:30:00Z",
  "classifier_status": {
    "active_layers": ["rules", "similarity"],
    "setfit_trained": false
  }
}
```

---

## Authentication

### `POST /auth/gmail`

Initiate Gmail OAuth2 flow. Opens browser for Google consent screen.

**Response `200 OK`:**

```json
{
  "status": "authenticated",
  "email": "user@gmail.com"
}
```

**Response `400 Bad Request`:**

```json
{
  "error": "oauth_cancelled",
  "message": "User cancelled the OAuth flow"
}
```

### `POST /auth/gmail/revoke`

Disconnect Gmail account. Removes stored OAuth tokens.

**Response `200 OK`:**

```json
{
  "status": "revoked",
  "email": "user@gmail.com"
}
```

### `POST /auth/icloud`

Save iCloud Mail credentials. Tests IMAP connection before saving.

**Request:**

```json
{
  "email": "user@icloud.com",
  "app_specific_password": "xxxx-xxxx-xxxx-xxxx"
}
```

**Response `200 OK`:**

```json
{
  "status": "authenticated",
  "email": "user@icloud.com"
}
```

**Response `401 Unauthorized`:**

```json
{
  "error": "imap_auth_failed",
  "message": "Could not authenticate with iCloud IMAP. Check your app-specific password."
}
```

### `POST /auth/icloud/revoke`

Disconnect iCloud account. Removes stored password.

### `GET /auth/status`

Get connection status for all accounts.

**Response `200 OK`:**

```json
{
  "accounts": [
    {
      "type": "gmail",
      "email": "user@gmail.com",
      "connected": true,
      "last_sync": "2026-02-09T10:30:00Z"
    },
    {
      "type": "icloud",
      "email": "user@icloud.com",
      "connected": true,
      "last_sync": "2026-02-09T10:28:00Z"
    }
  ]
}
```

---

## Email Sync

### `POST /sync`

Trigger email sync for connected accounts.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `account` | string | all | `gmail`, `icloud`, or omit for both |
| `full` | bool | false | Full re-sync instead of incremental |

**Response `200 OK`:**

```json
{
  "status": "completed",
  "accounts_synced": ["gmail", "icloud"],
  "emails_fetched": 23,
  "emails_new": 8,
  "emails_classified": 8,
  "flagged_for_review": 2,
  "duration_seconds": 4.2
}
```

**Response `409 Conflict`:**

```json
{
  "error": "sync_in_progress",
  "message": "A sync is already running. Please wait."
}
```

### `GET /sync/status`

Check current sync status.

**Response `200 OK`:**

```json
{
  "is_syncing": false,
  "last_sync": "2026-02-09T10:30:00Z",
  "next_scheduled_sync": "2026-02-09T10:45:00Z",
  "accounts": {
    "gmail": {"last_sync": "2026-02-09T10:30:00Z", "status": "idle", "error": null},
    "icloud": {"last_sync": "2026-02-09T10:28:00Z", "status": "idle", "error": null}
  }
}
```

---

## Emails

### `GET /emails`

List synced emails with filtering and pagination.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `classified_as` | string | — | Filter by classification category |
| `source` | string | — | `gmail` or `icloud` |
| `needs_review` | bool | — | `true` for low-confidence emails only |
| `application_id` | int | — | Filter by linked application |
| `search` | string | — | Full-text search in subject/body |
| `limit` | int | 50 | Results per page |
| `offset` | int | 0 | Pagination offset |
| `sort` | string | `received_at` | Sort field |
| `order` | string | `desc` | `asc` or `desc` |

**Response `200 OK`:**

```json
{
  "total": 142,
  "limit": 50,
  "offset": 0,
  "emails": [
    {
      "id": 1,
      "application_id": 5,
      "source_account": "gmail",
      "subject": "Your application to Acme Corp",
      "sender_name": "Acme Recruiting",
      "sender_email": "recruiting@acme.com",
      "received_at": "2026-02-08T14:22:00Z",
      "body_snippet": "Thank you for your interest in the Software Engineer position...",
      "classified_as": "applied",
      "classification_confidence": 0.92,
      "classification_method": "rules",
      "user_corrected": false,
      "is_reviewed": true
    }
  ]
}
```

### `GET /emails/{id}`

Get full email details including complete body.

**Response `200 OK`:**

```json
{
  "id": 1,
  "application_id": 5,
  "source_account": "gmail",
  "message_id": "<abc123@mail.gmail.com>",
  "thread_id": "thread_xyz",
  "subject": "Your application to Acme Corp",
  "sender_name": "Acme Recruiting",
  "sender_email": "recruiting@acme.com",
  "received_at": "2026-02-08T14:22:00Z",
  "body_text": "Full plain-text body of the email...",
  "body_snippet": "Thank you for your interest...",
  "classified_as": "applied",
  "classification_confidence": 0.92,
  "classification_method": "rules",
  "user_corrected": false,
  "is_reviewed": true,
  "created_at": "2026-02-08T15:00:00Z"
}
```

### `PUT /emails/{id}/classify`

User corrects an email's classification. This feeds the ML training pipeline.

**Request:**

```json
{
  "classified_as": "interview"
}
```

**Response `200 OK`:**

```json
{
  "id": 1,
  "classified_as": "interview",
  "classification_method": "user",
  "classification_confidence": 1.0,
  "user_corrected": true,
  "retrain_triggered": false,
  "training_data_counts": {
    "applied": 15,
    "interview": 8,
    "rejection": 20,
    "offer": 3,
    "assessment": 5,
    "other": 10
  }
}
```

### `PUT /emails/{id}/review`

Mark an email as reviewed (seen/acknowledged by user).

**Response `200 OK`:**

```json
{
  "id": 1,
  "is_reviewed": true
}
```

---

## Applications

### `GET /applications`

List all tracked job applications.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | — | Filter by status |
| `search` | string | — | Search company/position |
| `sort` | string | `updated_at` | `applied_date`, `updated_at`, `company` |
| `order` | string | `desc` | `asc` or `desc` |
| `limit` | int | 50 | Results per page |
| `offset` | int | 0 | Pagination offset |

**Response `200 OK`:**

```json
{
  "total": 34,
  "applications": [
    {
      "id": 5,
      "company": "Acme Corp",
      "position": "Software Engineer",
      "status": "interviewing",
      "applied_date": "2026-01-15",
      "source": "LinkedIn",
      "url": "https://acme.com/jobs/123",
      "email_count": 4,
      "last_email_at": "2026-02-08T14:22:00Z",
      "notes": "Referred by John",
      "created_at": "2026-01-15T10:00:00Z",
      "updated_at": "2026-02-08T14:22:00Z"
    }
  ]
}
```

### `GET /applications/{id}`

Get application details with linked emails, contacts, and interviews.

**Response `200 OK`:**

```json
{
  "id": 5,
  "company": "Acme Corp",
  "position": "Software Engineer",
  "status": "interviewing",
  "applied_date": "2026-01-15",
  "source": "LinkedIn",
  "url": "https://acme.com/jobs/123",
  "notes": "Referred by John",
  "created_at": "2026-01-15T10:00:00Z",
  "updated_at": "2026-02-08T14:22:00Z",
  "emails": [
    {
      "id": 1,
      "subject": "Application received",
      "received_at": "2026-01-15T10:05:00Z",
      "classified_as": "applied"
    },
    {
      "id": 12,
      "subject": "Interview invitation",
      "received_at": "2026-02-01T09:00:00Z",
      "classified_as": "interview"
    }
  ],
  "contacts": [
    {
      "id": 1,
      "name": "Jane Smith",
      "email": "jane@acme.com",
      "role": "recruiter"
    }
  ],
  "interviews": [
    {
      "id": 1,
      "type": "video",
      "scheduled_at": "2026-02-10T14:00:00Z",
      "duration_minutes": 45,
      "status": "scheduled"
    }
  ]
}
```

### `POST /applications`

Manually create a new application.

**Request:**

```json
{
  "company": "Acme Corp",
  "position": "Software Engineer",
  "status": "applied",
  "applied_date": "2026-02-09",
  "source": "LinkedIn",
  "url": "https://acme.com/jobs/123",
  "notes": "Referred by John"
}
```

**Response `201 Created`:**

```json
{
  "id": 35,
  "company": "Acme Corp",
  "position": "Software Engineer",
  "status": "applied",
  "applied_date": "2026-02-09",
  "created_at": "2026-02-09T12:00:00Z"
}
```

### `PUT /applications/{id}`

Update application details or status.

**Request:**

```json
{
  "status": "interviewing",
  "notes": "Phone screen went well, next round scheduled"
}
```

### `DELETE /applications/{id}`

Delete an application and unlink its emails (emails are kept, just unlinked).

---

## Analytics

### `GET /analytics/overview`

Summary statistics for the dashboard.

**Response `200 OK`:**

```json
{
  "total_applications": 34,
  "by_status": {
    "applied": 10,
    "interviewing": 5,
    "offered": 1,
    "rejected": 15,
    "ghosted": 3,
    "accepted": 0,
    "withdrawn": 0
  },
  "response_rate": 0.71,
  "avg_response_days": 8.3,
  "this_week": {
    "applied": 3,
    "responses_received": 2,
    "interviews_scheduled": 1
  }
}
```

### `GET /analytics/trends`

Time-series data for charts.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `period` | string | `weekly` | `weekly` or `monthly` |
| `months` | int | 3 | How many months back |

**Response `200 OK`:**

```json
{
  "period": "weekly",
  "data": [
    {
      "week_start": "2026-02-03",
      "applied": 5,
      "rejected": 3,
      "interviews": 1,
      "offers": 0
    },
    {
      "week_start": "2026-01-27",
      "applied": 8,
      "rejected": 4,
      "interviews": 2,
      "offers": 0
    }
  ]
}
```

---

## ML Model Management

### `GET /ml/status`

Get classifier status, active layers, and training data counts.

**Response `200 OK`:**

```json
{
  "active_layers": ["rules", "similarity", "setfit"],
  "setfit_model": {
    "version": "20260209_103000",
    "trained_at": "2026-02-09T10:30:00Z",
    "training_examples": 61,
    "estimated_accuracy": 0.88
  },
  "training_data_counts": {
    "applied": 15,
    "interview": 8,
    "rejection": 20,
    "offer": 3,
    "assessment": 5,
    "follow_up": 2,
    "other": 8
  },
  "can_retrain": true,
  "retrain_reason": "8 new corrections since last training"
}
```

### `POST /ml/retrain`

Manually trigger model retraining.

**Response `202 Accepted`:**

```json
{
  "status": "training_started",
  "estimated_duration_seconds": 180,
  "training_examples": 61
}
```

**Response `400 Bad Request`:**

```json
{
  "error": "insufficient_data",
  "message": "Need at least 5 examples in 3+ categories. Currently: applied=3, interview=2"
}
```

---

---

## WebSocket: Real-Time Sync Status

### `WS /ws/sync`

Connect for live sync progress updates. No polling needed.

**Connection:**

```javascript
const ws = new WebSocket('ws://127.0.0.1:8000/ws/sync');
```

**Server Messages:**

```json
// Sync started
{
  "event": "sync_started",
  "accounts": ["gmail", "icloud"],
  "timestamp": "2026-02-09T10:30:00Z"
}

// Progress update (sent every ~1 second during sync)
{
  "event": "sync_progress",
  "account": "gmail",
  "emails_fetched": 15,
  "emails_total": 50,
  "emails_classified": 10
}

// Sync completed
{
  "event": "sync_completed",
  "emails_fetched": 50,
  "emails_new": 12,
  "emails_classified": 12,
  "flagged_for_review": 3,
  "duration_seconds": 8.5
}

// Error during sync
{
  "event": "sync_error",
  "account": "gmail",
  "error": "rate_limited",
  "message": "Gmail API rate limit exceeded. Retry in 60 seconds."
}

// ML model retraining status
{
  "event": "ml_retrain_started",
  "training_examples": 65
}

{
  "event": "ml_retrain_completed",
  "duration_seconds": 180,
  "new_model_version": "20260209_103000"
}
```

**Client Messages:**

```json
// Request immediate sync (alternative to POST /sync)
{
  "action": "sync",
  "accounts": ["gmail"]
}

// Ping to keep connection alive
{
  "action": "ping"
}
```

---

## Error Responses

All errors follow this format:

```json
{
  "error": "error_code",
  "message": "Human-readable description of what went wrong",
  "details": {}
}
```

### Common Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `not_found` | 404 | Resource not found |
| `validation_error` | 422 | Invalid request body |
| `auth_required` | 401 | Account not connected |
| `sync_in_progress` | 409 | Sync already running |
| `rate_limited` | 429 | Too many requests (Gmail API) |
| `internal_error` | 500 | Unexpected server error |
