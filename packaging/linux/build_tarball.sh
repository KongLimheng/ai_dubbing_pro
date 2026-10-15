#!/usr/bin/env bash
# ==============================================================================
# build_tarball.sh — Linux Standalone Tarball Distribution Builder
# Creates ai-dubber-ultimate-<ver>-linux-x86_64.tar.gz with bundled install.sh
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APP_SOURCE_DIR="${1:-$DIST_DIR/AI_Dubber_Ultimate}"
VERSION="${VERSION:-1.2.9}"
VERSION="${VERSION#v}"
ARCH="${ARCH:-x86_64}"
OUTPUT_TARBALL="$DIST_DIR/ai-dubber-ultimate-v${VERSION}-linux-${ARCH}.tar.gz"
OUTPUT_STANDALONE_TARBALL="$DIST_DIR/ai-dubber-ultimate-${VERSION}-linux-${ARCH}.tar.gz"
STAGING_DIR="$DIST_DIR/tarball_staging/ai-dubber-ultimate-${VERSION}"

echo "=== Building Linux Tarball: $OUTPUT_TARBALL ==="

if [ "${1:-}" = "--dry-run" ]; then
    echo "[DRY-RUN] Validating tarball staging layout..."
    mkdir -p "$STAGING_DIR"
    cp "$SCRIPT_DIR/install.sh" "$STAGING_DIR/"
    chmod 755 "$STAGING_DIR/install.sh"
    echo "[DRY-RUN] Layout validated successfully."
    rm -rf "$DIST_DIR/tarball_staging"
    exit 0
fi

if [ ! -d "$APP_SOURCE_DIR" ]; then
    echo "ERROR: Application source directory not found at: $APP_SOURCE_DIR"
    echo "Run PyInstaller first: pyinstaller packaging/ai_dubber.spec"
    exit 1
fi

rm -rf "$DIST_DIR/tarball_staging"
mkdir -p "$STAGING_DIR"

echo "[1/3] Copying application files..."
cp -a "$APP_SOURCE_DIR" "$STAGING_DIR/"

echo "[2/3] Adding installer and desktop resources..."
cp "$SCRIPT_DIR/install.sh" "$STAGING_DIR/"
chmod 755 "$STAGING_DIR/install.sh"

mkdir -p "$STAGING_DIR/resources"
if [ -f "$PROJECT_ROOT/resources/icon.png" ]; then
    cp "$PROJECT_ROOT/resources/icon.png" "$STAGING_DIR/resources/"
fi
if [ -f "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" ]; then
    cp "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" "$STAGING_DIR/resources/"
fi
if [ -f "$PROJECT_ROOT/README.md" ]; then
    cp "$PROJECT_ROOT/README.md" "$STAGING_DIR/"
fi

echo "[3/3] Creating compressed archive..."
mkdir -p "$DIST_DIR"
tar -czf "$OUTPUT_TARBALL" -C "$DIST_DIR/tarball_staging" "ai-dubber-ultimate-${VERSION}"
cp "$OUTPUT_TARBALL" "$OUTPUT_STANDALONE_TARBALL" 2>/dev/null || true
rm -rf "$DIST_DIR/tarball_staging"

echo "=== Tarball build complete: $OUTPUT_TARBALL ==="
