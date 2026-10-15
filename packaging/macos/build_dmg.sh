#!/usr/bin/env bash
# ==============================================================================
# build_dmg.sh — macOS Drag-and-Drop (.dmg) Installer Builder
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APP_BUNDLE="${1:-$DIST_DIR/AI Dubber Ultimate.app}"
VERSION="${VERSION:-1.2.9}"
VERSION="${VERSION#v}"
OUTPUT_DMG="$DIST_DIR/ai-dubber-ultimate-v${VERSION}-macos-universal.dmg"
OUTPUT_STANDALONE_DMG="$DIST_DIR/ai-dubber-ultimate-${VERSION}-macos-universal.dmg"
OUTPUT_LEGACY_DMG="$DIST_DIR/AI-Dubber-Ultimate-v${VERSION}-macOS.dmg"
STAGING_DIR="$DIST_DIR/dmg_staging"

echo "=== Building macOS DMG Package: $OUTPUT_DMG ==="

if [ "${1:-}" = "--dry-run" ]; then
    echo "[DRY-RUN] Validating DMG structure..."
    mkdir -p "$STAGING_DIR"
    echo "[DRY-RUN] Symlinking /Applications..."
    ln -s /Applications "$STAGING_DIR/Applications" 2>/dev/null || true
    echo "[DRY-RUN] DMG staging layout validated."
    rm -rf "$STAGING_DIR"
    exit 0
fi

if [ ! -d "$APP_BUNDLE" ]; then
    echo "ERROR: macOS Application bundle not found at: $APP_BUNDLE"
    echo "Run PyInstaller first on macOS: pyinstaller packaging/ai_dubber.spec"
    exit 1
fi

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

echo "[1/3] Staging AI Dubber Ultimate.app..."
cp -R "$APP_BUNDLE" "$STAGING_DIR/"

echo "[2/3] Adding standard /Applications symlink..."
ln -s /Applications "$STAGING_DIR/Applications"

echo "[3/3] Generating compressed UDZO disk image..."
if command -v hdiutil >/dev/null 2>&1; then
    hdiutil create -volname "AI Dubber Ultimate" \
        -srcfolder "$STAGING_DIR" \
        -ov -format UDZO \
        "$OUTPUT_DMG"
    cp "$OUTPUT_DMG" "$OUTPUT_STANDALONE_DMG" 2>/dev/null || true
    echo "=== DMG build complete: $OUTPUT_DMG ==="
else
    echo "WARNING: 'hdiutil' is only available on macOS. Creating tar.gz fallback staging archive..."
    tar -czf "$DIST_DIR/AI-Dubber-Ultimate-v${VERSION}-macOS-App.tar.gz" -C "$STAGING_DIR" .
fi

rm -rf "$STAGING_DIR"
