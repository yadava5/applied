#!/bin/bash
# =============================================================================
# JobTracker Notarization Script
# =============================================================================
# Notarizes a signed .app bundle using xcrun notarytool and staples the result.
#
# Usage:
#   ./scripts/notarize.sh /path/to/JobTracker.app
#
# Auth options:
#   A) Use keychain profile:
#      export NOTARY_PROFILE="jobtracker-notary"
#
#   B) Use Apple ID credentials:
#      export APPLE_ID="you@example.com"
#      export APPLE_TEAM_ID="TEAMID1234"
#      export APPLE_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
# =============================================================================

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: ./scripts/notarize.sh /path/to/JobTracker.app"
    exit 1
fi

APP_PATH="$1"
if [[ ! -d "$APP_PATH" ]]; then
    echo "App not found: $APP_PATH"
    exit 1
fi

if ! command -v xcrun >/dev/null 2>&1; then
    echo "xcrun is required but not installed."
    exit 1
fi

if ! xcrun notarytool --help >/dev/null 2>&1; then
    echo "notarytool not available. Install Xcode command line tools."
    exit 1
fi

APP_BASENAME="$(basename "$APP_PATH" .app)"
PARENT_DIR="$(cd "$(dirname "$APP_PATH")" && pwd)"
ZIP_PATH="$PARENT_DIR/${APP_BASENAME}-notarize.zip"

echo "==> Preparing zip for notarization"
rm -f "$ZIP_PATH"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

echo "==> Submitting to Apple notarization service"
if [[ -n "${NOTARY_PROFILE:-}" ]]; then
    xcrun notarytool submit "$ZIP_PATH" \
        --keychain-profile "$NOTARY_PROFILE" \
        --wait
else
    : "${APPLE_ID:?APPLE_ID is required when NOTARY_PROFILE is not set}"
    : "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required when NOTARY_PROFILE is not set}"
    : "${APPLE_APP_PASSWORD:?APPLE_APP_PASSWORD is required when NOTARY_PROFILE is not set}"

    xcrun notarytool submit "$ZIP_PATH" \
        --apple-id "$APPLE_ID" \
        --team-id "$APPLE_TEAM_ID" \
        --password "$APPLE_APP_PASSWORD" \
        --wait
fi

echo "==> Stapling notarization ticket"
xcrun stapler staple "$APP_PATH"

echo "==> Verifying stapled app"
spctl --assess --type execute --verbose "$APP_PATH"

echo "==> Notarization complete: $APP_PATH"
