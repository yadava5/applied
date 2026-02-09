# Architecture

## System Overview

JobTracker is a two-process desktop application:

1. **Python Backend** — a FastAPI server running on `localhost:8000` that handles all data operations
2. **SwiftUI Frontend** — a native macOS app that provides the user interface

They communicate via REST API over localhost. Both read/write to a shared SQLite database.

## Why This Architecture?

| Decision | Reason |
|----------|--------|
| Python for backend | Best email libraries (google-api-python-client, imaplib), best ML ecosystem (scikit-learn, SetFit), cross-platform |
| SwiftUI for macOS | Native look and feel, Apple ecosystem integration, Keychain access |
| REST API between them | Language-agnostic, debuggable, testable, portable to other frontends later |
| SQLite | No server to manage, file-based, WAL mode allows concurrent read/write, perfect for desktop apps |
| Separate processes | Backend can run in background (launchd) even when the UI is closed |

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         macOS System                            │
│                                                                 │
│  ┌─────────────────────┐  REST API  ┌────────────────────────┐  │
│  │    SwiftUI App      │◄──────────►│    Python Backend      │  │
│  │                     │ :8000      │    (FastAPI + Uvicorn)  │  │
│  │  ┌───────────────┐  │           │                        │  │
│  │  │ Dashboard     │  │           │  ┌──────────────────┐  │  │
│  │  │ Applications  │  │           │  │ Gmail Client     │──┼──┼──► Gmail API
│  │  │ Email Viewer  │  │           │  │ (OAuth2)         │  │  │
│  │  │ Analytics     │  │           │  └──────────────────┘  │  │
│  │  │ Settings      │  │           │                        │  │
│  │  └───────────────┘  │           │  ┌──────────────────┐  │  │
│  │                     │           │  │ iCloud Client    │──┼──┼──► imap.mail.me.com
│  │  ┌───────────────┐  │           │  │ (IMAP + AppPass) │  │  │
│  │  │ GRDB.swift    │  │           │  └──────────────────┘  │  │
│  │  │ (DB reader)   │  │           │                        │  │
│  │  └───────┬───────┘  │           │  ┌──────────────────┐  │  │
│  └──────────┼──────────┘           │  │ Hybrid Classifier│  │  │
│             │                      │  │ Rules+Embed+ML   │  │  │
│             │ READ                 │  └──────────────────┘  │  │
│             │                      │                        │  │
│             │              WRITE   │  ┌──────────────────┐  │  │
│             └──────► SQLite ◄──────┼──│ SQLAlchemy       │  │  │
│                     (WAL mode)     │  └──────────────────┘  │  │
│                    ~/Library/      │                        │  │
│                    Application     └────────────────────────┘  │
│                    Support/                                     │
│                    JobTracker/     ┌────────────────────────┐  │
│                                   │       launchd          │  │
│                                   │  (Launch Agent)        │  │
│                                   │  - starts backend      │  │
│                                   │  - scheduled sync      │  │
│                                   └────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Email Sync Flow

```
1. launchd triggers sync (every 15 min) OR user clicks "Sync Now"
2. Backend receives POST /sync
3. Gmail Client fetches new emails via Gmail API (incremental via historyId)
4. iCloud Client fetches new emails via IMAP (SINCE last sync date)
5. Email Parser extracts: subject, sender, body, date, headers
6. Hybrid Classifier categorizes each email:
   a. Rules check → if high confidence, done
   b. Embedding similarity → if matches a known labeled email, done
   c. SetFit model → ML prediction with confidence score
7. Results stored in SQLite (emails table + applications table updated)
8. Low-confidence results flagged for user review
9. SwiftUI app picks up new data via DB read or API poll
```

### User Correction Flow

```
1. User sees misclassified email in SwiftUI app
2. User selects correct category from dropdown
3. SwiftUI sends PUT /emails/{id}/classify to backend
4. Backend stores correction in training_data table
5. Backend saves email embedding in known_examples store
6. When enough corrections accumulate (5-10 per category):
   → Backend retrains SetFit model (2-5 min, in background)
   → New model replaces old one
   → Future classifications improve
```

## Database Design

### Entity Relationship

```
applications 1──────┐
     │               │
     │ has many      │ has many
     ▼               ▼
  emails          contacts
                     
applications 1──────┐
     │               │
     │ has many      │
     ▼               │
  interviews         │
                     │
  training_data ─────┘ (independent, for ML)
  sync_state ──────── (independent, per-account)
```

### Tables

**applications** — one row per company/position you applied to

```sql
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    position TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied'
        CHECK(status IN (
            'applied', 'interviewing', 'offered',
            'rejected', 'accepted', 'withdrawn', 'ghosted'
        )),
    applied_date DATE,
    source TEXT,                        -- LinkedIn, company website, referral, etc.
    url TEXT,                           -- Job posting URL
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**emails** — synced emails linked to applications

```sql
CREATE TABLE emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER REFERENCES applications(id) ON DELETE SET NULL,
    source_account TEXT NOT NULL,       -- 'gmail' or 'icloud'
    message_id TEXT UNIQUE NOT NULL,    -- Email Message-ID header (dedup key)
    thread_id TEXT,                     -- Gmail thread ID (null for iCloud)
    subject TEXT,
    sender_name TEXT,
    sender_email TEXT,
    received_at TIMESTAMP NOT NULL,
    body_text TEXT,
    body_snippet TEXT,                  -- First 200 chars for quick display
    classified_as TEXT,                 -- ML classification result
    classification_confidence REAL,    -- 0.0 to 1.0
    classification_method TEXT,        -- 'rules', 'similarity', 'setfit', 'user'
    user_corrected BOOLEAN DEFAULT 0,  -- Did the user override the classification?
    is_reviewed BOOLEAN DEFAULT 0,     -- Has the user seen/acknowledged this?
    raw_headers TEXT,                   -- JSON of email headers for debugging
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**contacts** — people associated with applications (recruiters, hiring managers)

```sql
CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    name TEXT,
    email TEXT NOT NULL,
    role TEXT,                          -- 'recruiter', 'hiring_manager', 'hr'
    notes TEXT
);
```

**interviews** — scheduled interviews

```sql
CREATE TABLE interviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
    type TEXT CHECK(type IN (
        'phone', 'video', 'onsite', 'technical', 'behavioral', 'panel'
    )),
    scheduled_at TIMESTAMP,
    duration_minutes INTEGER,
    location TEXT,
    notes TEXT,
    status TEXT DEFAULT 'scheduled'
        CHECK(status IN ('scheduled', 'completed', 'cancelled', 'rescheduled'))
);
```

**training_data** — user corrections for ML improvement

```sql
CREATE TABLE training_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_text TEXT NOT NULL,
    label TEXT NOT NULL,
    source TEXT DEFAULT 'user_correction',  -- 'user_correction' or 'manual_label'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**sync_state** — tracks last sync position per email account

```sql
CREATE TABLE sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_type TEXT NOT NULL,         -- 'gmail' or 'icloud'
    account_email TEXT NOT NULL UNIQUE,
    last_sync_at TIMESTAMP,
    gmail_history_id TEXT,              -- For Gmail incremental sync
    imap_last_uid INTEGER,             -- For IMAP incremental sync
    status TEXT DEFAULT 'idle',
    error_message TEXT
);
```

### Indexes

```sql
CREATE INDEX idx_emails_application ON emails(application_id);
CREATE INDEX idx_emails_received ON emails(received_at DESC);
CREATE INDEX idx_emails_classified ON emails(classified_as);
CREATE INDEX idx_emails_source ON emails(source_account);
CREATE INDEX idx_emails_message_id ON emails(message_id);
CREATE INDEX idx_applications_status ON applications(status);
CREATE INDEX idx_applications_company ON applications(company);
CREATE INDEX idx_training_label ON training_data(label);
```

### Concurrent Access (WAL Mode)

Both Python (writer) and Swift (reader) access the same SQLite file safely using WAL mode:

```python
# Python side — enable WAL mode on connection
conn = sqlite3.connect('jobtracker.db')
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s for locks
```

```swift
// Swift side — GRDB.swift handles WAL automatically
let dbQueue = try DatabaseQueue(path: dbPath)
let emails = try dbQueue.read { db in
    try Email.fetchAll(db)
}
```

## Security

| Asset | Protection |
|-------|------------|
| Gmail OAuth tokens | macOS Keychain via `keyring` library |
| iCloud app-specific password | macOS Keychain via `keyring` library |
| Email content | SQLite in `~/Library/Application Support/JobTracker/` (user-only permissions) |
| API communication | localhost only (127.0.0.1), no external network exposure |
| Credentials in code | Never. All via environment variables or Keychain |

## Email Service Details

### Gmail

| Setting | Value |
|---------|-------|
| Method | Gmail REST API |
| Auth | OAuth 2.0 (desktop app flow) |
| Scope | `https://www.googleapis.com/auth/gmail.readonly` (read-only) |
| Incremental Sync | `history.list` with `historyId` |
| Rate Limit | 15,000 quota units/user/minute |

### iCloud Mail

| Setting | Value |
|---------|-------|
| Method | IMAP |
| Server | `imap.mail.me.com` |
| Port | 993 (SSL/TLS required) |
| Auth | App-specific password (requires 2FA on Apple Account) |
| Incremental Sync | IMAP `SEARCH SINCE <date>` + UID tracking |

## Cross-Platform Strategy (Future)

```
                    ┌──────────────────────────┐
                    │    Python Backend         │
                    │  (FastAPI + ML + Email)   │
                    │    100% Shared Code       │
                    └────────────┬──────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
             ▼                   ▼                   ▼
      ┌──────────┐        ┌──────────┐        ┌──────────┐
      │  macOS   │        │ Windows  │        │  Linux   │
      │ SwiftUI  │        │  Tauri   │        │  Tauri   │
      │ (native) │        │ (web UI) │        │ (web UI) │
      └──────────┘        └──────────┘        └──────────┘
```

The Python backend requires **zero changes** for other platforms. Only the UI layer changes:
- **macOS**: Native SwiftUI (best experience on Mac)
- **Windows/Linux**: Tauri with React/Svelte frontend (lightweight, ~5MB app)
- Both connect to the same Python backend via REST API on localhost
