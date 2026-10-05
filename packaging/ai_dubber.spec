# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller specification file for AI Dubber Ultimate desktop application.
Supports Windows, Linux, and macOS standalone onedir packaging.
"""

import os
import sys

spec_dir = os.path.abspath(SPECPATH)
project_root = os.path.abspath(os.path.join(spec_dir, ".."))
src_dir = os.path.join(project_root, "src")

# Determine platform icon
if sys.platform == "win32":
    app_icon = os.path.join(project_root, "resources", "icon.ico")
else:
    app_icon = os.path.join(project_root, "resources", "icon.png")

# Data files to bundle
datas = [
    (os.path.join(project_root, "resources"), "resources"),
    (os.path.join(project_root, "config"), "config"),
    (os.path.join(project_root, "runtime_packages.json"), "."),
    (os.path.join(project_root, "data.json"), "."),
]

# Include compiled bytecode runtime modules in both root and src
for pyc_file in ["core_app.pyc", "ui_widgets.pyc", "workers.pyc"]:
    pyc_path = os.path.join(src_dir, pyc_file)
    if os.path.exists(pyc_path):
        datas.append((pyc_path, "."))
        datas.append((pyc_path, "src"))

hidden_imports = [
    # Qt GUI
    "PyQt5",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "PyQt5.QtWidgets",
    "PyQt5.sip",
    "qtawesome",
    # Media & Audio
    "cv2",
    "numpy",
    "PIL",
    "PIL.Image",
    "soundfile",
    "pydub",
    # Networking & Scraping
    "requests",
    "aiohttp",
    "aiohttp.client",
    "deep_translator",
    "edge_tts",
    "google.genai",
    # Downloader Subsystem
    "yt_dlp",
    "dramabox",
    "dramabox.yoinks_engine",
    "dramabox.gui_downloader",
    "dramabox.portable_video",
    "dramabox.downloader",
    "dramabox.hongguo",
    "dramabox.sekai_api",
    # Utilities
    "psutil",
    "pydantic",
    "tqdm",
    "huggingface_hub",
]

if sys.platform == "win32":
    hidden_imports.extend([
        "win32api",
        "win32gui",
        "win32con",
        "win32process",
        "win32com",
        "pythoncom",
        "pywintypes",
    ])

excludes = [
    "tkinter",
    "matplotlib",
    "scipy",
    "tests",
]

a = Analysis(
    [os.path.join(src_dir, "main.py")],
    pathex=[src_dir, project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI_Dubber_Ultimate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=app_icon if os.path.exists(app_icon) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AI_Dubber_Ultimate",
)
