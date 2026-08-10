# Setup Guide

## Requirements

- macOS with Xcode installed
- Python 3.11+
- Git
- Internet for first model download (`intfloat/e5-small-v2`)

Current Xcode project target is `macOS 26.2` in `apps/macos/JobTracker/JobTracker/JobTracker.xcodeproj`.

## 1. Clone

```bash
git clone <your-repo-url>
cd applied
```

## 2. Backend Install (one-time)

```bash
./scripts/install.sh
```

What this script does:

- creates `backend/.venv` (if missing)
- installs PyTorch CPU wheels
- installs backend dependencies
- downloads embedding model
- initializes the SQLite database

## 3. Run Backend

```bash
./scripts/start_backend.sh
```

Optional hot reload:

```bash
./scripts/start_backend.sh --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 4. Run macOS App

```bash
open apps/macos/JobTracker/JobTracker/JobTracker.xcodeproj
```

In Xcode:

1. Select scheme `JobTracker`
2. Select destination `My Mac`
3. Build and run (`Cmd+R`)

The app talks to the local backend at `http://127.0.0.1:8000`.

## 5. Connect Email Accounts

Use the Settings tab in the app.

Gmail flow:

1. Paste Google OAuth `client_secret.json` content in Settings
2. Authenticate Gmail (browser-based OAuth)

iCloud flow:

1. Generate Apple app-specific password
2. Enter iCloud email + app password in Settings

## Useful Commands

Run backend tests:

```bash
cd backend
PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring pytest tests -q
```

Repair a malformed SQLite database:

```bash
./scripts/repair_local_db.sh
```

Build staged app + backend binary:

```bash
./scripts/bundle.sh --configuration Debug
```

## Common Issues

`Address already in use` on backend start:

- another process is already on port `8000`
- use `lsof -nP -iTCP:8000 -sTCP:LISTEN` to find it

`database disk image is malformed`:

- run `./scripts/repair_local_db.sh`
- this script makes a timestamped backup before repair
