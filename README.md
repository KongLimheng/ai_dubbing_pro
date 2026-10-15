# 🎙️ AI Dubber Ultimate

AI Dubber Ultimate is a cross-platform desktop suite for automated video dubbing, timeline subtitle editing, Demucs vocal separation, AI speech recognition, and multi-engine text-to-speech synthesis (Edge-TTS, CosyVoice, VoxCPM, and more).

---

## Releases & Downloads

On GitHub, the latest release has every build listed below, and all releases have earlier versions and their notes. `<ver>` in the file names is the version number (e.g. `1.2.9`), and `SHA256SUMS.txt` lists a checksum for every file.

### Windows

| Build | Installer | Portable |
| :--- | :--- | :--- |
| **x64** (64-bit Intel/AMD) | `ai-dubber-ultimate-<ver>-windows-x64-setup.exe` (or `.msi`) | `ai-dubber-ultimate-<ver>-windows-x64-portable.zip` |
| **arm64** (Snapdragon and other ARM PCs) | `ai-dubber-ultimate-<ver>-windows-arm64.msi` | `ai-dubber-ultimate-<ver>-windows-arm64-portable.zip` |
| **x86** (32-bit) | `ai-dubber-ultimate-<ver>-windows-x86.msi` | `ai-dubber-ultimate-<ver>-windows-x86-portable.zip` |

*Installers and executables are code-signed.*

#### Troubleshooting: If the app doesn't open on Windows
The desktop app initializes hardware acceleration by default. Letting OpenGL/Vulkan create an instance can crash some graphics drivers (AMD's `atio6axx.dll` or legacy Intel graphics) before the window appears, so the app would flash in Task Manager and quit. Rendering backend overrides the default for troubleshooting (for example software or dx12). In PowerShell, from the folder containing the executable:

```powershell
$env:QT_OPENGL="software"
$env:QT_QUICK_BACKEND="software"
.\ai-dubber-ultimate.exe
```

*Installers and executables are code-signed.*

---

### macOS

| Build | File | Notes |
| :--- | :--- | :--- |
| **App, universal** (Apple silicon + Intel) | `ai-dubber-ultimate-<ver>-macos-universal.dmg` | Signed and notarized |
| **Command-line tool, universal** | `ai-dubber-ultimate-cli-<ver>-macos-universal.zip` | Signed and notarized |

---

### Linux

| Format | x86_64 | aarch64 (ARM64) | Notes |
| :--- | :--- | :--- | :--- |
| **AppImage** | `ai-dubber-ultimate-<ver>-linux-x86_64.AppImage` | `ai-dubber-ultimate-<ver>-linux-aarch64.AppImage` | Runs anywhere; updates itself with AppImageUpdate (.zsync files) |
| **Flatpak** | `ai-dubber-ultimate-<ver>-linux-x86_64.flatpak` | `ai-dubber-ultimate-<ver>-linux-aarch64.flatpak` | Sandboxed; `flatpak install --user <file>` |
| **Debian/Ubuntu** | `ai-dubber-ultimate-<ver>-linux-x86_64.deb` | `ai-dubber-ultimate-<ver>-linux-aarch64.deb` | `sudo apt install ./<file>` |
| **Fedora/RHEL/openSUSE** | `ai-dubber-ultimate-<ver>-linux-x86_64.rpm` | `ai-dubber-ultimate-<ver>-linux-aarch64.rpm` | `sudo dnf install ./<file>` |
| **Tarball** | `ai-dubber-ultimate-<ver>-linux-x86_64.tar.gz` | `ai-dubber-ultimate-<ver>-linux-aarch64.tar.gz` | Unpack and run `./install.sh` |

**RISC-V (riscv64)**: `ai-dubber-ultimate-<ver>-linux-riscv64.tar.gz` (tarball only; needs glibc 2.39+, e.g. Ubuntu 24.04 or Debian 13).

#### Tarball Installer Instructions
The tarball installer places AI Dubber Ultimate, its command-line tool and desktop integration in `~/.local`, without administrator permissions:
```bash
tar -xzf ai-dubber-ultimate-<ver>-linux-x86_64.tar.gz
cd ai-dubber-ultimate-<ver>
./install.sh
```

For all users, run `sudo ./install.sh --prefix /usr/local` instead. Running the installer again updates the installation. To uninstall cleanly, run `./install.sh --uninstall`.

---

### Checksum & Integrity Verification
`SHA256SUMS.txt` lists a checksum for every file. To verify the integrity of downloaded files:

```bash
# On Linux / macOS
sha256sum -c SHA256SUMS.txt

# On Windows (PowerShell)
Get-FileHash .\ai-dubber-ultimate-<ver>-windows-x64-setup.exe -Algorithm SHA256
```

---

## How to Build the Installers

### Linux
```bash
# 1. Build PyInstaller onedir
pyinstaller packaging/ai_dubber.spec

# 2. Build .deb package
./packaging/linux/build_deb.sh dist/AI_Dubber_Ultimate

# 3. Build .tar.gz bundle with install.sh
./packaging/linux/build_tarball.sh dist/AI_Dubber_Ultimate

# 4. Build .rpm package (requires fpm or rpmbuild)
./packaging/linux/build_rpm.sh dist/AI_Dubber_Ultimate

# 5. Build .AppImage (requires appimagetool)
./packaging/linux/build_appimage.sh dist/AI_Dubber_Ultimate
```

### Windows (.exe Setup & Portable)
```cmd
rem 1. Build PyInstaller onedir
pyinstaller packaging/ai_dubber.spec

rem 2. Compile Inno Setup installer
packaging\windows\build_installer.bat

rem Output: dist\ai-dubber-ultimate-v1.2.9-windows-x64-setup.exe
```

### macOS (.dmg & Universal App)
```bash
# 1. Build PyInstaller .app bundle
pyinstaller packaging/ai_dubber.spec

# 2. Create drag-and-drop .dmg image
./packaging/macos/build_dmg.sh "dist/AI Dubber Ultimate.app"

# Output: dist/ai-dubber-ultimate-v1.2.9-macos-universal.dmg
```
