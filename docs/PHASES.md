# Implementation Phases

Track progress by checking off completed items. Each phase builds on the previous one.

> Last updated: February 12, 2026

---

## Phase 1: Project Foundation ✅

> Set up the project, async database, and basic backend infrastructure.

- [x] Initialize Python project with `pyproject.toml` and dependencies
- [x] Set up **async** FastAPI app skeleton with health check endpoint
- [x] Implement **aiosqlite + SQLModel** database connection with WAL mode
- [x] Create all database tables (applications, emails, contacts, interviews, training_data, sync_state, **email_embeddings**)
- [x] Add async database migration/initialization script
- [x] Set up project configuration (`config.py` — ports, paths, defaults)
- [x] Add structured logging (with async-safe handlers)
- [x] Write basic async tests for database operations
- [x] Create `requirements.txt` with all dependencies (aiosqlite, sqlmodel, etc.)
- [x] Verify: `uvicorn jobtracker.main:app` starts and `GET /health` returns 200

---

## Phase 2: Email Integration ✅

> Connect to Gmail and iCloud Mail, fetch and parse emails.

### Gmail

- [x] Set up Google Cloud project and enable Gmail API
- [x] Implement OAuth2 authentication flow (consent screen → token)
- [x] Store OAuth tokens securely in macOS Keychain (`keyring`)
- [x] Implement Gmail email fetching (`messages.list` + `messages.get`)
- [x] Implement incremental sync using `historyId`
- [x] Parse email content: subject, sender, body (plain text + HTML fallback), date, headers
- [x] Handle pagination for large mailboxes
- [x] Add Gmail-specific error handling (rate limits, token expiry, automatic refresh)
- [x] Write tests with mocked Gmail API responses

### iCloud Mail

- [x] Document user setup steps (enable 2FA, generate app-specific password)
- [x] Implement **async** IMAP connection using **aioimaplib** to `imap.mail.me.com:993` with SSL
- [x] Store app-specific password in macOS Keychain
- [x] Implement async email fetching via IMAP (`SEARCH`, `FETCH`)
- [x] Implement incremental sync using IMAP UIDs + `SINCE` date
- [x] Parse email content (shared parser with Gmail)
- [x] Handle IMAP-specific errors (connection drops, timeouts, async reconnection)
- [x] Write async tests with mocked IMAP responses

### Shared

- [x] Build unified email parser (normalize Gmail API format + IMAP format into common schema)
- [x] Decode quoted-printable/MIME scaffolding in parsed bodies so iCloud email text remains readable
- [x] Implement deduplication (via `Message-ID` header)
- [x] Store parsed emails in SQLite `emails` table
- [x] Create API endpoints: `POST /auth/gmail`, `POST /auth/icloud`, `POST /sync`, `GET /emails`
- [x] Verify: sync fetches real emails from both accounts and stores them in DB

---

## Phase 3: Email Classification (ML) ✅

> Classify job-related emails into categories automatically.

### Classification Categories

```
applied      — "We received your application"
interview    — "We'd like to schedule an interview"
rejection    — "We've decided to move forward with other candidates"
offer        — "We're pleased to offer you..."
assessment   — "Please complete this technical assessment"
follow_up    — "Just checking in on your application"
other        — Not job-related or uncategorizable
```

### Layer 1: Rule-Based

- [x] Build regex pattern sets for each category (strong patterns, weak patterns, negative patterns)
- [x] Implement weighted scoring: strong match (+3), weak match (+1), negative (−5)
- [x] Add sender domain rules (`greenhouse.io`, `lever.co`, `workday.com` → ATS email)
- [x] Add subject line analysis (subject patterns weighted 2× vs body patterns)
- [x] Implement confidence scoring for rules
- [x] Test against 20-30 sample emails (manually verify accuracy ≥ 70%)

### Layer 2: Sentence Embeddings

- [x] Download `intfloat/e5-small-v2` model (~80MB, one-time via sentence-transformers)
- [x] Build embedding store using **SQLite `email_embeddings` table** (not pickle files)
- [x] Implement cosine similarity matching against known examples
- [x] Set similarity threshold (0.85+ = confident match)
- [x] Implement efficient embedding serialization (numpy → bytes → SQLite BLOB)
- [x] Add model version tracking for future upgrades

### Layer 3: SetFit (Few-Shot ML)

- [x] Implement SetFit model wrapper (train, predict, save, load)
- [x] Build training trigger: auto-retrain when 5+ new corrections per category exist
- [x] Background retraining (2-5 min on CPU, non-blocking)
- [x] Model versioning: save models with timestamps, keep last 3 versions
- [x] Implement confidence scoring from SetFit's `predict_proba`

### Hybrid Classifier

- [x] Combine all 3 layers: rules → embeddings → SetFit → fallback
- [x] Route high-confidence results automatically (> 0.85)
- [x] Flag low-confidence results (< 0.7) for user review
- [x] Create API endpoint: `PUT /emails/{id}/correct` (user correction)
- [x] Store corrections in `training_data` table
- [x] Verify: classify 50 sample emails, expect ≥ 70% accuracy on Day 1

---

## Phase 4: Application Tracking Logic ✅

> Link emails to applications, track status changes, detect companies.

- [x] Implement company name extraction from emails (sender domain → company name mapping)
- [x] Build application auto-creation: new company detected in email → create application record
- [x] Improve company/position extraction for LinkedIn + ATS portal templates (one-line and multiline confirmation variants)
- [x] Implement application status state machine:
  ```
  applied → interviewing → offered → accepted
                                   → rejected
                        → rejected
           → rejected
           → ghosted (no response in 30+ days)
           → withdrawn (by user)
  ```
- [x] Auto-update application status when new classified email arrives
- [x] Link multiple emails to same application (by sender domain + position keyword matching)
- [x] Support same-company multi-role applications as separate records when position evidence exists
- [x] Make relinking idempotent and upgrade `Unknown Position` apps when better role evidence arrives
- [x] Detect contacts from email signatures (recruiter name, title) — heuristics added during Phase 7
- [x] Parse interview details from calendar invites / email body — interview extraction pipeline added in Phase 7
- [x] Create API endpoints: `GET /applications`, `GET /applications/{id}`, `PUT /applications/{id}`, `POST /applications`, `DELETE /applications/{id}`
- [x] Verify: synced emails correctly grouped into applications with accurate statuses

---

## Phase 5: macOS SwiftUI Frontend

> Build the native macOS desktop application with Liquid Glass design.

### Project Setup

- [x] Create Xcode project (**macOS 15+**, SwiftUI, Swift 5.9+)
- [x] Add **GRDB.swift + GRDBQuery** dependencies via SPM (reactive SQLite reads)
- [x] Implement `BackendAPIClient` service for `localhost:8000` (REST + WebSocket)
- [x] Implement reactive database reader using GRDBQuery property wrappers
- [x] Build backend health check + auto-start logic via **SMAppService**

### Views (Liquid Glass + SF Symbols 7)

- [x] **Dashboard View**: Status overview cards with Liquid Glass material, SF Symbols for status icons
- [x] **Applications List View**: Sortable/filterable list with search bar and toolbar filters/sort controls
- [x] **Application Detail View (Core)**: linked emails, full email content visibility, manual status override, "mark as not job posting"
- [x] **Application Detail View (Polish)**: timeline-style email chronology, contacts section, notes editor
- [x] **Email Inbox View**: Synced emails with classification badges + full body detail view, alongside review queue
- [x] **Analytics View removed from app navigation**: analytics feature de-scoped from production UI
- [x] **Settings View**: Connect Gmail (OAuth flow), connect iCloud (password entry), sync frequency, manage accounts

### Navigation

- [x] Implement `NavigationSplitView` with **Liquid Glass sidebar**
- [x] Sidebar items: Dashboard, Applications, Emails, Settings (SF Symbols icons)
- [x] Toolbar actions implemented across core views: Sync/Refresh + search/filter/sort controls

### Menu Bar Integration

- [x] Implement **`MenuBarExtra`** for status bar presence
- [x] Show sync status icon (idle, syncing, error)
- [x] Quick stats dropdown (new responses, pending reviews)
- [x] Quick actions: Sync Now, Open App

### Features

- [x] Real-time sync status via **WebSocket** connection (no polling)
- [x] User notifications for new interviews/offers (`UserNotifications` framework)
- [x] Quick correction: click classification badge → dropdown to fix category (including training via user corrections and "mark as not job posting")
- [x] Review queue approvals feed `training_data` so confirmed labels improve future classification
- [x] Manual application status override in Application Detail
- [x] Application notes editor
- [x] Light/Dark mode + adaptive material-based appearance
- [x] **Observation framework** (`@Observable`) for view models
- [x] Verify: core workflow — connect accounts → sync → dashboard/inbox/review updates (API + app smoke tested)

---

## Phase 6: Background Service

> Run email sync automatically in the background using modern macOS APIs.

- [x] Create `launchd` plist for Python backend (`com.jobtracker.backend.plist`)
- [x] Configure `RunAtLoad` and `KeepAlive` for auto-start on login
- [x] Configure `StartInterval` (900 = every 15 minutes) for periodic sync
- [x] Set up log files: `~/Library/Logs/JobTracker/`
- [x] **Implement `SMAppService` wrapper** for Launch Agent management (modern API)
- [x] SwiftUI app: backend lifecycle management via SMAppService (register, unregister, status)
- [x] SwiftUI Settings: toggle for "Start at Login" using SMAppService
- [x] Handle port conflicts (detect if `:8000` is already occupied)
- [x] Handle SMAppService authorization prompts gracefully
- [x] Verify: reboot Mac → backend auto-starts → emails sync without opening SwiftUI app (validation checklist + runtime checks in place)

### SMAppService Implementation

```swift
import ServiceManagement

// Register the launch agent
func registerBackendService() throws {
    let service = SMAppService.agent(plistName: "com.jobtracker.backend.plist")
    try service.register()
}

// Check status
func isBackendRegistered() -> Bool {
    let service = SMAppService.agent(plistName: "com.jobtracker.backend.plist")
    return service.status == .enabled
}

// Unregister
func unregisterBackendService() throws {
    let service = SMAppService.agent(plistName: "com.jobtracker.backend.plist")
    try service.unregister()
}
```

---

## Phase 7: Smart Features

> Add insights, charts, real-time updates, and intelligent suggestions.

### Analytics (De-scoped)

- [x] Analytics endpoints/charts were prototyped, then removed from active product surface
- [x] Reintroduce only if business value is clear and data quality is trustworthy (now feature-flagged via `JOBTRACKER_ANALYTICS_ENABLED`)

### Real-Time Updates

- [x] Implement **WebSocket endpoint** (`/ws/sync-status`) for live sync progress
- [x] Broadcast sync events: started, progress (N/M emails), completed, error
- [x] SwiftUI: connect to WebSocket, update UI without polling
- [x] Reconnection logic with exponential backoff

### Smart Features

- [x] "Ghosted" detection: auto-flag applications with no response after 30 days
- [x] Follow-up reminders: suggest sending follow-up for stale applications
- [x] Full-text search across emails, company names, notes (SQLite FTS5)
- [x] "Lite mode" toggle: disable SetFit for 8GB RAM machines

---

## Phase 8: Polish & Distribution

> Prepare for real daily usage and distribution to other macOS users.

### Error Handling & UX

- [x] Comprehensive backend error handling: graceful API failures for DB corruption, network/auth/sync surfaces
- [ ] First-run onboarding flow in SwiftUI (welcome → connect accounts → first sync)
- [ ] Empty states with helpful guidance (no applications yet, no emails synced)
- [x] Rate limit handling for Gmail API (exponential backoff + retryable quota error detection)

### Branding & Assets

- [ ] App icon using **Icon Composer** (supports all Liquid Glass appearance modes)
- [ ] Menu bar icon (SF Symbol or custom, 16x16 template)
- [ ] Write user-facing README with screenshots

### Local Development Setup

- [x] `install.sh` script: sets up Python venv, installs dependencies, downloads ML models
- [ ] Test complete flow end-to-end: fresh install → connect accounts → sync → classify → track

### Distribution (macOS)

- [ ] **PyInstaller bundling**: package Python backend as standalone executable
- [ ] Create `bundle.sh` script to build `JobTracker.app` with embedded backend
- [ ] Universal binary support (Intel + Apple Silicon)
- [ ] ML model bundling vs. first-launch download (decide based on app size)
- [ ] **Code signing** with Apple Developer certificate
- [ ] **Notarization** via `notarytool` for Gatekeeper approval
- [ ] Create `notarize.sh` script for automated notarization
- [ ] Package as `.dmg` with background image and Applications shortcut
- [ ] Test installation on clean macOS 15+ system
- [ ] GitHub Releases with downloadable `.dmg`
- [ ] Optional: Homebrew Cask formula

---

## Phase 9: Cross-Platform — Windows & Linux (Future)

> Extend to Windows and Linux using Tauri.

- [ ] Set up Tauri project with React or Svelte frontend
- [ ] Port SwiftUI views to web components (same visual design)
- [ ] Implement same API client targeting `localhost:8000`
- [ ] Replace `launchd` with platform-specific schedulers:
  - Windows: Task Scheduler
  - Linux: systemd user service
- [ ] Bundle Python backend with platform-specific installers
- [ ] Test on Windows 10/11 and Ubuntu 22.04+

---

## Progress Tracker

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Complete | Project Foundation |
| Phase 2 | ✅ Complete | Email Integration (Gmail + iCloud) |
| Phase 3 | ✅ Complete | Email Classification (ML) |
| Phase 4 | ✅ Complete | Application Tracking Logic |
| Phase 5 | ✅ Complete | Core macOS app shipped: dashboard, applications, emails/review queue, settings, menu bar, WebSocket status |
| Phase 6 | ✅ Complete | Background service controls + `@Observable` cleanup + validation workflow finalized |
| Phase 7 | ✅ Complete | Realtime robustness, ghosted/follow-up intelligence, FTS search, and lite-mode controls delivered |
| Phase 8 | 🟨 In Progress | Error-handling/logging hardening + Gmail rate-limit backoff + installer script |
| Phase 9 | ⬜ Not Started | Cross-Platform (Future) |
