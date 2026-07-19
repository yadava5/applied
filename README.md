# JobTracker

JobTracker is a native macOS app plus a local Python backend that tracks your job pipeline by syncing Gmail/iCloud emails, classifying messages, and linking them to applications.

> **Live (web):** https://jobtracker-web-five.vercel.app · fixture demo at `/demo` · in-browser classifier: https://huggingface.co/spaces/yadava5/jobtracker-classifier
>
> **2026 status — hosted web app + portable ML.** Beyond the original desktop app, the pipeline now ships as a Next.js 16 web product and a 3-layer email classifier (201 regex rules → e5 embedding similarity → fine-tuned SetFit head) exported to int8 ONNX that runs **entirely in the browser** (22.8MB, zero servers), verified output-identical to the Python model. 0.979 macro-F1, CI-gated ≥ 0.95; 182 tests. The landing hero runs a real email through all three layers past the 0.85 confidence gate. Independently audited live (2026-07): ship-ready — zero functional bugs, zero console errors.

This repo is intentionally documented without screenshots right now. The previous images were outdated and have been removed.

## What Works Today

- Gmail and iCloud account connection
- Incremental or full sync from connected accounts
- Hybrid email classifier:
  - rules
  - embedding similarity
  - SetFit (when enough training data exists)
- Classification categories:
  - `applied`
  - `pending_application`
  - `interview`
  - `rejection`
  - `offer`
  - `assessment`
  - `follow_up`
  - `needs_review`
  - `other`
- Review queue and user corrections feeding training data
- Application linking and relinking from email signals
- "Mark as Not Job Posting" flow (reclassifies linked emails to `other` and removes the application)
- Email filters in UI and backend:
  - `Unreviewed Only`
  - `Unlinked Job Emails Only`
- Applications tab layout options:
  - `Feature Cards`
  - `Compact Rows`
  - `Status Board`
- Theme presets with per-theme background images
- WebSocket sync status updates (`/ws/sync-status`)

## Monorepo Layout

```text
jobtracker/
├── backend/                    # FastAPI backend, classifier, DB, tests
├── apps/
│   ├── macos/                  # SwiftUI macOS app
│   └── mobile/                 # Reserved for future mobile app
├── docs/                       # Active project documentation
├── scripts/                    # Setup, run, bundle, repair scripts
└── .github/workflows/          # Backend + macOS CI
```

## Quick Start

```bash
git clone <your-repo-url>
cd jobtracker

# One-time backend install
./scripts/install.sh

# Start backend on 127.0.0.1:8000
./scripts/start_backend.sh
```

Open the macOS app project:

```bash
open apps/macos/JobTracker/JobTracker/JobTracker.xcodeproj
```

## Web app (beta)

A Next.js 16 frontend for the cloud deployment lives in `apps/web/` (scaffolded in issue #24). It is not wired to a production backend yet — the typed API client ships in a follow-up — but the auth shell and Supabase session handling are in place.

Quickstart:

```bash
cd apps/web
cp .env.example .env.local       # fill Supabase URL, anon key, BACKEND_API_URL
pnpm install --frozen-lockfile
pnpm dev                         # http://localhost:3000
```

Full setup, stack, and auth-flow notes: see `apps/web/README.md` and the "Frontend scaffold (C9)" section of `docs/WEB_ARCHITECTURE.md`.

## Active Docs

- `docs/SETUP.md` - local setup and day-to-day development flow
- `docs/ARCHITECTURE.md` - system architecture and component boundaries
- `docs/API_SPEC.md` - backend API and WebSocket contract
- `docs/ML_STRATEGY.md` - classifier behavior and training lifecycle

## CI

- `backend-ci.yml`: runs backend tests on backend-related changes
- `macos-ci.yml`: builds the macOS app on macOS runners for app-related changes

Both pipelines are read-only quality gates and do not rewrite source files.

## Troubleshooting

If backend logs show `database disk image is malformed`:

```bash
./scripts/repair_local_db.sh
```

If port `8000` is already in use:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

Use `./scripts/start_backend.sh` so it can detect healthy existing backend instances and avoid duplicate launches.

## Packaging

```bash
./scripts/bundle.sh --configuration Debug
```

This stages:

- `dist/backend/jobtracker-backend`
- `dist/app/JobTracker.app`

## License

MIT
