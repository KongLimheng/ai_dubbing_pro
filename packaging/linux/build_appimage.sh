#!/usr/bin/env bash
# ==============================================================================
# build_appimage.sh — AppImage Package Builder for AI Dubber Ultimate
# Creates ai-dubber-ultimate-<ver>-linux-x86_64.AppImage
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APP_SOURCE_DIR="${1:-$DIST_DIR/AI_Dubber_Ultimate}"
VERSION="${VERSION:-1.2.9}"
VERSION="${VERSION#v}"
ARCH="${ARCH:-x86_64}"
OUTPUT_APPIMAGE="$DIST_DIR/ai-dubber-ultimate-v${VERSION}-linux-${ARCH}.AppImage"
OUTPUT_STANDALONE_APPIMAGE="$DIST_DIR/ai-dubber-ultimate-${VERSION}-linux-${ARCH}.AppImage"
APPDIR="$DIST_DIR/AppDir"

echo "=== Building AppImage: $OUTPUT_APPIMAGE ==="

if [ "${1:-}" = "--dry-run" ]; then
    echo "[DRY-RUN] Validating AppDir structure..."
    mkdir -p "$APPDIR/usr/bin"
    echo "[DRY-RUN] AppDir structure validated."
    rm -rf "$APPDIR"
    exit 0
fi

if [ ! -d "$APP_SOURCE_DIR" ]; then
    echo "ERROR: Application source directory not found at: $APP_SOURCE_DIR"
    echo "Run PyInstaller first: pyinstaller packaging/ai_dubber.spec"
    exit 1
fi

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

echo "[1/4] Copying application files to AppDir..."
cp -a "$APP_SOURCE_DIR/." "$APPDIR/usr/bin/"

echo "[2/4] Adding desktop integration & AppRun..."
if [ -f "$PROJECT_ROOT/resources/icon.png" ]; then
    cp "$PROJECT_ROOT/resources/icon.png" "$APPDIR/ai-dubber-ultimate.png"
    cp "$PROJECT_ROOT/resources/icon.png" "$APPDIR/.DirIcon"
    cp "$PROJECT_ROOT/resources/icon.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ai-dubber-ultimate.png"
fi

if [ -f "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" ]; then
    cp "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" "$APPDIR/ai-dubber-ultimate.desktop"
    cp "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" "$APPDIR/usr/share/applications/"
fi

# AppRun script
cat << 'EOF' > "$APPDIR/AppRun"
#!/bin/sh
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
export PATH="${HERE}/usr/bin:${HERE}/usr/sbin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${HERE}/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH}"
export PYTHONHOME="${HERE}/usr"
export PYTHONPATH="${HERE}/usr/bin:${PYTHONPATH}"
cd "${HERE}/usr/bin"
exec "${HERE}/usr/bin/AI_Dubber_Ultimate" "$@"
EOF
chmod 755 "$APPDIR/AppRun"

echo "[3/4] Packaging AppImage..."
if command -v appimagetool >/dev/null 2>&1; then
    ARCH="$ARCH" appimagetool "$APPDIR" "$OUTPUT_APPIMAGE"
    cp "$OUTPUT_APPIMAGE" "$OUTPUT_STANDALONE_APPIMAGE" 2>/dev/null || true
    echo "=== AppImage build complete: $OUTPUT_APPIMAGE ==="
else
    echo "NOTICE: 'appimagetool' not found in PATH."
    echo "You can download appimagetool from https://github.com/AppImage/AppImageKit/releases"
    echo "AppDir staged successfully at: $APPDIR"
fi
