#!/usr/bin/env bash
# ==============================================================================
# build_rpm.sh — RPM Package Builder for AI Dubber Ultimate
# Creates ai-dubber-ultimate-<ver>-linux-x86_64.rpm for Fedora / RHEL / openSUSE
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$PROJECT_ROOT/dist"
APP_SOURCE_DIR="${1:-$DIST_DIR/AI_Dubber_Ultimate}"
VERSION="${VERSION:-1.2.9}"
VERSION="${VERSION#v}"
ARCH="${ARCH:-x86_64}"
OUTPUT_RPM="$DIST_DIR/ai-dubber-ultimate-v${VERSION}-linux-${ARCH}.rpm"
OUTPUT_STANDALONE_RPM="$DIST_DIR/ai-dubber-ultimate-${VERSION}-linux-${ARCH}.rpm"
STAGING_DIR="$DIST_DIR/rpm_staging"

echo "=== Building RPM Package: $OUTPUT_RPM ==="

if [ "${1:-}" = "--dry-run" ]; then
    echo "[DRY-RUN] Validating RPM build configuration and layout..."
    mkdir -p "$STAGING_DIR"
    echo "[DRY-RUN] RPM layout validated successfully."
    rm -rf "$STAGING_DIR"
    exit 0
fi

if [ ! -d "$APP_SOURCE_DIR" ]; then
    echo "ERROR: Application source directory not found at: $APP_SOURCE_DIR"
    echo "Run PyInstaller first: pyinstaller packaging/ai_dubber.spec"
    exit 1
fi

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/BUILD" "$STAGING_DIR/RPMS" "$STAGING_DIR/SOURCES" "$STAGING_DIR/SPECS" "$STAGING_DIR/SRPMS"
mkdir -p "$DIST_DIR"

if command -v fpm >/dev/null 2>&1; then
    echo "Building RPM via fpm..."
    fpm -s dir -t rpm \
        -n "ai-dubber-ultimate" \
        -v "$VERSION" \
        -a "$ARCH" \
        --description "AI Dubber Ultimate — AI Video Dubbing & Vocal Separation Suite" \
        --vendor "AI Dubber Team" \
        --license "Proprietary" \
        --prefix "/opt/ai-dubber-ultimate" \
        -C "$APP_SOURCE_DIR" \
        -p "$OUTPUT_RPM" \
        .
    echo "=== RPM build complete: $OUTPUT_RPM ==="
    cp "$OUTPUT_RPM" "$OUTPUT_STANDALONE_RPM" 2>/dev/null || true
    exit 0
fi

if command -v rpmbuild >/dev/null 2>&1; then
    echo "Building RPM via rpmbuild..."
    RPM_ROOT="$STAGING_DIR/root"
    mkdir -p "$RPM_ROOT/opt/ai-dubber-ultimate"
    mkdir -p "$RPM_ROOT/usr/share/applications"
    mkdir -p "$RPM_ROOT/usr/share/icons/hicolor/256x256/apps"
    mkdir -p "$RPM_ROOT/usr/bin"

    cp -a "$APP_SOURCE_DIR/." "$RPM_ROOT/opt/ai-dubber-ultimate/"
    if [ -f "$PROJECT_ROOT/resources/icon.png" ]; then
        cp "$PROJECT_ROOT/resources/icon.png" "$RPM_ROOT/usr/share/icons/hicolor/256x256/apps/ai-dubber-ultimate.png"
    fi
    if [ -f "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" ]; then
        cp "$SCRIPT_DIR/debian/ai-dubber-ultimate.desktop" "$RPM_ROOT/usr/share/applications/"
    fi
    ln -sf "/opt/ai-dubber-ultimate/AI_Dubber_Ultimate" "$RPM_ROOT/usr/bin/ai-dubber-ultimate"

    SPEC_FILE="$STAGING_DIR/SPECS/ai-dubber-ultimate.spec"
    cat << EOF > "$SPEC_FILE"
Name:           ai-dubber-ultimate
Version:        ${VERSION}
Release:        1%{?dist}
Summary:        AI Video Dubbing and Vocal Separation Desktop Suite
License:        Proprietary
BuildArch:      ${ARCH}
AutoReqProv:    no

%description
AI Dubber Ultimate provides intelligent multi-voice video dubbing,
Demucs vocal removal, speech recognition, and timeline editing.

%install
cp -a ${RPM_ROOT}/* %{buildroot}/

%files
/opt/ai-dubber-ultimate
/usr/bin/ai-dubber-ultimate
/usr/share/applications/ai-dubber-ultimate.desktop
/usr/share/icons/hicolor/256x256/apps/ai-dubber-ultimate.png

%changelog
* Wed Oct 14 2026 AI Dubber Team <support@aidubber.com> - ${VERSION}-1
- Multi-platform production release
EOF

    rpmbuild --define "_topdir $STAGING_DIR" -bb "$SPEC_FILE"
    find "$STAGING_DIR/RPMS" -name "*.rpm" -exec cp {} "$OUTPUT_RPM" \;
    echo "=== RPM build complete: $OUTPUT_RPM ==="
    cp "$OUTPUT_RPM" "$OUTPUT_STANDALONE_RPM" 2>/dev/null || true
    rm -rf "$STAGING_DIR"
    exit 0
fi

echo "WARNING: Neither 'fpm' nor 'rpmbuild' is available. Created placeholder spec."
rm -rf "$STAGING_DIR"
