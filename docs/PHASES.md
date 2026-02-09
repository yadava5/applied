# Implementation Phases

Track progress by checking off completed items. Each phase builds on the previous one.

---

## Phase 1: Project Foundation

> Set up the project, database, and basic backend infrastructure.

- [ ] Initialize Python project with `pyproject.toml` and dependencies
- [ ] Set up FastAPI app skeleton with health check endpoint
- [ ] Implement SQLite database connection with WAL mode
- [ ] Create all database tables (applications, emails, contacts, interviews, training_data, sync_state)
- [ ] Add database migration/initialization script
- [ ] Set up project configuration (`config.py` — ports, paths, defaults)
- [ ] Add logging infrastructure
- [ ] Write basic tests for database operations
- [ ] Create `requirements.txt` with all dependencies
- [ ] Verify: `uvicorn jobtracker.main:app` starts and `GET /health` returns 200

---

## Phase 2: Email Integration

> Connect to Gmail and iCloud Mail, fetch and parse emails.

### Gmail

- [ ] Set up Google Cloud project and enable Gmail API
- [ ] Implement OAuth2 authentication flow (consent screen → token)
- [ ] Store OAuth tokens securely in macOS Keychain (`keyring`)
- [ ] Implement Gmail email fetching (`messages.list` + `messages.get`)
- [ ] Implement incremental sync using `historyId`
- [ ] Parse email content: subject, sender, body (plain text + HTML fallback), date, headers
- [ ] Handle pagination for large mailboxes
- [ ] Add Gmail-specific error handling (rate limits, token expiry, automatic refresh)
- [ ] Write tests with mocked Gmail API responses

### iCloud Mail

- [ ] Document user setup steps (enable 2FA, generate app-specific password)
- [ ] Implement IMAP connection to `imap.mail.me.com:993` with SSL
- [ ] Store app-specific password in macOS Keychain
- [ ] Implement email fetching via IMAP (`SEARCH`, `FETCH`)
- [ ] Implement incremental sync using IMAP UIDs + `SINCE` date
- [ ] Parse email content (shared parser with Gmail)
- [ ] Handle IMAP-specific errors (connection drops, timeouts, reconnection)
- [ ] Write tests with mocked IMAP responses

### Shared

- [ ] Build unified email parser (normalize Gmail API format + IMAP format into common schema)
- [ ] Implement deduplication (via `Message-ID` header)
- [ ] Store parsed emails in SQLite `emails` table
- [ ] Create API endpoints: `POST /auth/gmail`, `POST /auth/icloud`, `POST /sync`, `GET /emails`
- [ ] Verify: sync fetches real emails from both accounts and stores them in DB

---

## Phase 3: Email Classification (ML)

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

- [ ] Build regex pattern sets for each category (strong patterns, weak patterns, negative patterns)
- [ ] Implement weighted scoring: strong match (+3), weak match (+1), negative (−5)
- [ ] Add sender domain rules (`greenhouse.io`, `lever.co`, `workday.com` → ATS email)
- [ ] Add subject line analysis (subject patterns weighted 2× vs body patterns)
- [ ] Implement confidence scoring for rules
- [ ] Test against 20-30 sample emails (manually verify accuracy ≥ 70%)

### Layer 2: Sentence Embeddings

- [ ] Download `all-MiniLM-L6-v2` model (80MB, one-time)
- [ ] Build embedding store for known labeled emails
- [ ] Implement cosine similarity matching against known examples
- [ ] Set similarity threshold (0.85+ = confident match)
- [ ] Store embeddings efficiently (numpy arrays, pickle file)

### Layer 3: SetFit (Few-Shot ML)

- [ ] Implement SetFit model wrapper (train, predict, save, load)
- [ ] Build training trigger: auto-retrain when 5+ new corrections per category exist
- [ ] Background retraining (2-5 min on CPU, non-blocking)
- [ ] Model versioning: save models with timestamps, keep last 3 versions
- [ ] Implement confidence scoring from SetFit's `predict_proba`

### Hybrid Classifier

- [ ] Combine all 3 layers: rules → embeddings → SetFit → fallback
- [ ] Route high-confidence results automatically (> 0.85)
- [ ] Flag low-confidence results (< 0.7) for user review
- [ ] Create API endpoint: `PUT /emails/{id}/classify` (user correction)
- [ ] Store corrections in `training_data` table
- [ ] Verify: classify 50 sample emails, expect ≥ 70% accuracy on Day 1

---

## Phase 4: Application Tracking Logic

> Link emails to applications, track status changes, detect companies.

- [ ] Implement company name extraction from emails (sender domain → company name mapping)
- [ ] Build application auto-creation: new company detected in email → create application record
- [ ] Implement application status state machine:
  ```
  applied → interviewing → offered → accepted
                                   → rejected
                        → rejected
           → rejected
           → ghosted (no response in 30+ days)
           → withdrawn (by user)
  ```
- [ ] Auto-update application status when new classified email arrives
- [ ] Link multiple emails to same application (by sender domain + position keyword matching)
- [ ] Detect contacts from email signatures (recruiter name, title)
- [ ] Parse interview details from calendar invites / email body
- [ ] Create API endpoints: `GET /applications`, `GET /applications/{id}`, `PUT /applications/{id}`, `POST /applications`, `DELETE /applications/{id}`
- [ ] Verify: synced emails correctly grouped into applications with accurate statuses

---

## Phase 5: macOS SwiftUI Frontend

> Build the native macOS desktop application.

### Project Setup

- [ ] Create Xcode project (macOS 13+, SwiftUI, Swift 5.9+)
- [ ] Add GRDB.swift dependency via SPM (SQLite reader)
- [ ] Implement `BackendAPIClient` service for `localhost:8000`
- [ ] Implement database reader for direct SQLite reads (faster for UI rendering)
- [ ] Build backend health check + auto-start logic

### Views

- [ ] **Dashboard View**: Status overview cards (Applied: N, Interviewing: N, Offers: N, Rejected: N)
- [ ] **Applications List View**: Sortable/filterable table with search bar
- [ ] **Application Detail View**: Timeline of status changes, linked emails, contacts, notes editor
- [ ] **Email Inbox View**: Synced emails with classification badge, review queue for low-confidence items
- [ ] **Analytics View**: Charts — applications over time, response rate, average time to response
- [ ] **Settings View**: Connect Gmail (OAuth flow), connect iCloud (password entry), sync frequency, manage accounts

### Navigation

- [ ] Implement `NavigationSplitView` (sidebar + detail)
- [ ] Sidebar items: Dashboard, Applications, Emails, Analytics, Settings
- [ ] Toolbar: Sync Now button, search, filter dropdown

### Features

- [ ] Real-time sync status indicator (syncing spinner, last sync timestamp)
- [ ] User notifications for new interviews/offers (`UserNotifications` framework)
- [ ] Quick correction: click classification badge → dropdown to fix category
- [ ] Application notes and manual status override
- [ ] Dark mode support
- [ ] Verify: full workflow — connect accounts → sync → view dashboard → correct classification

---

## Phase 6: Background Service

> Run email sync automatically in the background.

- [ ] Create `launchd` plist for Python backend (`com.jobtracker.backend.plist`)
- [ ] Configure `RunAtLoad` and `KeepAlive` for auto-start on login
- [ ] Configure `StartInterval` (900 = every 15 minutes) for periodic sync
- [ ] Set up log files: `~/Library/Logs/JobTracker/`
- [ ] SwiftUI app: backend lifecycle management (start, stop, restart buttons)
- [ ] SwiftUI app: install/uninstall Launch Agent from Settings
- [ ] Handle port conflicts (detect if `:8000` is already occupied)
- [ ] Verify: reboot Mac → backend auto-starts → emails sync without opening swiftUI app

---

## Phase 7: Analytics & Smart Features

> Add insights, charts, and intelligent suggestions.

- [ ] Response rate calculation (responses received ÷ applications sent)
- [ ] Average time to response per company
- [ ] Application volume over time (weekly/monthly chart data)
- [ ] Status funnel visualization (applied → interview → offer conversion rates)
- [ ] "Ghosted" detection: auto-flag applications with no response after 30 days
- [ ] Follow-up reminders: suggest sending follow-up for stale applications
- [ ] Full-text search across emails, company names, notes
- [ ] Create API endpoints: `GET /analytics/overview`, `GET /analytics/trends`
- [ ] Verify: analytics page shows accurate data matching database content

---

## Phase 8: Polish & Distribution

> Prepare for real daily usage and sharing.

- [ ] Comprehensive error handling: graceful failures for network, auth, sync issues
- [ ] First-run onboarding flow in SwiftUI (welcome → connect accounts → first sync)
- [ ] `install.sh` script: sets up Python venv, installs dependencies, downloads ML models
- [ ] App icon and branding
- [ ] Write user-facing README with screenshots
- [ ] Test complete flow end-to-end: fresh install → connect accounts → sync → classify → track
- [ ] Optional: package as `.dmg` for macOS distribution

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
| Phase 1 | ⬜ Not Started | Project Foundation |
| Phase 2 | ⬜ Not Started | Email Integration (Gmail + iCloud) |
| Phase 3 | ⬜ Not Started | Email Classification (ML) |
| Phase 4 | ⬜ Not Started | Application Tracking Logic |
| Phase 5 | ⬜ Not Started | macOS SwiftUI Frontend |
| Phase 6 | ⬜ Not Started | Background Service (launchd) |
| Phase 7 | ⬜ Not Started | Analytics & Smart Features |
| Phase 8 | ⬜ Not Started | Polish & Distribution |
| Phase 9 | ⬜ Not Started | Cross-Platform (Future) |
