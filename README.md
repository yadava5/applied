# JobTracker — Email-Powered Job Application Tracker

A desktop application that automatically tracks your job applications by reading your Gmail and iCloud Mail, classifying emails using ML, and presenting a clean dashboard of your job search progress.

## Overview

JobTracker syncs your email from Gmail and iCloud, identifies job-related messages (rejections, interview requests, offers, confirmations), and organizes them into a trackable pipeline — so you never lose track of where you stand.

## Architecture

- **Backend**: Python (FastAPI) — handles email fetching, ML classification, and data management
- **Frontend (macOS)**: SwiftUI — native macOS experience
- **Frontend (Windows/Linux)**: Tauri (planned, Phase 9)
- **Database**: SQLite (WAL mode) — shared between backend and frontend
- **ML**: Rule-based + sentence embeddings + SetFit (few-shot learning)
- **Background Sync**: launchd (macOS) / system scheduler

```
┌──────────────────┐    HTTP/REST     ┌─────────────────────┐
│   SwiftUI App    │◄────────────────►│   Python Backend    │
│   (macOS UI)     │  localhost:8000  │    (FastAPI)        │
└────────┬─────────┘                  └──────────┬──────────┘
         │                                       │
         │  Read                         Write   │
         └───────────►  SQLite  ◄────────────────┘
                       (WAL mode)
```

## Key Features

- [x] Gmail OAuth2 integration (read-only)
- [x] iCloud Mail IMAP integration
- [x] ML email classification (rule-based → few-shot learning)
- [x] Application pipeline dashboard (Applied → Interview → Offer → Rejected)
- [x] Scheduled background email sync
- [x] Analytics (response rates, timelines, trends)
- [x] Confidence-based review (uncertain classifications flagged for user)
- [x] User correction feedback loop (improves ML over time)
- [ ] Smart reminders (follow-up suggestions)
- [ ] Browser extension (capture applications from job sites)
- [ ] Windows/Linux support via Tauri

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
| Backend API | Python 3.11+, FastAPI, Uvicorn |
| Gmail Integration | google-api-python-client (OAuth2) |
| iCloud Integration | imaplib (IMAP + app-specific password) |
| ML Classification | scikit-learn, sentence-transformers, SetFit |
| Database | SQLite (WAL mode) |
| macOS Frontend | SwiftUI (macOS 13+) |
| Future: Win/Linux Frontend | Tauri (Rust + Web) |
| Background Service | launchd (macOS) |
| Credential Storage | macOS Keychain via `keyring` |

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
│   │   ├── main.py                 # FastAPI app entry point
│   │   ├── config.py               # Settings and configuration
│   │   ├── database/
│   │   │   ├── __init__.py
│   │   │   ├── models.py           # SQLAlchemy/SQLite models
│   │   │   ├── schema.sql          # Raw SQL schema
│   │   │   └── connection.py       # DB connection (WAL mode)
│   │   ├── email_clients/
│   │   │   ├── __init__.py
│   │   │   ├── gmail_client.py     # Gmail API OAuth2 client
│   │   │   ├── icloud_client.py    # iCloud IMAP client
│   │   │   └── email_parser.py     # Shared email parsing logic
│   │   ├── classifier/
│   │   │   ├── __init__.py
│   │   │   ├── rules.py            # Rule-based regex classifier
│   │   │   ├── embeddings.py       # Sentence embeddings (MiniLM)
│   │   │   ├── setfit_model.py     # SetFit few-shot model
│   │   │   └── hybrid.py           # Hybrid classifier (combines all layers)
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── sync_service.py     # Email sync orchestration
│   │   │   ├── classification_service.py
│   │   │   └── analytics_service.py
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── auth_routes.py      # Gmail OAuth, iCloud credentials
│   │       ├── email_routes.py     # Email sync and listing
│   │       ├── application_routes.py
│   │       └── analytics_routes.py
│   └── tests/
│       ├── test_gmail_client.py
│       ├── test_icloud_client.py
│       ├── test_classifier.py
│       └── test_api.py
├── macos/
│   └── JobTracker/                 # Xcode SwiftUI project
│       ├── JobTracker.xcodeproj
│       ├── JobTrackerApp.swift
│       ├── Models/
│       ├── Views/
│       ├── Services/
│       └── Resources/
└── scripts/
    ├── install.sh                  # One-command setup
    ├── com.jobtracker.backend.plist # launchd config
    └── seed_rules.py               # Initial classification rules
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

## License

MIT
