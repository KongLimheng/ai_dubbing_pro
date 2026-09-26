# AI Dubber Ultimate v1.2.9 — Gemini Agent Context

> **Purpose:** This file gives a Gemini AI agent (or any LLM session) a complete picture of the project so it can work effectively without re-exploring the codebase from scratch.

---

## What This Application Is

**AI Dubber Ultimate** is a desktop **AI-powered dubbing and video processing suite** built with **Python + PyQt5**. It was originally distributed as a Windows `.exe` (PyInstaller-frozen) and has been **decompiled / ported to a portable cross-platform source layout** at this workspace path.

The app's primary purpose is to take video content (from Hongguo Chinese micro-dramas, social media platforms, or local files), **transcribe speech → translate text → generate dubbed audio in Khmer (Cambodian)** and other languages using cloud AI services. A secondary subsystem is a **multi-platform video downloader** (Hongguo, DramaBox, ReelShort, YouTube, TikTok, Facebook).

### Key Capabilities
| Feature | Technology |
|---------|-----------|
| Speech-to-text (STR) | FunASR (local offline) / Gladia / Google |
| Translation | Gemini AI / OpenAI / DeepTranslator |
| Text-to-speech (TTS) | Edge-TTS (Microsoft) / Azure TTS / VoxCPM |
| Vocal isolation | Demucs (GPU/CPU, local) |
| Voice cloning | VoxCPM engine (external process) |
| Video download | yt-dlp + Hongguo API + SekaiDrama API |
| Face detection | OpenCV Haar cascade |
| Video editing | ffmpeg (bundled or system) |
| Chrome sessions | Chrome Profile Manager with multi-profile support |

---

## Project Layout

```
AI_Dubber_Ultimate_v1.2.9_portable/
├── src/                        ← All Python source code (PYTHONPATH root)
│   ├── main.py                 ← Entry point: sets PYTHONPATH, chdirs, calls launch_app()
│   ├── app_launcher.py         ← QApplication init, splash screen, license check, loads DubbingApp
│   ├── core_app.py             ← Loads DubbingApp from compiled .pyc, monkey-patches for cross-platform
│   ├── ai_clients.py           ← Lazy loader for google.generativeai with REST fallback + patching
│   ├── settings_manager.py     ← Config file I/O (JSON), API keys, feature flags, UI state
│   ├── settings_window.py      ← Settings UI: tabs for APIs, translation, appearance, export, advanced
│   ├── theme_manager.py        ← Light/dark theme switcher for PyQt5 stylesheet
│   ├── workers.py              ← Gemini transcription worker patches (enhanced SRT parsing)
│   ├── batch_loader.py         ← File/folder scanner + EnhancedBatchSrtMappingDialog factory (Demucs vocal removal, audio mix & speech timing sync controls)
│   ├── batch_processor.py      ← BatchJobItem, BatchParallelManager (parallel dubbing, vocal removal, mix settings, speech sync), progress UI
│   ├── batch_runner.py         ← CLI job runner (run_job spec dict) for isolated subprocess batch with speech timing sync parity, Demucs vocal removal, mix levels & multi-voice resolution
│   ├── cutter.py               ← VideoCutterApp: split/merge/trim video with ffmpeg
│   ├── video_to_mp3.py         ← Parallel Video-to-MP3 converter engine & VideoToMp3Dialog monitor
│   ├── chrome.py               ← ChromeProfileManager: multi-profile Chrome session launcher
│   ├── audio_speed.py          ← ffmpeg atempo audio speed adjustment helpers
│   ├── emotion_match.py        ← VoxCPM emotion/style tag extractor + audio segment analysis
│   ├── full_detect.py          ← OpenCV face detector (single-face visible flag per frame)
│   ├── FunASR.py               ← FunASR local STR engine wrapper (HuggingFace model download)
│   ├── funasr_subprocess.py    ← Subprocess entry point for FunASR worker process
│   ├── khmer_dict.py           ← Khmer numeral + word normalization for TTS
│   ├── license_manager.py      ← License validation (online + offline), QR payment, activation
│   ├── proxy_manager.py        ← HTTP proxy config load/save + ProxyConfig dict
│   ├── runtime_package_manager.py ← Download/extract optional AI runtime zip packages
│   ├── runtime_paths.py        ← Platform-safe path helpers (app_dir, resource_path, resolve_binary)
│   ├── utils.py                ← Qt plugin setup, Khmer font patch, ffmpeg finder, SSL bypass
│   ├── voice_clone.py          ← Voice clone model scanner + apply_voice_clone_to_audio()
│   ├── voxcpm_support.py       ← VoxCPM TTS subprocess driver (generate audio, install check)
│   ├── debug_log.py            ← TeeTextIO: mirrors stdout/stderr to app_debug.log
│   ├── app_links.py            ← Hardcoded URLs (update server, help links)
│   ├── ui_widgets.py           ← Shared PyQt5 widget helpers
│   ├── demucs_support.py       ← Demucs path resolver, managed runtime installer
│   ├── demucs_wrapper.py       ← Subprocess wrapper script for running Demucs in isolation
│   └── dramabox/               ← Video downloader subsystem (separate sub-package)
│       ├── __init__.py
│       ├── gui_downloader.py   ← DramaBoxTool QMainWindow (multi-platform downloader GUI, ~2850 lines)
│       ├── downloader.py       ← DramaboxDownloader class (download_file, yt-dlp dispatch)
│       ├── portable_video.py   ← PortableVideoSupport: yt-dlp wrapper for YouTube/TikTok/Facebook
│       ├── hongguo.py          ← HongguoClient: Hongguo API (catalog, series, stream URL)
│       ├── sekai_api.py        ← SekaiDramaAPI: unified drama API for DramaBox/ReelShort/etc.
│       ├── dramabox.py         ← DramaBoxBypassManager (legacy bypass chains)
│       ├── reelshort.py        ← ReelShortBypassManager
│       ├── shortmax_decrypt.py ← ShortMax segment decryption
│       ├── base.py             ← BaseBypass, BypassResult, URL parsing helpers
│       ├── api_bypass.py       ← ApiBypass(BaseBypass): API endpoint bypass
│       ├── cache_bypass.py     ← CacheBypass
│       ├── jsonld_bypass.py    ← JSON-LD schema extractor bypass
│       ├── mp4_bypass.py       ← Direct MP4 link bypass
│       ├── nextdata_bypass.py  ← Next.js __NEXT_DATA__ scraper bypass
│       ├── probe_bypass.py     ← ffprobe stream probe bypass
│       └── script_bypass.py    ← Inline JS variable extractor bypass
├── main.py                     ← Thin stub (calls src/main.py via run.sh / run.bat)
├── run.sh                      ← Linux/macOS launcher: activates .venv, sets PYTHONPATH, runs src/main.py
├── run.bat                     ← Windows launcher equivalent
├── requirements.txt            ← pip dependencies (PyQt5, edge-tts, yt-dlp, google-generativeai, etc.)
├── pyproject.toml              ← uv/PEP 517 project config (Python >= 3.11)
├── runtime_packages.json       ← Manifest for optional downloadable AI packages (FunASR, Demucs models)
├── data.json                   ← Chrome profile metadata (groups, favorites, URLs)
├── config/                     ← User config dir (AI Dubber config JSON)
├── resources/                  ← Icons, fonts, static assets
├── models/                     ← Local AI model weights (Demucs, FunASR)
├── temp_audio/                 ← Temporary audio processing files
├── .venv/                      ← Python virtual environment (Python 3.11)
├── ffmpeg.exe / ffprobe.exe / ffplay.exe  ← Bundled Windows ffmpeg binaries
│                                             (Linux uses system ffmpeg via PATH)
├── VoxCPM-main/                ← VoxCPM TTS engine (external repo, optional)
├── _internal/                  ← PyInstaller extraction from original .exe
└── AI_Dubber_Ultimate_v1.2.9.exe  ← Original Windows frozen build (reference only)
```

---

## Application Startup Flow

```
run.sh / run.bat
  └── src/main.py
        ├── get_app_dir()              [runtime_paths.py]
        ├── setup_vscode_debug_log()   [debug_log.py]
        └── launch_app()               [app_launcher.py]
              ├── QApplication setup + high-DPI
              ├── Splash screen shown
              ├── verify_license()     [license_manager.py]
              ├── from core_app import DubbingApp, APP_VERSION
              │     └── core_app.py loads compiled DubbingApp from .pyc via marshal
              │         and monkey-patches it for cross-platform (Linux/macOS)
              └── DubbingApp().show()
```

---

## Core Architecture

### DubbingApp (Main Window)
- Defined in compiled bytecode loaded by `core_app.py`
- `core_app.py` monkey-patches `DubbingApp` with:
  - `check_dependencies_on_startup` — cross-platform dependency checks
  - `__init__` — responsive layout, icon, VoxCPM detection
  - `start_batch_processing` — parallel batch with `BatchParallelManager`, isolated subprocesses (`batch_runner.py`), Demucs vocal removal, volume mixing (BG/AI), and multi-voice resolution
  - `start_transcription` — enhanced Gemini transcription with SRT parsing
  - `open_settings_dialog` — uses Python-source `SettingsDialog`
  - `convert_video_to_mp3` — parallel multi-worker batch audio extraction with live progress
  - `_start_export_worker` & timeline synchronization — multi-voice resolution ensuring segments with distinct voice roles (Male, Female, Old Man, Old Woman, Boy, Girl) export with their exact assigned voices without reverting to default Sreymom

### Background Workers (QThread pattern)
All heavy operations run in QThread subclasses:
- `CrossPlatformPythonFunASRInstallWorker` — installs FunASR python + models
- `BatchParallelManager` — parallel multi-file dubbing coordinator
- `VideoCutterThread` / `VideoMergeThread` — ffmpeg cut/merge
- `UnifiedSeriesDetailWorker` — fetches drama series info (gui_downloader.py)
- `UnifiedDownloadWorker` — parallel episode download (gui_downloader.py)
- `SocialMetadataWorker` — async yt-dlp metadata fetch for YouTube/TikTok/Facebook (gui_downloader.py)
- `CatalogWorker` — Hongguo catalog API fetch (gui_downloader.py)
- `LicenseActivationWorker`, `PaymentPollingWorker` — license system
- `QRGeneratorWorker` — QR code image generation

### Config System (`settings_manager.py`)
- Config file: `config/AI_Dubber_config.json`
- Legacy paths migrated automatically on first run
- Key sections: Gemini API keys, Azure TTS, OpenAI, Gladia, translation engine, UI flags
- `QSettings("AI_Dubber", "VideoDownloader")` used separately for the downloader tool

---

## Dramabox / Video Downloader Subsystem

### Supported Platforms
| Platform | API | Auth Required |
|----------|-----|---------------|
| **Hongguo (红果短剧)** | `HongguoClient` (REST) | None |
| **DramaBox** | `SekaiDramaAPI` | CF clearance cookie |
| **ReelShort** | `SekaiDramaAPI` | CF clearance cookie |
| **NetShort, FlickReels, ShortMax, GoodShort, PineDrama** | `SekaiDramaAPI` | CF clearance cookie |
| **YouTube** | `PortableVideoSupport` (yt-dlp) | None |
| **TikTok** | `PortableVideoSupport` (yt-dlp) | None |
| **Facebook** | `PortableVideoSupport` (yt-dlp) | None |

### Download Flow (Drama Platforms)
```
User pastes URL / clicks catalog card
  -> detect_platform_from_url()
  -> UnifiedSeriesDetailWorker.run()
      -> HongguoClient.get_series()   [Hongguo]
      -> SekaiDramaAPI.get_series()   [other drama]
  -> _apply_series_detail()           [populate episode chips UI]
  -> handle_download_now()
      -> UnifiedDownloadWorker._download_task()
          -> resolve_episode_stream()
          -> downloader.download_file()
```

### Download Flow (Social Platforms — YouTube/TikTok/Facebook)
```
User pastes URL
  -> on_link_text_changed() -> debounce 500ms timer
  -> _trigger_social_fetch() -> SocialMetadataWorker [QThread]
      -> PortableVideoSupport.get_youtube_info()  [yt-dlp extract_info]
      -> _info_to_series_detail()
  -> _apply_series_detail()  [show real title, thumbnail, chips]
  -> handle_download_now()
      -> UnifiedDownloadWorker -> resolve_episode_stream()
          -> PortableVideoSupport.download()  [yt-dlp actual download]
```

### Key Classes in gui_downloader.py
| Class / Function | Approx. Line | Purpose |
|-----------------|-------------|---------|
| `DramaBoxTool` | ~1480 | Main QMainWindow for downloader |
| `SocialMetadataWorker` | ~1062 | Async yt-dlp metadata fetcher (NEW) |
| `UnifiedSeriesDetailWorker` | ~832 | Drama series info fetcher |
| `UnifiedDownloadWorker` | ~883 | Parallel episode downloader |
| `CatalogWorker` | ~800 | Hongguo catalog fetcher |
| `detect_platform_from_url()` | ~198 | URL -> platform name string |
| `fetch_social_series_info()` | ~614 | Stub/fallback series info for social |
| `build_platform_chapters()` | ~641 | Episodes list -> chapter list dict |
| `resolve_episode_stream()` | ~643 | Episode -> final stream URL |
| `set_active_platform()` | ~1980 | Platform tab switch handler |
| `on_link_text_changed()` | ~2018 | URL input debounce handler |
| `_trigger_social_fetch()` | ~2029 | Debounce timer callback |
| `_load_series_into_preview()` | ~2554 | Check button / card click handler |
| `_apply_series_detail()` | ~2613 | Populate UI from series detail dict |
| `handle_download_now()` | ~2650 | Start download with selected episodes |

---

## AI & TTS Pipeline

### Transcription (Speech -> Text -> SRT)
1. Audio extracted from video with ffmpeg
2. **FunASR** (local) — Chinese STR, runs as subprocess via `funasr_subprocess.py`, outputs SRT
3. OR **Gladia** (cloud) — REST API `gladia_api_key`
4. SRT enhanced/translated by Gemini: `_enhanced_transcribe_with_gemini()` in `workers.py`

### Translation
- Engine selectable: `gemini` / `openai` / `deep-translator` / `azure`
- Gemini: `ai_clients.genai.GenerativeModel` (lazy-loaded, REST fallback if SDK missing)
- Key rotation for Gemini: `normalize_gemini_api_keys()` in `settings_manager.py`

### TTS (Text -> Speech)
- **Edge-TTS** (default): `edge-tts` package, async coroutines
- **Azure TTS**: REST API with `azure_api_key` + `azure_region`
- **VoxCPM**: Local GPU TTS via `voxcpm_support.generate_voxcpm_audio()` (subprocess to VoxCPM-main/)
- **Voice Clone**: `voice_clone.apply_voice_clone_to_audio()` wraps VoxCPM with reference audio

### Audio Post-Processing
- Speed matching: `audio_speed.apply_audio_tempo()` — ffmpeg `atempo` filter
- Vocal separation: `demucs_support` + `demucs_wrapper.py` subprocess
- Emotion style: `emotion_match.apply_voxcpm_emotion_style()`

---

## ffmpeg Usage

ffmpeg is used throughout the app. Binary resolved in order:
1. `ffmpeg.exe` / `ffprobe.exe` in project root (Windows bundles)
2. System `ffmpeg` in `PATH` (Linux/macOS)
3. `_internal/ffmpeg` (PyInstaller extraction fallback)

Resolution entry point: `utils.get_ffmpeg_path()` -> `runtime_paths.resolve_binary_path("ffmpeg")`

---

## License System

- `license_manager.LicenseManager` — CPU-ID-based license verified against remote server
- `verify_license()` -> online first, falls back to offline cached activation
- UI: QR code payment + polling worker
- `get_days_used()` / `reset_days_used()` in `utils.py` — tracks trial usage days

---

## Key External Services & APIs

| Service | Purpose | Config Key in settings |
|---------|---------|------------------------|
| Google Gemini API | Transcription + translation | `gemini_api_key` |
| Azure Cognitive TTS | Speech synthesis | `azure_api_key`, `azure_region` |
| OpenAI API | Translation (optional) | `openai_api_key` |
| Gladia | Cloud STR (speech recognition) | `gladia_api_key` |
| Sansekai API (`api.sansekai.my.id`) | DramaBox/ReelShort metadata | `api_base` (downloader settings) |
| Hongguo Explorer API | 红果短剧 catalog + streams | Hardcoded in `hongguo.py` |

---

## Development & Coding Notes

- **Python version:** 3.11 (`.python-version`, `pyproject.toml requires-python = ">=3.11"`)
- **Virtual env:** `.venv/` — always use `.venv/bin/python` or activate before running
- **PYTHONPATH must include `src/`** — set by `run.sh`; never run `python src/main.py` from root without it
- **`core_app.py` is a monkey-patch orchestrator** — it loads `DubbingApp` from compiled `.pyc` via `marshal` + `types.CodeType` and patches methods at import time. Do not restructure without understanding the patch chain.
- **UI language:** Interface labels are in **Khmer (ខ្មែរ)** + Chinese + English. Khmer font patch applied at startup via `utils.apply_khmer_font_patch()`.
- **No test suite** — manual verification only. Use `python -c "import ast; ast.parse(open('src/file.py').read())"` for syntax checks.
- **Windows-only binaries in repo:** `ffmpeg.exe`, `ffprobe.exe`, `ffplay.exe`, `msvcp140.dll`, `vcruntime140.dll` — present but Linux ignores them (uses system `ffmpeg`).
- **Logging:** `app_debug.log` — live stdout/stderr mirror. `app_crash.log` — unhandled exceptions.
- **`ai_clients.genai`** is a `_LazyModule` proxy — it loads `google.generativeai` on first attribute access, and if the SDK is missing, falls back to a lightweight REST implementation that speaks the v1beta API directly.
