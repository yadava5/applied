# JobTracker — Email-Powered Job Application Tracker

A native macOS application that automatically tracks your job applications by reading your Gmail and iCloud Mail, classifying emails using local ML, and presenting a beautiful Liquid Glass dashboard of your job search progress.

## Overview

JobTracker syncs your email from Gmail and iCloud, identifies job-related messages (rejections, interview requests, offers, confirmations), and organizes them into a trackable pipeline — so you never lose track of where you stand.

**Key principles:**
- 🔒 **Privacy-first**: All processing happens locally. Your emails never leave your machine.
- 💰 **Zero cost**: No API fees, no subscriptions. Uses free local ML models.
- 🍎 **Native macOS**: Built with SwiftUI and Liquid Glass design for macOS 15+.

## Architecture

- **Backend**: Python 3.11+ (FastAPI, async) — handles email fetching, ML classification, and data management
- **Frontend**: SwiftUI with Liquid Glass — native macOS 15+ experience
- **Database**: SQLite (WAL mode, async via aiosqlite) — shared between backend and frontend
- **ML**: 3-layer hybrid classifier (rules → embeddings → SetFit)
- **Background Sync**: SMAppService + launchd (modern macOS approach)
- **Icons**: SF Symbols 7

```
┌─────────────────────────────────────────────────────────────────┐
│                        macOS 15+ (Sequoia/Tahoe)                │
│                                                                 │
│  ┌─────────────────────┐  REST API   ┌────────────────────────┐ │
│  │   SwiftUI App       │◄───────────►│   Python Backend       │ │
│  │   (Liquid Glass UI) │ :8000       │   (FastAPI + async)    │ │
│  │                     │             │                        │ │
│  │  ┌───────────────┐  │             │  ┌──────────────────┐  │ │
│  │  │ MenuBarExtra  │  │             │  │ Gmail + iCloud   │  │ │
│  │  │ Dashboard     │  │             │  │ Hybrid Classifier│  │ │
│  │  │ SF Symbols 7  │  │             │  │ Embeddings Store │  │ │
│  │  └───────────────┘  │             │  └──────────────────┘  │ │
│  │                     │             │                        │ │
│  │  GRDB.swift (read)  │             │  aiosqlite (write)     │ │
│  └──────────┬──────────┘             └───────────┬────────────┘ │
│             │                                    │              │
│             └──────────► SQLite (WAL) ◄──────────┘              │
│                    ~/Library/Application Support/               │
│                                                                 │
│             SMAppService → launchd (background sync)            │
└─────────────────────────────────────────────────────────────────┘
```

## Key Features

- [x] Gmail OAuth2 integration (read-only)
- [x] iCloud Mail IMAP integration (async via aioimaplib)
- [x] ML email classification (3-layer hybrid: rules → embeddings → SetFit)
- [x] Application pipeline dashboard (Applied → Interview → Offer → Rejected)
- [x] Scheduled background email sync (via SMAppService + launchd)
- [ ] Analytics module (currently de-scoped from active app surface)
- [x] Confidence-based review (uncertain classifications flagged for user)
- [x] User correction feedback loop (improves ML over time)
- [x] Menu bar status icon (MenuBarExtra)
- [x] Liquid Glass UI + SF Symbols 7 (native macOS Tahoe design)
- [ ] Smart reminders (follow-up suggestions)
- [ ] Spotlight integration (search applications from Spotlight)
- [ ] Browser extension (capture applications from job sites)
- [ ] Windows/Linux support via Tauri (Phase 9, future)

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System design, technology choices, and component interactions |
| [Phases](docs/PHASES.md) | Implementation phases with trackable checkboxes |
| [ML Strategy](docs/ML_STRATEGY.md) | Email classification approach, models, and training strategy |
| [API Specification](docs/API_SPEC.md) | Python backend REST API endpoints |
| [Setup Guide](docs/SETUP.md) | Development environment setup instructions |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Backend API | Python 3.11+, FastAPI (async), Uvicorn |
| Database (Backend) | SQLite + aiosqlite + SQLModel (async ORM) |
| Gmail Integration | google-api-python-client (OAuth2) |
| iCloud Integration | aioimaplib (async IMAP) |
| ML Classification | sentence-transformers (e5-small-v2), SetFit, scikit-learn |
| Embeddings Storage | SQLite (not pickle files) |
| macOS Frontend | SwiftUI (macOS 15+), Liquid Glass, SF Symbols 7 |
| Database (Frontend) | GRDB.swift + GRDBQuery (reactive reads) |
| Charts | Swift Charts (built-in) |
| Background Service | SMAppService + launchd |
| Credential Storage | macOS Keychain via `keyring` |
| Distribution | PyInstaller (backend bundling), notarized DMG |
| Future: Win/Linux | Tauri + platform-specific credential storage |

## System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| macOS | 15.0 (Sequoia) | 26.0 (Tahoe) |
| RAM | 8GB | 16GB |
| Disk Space | 5GB free | 10GB free |
| CPU | Any Apple Silicon or Intel | M1 or later |
| GPU | Not required | Not required |

> **Note:** 8GB RAM works fine for normal operation. SetFit retraining (2-5 min, occasional) uses ~2GB peak RAM. A "lite mode" disables SetFit for constrained machines.

## Project Structure (Planned)

```
jobtracker/
├── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PHASES.md
│   ├── ML_STRATEGY.md
│   ├── API_SPEC.md
│   └── SETUP.md
├── backend/
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── jobtracker/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app entry point (async)
│   │   ├── config.py               # Settings and configuration
│   │   ├── database/
│   │   │   ├── __init__.py
│   │   │   ├── models.py           # SQLModel async models
│   │   │   ├── schema.sql          # Raw SQL schema (reference)
│   │   │   └── connection.py       # Async DB connection (aiosqlite + WAL)
│   │   ├── email_clients/
│   │   │   ├── __init__.py
│   │   │   ├── gmail_client.py     # Gmail API OAuth2 client (async)
│   │   │   ├── icloud_client.py    # iCloud IMAP client (aioimaplib)
│   │   │   └── email_parser.py     # Shared email parsing logic
│   │   ├── classifier/
│   │   │   ├── __init__.py
│   │   │   ├── rules.py            # Rule-based regex classifier
│   │   │   ├── embeddings.py       # Sentence embeddings (e5-small-v2)
│   │   │   ├── setfit_model.py     # SetFit few-shot model
│   │   │   └── hybrid.py           # Hybrid classifier (combines all layers)
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── sync_service.py     # Email sync orchestration (async)
│   │   │   ├── classification_service.py
│   │   │   ├── analytics_service.py
│   │   │   └── task_manager.py     # Background task tracking
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── auth_routes.py      # Gmail OAuth, iCloud credentials
│   │       ├── email_routes.py     # Email sync and listing
│   │       ├── application_routes.py
│   │       ├── analytics_routes.py
│   │       └── websocket.py        # Real-time sync status (WebSocket)
│   └── tests/
│       ├── test_gmail_client.py
│       ├── test_icloud_client.py
│       ├── test_classifier.py
│       └── test_api.py
├── macos/
│   └── JobTracker/                 # Xcode SwiftUI project
│       ├── JobTracker.xcodeproj
│       ├── JobTrackerApp.swift
│       ├── Models/                 # GRDB models matching SQLite schema
│       ├── Views/
│       │   ├── Dashboard/          # Main dashboard with status cards
│       │   ├── Applications/       # Application list and detail
│       │   ├── Emails/             # Email inbox and review queue
│       │   ├── Analytics/          # Optional future module (currently de-scoped)
│       │   ├── Settings/           # Account connection, preferences
│       │   └── Components/         # Reusable Liquid Glass components
│       ├── Services/
│       │   ├── BackendAPIClient.swift
│       │   ├── DatabaseReader.swift  # GRDB + GRDBQuery
│       │   └── BackendLifecycle.swift # SMAppService management
│       ├── MenuBar/                # MenuBarExtra implementation
│       └── Resources/
│           └── Assets.xcassets     # App icon (Icon Composer)
├── scripts/
│   ├── install.sh                  # One-command setup
│   ├── bundle.sh                   # PyInstaller bundling for distribution
│   ├── notarize.sh                 # Apple notarization script
│   ├── com.jobtracker.backend.plist # launchd config (reference)
│   └── seed_rules.py               # Initial classification rules
└── dist/                           # Distribution artifacts (gitignored)
    ├── JobTracker.app
    └── JobTracker.dmg
```

## Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/jobtracker.git
cd jobtracker

# Backend setup
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start backend
uvicorn jobtracker.main:app --host 127.0.0.1 --port 8000 --reload

# See docs/SETUP.md for full setup including Gmail/iCloud auth
```

## Troubleshooting

If backend responses include `database disk image is malformed`, run:

```bash
./scripts/repair_local_db.sh
```

By default this repairs:

- `~/Library/Application Support/JobTracker/jobtracker.db`
- and creates a timestamped backup under `~/Library/Application Support/JobTracker/backups`

## License

MIT
