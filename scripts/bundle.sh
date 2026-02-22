#!/bin/bash
# =============================================================================
# JobTracker macOS Bundle Script
# =============================================================================
# Builds:
#  1) PyInstaller backend binary
#  2) Release JobTracker.app from Xcode
#  3) App bundle staged under dist/app with embedded backend binary
#
# Usage:
#   ./scripts/bundle.sh
#   ./scripts/bundle.sh --configuration Debug
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
MACOS_PROJECT_DIR="$PROJECT_ROOT/apps/macos/JobTracker/JobTracker"
XCODE_PROJECT="$MACOS_PROJECT_DIR/JobTracker.xcodeproj"
SCHEME="JobTracker"
CONFIGURATION="Release"
UNIVERSAL_BUILD=true
MODEL_STRATEGY="download_on_first_launch"
BACKEND_UNIVERSAL=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --configuration)
            CONFIGURATION="${2:-}"
            shift 2
            ;;
        --no-universal)
            UNIVERSAL_BUILD=false
            shift
            ;;
        --model-strategy)
            MODEL_STRATEGY="${2:-}"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: ./scripts/bundle.sh [--configuration Release|Debug] [--no-universal] [--model-strategy download_on_first_launch|bundle_in_app]"
            exit 1
            ;;
    esac
done

DIST_DIR="$PROJECT_ROOT/dist"
DERIVED_DATA_DIR="$DIST_DIR/derived-data"
APP_STAGE_DIR="$DIST_DIR/app"
BACKEND_STAGE_DIR="$DIST_DIR/backend"
BACKEND_BINARY_NAME="jobtracker-backend"

if [[ ! -d "$BACKEND_DIR" ]]; then
    echo "Backend directory not found: $BACKEND_DIR"
    exit 1
fi

if [[ ! -d "$MACOS_PROJECT_DIR" ]]; then
    echo "macOS project directory not found: $MACOS_PROJECT_DIR"
    exit 1
fi

if ! command -v xcodebuild >/dev/null 2>&1; then
    echo "xcodebuild is required but not installed."
    exit 1
fi

PYTHON_BIN=""
if [[ -x "$BACKEND_DIR/.venv311/bin/python" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv311/bin/python"
elif [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python 3 not found."
    exit 1
fi

echo "==> Using python: $PYTHON_BIN"
echo "==> Installing/updating PyInstaller"
"$PYTHON_BIN" -m pip install --quiet --upgrade pyinstaller

echo "==> Building backend binary with PyInstaller"
pushd "$BACKEND_DIR" >/dev/null
"$PYTHON_BIN" -m PyInstaller \
    --clean \
    --noconfirm \
    --onefile \
    --name "$BACKEND_BINARY_NAME" \
    jobtracker/main.py
popd >/dev/null

BACKEND_BINARY_PATH="$BACKEND_DIR/dist/$BACKEND_BINARY_NAME"
if [[ ! -x "$BACKEND_BINARY_PATH" ]]; then
    echo "Expected backend binary not found: $BACKEND_BINARY_PATH"
    exit 1
fi

if [[ "$UNIVERSAL_BUILD" == true ]]; then
    PYTHON_BIN_X86="${PYTHON_BIN_X86_64:-}"
    if [[ -n "$PYTHON_BIN_X86" ]] && command -v lipo >/dev/null 2>&1; then
        echo "==> Attempting x86_64 backend build for universal binary"
        pushd "$BACKEND_DIR" >/dev/null
        arch -x86_64 "$PYTHON_BIN_X86" -m PyInstaller \
            --clean \
            --noconfirm \
            --onefile \
            --name "${BACKEND_BINARY_NAME}-x86_64" \
            jobtracker/main.py
        popd >/dev/null

        X86_BINARY="$BACKEND_DIR/dist/${BACKEND_BINARY_NAME}-x86_64"
        if [[ -x "$X86_BINARY" ]]; then
            lipo -create "$BACKEND_BINARY_PATH" "$X86_BINARY" \
                -output "$BACKEND_DIR/dist/${BACKEND_BINARY_NAME}-universal"
            BACKEND_BINARY_PATH="$BACKEND_DIR/dist/${BACKEND_BINARY_NAME}-universal"
            BACKEND_UNIVERSAL=true
        else
            echo "warning: x86_64 backend artifact missing; using single-arch backend binary"
        fi
    else
        echo "warning: x86_64 Python not configured (set PYTHON_BIN_X86_64 to enable universal backend lipo)."
        echo "warning: proceeding with current-arch backend binary."
    fi
fi

mkdir -p "$BACKEND_STAGE_DIR"
cp "$BACKEND_BINARY_PATH" "$BACKEND_STAGE_DIR/$BACKEND_BINARY_NAME"

echo "==> Building macOS app ($CONFIGURATION)"
if [[ "$UNIVERSAL_BUILD" == true ]]; then
    xcodebuild \
        -project "$XCODE_PROJECT" \
        -scheme "$SCHEME" \
        -configuration "$CONFIGURATION" \
        -derivedDataPath "$DERIVED_DATA_DIR" \
        ARCHS="arm64 x86_64" \
        ONLY_ACTIVE_ARCH=NO \
        build
else
    xcodebuild \
        -project "$XCODE_PROJECT" \
        -scheme "$SCHEME" \
        -configuration "$CONFIGURATION" \
        -derivedDataPath "$DERIVED_DATA_DIR" \
        build
fi

BUILT_APP_PATH="$DERIVED_DATA_DIR/Build/Products/$CONFIGURATION/JobTracker.app"
if [[ ! -d "$BUILT_APP_PATH" ]]; then
    echo "Built app not found: $BUILT_APP_PATH"
    exit 1
fi

mkdir -p "$APP_STAGE_DIR"
rm -rf "$APP_STAGE_DIR/JobTracker.app"
cp -R "$BUILT_APP_PATH" "$APP_STAGE_DIR/JobTracker.app"

TARGET_APP="$APP_STAGE_DIR/JobTracker.app"
mkdir -p "$TARGET_APP/Contents/Resources/backend"
cp "$BACKEND_STAGE_DIR/$BACKEND_BINARY_NAME" "$TARGET_APP/Contents/Resources/backend/$BACKEND_BINARY_NAME"
chmod +x "$TARGET_APP/Contents/Resources/backend/$BACKEND_BINARY_NAME"

echo "==> Bundle complete"
echo "Backend binary: $BACKEND_STAGE_DIR/$BACKEND_BINARY_NAME"
echo "App bundle:      $TARGET_APP"
if [[ "$UNIVERSAL_BUILD" == true ]]; then
    echo "Universal app:   enabled (arm64 + x86_64)"
    if [[ "$BACKEND_UNIVERSAL" == true ]]; then
        echo "Universal backend binary: yes"
    else
        echo "Universal backend binary: no (current architecture only)"
    fi
fi
echo "ML model strategy: $MODEL_STRATEGY"
echo ""
echo "Next steps:"
echo "  1) Code sign the staged app."
echo "  2) Run ./scripts/notarize.sh \"$TARGET_APP\" after signing."
