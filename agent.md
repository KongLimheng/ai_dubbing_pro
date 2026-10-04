# AI Dubber Ultimate — Agent Instructions

> **Read this file at the start of every session.**
> It tells AI coding agents exactly how this codebase is structured, what conventions to follow, where to make changes, and what traps to avoid.

---

## 1. Quick Orientation

| Item | Value |
|------|-------|
| **App name** | AI Dubber Ultimate v1.2.9 |
| **Language** | Python 3.11 |
| **GUI framework** | PyQt5 |
| **Entry point** | `run.sh` → `src/main.py` → `app_launcher.launch_app()` |
| **Main window class** | `DubbingApp` (in compiled `.pyc`, patched by `core_app.py`) |
| **Downloader window class** | `DramaBoxTool` in `src/dramabox/gui_downloader.py` |
| **Virtual env** | `.venv/` (Python 3.11) — always use `.venv/bin/python` |
| **PYTHONPATH** | Must include `src/` — `run.sh` sets this automatically |

**Full architecture details are in [`gemini.md`](./gemini.md).**

---

## 2. Before You Make Any Change

### Step 1 — Check syntax after every edit
```bash
.venv/bin/python -c "import ast; ast.parse(open('src/path/to/file.py').read()); print('OK')"
```

### Step 2 — Test imports
```bash
DISPLAY=:99 .venv/bin/python -c "from dramabox.gui_downloader import SocialMetadataWorker; print('OK')"
```
*(Use `DISPLAY=:99` or any virtual display when PyQt5 needs to be imported without a real screen.)*

### Step 3 — Run the app (optional manual test)
```bash
./run.sh
```

---

## 3. Where to Edit What

### Main dubbing/processing logic
> These files are **Python-source** — edit freely.

| What you want to change | File |
|------------------------|------|
| Gemini transcription / SRT parsing | `src/workers.py` |
| Batch processing parallel logic | `src/batch_processor.py`, `src/batch_loader.py` |
| TTS speed/tempo | `src/audio_speed.py` |
| Vocal isolation (Demucs) paths | `src/demucs_support.py` |
| Settings/config reading + writing | `src/settings_manager.py` |
| Settings UI (tabs, forms) | `src/settings_window.py` |
| Khmer text normalization | `src/khmer_dict.py` |
| License validation | `src/license_manager.py` |
| VoxCPM TTS generation | `src/voxcpm_support.py` |
| Voice clone | `src/voice_clone.py` |
| Emotion style tagging | `src/emotion_match.py` |
| Face detection flags | `src/full_detect.py` |
| Chrome profile manager | `src/chrome.py` |
| Video cutter / merger GUI | `src/cutter.py` |
| Video to MP3 parallel converter & UI monitor | `src/video_to_mp3.py` |
| ffmpeg binary resolution | `src/utils.py` → `get_ffmpeg_path()` |
| App/resource path helpers | `src/runtime_paths.py` |
| Gemini API client / fallback | `src/ai_clients.py` |

### Video downloader subsystem (`src/dramabox/`)
| What you want to change | File |
|------------------------|------|
| Downloader GUI (main window, all UI) | `src/dramabox/gui_downloader.py` |
| Social platform metadata fetch | `src/dramabox/gui_downloader.py` → `SocialMetadataWorker` |
| yt-dlp wrapper (YouTube/TikTok/Facebook) | `src/dramabox/portable_video.py` |
| Hongguo (红果短剧) API | `src/dramabox/hongguo.py` |
| DramaBox/ReelShort/NetShort API | `src/dramabox/sekai_api.py` |
| File download + stream dispatch | `src/dramabox/downloader.py` |
| Platform detection from URL | `src/dramabox/gui_downloader.py` → `detect_platform_from_url()` |

### ⚠️ Do NOT edit
| File | Reason |
|------|--------|
| `src/core_app.py` (the `.pyc` loading section) | Fragile marshal/bytecode loading — touch only the Python-source patch functions |
| `src/_internal/` | PyInstaller extraction, auto-generated |
| `AI_Dubber_Ultimate_v1.2.9.exe` | Original frozen Windows binary, reference only |

---

## 4. Key Patterns & Conventions

### QThread Worker Pattern
Every background task uses this pattern:
```python
class MyWorker(QThread):
    result_sig = pyqtSignal(object)
    error = pyqtSignal(str)

    def run(self):
        try:
            result = do_work()
            self.result_sig.emit(result)
        except Exception as e:
            self.error.emit(str(e))

# In main window:
self._worker = MyWorker(...)
self._worker.result_sig.connect(self._on_result)
self._worker.error.connect(self._on_error)
self._worker.start()
```
Always terminate old workers before starting new ones:
```python
if self._worker and self._worker.isRunning():
    self._worker.terminate()
    self._worker.wait()
```

### Series Detail Dict Shape
This dict is the central data contract for the downloader:
```python
{
    "platform": "YouTube",          # platform name string
    "series_id": "https://...",     # URL or numeric ID
    "series_name": "Video Title",   # display title
    "series_cover": "https://...",  # thumbnail URL
    "series_intro": "description",  # short description
    "episode_cnt": 1,               # total episode/video count
    "vid_list": [],                 # raw video ID list
    "chapters": [...],              # normalized chapter dicts (see below)
    "page_html": "",                # raw HTML if scraped
}
```

### Chapter Dict Shape
```python
{
    "chapterName": "Episode Title",
    "url": "https://...",           # source URL
    "resolved_url": "ytdlp://...", # or direct MP4/m3u8
    "num": 1,                       # episode number
    "locked": False,
    "id": "video_id",
}
```

### Config Key Names (settings_manager.py)
```python
# Read:
cfg = settings_manager.read_config()
cfg["gemini_api_key"]       # primary Gemini key
cfg["gemini_api_keys"]      # list of rotation keys
cfg["azure_api_key"]
cfg["azure_region"]
cfg["openai_api_key"]
cfg["gladia_api_key"]
cfg["translation_engine"]   # "gemini" | "openai" | "deep-translator" | "azure"

# Write:
settings_manager.write_config(cfg)
settings_manager.save_gemini_api_config(api_key, ...)
```

### Downloader QSettings Keys
```python
# QSettings("AI_Dubber", "VideoDownloader") — separate from JSON config
settings.value("output_dir", ...)
settings.value("max_workers", 4, type=int)
settings.value("api_base", "https://api.sansekai.my.id/api", type=str)
settings.value("proxy_url", "", type=str)
settings.value("cf_clearance", "", type=str)
```

---

## 5. Platform Detection Logic

```python
# src/dramabox/gui_downloader.py ~ line 198
def detect_platform_from_url(url_text: str) -> Optional[str]:
    ...
# Returns: "Hongguo" | "DramaBox" | "ReelShort" | "YouTube" | "TikTok" | "Facebook" | None
```

Social platforms = `{"YouTube", "TikTok", "Facebook"}` — use yt-dlp, no episode prefetch needed.  
Drama platforms = everything else — use `SekaiDramaAPI` or `HongguoClient`.

---

## 6. ffmpeg Path Resolution

```python
from utils import get_ffmpeg_path
ffmpeg_bin = get_ffmpeg_path()  # Returns str path to ffmpeg binary
```

On Linux: returns system `ffmpeg` from PATH.  
On Windows: returns `ffmpeg.exe` from project root.

**Never hardcode `"ffmpeg"` as the executable** — always call `get_ffmpeg_path()`.

---

## 7. Gemini API Usage

The application uses the modern **Google GenAI SDK (`google-genai`)** with stateless clients, direct REST endpoints, and transparent backward compatibility for compiled bytecode:

### Modern SDK Usage (Recommended)
```python
from ai_clients import get_genai_client

# Obtain a cached client instance for the specified (or settings default) key:
client = get_genai_client(api_key="YOUR_KEY")

# Text generation:
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Your prompt",
)
print(response.text)

# Audio / File API:
audio_file = client.files.upload(file="path/to/audio.mp3")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[audio_file, "Transcribe this audio file"],
)
client.files.delete(name=audio_file.name)
```

### Legacy Compatibility Shim
For pre-compiled bytecode (`core_app.pyc`, `workers.pyc`), `src/ai_clients.py` provides a drop-in compatibility shim for `google.generativeai`:
```python
from ai_clients import genai

genai.configure(api_key="YOUR_KEY")
model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content("Your prompt")
print(response.text)
```

- If `google-genai` SDK is unavailable, `src/ai_clients.py` provides a pure REST fallback automatically.
- No Google Discovery document fetching bug (`AQ.Ab8...` keys work out-of-the-box).
- API key rotation: use `settings_manager.normalize_gemini_api_keys()` to obtain the key list.

---

## 8. UI Pattern & 3-Color Design System Rules

All GUI windows, dialogs, widgets, and styles must strictly adhere to the project's 3-color design system (modeled after `src/dramabox/gui_downloader.py`).

**Detailed specifications are in:**
- Rule file: [`.agent/rules/ui-patterns.md`](./.agent/rules/ui-patterns.md)
- Documentation: [`docs/UI_DESIGN_SYSTEM.md`](./docs/UI_DESIGN_SYSTEM.md)
- Reusable Tokens & QSS generator: [`src/ui_theme_tokens.py`](./src/ui_theme_tokens.py)

### The 3 Core Colors (60-30-10 Rule):
1. **Base Canvas (60%)**: `#0F141C` (Obsidian Midnight Dark) — Window & dialog backdrops
2. **Structural Surface (30%)**: `#161D28` (Charcoal Slate) with `#212936` borders — Cards, sidebars, panels, inputs
3. **Hero Accent (10%)**: `#F97316` (Flame Orange) — CTAs, active tabs, focus rings, progress bars

### Key Constraints:
- **Font Stack**: Always use `'Segoe UI', 'Noto Sans Khmer', 'Khmer OS Battambang', 'PingFang SC', -apple-system, sans-serif` and ensure `utils.apply_khmer_font_patch()` is active.
- **Border Radii Hierarchy**: `4-6px` micro, `8-10px` controls/inputs, `12px` cards/panels, `16-20px` major containers.
- **Spacing Grid**: 4px / 8px scale (`14px` root layout margin, `12px` container margin, `8-10px` elements).

---

## 9. Running Individual Modules

```bash
# Run just the video downloader (standalone)
PYTHONPATH=src .venv/bin/python -c "
from PyQt5.QtWidgets import QApplication
import sys
from dramabox.gui_downloader import DramaBoxTool
app = QApplication(sys.argv)
w = DramaBoxTool()
w.show()
sys.exit(app.exec_())
"

# Run a quick import test
PYTHONPATH=src .venv/bin/python -c "import settings_manager; print(settings_manager.read_config())"

# Syntax check a file
.venv/bin/python -c "import ast; ast.parse(open('src/dramabox/gui_downloader.py').read()); print('OK')"
```

---

## 10. Recent Changes (Session Log)

### 2026-10-02 — Facebook Graph API Posting Enhancements (Playlists, Group Sharing, Schedule Public)
**Files:** `src/social_post_config.py`, `src/social_post_uploader.py`, `src/social_post_window.py`, `test_facebook_graph_enhancements.py` (new)

**Features & Improvements:**
1. **Facebook Status Control**: Added support for "🚀 Publish Immediately", "🕒 Schedule Public", and "📝 Save as Draft".
   - Scheduled posts adhere to Meta Graph API requirements (`published=false`, `scheduled_publish_time=<unix_ts>`, min 11 minutes in the future).
   - Added schedule panel with `QDateTimeEdit`, calendar popup, quick presets (`+30m`, `+1h`, `+3h`, `+1d`, `Tomorrow 9AM`), and batch queue interval offsetting.
2. **Page Playlists Retrieval**:
   - Upgraded `FacebookUploader.fetch_page_playlists` with schema fallback across Graph API version differences and cursor pagination (`paging.next`).
   - Integrated non-blocking `FacebookPlaylistsWorker(QThread)`.
3. **Fetch All Available Groups & Multi-Group Sharing**:
   - Implemented `FacebookUploader.fetch_all_available_groups` querying `/me/groups` (with page_token and user_token) and `/{page_id}/groups` with pagination, deduplication, and admin-first sorting.
   - Integrated non-blocking `FacebookGroupsWorker(QThread)`.
   - Added `FacebookGroupSelectorDialog` modal with search/filter, admin/public chips, "Select All", and counter.
   - Enhanced `FacebookUploader.share_video_to_groups` for distributing post links with per-group error isolation.
4. Added unit test suite `test_facebook_graph_enhancements.py` with 100% pass rate.

### 2026-09-25 — Batch Vocal Removal (Demucs) & Background Music Mixing Parity
**Files:** `src/batch_loader.py`, `src/batch_processor.py`, `src/batch_runner.py`, `test_batch_vocal_removal.py` (new)

**Problem:** Batch video export exported only video and AI voice, completely omitting the original video's background music. Individual video export used Demucs AI vocal removal (`no_vocals.wav` -> `instrumental.mp3`) and mixed background music (30%) with AI voice (100%), whereas batch export hardcoded `"remove_vocal": False` and `"use_demucs": False`.

**Fix:**
1. Injected Demucs vocal removal controls into `EnhancedBatchSrtMappingDialog` (`src/batch_loader.py`):
   - Checkbox: "🎵 Auto Remove Vocals (Demucs) & Keep Background Music"
   - Spinboxes: Background volume (default 30%, 0-500%) & AI Voice volume (default 100%, 0-500%)
   - Synchronized with parent window and configuration persistence (`settings_manager`).
2. Updated `src/batch_processor.py`:
   - `BatchJobItem` and `BatchParallelManager`: added `remove_vocal`, `use_demucs`, `background_percent`, and `ai_voice_percent`.
   - `_launch_job`: writes vocal removal and volume mix values to `job_spec.json`.
   - `BatchProcessingProgressDialog`: added header card status badge (`🎵 Vocal Removal: ON (BG: {bg}% | Voice: {ai}%)`) and real-time `Vocal Removal` table status badge.
3. Updated `src/batch_runner.py`:
   - Extracted vocal removal and volume settings from `job_spec.json`.
   - Resolved multi-voice characters and pitch offsets per clip using `resolve_voice_and_pitch`.
   - Passed `remove_vocal_on_export=remove_vocal, use_demucs=use_demucs, background_volume_percent=background_percent, ai_voice_volume_percent=ai_voice_percent` into `ExportWorker`.
   - Verified that isolated subprocess working directories (`tempfile.mkdtemp(prefix="dub_job_...")`) prevent Demucs file collision across parallel jobs.
4. Added test suite `test_batch_vocal_removal.py` with 100% pass rate across 5 test suites.

---

### 2026-09-25 — Multi-Voice Video Export & Timeline Table Synchronization Fix
**Files:** `src/utils.py`, `src/workers.py`, `src/core_app.py`, `test_multi_voice_export.py`

**Problem:** In the timeline editor with loaded transcript segments containing multiple voice types (`Female-sreymom (khmer)`, `Male - Piseth (Khmer)`, `Old Man - (piset)`, `old woman`, `Boy - Piseth`, `Girl - Sreymom`), exporting video only exported `km-KH-SreymomNeural` for all clips instead of respecting each segment's assigned voice.

**Fix:**
1. Created `normalize_voice_id` and `resolve_voice_and_pitch` in `src/utils.py`:
   - Normalized 40+ display labels, aliases, and Khmer tags (`មនុស្សចាស់ប្រុស`, `យាយ`, `ក្មេងប្រុស`, etc.).
   - Mapped custom roles (`Old Man`, `Old Woman`, `Boy`, `Girl`) to underlying base neural voice (`km-KH-PisethNeural`, `km-KH-SreymomNeural`) with pitch adjustments (`-20Hz`, `+25Hz`, `+20Hz`).
2. Patched `_resolve_special_voice` on `ExportWorker`, `SegmentAudioAnalysisWorker`, and `PreviewWorker` in `src/workers.py`.
3. Patched `DubbingApp` in `src/core_app.py`:
   - `_normalize_gender_result`: fixed case sensitivity bug that forced non-lowercase strings to `female`.
   - `_apply_gender_result_to_row`: synchronizes both table combobox AND `self.segments[row_index]['voice']`.
   - `_populate_table_row` & `_collect_table_row_state`: preserves normalized voice ID across table and backing store.
   - `_collect_segment_analysis_rows`: ensures timing analysis rows retain assigned voices.
   - `_start_export_worker`: pre-export gateway validating voices, pitches, and re-checking row audio cache with the resolved voice and pitch so stale female audio cache hits are not reused.
4. Added test suite `test_multi_voice_export.py` with 100% pass rate.

---

### 2026-09-25 — Batch Audio Speech Quality & Dialogue Timing Parity Fix
**Files:** `src/batch_loader.py`, `src/batch_processor.py`, `src/batch_runner.py`

**Problem:** Batch video export sounded different from individual export: TTS dialogue was out of sync with video scenes, suffered cumulative timeline drift, and volume dynamics were altered.

**Fix:**
1. Defaulted `fit_audio` to `True` across `BatchJobItem`, `BatchParallelManager`, `BatchProcessingProgressDialog`, and `batch_runner.py` (previously hardcoded to `False`).
2. Enabled `ExportWorker._fit_clip_to_timeline_duration` in batch runs to apply natural Khmer tempo retiming (0.85x–1.25x), eliminating drift and synchronizing speech to video timing.
3. Fixed `s_vol` default in `batch_runner.py` from `1.0` to `0.0`, preventing lossy ffmpeg `-af volume=1.0dB` re-encoding on every segment and preserving pristine audio dynamics.
4. Added `chk_batch_sync_tts` toggle in `EnhancedBatchSrtMappingDialog` and added Speech Sync status badge to monitor header.
5. Normalized rate/pitch formats (`+0%`, `+0Hz`) and trimmed trailing ellipses (`...`).

---

### 2026-09-25 — Batch Vocal Removal (Demucs) & Background Music Mixing
**Files:** `src/batch_loader.py`, `src/batch_processor.py`, `src/batch_runner.py`

**Problem:** Batch video export lacked vocal removal and background music mixing, which was available only in individual video export.

**Fix:**
1. Injected Demucs vocal removal checkbox (`chk_batch_demucs`) and volume spinboxes (`spin_batch_bg_mix`, `spin_batch_ai_mix`) into `EnhancedBatchSrtMappingDialog`.
2. Passed `remove_vocal`, `use_demucs`, `background_percent`, and `ai_voice_percent` into `BatchJobItem`, `BatchParallelManager`, and `job_spec.json`.
3. Updated `batch_runner.py` to forward Demucs and mix options directly to `ExportWorker`.
4. Added vocal removal badge and status pills to `BatchProcessingProgressDialog`.

---

### 2026-09-25 — Multi-Voice Export & Timeline Table Synchronization
**Files:** `src/patch_manager.py`, `src/batch_runner.py`

**Problem:** Exporting video with multiple voices (e.g., Sreymom, Piseth, Old Man, Old Woman) collapsed all segments to `km-KH-SreymomNeural`.

**Fix:**
1. Patched `DubbingApp._continue_export_with_path` in `src/patch_manager.py` to preserve per-segment voices and character roles across the entire export pipeline.
2. Implemented voice normalization for English, Khmer, and character label variants.
3. Resolved specialized pitch offsets (e.g., Old Man: Piseth -20Hz, Old Woman: Sreymom -20Hz).
4. Synchronized table segments in `batch_runner.py` to resolve voice and pitch per segment.

---

### 2026-09-25 — Parallel Video to MP3 Converter with Real-Time Progress
**Files:** `src/video_to_mp3.py` (new), `src/core_app.py` (patched)

**Problem:** "🎵 Vid to MP3" previously executed sequentially one video at a time on a single background worker, showing only a single aggregate progress bar with no visibility into individual video conversion progress or speed.

**Fix:**
1. Created `src/video_to_mp3.py`:
   - `VideoToMp3Item`: Data model tracking duration, status, real-time percent, speed, output file size.
   - `VideoToMp3WorkerThread`: Dedicated per-video thread executing `ffmpeg` with `-progress pipe:1` to emit live percentage and speed (e.g., `45x`).
   - `VideoToMp3ParallelManager`: Concurrency coordinator managing job queue, active threads (1-8 configurable), pause/resume, cancel all, retry.
   - `VideoToMp3Dialog`: Modern monitor dialog with per-file inline progress bars, status badges (`Queued`, `⚡ Converting`, `✅ Done`, `❌ Failed`), overall progress bar, metric pills, `➕ Add Videos` button, and direct `▶️ Play MP3` / `📁 Open Folder` actions.
   - `convert_video_to_mp3_enhanced`: Drop-in replacement for `DubbingApp.convert_video_to_mp3`.
   - `VideoToMp3WorkerAdapter`: Backward-compatible adapter for legacy worker callers.
2. Patched `src/core_app.py` to route `DubbingApp.convert_video_to_mp3` to `convert_video_to_mp3_enhanced`.

---

### 2026-09-24 — Social Platform Video Downloader Fix
**File:** `src/dramabox/gui_downloader.py`

**Problem:** YouTube/TikTok/Facebook URL paste showed stub "YouTube Video" title with no real metadata.

**Fix:**
1. Added `SocialMetadataWorker(QThread)` (~line 1062) — async yt-dlp metadata fetch
2. Added 500ms debounce timer in `DramaBoxTool.__init__` to avoid keystroke flooding
3. Updated `on_link_text_changed()` to use debounce instead of immediate call
4. Added `_trigger_social_fetch()` method — debounce callback
5. Updated `_load_series_into_preview()` — social path now async
6. Updated `_apply_series_detail()` — platform-specific helper messages + emoji icons
7. Updated `set_active_platform()` — platform-specific input placeholder text

**Flow now:** paste URL → 500ms debounce → `SocialMetadataWorker` → yt-dlp `extract_info()` → real title/thumbnail/episode count shown → click Download.

---

## 11. Common Traps to Avoid

| Trap | Correct Approach |
|------|-----------------|
| Running without PYTHONPATH | Always use `run.sh` or set `PYTHONPATH=src` |
| Importing PyQt5 without a display | Use `DISPLAY=:99` or ensure virtual display exists |
| Hardcoding `"ffmpeg"` | Use `utils.get_ffmpeg_path()` |
| Calling QThread methods from non-main thread | Use signals/slots, never call Qt UI methods from `run()` |
| Starting a new worker without stopping the old one | Always check `isRunning()` + `terminate()` + `wait()` |
| Writing to `core_app.py`'s bytecode loader section | Only edit the Python patch functions after line ~91 |
| Assuming yt-dlp is installed | Always check `PortableVideoSupport.available` first |
| Using `QSettings` for main app config | Main config is JSON via `settings_manager` — `QSettings` is only for the downloader tool |
| Violating the 3-Color UI palette | Always use `.agent/rules/ui-patterns.md` tokens (`#0F141C`, `#161D28`, `#F97316`) |
| Hardcoding fonts to Arial/Helvetica for Khmer | Always use font stack with `'Noto Sans Khmer'` and call `apply_khmer_font_patch()` |
