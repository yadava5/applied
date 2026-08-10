# Architecture

## High-Level Design

Applied runs as two local processes:

1. SwiftUI macOS app (`apps/macos/...`)
2. FastAPI backend (`backend/jobtracker/...`)

Communication is local HTTP + WebSocket on `127.0.0.1:8000`.

SQLite is the shared data store:

- backend is the writer (`aiosqlite` / SQLModel)
- app reads and writes through backend APIs (and local read models where needed)

## Backend Components

- `jobtracker/main.py`
  - app lifecycle
  - DB init on startup
  - router registration
- `jobtracker/api/auth.py`
  - Gmail and iCloud credential lifecycle
- `jobtracker/api/sync.py`
  - email sync trigger and status
- `jobtracker/api/emails.py`
  - email listing, filters, stats, detail, review/delete operations
- `jobtracker/api/classification.py`
  - classification endpoints, corrections, review queue, SetFit/lite-mode controls
- `jobtracker/api/applications.py`
  - application CRUD, linking, mark-not-job flow, overview stats
- `jobtracker/api/websocket.py`
  - `/ws/sync-status` event stream

## Classifier Architecture

Hybrid pipeline in `backend/jobtracker/classifier`:

1. Rules layer (regex/domain heuristics)
2. Embedding similarity layer (`intfloat/e5-small-v2`)
3. SetFit layer (enabled once enough training data exists)

Current categories:

- `applied`
- `pending_application`
- `interview`
- `rejection`
- `offer`
- `assessment`
- `follow_up`
- `needs_review`
- `other`

Training feedback loop:

- user corrections write to `training_data`
- embeddings are stored in `email_embeddings`
- SetFit retraining is triggered when data thresholds are met

## macOS App Structure

Primary files under `apps/macos/JobTracker/JobTracker/JobTracker`:

- `AppShellView.swift`: top-level shell with sidebar sections (Dashboard, Applications, Emails, Settings)
- `AppModel.swift`: shared state and backend lifecycle handling
- `DashboardView.swift`: pipeline/system summary
- `ContentView.swift` (`ApplicationsView`): application list and detail views
- `EmailsView.swift`: inbox + filters + correction actions
- `SettingsView.swift`: accounts, sync controls, classifier mode, themes
- `Formatting.swift`: theming, backdrop, card/button styles

Recent UX architecture updates:

- section views are kept initialized/cached in `AppShellView` to avoid visible re-render lag when switching tabs
- backdrop rendering is centralized to reduce repeated heavy backgrounds per tab

## Data Model Highlights

Core DB entities (`backend/jobtracker/database/models.py`):

- `Application`
- `Email`
- `TrainingData`
- `EmailEmbedding`
- `SyncState`
- `Contact`
- `Interview`

Notable behavior:

- unlinked job emails are tracked explicitly (`application_id IS NULL` for job-related categories)
- `mark-not-job` reclassifies linked emails to `other`, unlinks them, and removes the application

## Repository Boundaries

```text
backend/        API, DB, ML, tests
apps/macos/     desktop app
apps/mobile/    reserved for future mobile app
scripts/        local tooling and packaging
```

CI workflows:

- `.github/workflows/backend-ci.yml`
- `.github/workflows/macos-ci.yml`

Both workflows are path-scoped and read-only (build/test checks only).
