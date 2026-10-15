#!/usr/bin/env bash
# ==============================================================================
# build_deb.sh — Debian (.deb) Package Builder for AI Dubber Ultimate
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APP_SOURCE_DIR="${1:-$DIST_DIR/AI_Dubber_Ultimate}"
VERSION="${VERSION:-1.2.9}"
VERSION="${VERSION#v}"
ARCH="${ARCH:-x86_64}"
OUTPUT_DEB="$DIST_DIR/ai-dubber-ultimate-v${VERSION}-linux-${ARCH}.deb"
OUTPUT_STANDALONE_DEB="$DIST_DIR/ai-dubber-ultimate-${VERSION}-linux-${ARCH}.deb"
OUTPUT_LEGACY_DEB="$DIST_DIR/ai-dubber-ultimate_${VERSION}_amd64.deb"
STAGING_DIR="$DIST_DIR/deb_staging"

echo "=== Building Debian Package: $OUTPUT_DEB ==="

if [ "${1:-}" = "--dry-run" ]; then
    echo "[DRY-RUN] Validating package layout..."
    mkdir -p "$STAGING_DIR/DEBIAN"
    mkdir -p "$STAGING_DIR/opt/ai-dubber-ultimate"
    mkdir -p "$STAGING_DIR/usr/share/applications"
    mkdir -p "$STAGING_DIR/usr/share/icons/hicolor/256x256/apps"
    cp "$SCRIPT_DIR/debian/control" "$STAGING_DIR/DEBIAN/"
    cp "$SCRIPT_DIR/debian/postinst" "$STAGING_DIR/DEBIAN/"
    cp "$SCRIPT_DIR/debian/postrm" "$STAGING_DIR/DEBIAN/"
    chmod 755 "$STAGING_DIR/DEBIAN/postinst" "$STAGING_DIR/DEBIAN/postrm"
    cp "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" "$STAGING_DIR/usr/share/applications/"
    if [ -f "$PROJECT_ROOT/resources/icon.png" ]; then
        cp "$PROJECT_ROOT/resources/icon.png" "$STAGING_DIR/usr/share/icons/hicolor/256x256/apps/ai-dubber-ultimate.png"
    fi
    echo "[DRY-RUN] Layout validated successfully."
    rm -rf "$STAGING_DIR"
    exit 0
fi

if [ ! -d "$APP_SOURCE_DIR" ]; then
    echo "ERROR: Application source directory not found at: $APP_SOURCE_DIR"
    echo "Run PyInstaller first: pyinstaller packaging/ai_dubber.spec"
    exit 1
fi

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/DEBIAN"
mkdir -p "$STAGING_DIR/opt/ai-dubber-ultimate"
mkdir -p "$STAGING_DIR/usr/share/applications"
mkdir -p "$STAGING_DIR/usr/share/icons/hicolor/256x256/apps"

echo "[1/4] Copying application files..."
cp -a "$APP_SOURCE_DIR/." "$STAGING_DIR/opt/ai-dubber-ultimate/"

# Clean cache and temporary files from package payload
find "$STAGING_DIR/opt/ai-dubber-ultimate" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$STAGING_DIR/opt/ai-dubber-ultimate" -name ".git*" -exec rm -rf {} + 2>/dev/null || true

# Verify critical compiled bytecode runtime modules exist
for pyc_file in "core_app.pyc" "ui_widgets.pyc" "workers.pyc"; do
    if [ ! -f "$STAGING_DIR/opt/ai-dubber-ultimate/_internal/$pyc_file" ] && \
       [ ! -f "$STAGING_DIR/opt/ai-dubber-ultimate/_internal/src/$pyc_file" ] && \
       [ ! -f "$STAGING_DIR/opt/ai-dubber-ultimate/$pyc_file" ]; then
        echo "ERROR: Critical runtime bytecode module '$pyc_file' is missing from staging layout!" >&2
        exit 1
    fi
done

# Ensure main binary is executable
if [ -f "$STAGING_DIR/opt/ai-dubber-ultimate/AI_Dubber_Ultimate" ]; then
    chmod 755 "$STAGING_DIR/opt/ai-dubber-ultimate/AI_Dubber_Ultimate"
fi

echo "[2/4] Installing system icons and desktop entry..."
cp "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" "$STAGING_DIR/usr/share/applications/"
if [ -f "$PROJECT_ROOT/resources/icon.png" ]; then
    cp "$PROJECT_ROOT/resources/icon.png" "$STAGING_DIR/usr/share/icons/hicolor/256x256/apps/ai-dubber-ultimate.png"
fi

echo "[3/4] Installing Debian package control scripts..."
cp "$SCRIPT_DIR/debian/control" "$STAGING_DIR/DEBIAN/"
cp "$SCRIPT_DIR/debian/postinst" "$STAGING_DIR/DEBIAN/"
cp "$SCRIPT_DIR/debian/postrm" "$STAGING_DIR/DEBIAN/"
chmod 755 "$STAGING_DIR/DEBIAN/postinst" "$STAGING_DIR/DEBIAN/postrm"

# Synchronize dynamic package metadata in control file
DEB_ARCH="amd64"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    DEB_ARCH="arm64"
elif [ "$ARCH" = "x86_64" ] || [ "$ARCH" = "amd64" ]; then
    DEB_ARCH="amd64"
else
    DEB_ARCH="$ARCH"
fi

sed -i "s/^Version:.*/Version: ${VERSION}/" "$STAGING_DIR/DEBIAN/control"
sed -i "s/^Architecture:.*/Architecture: ${DEB_ARCH}/" "$STAGING_DIR/DEBIAN/control"

INSTALLED_SIZE_KB=$(du -sk "$STAGING_DIR/opt" 2>/dev/null | cut -f1 || echo "")
if [ -n "$INSTALLED_SIZE_KB" ]; then
    if grep -q "^Installed-Size:" "$STAGING_DIR/DEBIAN/control"; then
        sed -i "s/^Installed-Size:.*/Installed-Size: ${INSTALLED_SIZE_KB}/" "$STAGING_DIR/DEBIAN/control"
    else
        sed -i "/^Architecture:.*/a Installed-Size: ${INSTALLED_SIZE_KB}" "$STAGING_DIR/DEBIAN/control"
    fi
fi

# Configure fast compression: default to -Zgzip -z6 (20x faster than xz, universal across all Debian/Ubuntu releases)
# or -Zzstd -z3 if configured via DEB_COMPRESSION=zstd
COMPRESSION_OPT="-Zgzip"
COMPRESSION_LEVEL="-z6"

if [ "${DEB_COMPRESSION:-}" = "zstd" ]; then
    COMPRESSION_OPT="-Zzstd"
    COMPRESSION_LEVEL="-z3"
elif [ -n "${DEB_COMPRESSION:-}" ]; then
    COMPRESSION_OPT="-Z${DEB_COMPRESSION}"
fi

echo "[4/4] Generating Debian package archive with dpkg-deb ($COMPRESSION_OPT $COMPRESSION_LEVEL)..."
START_TIME=$(date +%s)
dpkg-deb --build --root-owner-group $COMPRESSION_OPT $COMPRESSION_LEVEL "$STAGING_DIR" "$OUTPUT_DEB"
END_TIME=$(date +%s)
BUILD_DURATION=$((END_TIME - START_TIME))
echo "Package archived in ${BUILD_DURATION}s."

echo "=== Package build complete: $OUTPUT_DEB ==="
cp "$OUTPUT_DEB" "$OUTPUT_LEGACY_DEB" 2>/dev/null || true
cp "$OUTPUT_DEB" "$OUTPUT_STANDALONE_DEB" 2>/dev/null || true
dpkg-deb --info "$OUTPUT_DEB"
rm -rf "$STAGING_DIR"
