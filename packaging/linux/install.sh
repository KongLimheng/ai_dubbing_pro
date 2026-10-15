#!/usr/bin/env bash
# ==============================================================================
# install.sh — AI Dubber Ultimate Linux Tarball Installer
#
# Installs AI Dubber Ultimate, its launcher command, and desktop integration.
# Default target: ~/.local (no root permissions required)
# System-wide target: /usr/local (run with: sudo ./install.sh --prefix /usr/local)
#
# Usage:
#   ./install.sh [OPTIONS]
#
# Options:
#   --prefix <DIR>     Installation prefix directory (default: ~/.local or /usr/local if root)
#   --uninstall        Remove installed files and desktop integration
#   --dry-run          Show actions without making changes
#   -h, --help         Show this help message
#   -v, --version      Show installer version
# ==============================================================================
set -euo pipefail

APP_NAME="AI Dubber Ultimate"
APP_SLUG="ai-dubber-ultimate"
APP_VERSION="1.2.9"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Determine default prefix
if [ "$(id -u)" -eq 0 ]; then
    DEFAULT_PREFIX="/usr/local"
else
    DEFAULT_PREFIX="${HOME}/.local"
fi

PREFIX="$DEFAULT_PREFIX"
UNINSTALL=false
DRY_RUN=false

show_help() {
    cat << EOF
${APP_NAME} v${APP_VERSION} — Linux Installer

USAGE:
    ./install.sh [OPTIONS]

OPTIONS:
    --prefix <DIR>     Set install destination prefix (default: ${DEFAULT_PREFIX})
    --uninstall        Remove an existing installation
    --dry-run          Simulate installation/uninstallation without writing files
    -h, --help         Display this help message
    -v, --version      Display installer version

EXAMPLES:
    # Standard user installation into ~/.local (no root required):
    ./install.sh

    # System-wide installation for all users:
    sudo ./install.sh --prefix /usr/local

    # Update an existing installation:
    ./install.sh

    # Uninstall:
    ./install.sh --uninstall
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)
            if [ -n "${2:-}" ]; then
                PREFIX="$2"
                shift 2
            else
                echo "ERROR: --prefix requires a directory path." >&2
                exit 1
            fi
            ;;
        --uninstall)
            UNINSTALL=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -v|--version)
            echo "${APP_NAME} Installer v${APP_VERSION}"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Run './install.sh --help' for usage." >&2
            exit 1
            ;;
    esac
done

BIN_DIR="${PREFIX}/bin"
LIB_DIR="${PREFIX}/lib/${APP_SLUG}"
APPS_DIR="${PREFIX}/share/applications"
ICONS_DIR="${PREFIX}/share/icons/hicolor/256x256/apps"
DESKTOP_FILE="${APPS_DIR}/${APP_SLUG}.desktop"
ICON_FILE="${ICONS_DIR}/${APP_SLUG}.png"
EXEC_LINK="${BIN_DIR}/${APP_SLUG}"
CLI_LINK="${BIN_DIR}/ai-dubber"

# ── Uninstall Action ──────────────────────────────────────────────────────────
if [ "$UNINSTALL" = true ]; then
    echo "=== Uninstalling ${APP_NAME} from ${PREFIX} ==="

    remove_item() {
        local target="$1"
        if [ -e "$target" ] || [ -L "$target" ]; then
            if [ "$DRY_RUN" = true ]; then
                echo "[DRY-RUN] Would remove: $target"
            else
                echo "Removing: $target"
                rm -rf "$target"
            fi
        fi
    }

    remove_item "$EXEC_LINK"
    remove_item "$CLI_LINK"
    remove_item "$DESKTOP_FILE"
    remove_item "$ICON_FILE"
    remove_item "$LIB_DIR"

    if [ "$DRY_RUN" = false ]; then
        if command -v update-desktop-database >/dev/null 2>&1; then
            update-desktop-database "$APPS_DIR" 2>/dev/null || true
        fi
        if command -v gtk-update-icon-cache >/dev/null 2>&1; then
            gtk-update-icon-cache -f -t "${PREFIX}/share/icons/hicolor" 2>/dev/null || true
        fi
        echo "=== ${APP_NAME} uninstalled successfully. ==="
    else
        echo "=== [DRY-RUN] Uninstallation complete. ==="
    fi
    exit 0
fi

# ── Install Action ────────────────────────────────────────────────────────────
echo "=================================================="
echo "    ${APP_NAME} v${APP_VERSION} Linux Installer   "
echo "=================================================="
echo "Destination Prefix: ${PREFIX}"
echo "Binary directory:   ${BIN_DIR}"
echo "Library directory:  ${LIB_DIR}"
echo "Desktop launcher:   ${DESKTOP_FILE}"
echo ""

# Find application source root
APP_SRC_DIR=""
if [ -d "${SCRIPT_DIR}/AI_Dubber_Ultimate" ]; then
    APP_SRC_DIR="${SCRIPT_DIR}/AI_Dubber_Ultimate"
elif [ -d "${SCRIPT_DIR}/src" ]; then
    APP_SRC_DIR="${SCRIPT_DIR}"
elif [ -f "${SCRIPT_DIR}/${APP_SLUG}" ] || [ -f "${SCRIPT_DIR}/AI_Dubber_Ultimate" ]; then
    APP_SRC_DIR="${SCRIPT_DIR}"
else
    APP_SRC_DIR="${SCRIPT_DIR}"
fi

if [ "$DRY_RUN" = true ]; then
    echo "[DRY-RUN] Validating directories and permissions..."
    echo "[DRY-RUN] Would create: ${BIN_DIR}"
    echo "[DRY-RUN] Would create: ${LIB_DIR}"
    echo "[DRY-RUN] Would create: ${APPS_DIR}"
    echo "[DRY-RUN] Would create: ${ICONS_DIR}"
    echo "[DRY-RUN] Would install application bundle to ${LIB_DIR}"
    echo "[DRY-RUN] Would create launcher wrapper at ${EXEC_LINK}"
    echo "[DRY-RUN] Would create desktop entry at ${DESKTOP_FILE}"
    echo "=== [DRY-RUN] Verification successful. ==="
    exit 0
fi

# Create target directories
mkdir -p "${BIN_DIR}"
mkdir -p "${LIB_DIR}"
mkdir -p "${APPS_DIR}"
mkdir -p "${ICONS_DIR}"

# 1. Copy application files to library directory
echo "[1/4] Installing application files to ${LIB_DIR}..."
# Clean old files to ensure a clean update
rm -rf "${LIB_DIR:?}"/* 2>/dev/null || true

# Copy either standalone frozen distribution or portable python layout
if [ -d "${SCRIPT_DIR}/AI_Dubber_Ultimate" ]; then
    cp -a "${SCRIPT_DIR}/AI_Dubber_Ultimate/." "${LIB_DIR}/"
else
    # Exclude installer itself and temporary tarballs from bundle copy
    for item in "${SCRIPT_DIR}"/*; do
        bname="$(basename "$item")"
        if [ "$bname" != "install.sh" ] && [ "$bname" != "dist" ] && [[ "$bname" != *.tar.gz ]]; then
            cp -a "$item" "${LIB_DIR}/"
        fi
    done
fi

# Ensure executable permissions on binaries
if [ -f "${LIB_DIR}/AI_Dubber_Ultimate" ]; then
    chmod 755 "${LIB_DIR}/AI_Dubber_Ultimate"
fi
if [ -f "${LIB_DIR}/run.sh" ]; then
    chmod 755 "${LIB_DIR}/run.sh"
fi

# 2. Create wrapper launcher script in bin/
echo "[2/4] Creating launcher command in ${BIN_DIR}..."
cat << 'EOF' > "${EXEC_LINK}"
#!/usr/bin/env bash
# AI Dubber Ultimate command-line & desktop launcher
set -e
RESOLVED_BIN="$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")"
BIN_DIR="$(dirname "$RESOLVED_BIN")"
PREFIX="$(dirname "$BIN_DIR")"
APP_DIR="${PREFIX}/lib/ai-dubber-ultimate"

if [ -f "${APP_DIR}/AI_Dubber_Ultimate" ] && [ -x "${APP_DIR}/AI_Dubber_Ultimate" ]; then
    exec "${APP_DIR}/AI_Dubber_Ultimate" "$@"
elif [ -f "${APP_DIR}/run.sh" ]; then
    cd "${APP_DIR}"
    exec bash run.sh "$@"
elif [ -f "${APP_DIR}/src/main.py" ]; then
    cd "${APP_DIR}"
    if [ -x "${APP_DIR}/.venv/bin/python" ]; then
        export PYTHONPATH="${APP_DIR}/src:${PYTHONPATH:-}"
        exec "${APP_DIR}/.venv/bin/python" "${APP_DIR}/src/main.py" "$@"
    else
        export PYTHONPATH="${APP_DIR}/src:${PYTHONPATH:-}"
        exec python3 "${APP_DIR}/src/main.py" "$@"
    fi
else
    echo "ERROR: AI Dubber Ultimate executable not found in ${APP_DIR}" >&2
    exit 1
fi
EOF

chmod 755 "${EXEC_LINK}"
# Also create short symlink `ai-dubber` for terminal convenience
ln -sf "${APP_SLUG}" "${CLI_LINK}"

# 3. Install App Icon
echo "[3/4] Installing application icon..."
ICON_SRC=""
for cand in "${SCRIPT_DIR}/resources/icon.png" "${LIB_DIR}/resources/icon.png" "${SCRIPT_DIR}/icon.png"; do
    if [ -f "$cand" ]; then
        ICON_SRC="$cand"
        break
    fi
done

if [ -n "$ICON_SRC" ]; then
    cp "$ICON_SRC" "${ICON_FILE}"
    chmod 644 "${ICON_FILE}"
fi

# 4. Install Desktop Entry
echo "[4/4] Installing desktop entry in ${APPS_DIR}..."
cat << EOF > "${DESKTOP_FILE}"
[Desktop Entry]
Version=1.0
Type=Application
Name=${APP_NAME}
GenericName=AI Video Dubber & Vocal Suite
Comment=Professional AI Video Dubbing, Demucs Vocal Removal, and Multi-Voice Synthesis
Exec="${EXEC_LINK}" %F
Icon=${APP_SLUG}
Terminal=false
StartupNotify=true
StartupWMClass=AI_Dubber_Ultimate
Categories=AudioVideo;AudioVideoEditing;Video;Audio;
Keywords=audio;video;dubbing;tts;demucs;vocal;funasr;ai;khmer;
EOF

chmod 644 "${DESKTOP_FILE}"

# Update desktop databases if tools are available
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${APPS_DIR}" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "${PREFIX}/share/icons/hicolor" 2>/dev/null || true
fi

echo ""
echo "=================================================="
echo "    Installation Complete!                        "
echo "=================================================="
echo "Run '${APP_SLUG}' in your terminal, or launch '${APP_NAME}'"
echo "from your desktop application menu."
if [[ ":$PATH:" != *":${BIN_DIR}:"* ]]; then
    echo ""
    echo "NOTE: ${BIN_DIR} is not currently in your PATH."
    echo "To run '${APP_SLUG}' directly from anywhere, add it to your ~/.bashrc or ~/.zshrc:"
    echo "    export PATH=\"${BIN_DIR}:\$PATH\""
fi
echo "=================================================="
