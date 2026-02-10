# Development Setup Guide

## Prerequisites

| Requirement | Version | Check Command |
|-------------|---------|---------------|
| macOS | **15+** (Sequoia or Tahoe) | Apple menu → About This Mac |
| Python | 3.11+ | `python3 --version` |
| Xcode | 16+ | `xcode-select --version` |
| Git | any | `git --version` |
| Homebrew | any (recommended) | `brew --version` |
| RAM | 8GB minimum, 16GB recommended | Apple menu → About This Mac |

> **Note:** macOS 15+ is required for Swift Charts, modern SwiftUI APIs, and Liquid Glass design on Tahoe.

## Step 1: Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/jobtracker.git
cd jobtracker
```

## Step 2: Python Backend Setup

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install PyTorch (CPU-only — much smaller, no GPU bloat)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install all other dependencies
pip install -r requirements.txt

# Download ML models (one-time, ~80MB)
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/e5-small-v2')"

# Initialize database (creates tables, enables WAL mode)
python -m jobtracker.database.init

# Start backend server (async)
uvicorn jobtracker.main:app --host 127.0.0.1 --port 8000 --reload
```

**Verify it works:**

```bash
curl http://127.0.0.1:8000/health
# Expected: {"status": "ok", ...}
```

## Step 3: Gmail API Setup

This requires a one-time Google Cloud setup (free tier, no credit card needed).

### 3a. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a Project** → **New Project**
3. Name: `JobTracker`
4. Click **Create**

### 3b. Enable Gmail API

1. Go to **APIs & Services → Library**
2. Search for **Gmail API**
3. Click **Enable**

### 3c. Configure OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. User type: **External** → Create
3. Fill in:
   - App name: `JobTracker`
   - User support email: your email
   - Developer contact: your email
4. Click **Save and Continue**
5. **Scopes**: Add `https://www.googleapis.com/auth/gmail.readonly`
6. **Test users**: Add your Gmail address
7. Click **Save and Continue** through remaining steps

### 3d. Create OAuth Credentials

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth Client ID**
3. Application type: **Desktop app**
4. Name: `JobTracker Desktop`
5. Click **Create**
6. **Download JSON** → save as `backend/credentials/gmail_credentials.json`

### 3e. First Authentication

```bash
# Start the backend, then:
curl -X POST http://127.0.0.1:8000/auth/gmail
```

This opens your browser for Google consent. Approve it. The OAuth token is stored securely in your macOS Keychain — never in plain files.

> **Note:** While in "Testing" status, Google shows a warning screen saying the app isn't verified. This is normal for personal use. Click "Advanced" → "Go to JobTracker (unsafe)" → Allow. You do NOT need to publish or verify the app for personal use.

## Step 4: iCloud Mail Setup

### 4a. Enable Two-Factor Authentication

If not already enabled:
1. Go to **System Settings → Apple Account → Sign-In & Security**
2. Enable **Two-Factor Authentication**

### 4b. Generate App-Specific Password

1. Go to [account.apple.com](https://account.apple.com)
2. Sign in with your Apple Account
3. Go to **Sign-In and Security → App-Specific Passwords**
4. Click **Generate an app-specific password**
5. Name it: `JobTracker`
6. Copy the generated password (format: `xxxx-xxxx-xxxx-xxxx`)

### 4c. Connect in the App

```bash
curl -X POST http://127.0.0.1:8000/auth/icloud \
  -H "Content-Type: application/json" \
  -d '{"email": "your@icloud.com", "app_specific_password": "xxxx-xxxx-xxxx-xxxx"}'
```

The password is stored in your macOS Keychain.

**iCloud IMAP Settings (reference):**

| Setting | Value |
|---------|-------|
| Server | `imap.mail.me.com` |
| Port | 993 |
| SSL/TLS | Required |
| Username | Your full iCloud email address |
| Password | App-specific password (NOT your Apple Account password) |

## Step 5: First Sync

```bash
# Trigger sync for all connected accounts
curl -X POST http://127.0.0.1:8000/sync

# Check results
curl http://127.0.0.1:8000/emails?limit=5
```

## Step 6: macOS SwiftUI App (Development)

```bash
cd macos/JobTracker
open JobTracker.xcodeproj
```

In Xcode:
1. Set **Minimum Deployment Target** to **macOS 15.0** (or 26.0 for full Liquid Glass)
2. Select your **Development Team** in Signing & Capabilities
3. Add Swift Package dependencies:
   - GRDB.swift: `https://github.com/groue/GRDB.swift.git`
   - GRDBQuery: `https://github.com/groue/GRDBQuery.git`
4. Build target: **My Mac**
5. Build and run: **⌘R**
6. The app connects to the Python backend at `localhost:8000`

> **Tip:** For Liquid Glass development, run on macOS 26 (Tahoe) to see the full design system.

## Step 7: Background Service (Optional)

Install the Launch Agent for automatic background syncing:

```bash
# Copy plist to LaunchAgents directory
cp scripts/com.jobtracker.backend.plist ~/Library/LaunchAgents/

# Edit the plist to set YOUR paths:
#   - Python venv path
#   - Project directory path
#   - Log file paths
nano ~/Library/LaunchAgents/com.jobtracker.backend.plist

# Load the Launch Agent
launchctl load ~/Library/LaunchAgents/com.jobtracker.backend.plist

# Verify it's running
curl http://127.0.0.1:8000/health
```

To stop/unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.jobtracker.backend.plist
```

---

## Dependencies

### Python Backend (`backend/requirements.txt`)

```
# Web framework (async)
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
pydantic>=2.5.0
websockets>=12.0               # WebSocket support for real-time updates

# Async database
aiosqlite>=0.19.0              # Async SQLite driver
sqlmodel>=0.0.14               # SQLAlchemy + Pydantic ORM
sqlalchemy[asyncio]>=2.0.25    # Async SQLAlchemy core

# Gmail API
google-api-python-client>=2.100.0
google-auth-httplib2>=0.1.1
google-auth-oauthlib>=1.1.0

# Async IMAP
aioimaplib>=2.0.0              # Async IMAP client for iCloud

# Credential storage
keyring>=24.3.0                # macOS Keychain integration

# ML & NLP
sentence-transformers>=2.2.0   # Loads e5-small-v2 model
setfit>=1.0.0                  # Few-shot classification
scikit-learn>=1.3.0
numpy>=1.24.0

# Note: Install PyTorch CPU-only separately:
# pip install torch --index-url https://download.pytorch.org/whl/cpu

# Email parsing
beautifulsoup4>=4.12.0
python-dateutil>=2.8.0
lxml>=5.0.0                    # Faster HTML parsing

# Testing
pytest>=7.4.0
pytest-asyncio>=0.23.0         # Async test support
httpx>=0.26.0                  # Async HTTP client for testing

# Distribution (optional, for bundling)
pyinstaller>=6.3.0             # Bundle Python as standalone app
```

### Swift macOS App

```swift
// Package.swift dependencies (via SPM)
dependencies: [
    .package(url: "https://github.com/groue/GRDB.swift.git", from: "6.24.0"),
    .package(url: "https://github.com/groue/GRDBQuery.git", from: "0.8.0"),
]
```

Swift Charts is built into SwiftUI on macOS 14+ — no third-party library needed.

---

## Verify Everything Works

Run these checks after setup:

```bash
# 1. Backend is running
curl http://127.0.0.1:8000/health
# ✅ {"status": "ok", "db_connected": true, ...}

# 2. Gmail is connected
curl http://127.0.0.1:8000/auth/status
# ✅ gmail connected: true

# 3. Trigger a sync
curl -X POST http://127.0.0.1:8000/sync
# ✅ {"status": "completed", "emails_fetched": N, ...}

# 4. Check classified emails
curl "http://127.0.0.1:8000/emails?limit=5"
# ✅ List of emails with classified_as field populated

# 5. ML classifier is working
curl http://127.0.0.1:8000/ml/status
# ✅ {"active_layers": ["rules"], ...}
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `python3: command not found` | Install Python 3.11+: `brew install python@3.11` |
| Port 8000 already in use | Find what's using it: `lsof -i :8000` → kill the process, or change port in `config.py` |
| Gmail OAuth fails | Delete token from Keychain app (search "jobtracker"), try `POST /auth/gmail` again |
| Gmail shows "unverified app" warning | Normal for personal use — click Advanced → Continue |
| iCloud connection refused | Verify 2FA is enabled on your Apple Account, regenerate app-specific password |
| iCloud: "Authentication failed" | Make sure you're using the app-specific password, NOT your Apple Account password |
| ML models won't download | Check internet connection, try: `pip install sentence-transformers --force-reinstall` |
| SetFit training is slow | Normal — 2-5 min on CPU with ~50 examples. It runs in the background, doesn't block the app |
| SwiftUI "Connection refused" | Backend must be running first: `curl localhost:8000/health` |
| Database locked errors | Shouldn't happen with WAL mode. If it does: stop all processes, delete `.db-wal` and `.db-shm` files, restart |
| `launchd` service not starting | Check logs: `cat ~/Library/Logs/JobTracker/backend-error.log` |

---

## Distribution (For Sharing With Others)

### Bundling the Python Backend

Use PyInstaller to create a standalone executable:

```bash
cd backend
source .venv/bin/activate

# Create spec file (first time)
pyinstaller --name jobtracker-backend \
  --onedir \
  --hidden-import=aiosqlite \
  --hidden-import=sqlmodel \
  jobtracker/main.py

# Build
pyinstaller jobtracker-backend.spec

# Output: dist/jobtracker-backend/
```

### Code Signing & Notarization

Requires Apple Developer account ($99/year):

```bash
# Sign the app
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name (TEAMID)" \
  dist/JobTracker.app

# Notarize (submit to Apple)
xcrun notarytool submit dist/JobTracker.dmg \
  --apple-id "your@email.com" \
  --team-id "TEAMID" \
  --password "@keychain:AC_PASSWORD" \
  --wait

# Staple the ticket
xcrun stapler staple dist/JobTracker.dmg
```

### Creating DMG

```bash
# Use create-dmg (install via: brew install create-dmg)
create-dmg \
  --volname "JobTracker" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "JobTracker.app" 150 190 \
  --app-drop-link 450 185 \
  "dist/JobTracker.dmg" \
  "dist/JobTracker.app"
```

---

## Development Tips

### Running backend in development mode

```bash
cd backend
source .venv/bin/activate
uvicorn jobtracker.main:app --host 127.0.0.1 --port 8000 --reload
```

The `--reload` flag auto-restarts the server when you change Python files.

### Viewing API docs

FastAPI auto-generates interactive API docs:
- **Swagger UI**: http://127.0.0.1:8000/docs
- **ReDoc**: http://127.0.0.1:8000/redoc

### Running tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

### Inspecting the database

```bash
sqlite3 ~/Library/Application\ Support/JobTracker/jobtracker.db
.tables
SELECT * FROM applications LIMIT 5;
SELECT * FROM emails WHERE classified_as = 'rejection' LIMIT 5;
.quit
```

### Resetting everything

```bash
# Delete database (start fresh)
rm ~/Library/Application\ Support/JobTracker/jobtracker.db

# Re-initialize
python -m jobtracker.database.init

# Delete ML models (re-download)
rm -rf backend/models/

# Delete stored credentials
python -c "import keyring; keyring.delete_password('jobtracker', 'gmail_token')"
python -c "import keyring; keyring.delete_password('jobtracker', 'icloud_password')"
```
