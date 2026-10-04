# -*- coding: utf-8 -*-
"""
workers module wrapper.
Loads native compiled bytecode from workers.pyc with cross-platform runtime support.
"""

import shutil
import subprocess

import settings_manager
import time
import re
import os
import sys
from importlib.machinery import SourcelessFileLoader

_pyc_path = os.path.join(os.path.dirname(__file__), 'workers.pyc')
if not os.path.exists(_pyc_path):
    raise FileNotFoundError(f"Missing compiled bytecode module: {_pyc_path}")

_mod = SourcelessFileLoader(__name__, _pyc_path).load_module()

# Apply cross-platform FunASR python resolver to TranscriptionWorker
try:
    from core_app import pick_funasr_python
    if hasattr(_mod, 'TranscriptionWorker'):
        _mod.TranscriptionWorker._pick_funasr_python = lambda self: pick_funasr_python()
except Exception:
    pass


def _robust_parse_gemini_srt(self, srt_content):
    if not srt_content:
        return []
    text = str(srt_content).replace("```srt", "").replace("```", "").strip()
    segments = []
    pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*[\r\n]+(.*?)(?=(?:\r?\n\s*(?:\d+\s+)?\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}\s*-->|\Z))",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        s_str, e_str, content = m.group(1), m.group(2), m.group(3).strip()
        if content:
            content = re.sub(r"\n+\d+$", "", content).strip()
            s_time = self.parse_srt_timestamp(s_str)
            e_time = self.parse_srt_timestamp(e_str)
            segments.append({"start": s_time, "end": e_time, "text": content})

    if segments:
        print(f"[DEBUG] Successfully parsed {len(segments)} segments total")
        if 0.0 < segments[0]["start"] <= 1.0:
            segments[0]["start"] = 0.0
            print("[DEBUG] Adjusted first segment to start at 0.0s")
    else:
        print("[WARNING] No segments parsed from transcription")
    return segments


def _get_transcribe_prompt(content, targetLangCode, targetLang):
    if not isinstance(content, str):
        return (
            f"You are a professional subtitle transcription and localization expert.\n"
            f"Listen carefully to the provided audio and transcribe all spoken dialogue into {targetLang} ({targetLangCode}) in accurate SRT format with precise timestamps.\n\n"
            f"CRITICAL RULES:\n"
            f"1. Provide accurate timestamps matching the spoken words.\n"
            f"2. Structure the output as standard SRT format:\n"
            f"1\n"
            f"00:00:01,000 --> 00:00:04,000\n"
            f"[Translated text in {targetLang}]\n"
            f"3. Translate naturally, elegantly, and fluently in {targetLang}, matching tone and context.\n"
            f"4. DO NOT output any conversational text, explanations, or code blocks. Output ONLY valid SRT content."
        )

    return (
        f"""You are a professional subtitle translator and localization expert.
                Translate the following Subtitle file (SRT format) accurately into {targetLang} ({targetLangCode}).
        
                CRITICAL RULES:
                1. Preserve the EXACT SRT structure, line numbering, and timestamps intact.
                Example format:
                1
                00:00:01,000 --> 00:00:04,000
                [Translated text in {targetLang}]
                2. Translate naturally, elegantly, and fluently in {targetLang}, matching tone and context.
                3. DO NOT output any conversational text, explanations, or code blocks. Output ONLY valid SRT content.
        
                Here is the SRT content to translate:
                {content}`;
            """
    )


def _enhanced_transcribe_with_gemini(self, audio_path, api_key):
    from ai_clients import get_genai_client, genai
    try:
        from google.genai import types as genai_types
    except ImportError:
        genai_types = None

    # Collect key pool with deduplication
    key_pool = []
    if api_key and str(api_key).strip():
        key_pool.append(str(api_key).strip())

    try:
        from settings_manager import get_gemini_api_config
        cfg = get_gemini_api_config()
        for k in cfg.get("api_keys", []):
            k_str = str(k).strip()
            if k_str and k_str not in key_pool:
                key_pool.append(k_str)
        primary_k = cfg.get("api_key")
        if primary_k and str(primary_k).strip() not in key_pool:
            key_pool.append(str(primary_k).strip())
    except Exception:
        pass

    if not key_pool:
        raise Exception(
            "No Gemini API key provided. Please configure your API key in Settings.")

    last_error = None

    for key_idx, current_key in enumerate(key_pool):
        key_masked = f"{current_key[:6]}...{current_key[-4:]}" if len(
            current_key) > 10 else "***"
        if len(key_pool) > 1:
            self.progress.emit(
                f"🔑 Using Gemini API Key {key_idx + 1}/{len(key_pool)} ({key_masked})...")

        genai.configure(api_key=current_key)
        try:
            client = get_genai_client(api_key=current_key)
        except Exception as e:
            print(
                f"[WARN] Failed to initialize client for key {key_masked}: {e}")
            last_error = e
            continue

        # Discover available models
        self.progress.emit("🔍 Checking available models...")
        try:
            models_pager = client.models.list()
            available_models = []
            for m in models_pager:
                actions = getattr(m, "supported_actions", None) or getattr(
                    m, "supported_generation_methods", None) or []
                if "generateContent" in actions or not actions:
                    available_models.append(getattr(m, "name", str(m)))
            print(f"[DEBUG] Available models count: {len(available_models)}")
        except Exception as e:
            err_msg = str(e)
            print(
                f"[WARN] Failed to list models with key {key_masked}: {err_msg}")
            if "400" in err_msg or "API key not valid" in err_msg or "429" in err_msg or "quota" in err_msg.lower():
                self.progress.emit(
                    f"⚠️ Key {key_masked} returned error. Rotating to backup key...")
                last_error = e
                continue
            available_models = []

        # Candidate models sequence
        candidate_models = []
        user_model = getattr(self, "model_name",
                             None) or "gemini-3.1-flash-lite"
        user_model_clean = user_model.replace("models/", "")
        candidate_models.append(user_model_clean)
        candidate_models.append(f"models/{user_model_clean}")

        fallback_preferences = [
            "gemini-3.8-flash",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-3.5-flash",
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
        ]
        for pref in fallback_preferences:
            if pref not in candidate_models and f"models/{pref}" not in candidate_models:
                candidate_models.append(pref)

        # Upload audio file
        audio_file = None
        upload_success = False
        try:
            self.progress.emit("📤 Uploading audio to Gemini...")
            audio_file = client.files.upload(file=audio_path)

            while True:
                st = getattr(audio_file, "state", None)
                st_name = getattr(st, "name", str(st)) if st else ""
                if st_name == "PROCESSING" or st == "PROCESSING":
                    time.sleep(2)
                    audio_file = client.files.get(name=audio_file.name)
                else:
                    break

            st = getattr(audio_file, "state", None)
            st_name = getattr(st, "name", str(st)) if st else ""
            if st_name == "FAILED" or st == "FAILED":
                raise Exception(
                    "Audio file processing failed on Gemini server.")

            upload_success = True
        except Exception as e:
            err_msg = str(e)
            print(
                f"[ERROR] Gemini upload failed with key {key_masked}: {err_msg}")
            last_error = e
            if "400" in err_msg or "API key not valid" in err_msg or "429" in err_msg or "quota" in err_msg.lower():
                self.progress.emit(
                    f"⚠️ Key {key_masked} upload failed ({err_msg[:60]}). Rotating to backup key...")
                continue
            if key_idx < len(key_pool) - 1:
                self.progress.emit(
                    f"⚠️ Key {key_masked} failed. Rotating to backup key...")
                continue
            raise Exception(f"Gemini transcription error: {err_msg}")

        if not upload_success or audio_file is None:
            continue

        try:
            # Try candidate models
            for candidate in candidate_models:
                if available_models:
                    model_in_available = (
                        candidate in available_models or
                        f"models/{candidate}" in available_models or
                        candidate.replace(
                            "models/", "") in [m.replace("models/", "") for m in available_models]
                    )
                    if not model_in_available:
                        continue

                self.progress.emit(f"🤖 Using model: {candidate}...")
                self.progress.emit("🎯 Transcribing audio...")

                from settings_manager import get_gemini_api_config
                cfg = get_gemini_api_config()
                _GEMINI_TRANSCRIBE_PROMPT = _get_transcribe_prompt(
                    content=audio_file, targetLangCode=cfg.get('target_language', 'km'), targetLang='Khmer')
                try:
                    config = None
                    if genai_types:
                        config = genai_types.GenerateContentConfig(
                            http_options=genai_types.HttpOptions(
                                timeout=120000)
                        )
                    response = client.models.generate_content(
                        model=candidate,
                        contents=[audio_file, _GEMINI_TRANSCRIBE_PROMPT],
                        config=config,
                    )
                    srt_content = getattr(response, "text", "")
                    if srt_content:
                        print(
                            "[DEBUG] ===== GEMINI RAW RESPONSE (First 300 chars) =====")
                        print(srt_content[:300])
                        print("[DEBUG] ===== END RESPONSE PREVIEW =====")

                        segments = self.parse_gemini_srt(srt_content)
                        if segments:
                            self.progress.emit(
                                f"✅ Parsed {len(segments)} subtitles successfully")
                            return segments
                        else:
                            self.progress.emit(
                                "⚠️ No segments parsed from transcription response")
                except Exception as model_err:
                    err_str = str(model_err).lower()
                    print(f"[WARN] Model {candidate} failed: {model_err}")
                    if "503" in err_str or "high demand" in err_str or "404" in err_str or "not found" in err_str or "no longer available" in err_str:
                        self.progress.emit(
                            f"⚠️ Model {candidate} busy or unavailable. Trying fallback model...")
                        continue
                    if "429" in err_str or "quota" in err_str or "rate limit" in err_str:
                        self.progress.emit(
                            f"⚠️ Quota exceeded for model {candidate} on key {key_masked}.")
                        last_error = model_err
                        break
                    last_error = model_err
                    continue
        finally:
            if audio_file and hasattr(audio_file, "name"):
                try:
                    client.files.delete(name=audio_file.name)
                    print(
                        f"[DEBUG] Deleted Gemini audio file: {audio_file.name}")
                except Exception:
                    pass

    if last_error:
        raise Exception(f"Gemini transcription error: {str(last_error)}")
    raise Exception(
        "Gemini transcription failed with all configured API keys.")


if hasattr(_mod, 'TranscriptionWorker'):
    _mod.TranscriptionWorker.parse_gemini_srt = _robust_parse_gemini_srt
    _mod.TranscriptionWorker.transcribe_with_gemini = _enhanced_transcribe_with_gemini

# Universal voice & pitch resolver patch for ExportWorker, SegmentAudioAnalysisWorker, and PreviewWorker


def _enhanced_resolve_special_voice(self, voice_id, pitch_str="+0Hz"):
    try:
        from utils import resolve_voice_and_pitch
        return resolve_voice_and_pitch(voice_id, pitch_str)
    except Exception:
        return voice_id or "km-KH-SreymomNeural", pitch_str or "+0Hz"


for _w_cls_name in ("ExportWorker", "SegmentAudioAnalysisWorker", "PreviewWorker"):
    if hasattr(_mod, _w_cls_name):
        setattr(getattr(_mod, _w_cls_name), "_resolve_special_voice",
                _enhanced_resolve_special_voice)

# ── Facebook 720p Video Quality & Compression Optimization ────────────────────


def probe_video_dimensions(video_path: str):
    """
    Probe video width, height, fps, and bitrate using ffprobe or ffmpeg.
    Returns (width, height, fps, bitrate).
    """
    if not video_path or not os.path.exists(video_path):
        return (0, 0, 30.0, 0)

    from utils import get_ffmpeg_path
    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
    try:
        cmd = [
            ffprobe_bin, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,bit_rate",
            "-of", "json", video_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            import json
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            if streams:
                s = streams[0]
                w = int(s.get("width") or 0)
                h = int(s.get("height") or 0)
                br = int(s.get("bit_rate") or 0)
                fps_str = s.get("r_frame_rate", "30/1")
                if "/" in fps_str:
                    num, den = fps_str.split("/", 1)
                    fps = float(num) / max(1.0, float(den))
                else:
                    fps = float(fps_str or 30.0)
                if w > 0 and h > 0:
                    return (w, h, fps, br)
    except Exception:
        pass

    try:
        ffmpeg_bin = get_ffmpeg_path()
        res = subprocess.run([ffmpeg_bin, "-i", video_path],
                             capture_output=True, text=True, timeout=10)
        out = res.stderr or ""
        m = re.search(r'Stream #\d+:\d+.*Video:.*,\s*(\d{2,5})x(\d{2,5})', out)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            fps = 30.0
            fps_m = re.search(r'(\d+(?:\.\d+)?)\s*fps', out)
            if fps_m:
                fps = float(fps_m.group(1))
            br = 0
            br_m = re.search(r'bitrate:\s*(\d+)\s*kb/s', out)
            if br_m:
                br = int(br_m.group(1)) * 1000
            return (w, h, fps, br)
    except Exception:
        pass

    return (0, 0, 30.0, 0)


def compute_target_dimensions(width: int, height: int, target_res: str = "auto", allow_upscale: bool = False):
    """
    Compute smart target dimensions for video export.
    - If target_res is 'source' or 'auto': maintains original dimensions (rounded to even numbers).
    - If target_res is '720p': target is 720p. If source is smaller than 720p and allow_upscale is False,
      keeps source dimensions to avoid quality degradation and file bloat!
    - If target_res is '1080p': target is 1080p. If source is smaller, keeps source dimensions unless allow_upscale=True.
    - Guarantees even dimensions for H.264 compatibility.
    """
    if not width or not height or width <= 0 or height <= 0:
        return (1280, 720) if target_res == "720p" else (1920, 1080)

    clean_res = str(target_res or "auto").lower().strip()
    if clean_res in ("source", "auto"):
        return (max(2, width - (width % 2)), max(2, height - (height % 2)))

    max_dim = 1080 if clean_res == "1080p" else 720

    if width >= height:
        # Landscape: short edge is height
        if not allow_upscale and height <= max_dim:
            return (max(2, width - (width % 2)), max(2, height - (height % 2)))
        new_h = max_dim
        new_w = int(round(width * (float(max_dim) / float(height)) / 2.0)) * 2
    else:
        # Portrait / Reels: short edge is width
        if not allow_upscale and width <= max_dim:
            return (max(2, width - (width % 2)), max(2, height - (height % 2)))
        new_w = max_dim
        new_h = int(round(height * (float(max_dim) / float(width)) / 2.0)) * 2

    return (max(2, new_w), max(2, new_h))


def _parse_bitrate_str_to_bps(bitrate_val, default_bps=3200000):
    """Parse bitrate string (e.g. '3.2M', '1500k', 1200000) into integer bps."""
    if not bitrate_val:
        return default_bps
    if isinstance(bitrate_val, (int, float)):
        return int(bitrate_val)
    s = str(bitrate_val).strip().upper()
    try:
        if s.endswith('M') or s.endswith('MBPS'):
            num = float(re.sub(r'[^\d\.]', '', s))
            return int(num * 1000000)
        elif s.endswith('K') or s.endswith('KBPS'):
            num = float(re.sub(r'[^\d\.]', '', s))
            return int(num * 1000)
        else:
            return int(float(s))
    except Exception:
        return default_bps


def build_facebook_video_encoder_args(video_encoder="cpu", target_w=1280, target_h=720,
                                      crf=25, target_bitrate="3.2M", max_bitrate="4.5M",
                                      source_bitrate=0, faststart=True, fps=None):
    """
    Build optimized FFmpeg video encoding arguments for Facebook 720p/1080p compression.
    Supports smart source-bitrate adaptation so compact source videos (e.g. ~18MB / 1Mbps)
    never blow up in size during export.
    """
    encoder = str(video_encoder or "cpu").lower().strip()
    args = []

    # Calculate adaptive bitrates
    src_bps = int(source_bitrate or 0)
    preset_tb_bps = _parse_bitrate_str_to_bps(target_bitrate, 3200000)
    preset_mb_bps = _parse_bitrate_str_to_bps(max_bitrate, 4500000)

    if 0 < src_bps <= 2500000:
        # Source video is already compact (< 2.5 Mbps). Cap target bitrate to match source!
        eff_tb_bps = min(2200000, max(450000, int(src_bps * 1.10)))
        eff_mb_bps = min(2800000, max(600000, int(src_bps * 1.30)))
        eff_buf_bps = int(eff_mb_bps * 1.5)
        eff_crf = max(24, min(28, int(crf or 25)))
    else:
        # Source is high bitrate (> 2.5 Mbps) or unknown
        eff_tb_bps = preset_tb_bps
        eff_mb_bps = preset_mb_bps
        eff_buf_bps = min(6000000, int(eff_mb_bps * 1.5))
        eff_crf = max(20, min(30, int(crf or 25)))

    tb_str = f"{eff_tb_bps // 1000}k"
    mb_str = f"{eff_mb_bps // 1000}k"
    buf_str = f"{eff_buf_bps // 1000}k"

    if encoder == "nvenc":
        args = [
            "-c:v", "h264_nvenc",
            "-preset", "p4",
            "-rc", "vbr",
            "-cq", str(eff_crf),
            "-b:v", tb_str,
            "-maxrate", mb_str,
            "-bufsize", buf_str,
            "-pix_fmt", "yuv420p"
        ]
    elif encoder == "amf":
        args = [
            "-c:v", "h264_amf",
            "-rc", "vbr_peak",
            "-b:v", tb_str,
            "-maxrate", mb_str,
            "-bufsize", buf_str,
            "-pix_fmt", "yuv420p"
        ]
    elif encoder == "qsv":
        args = [
            "-c:v", "h264_qsv",
            "-global_quality", str(eff_crf),
            "-b:v", tb_str,
            "-maxrate", mb_str,
            "-bufsize", buf_str,
            "-pix_fmt", "yuv420p"
        ]
    else:  # cpu / libx264
        args = [
            "-c:v", "libx264",
            "-preset", "faster",
            "-crf", str(eff_crf),
            "-maxrate", mb_str,
            "-bufsize", buf_str,
            "-pix_fmt", "yuv420p"
        ]

    if fps:
        try:
            fps_val = float(fps)
            if 10.0 <= fps_val <= 120.0:
                args.extend(["-r", f"{fps_val:g}"])
        except Exception:
            args.extend(["-r", str(fps)])

    if faststart:
        args.extend(["-movflags", "+faststart"])

    return args


def _safe_get_worker_attr(worker, attr_name, default=None):
    """Safely get worker attribute bypassing PyQt uninitialized QObject RuntimeError."""
    try:
        if hasattr(worker, "__dict__") and attr_name in worker.__dict__:
            return worker.__dict__[attr_name]
        return getattr(worker, attr_name, default)
    except Exception:
        return default


def _probe_file_media_duration(ffprobe_bin, file_path):
    try:
        cmd = [
            ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            d = float(res.stdout.strip())
            if d > 0:
                return d
    except Exception:
        pass
    return 0.0


def _probe_file_has_audio(ffprobe_bin, file_path):
    if not file_path or not os.path.exists(file_path):
        return False
    try:
        cmd = [
            ffprobe_bin, "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            file_path
        ]
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return "audio" in (res.stdout or "").lower()
    except Exception:
        return False


def _build_atempo_filter_chain(factor):
    if factor <= 0.0:
        return "anull"
    f = float(factor)
    if 0.999 <= f <= 1.001:
        return "atempo=1.0"
    filters = []
    while f > 2.0:
        filters.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        filters.append("atempo=0.5")
        f /= 0.5
    filters.append(f"atempo={f:.6f}")
    return ",".join(filters)


def _enhanced_vspeed_run(self):
    """
    Seamless Constant Frame Rate (CFR) VideoSpeedAdjustWorker implementation.
    Fixes frame rate degradation (e.g. 30.00 fps -> 29.97 fps) and audio extraction for vocal removal by:
    1. Using MPEG-TS (.ts) intermediate video segments to eliminate container-level millisecond duration rounding gaps.
    2. Generating parallel speed-adjusted audio segments (.m4a) using atempo filter chain in a single FFmpeg call per segment.
    3. Strictly enforcing target Constant Frame Rate (-r {target_fps} and 90000 timescale).
    4. Concat-merging both CFR video and speed-adjusted audio via stream copy into temp_speed_adjusted.mp4.
    """
    temp_dir = None
    try:
        if getattr(self, "_is_cancelled", False) or (hasattr(self, "isInterruptionRequested") and self.isInterruptionRequested()):
            raise getattr(_mod, "OperationCancelled", RuntimeError)(
                "Video speed adjustment cancelled.")

        self.progress.emit("Applying audio-driven video timing adjustments...")
        self.progress_value.emit(0)

        raw_segments = getattr(self, "segments", None) or getattr(
            self, "segments_with_audio_duration", None) or []
        sorted_segments = sorted(
            raw_segments, key=lambda x: float(x.get("start", 0.0)))

        needs_adjustment = any(
            abs(float(seg.get("speed_factor", 1.0)) - 1.0) > 0.01
            for seg in sorted_segments
        )
        if not needs_adjustment:
            self.progress.emit(
                "No speed adjustment needed. All segments are synced.")
            self.progress_value.emit(100)
            self.finished.emit(self.video_path)
            return

        self.progress.emit("⚡ Adjusting speed and constructing segments...")
        self.progress_value.emit(5)

        import tempfile
        import shutil
        from utils import get_ffmpeg_path

        temp_dir = tempfile.mkdtemp(prefix="temp_speed_segments_")
        timestamp = int(time.time())
        output_path = os.path.abspath(f"temp_speed_adjusted_{timestamp}.mp4")

        video_input_path = self.video_path
        if not all(ord(c) < 128 for c in str(video_input_path)):
            try:
                ext = os.path.splitext(video_input_path)[1] or ".mp4"
                copied_path = os.path.join(temp_dir, f"source{ext}")
                shutil.copy2(video_input_path, copied_path)
                video_input_path = copied_path
            except Exception:
                video_input_path = self.video_path

        ffmpeg_bin = get_ffmpeg_path()
        ffprobe_bin = shutil.which("ffprobe") or "ffprobe"

        # Probe video dimensions and framerate
        w, h, fps, br = probe_video_dimensions(video_input_path)
        target_fps = float(fps or 30.0)
        if target_fps < 10.0 or target_fps > 120.0:
            target_fps = 30.0

        # Probe duration
        video_duration = 0.0
        try:
            cmd_dur = [
                ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", video_input_path
            ]
            res_dur = subprocess.run(
                cmd_dur, capture_output=True, text=True, timeout=10)
            if res_dur.returncode == 0 and res_dur.stdout.strip():
                video_duration = float(res_dur.stdout.strip())
        except Exception:
            pass
        if video_duration <= 0.0 and sorted_segments:
            video_duration = float(sorted_segments[-1].get("end", 0.0))

        # Check if source video contains an audio stream
        has_audio = _probe_file_has_audio(ffprobe_bin, video_input_path)

        # Build complete segment sequence including gap segments
        all_segments = []
        current_time = 0.0
        for seg in sorted_segments:
            s_start = float(seg.get("start", 0.0))
            s_end = float(seg.get("end", 0.0))
            if s_start < current_time:
                s_start = current_time
            if s_end <= s_start:
                continue
            if s_start > current_time:
                all_segments.append({
                    "start": current_time,
                    "end": s_start,
                    "speed_factor": 1.0
                })
            all_segments.append({
                "start": s_start,
                "end": s_end,
                "speed_factor": float(seg.get("speed_factor", 1.0)),
                "target_duration": seg.get("target_duration"),
                "audio_tempo_factor": seg.get("audio_tempo_factor", 1.0),
                "row": seg.get("row")
            })
            current_time = s_end

        if current_time < video_duration:
            all_segments.append({
                "start": current_time,
                "end": video_duration,
                "speed_factor": 1.0
            })

        self.progress.emit(
            f"⚡ Adjusting {len(all_segments)} total video segments (including gaps)...")

        # Get compression & export settings
        comp_enabled = _safe_get_worker_attr(self, "compress_enabled", None)
        if comp_enabled is None:
            v_cfg = settings_manager.get_export_video_config()
            comp_enabled = v_cfg.get("compress_enabled", True)
            v_quality = v_cfg.get("video_quality", "auto")
            v_crf = v_cfg.get("video_crf", 25)
            v_tb = v_cfg.get("target_bitrate", "3.2M")
            v_mb = v_cfg.get("max_bitrate", "4.5M")
            allow_upscale = v_cfg.get("allow_upscale", False)
            faststart = v_cfg.get("facebook_faststart", True)
        else:
            v_quality = _safe_get_worker_attr(self, "video_quality", "auto")
            v_crf = _safe_get_worker_attr(self, "video_crf", 25)
            v_tb = _safe_get_worker_attr(self, "target_bitrate", "3.2M")
            v_mb = _safe_get_worker_attr(self, "max_bitrate", "4.5M")
            allow_upscale = _safe_get_worker_attr(self, "allow_upscale", False)
            faststart = _safe_get_worker_attr(self, "facebook_faststart", True)

        tw, th = compute_target_dimensions(
            w, h, v_quality, allow_upscale=allow_upscale)
        hw_cfg = settings_manager.get_hardware_config()
        enc_args = build_facebook_video_encoder_args(
            video_encoder=hw_cfg.get("video_encoder", "cpu"),
            target_w=tw, target_h=th, crf=v_crf,
            target_bitrate=v_tb, max_bitrate=v_mb,
            source_bitrate=br,
            faststart=False,
            fps=target_fps
        )

        scale_filter = ""
        if (tw, th) != (w, h) and tw > 0 and th > 0:
            scale_filter = f",scale={tw}:{th}:flags=bicubic,setsar=1"

        new_table_times = []
        current_output_time = 0.0
        temp_v_segments = []
        temp_a_segments = []
        last_segment_error = ""

        total_segs = len(all_segments)
        for i, seg in enumerate(all_segments):
            if getattr(self, "_is_cancelled", False) or (hasattr(self, "isInterruptionRequested") and self.isInterruptionRequested()):
                op_cancelled = getattr(
                    _mod, "OperationCancelled", RuntimeError)
                raise op_cancelled("Video speed adjustment cancelled.")

            start_time = float(seg["start"])
            end_time = float(seg["end"])
            speed_factor = float(seg.get("speed_factor", 1.0))
            if speed_factor <= 0.0:
                speed_factor = 1.0

            orig_duration = max(0.01, end_time - start_time)
            new_duration = orig_duration / speed_factor
            setpts_value = 1.0 / speed_factor

            progress_pct = 5 + int((i / max(1, total_segs)) * 80)
            self.progress_value.emit(progress_pct)
            self.progress.emit(
                f"Processing segment {i+1}/{total_segs}: {start_time:.2f}s - {end_time:.2f}s (speed: {speed_factor:.2f}x)")

            # Use MPEG-TS (.ts) segment for video to prevent container duration rounding
            seg_v_file = os.path.join(temp_dir, f"segment_{i:04d}.ts")
            vf = f"setpts={setpts_value}*PTS,fps={target_fps}{scale_filter}"

            cmd = [
                ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
                "-ss", str(start_time), "-t", str(orig_duration),
                "-i", video_input_path,
                "-filter:v", vf
            ] + enc_args + [
                "-r", str(target_fps),
                "-an",
                "-video_track_timescale", "90000",
                seg_v_file
            ]

            seg_a_file = None
            if has_audio:
                seg_a_file = os.path.join(temp_dir, f"a_segment_{i:04d}.m4a")
                af = _build_atempo_filter_chain(speed_factor)
                cmd.extend([
                    "-vn",
                    "-filter:a", af,
                    "-c:a", "aac", "-b:a", "192k",
                    seg_a_file
                ])

            timeout = max(45, min(180, int(orig_duration * 3.0)))
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self._active_process = proc
            stdout, stderr = proc.communicate(timeout=timeout)
            self._active_process = None

            video_ok = (proc.returncode == 0 and os.path.exists(seg_v_file) and os.path.getsize(seg_v_file) > 0)
            audio_ok = (not has_audio) or (seg_a_file and os.path.exists(seg_a_file) and os.path.getsize(seg_a_file) > 0)

            if video_ok and audio_ok:
                actual_duration = _probe_file_media_duration(
                    ffprobe_bin, seg_v_file)
                if actual_duration <= 0.0:
                    actual_duration = new_duration

                if "row" in seg:
                    new_table_times.append({
                        "row": seg["row"],
                        "start": current_output_time,
                        "end": current_output_time + actual_duration,
                        "new_start": current_output_time,
                        "new_end": current_output_time + actual_duration,
                        "audio_tempo_factor": seg.get("audio_tempo_factor", 1.0)
                    })
                current_output_time += actual_duration
                temp_v_segments.append(seg_v_file)
                if has_audio and seg_a_file:
                    temp_a_segments.append(seg_a_file)
            else:
                last_segment_error = stderr or "Unknown ffmpeg segment error"
                self.progress.emit(
                    f"⚠️ Failed to process segment {i+1}, using original speed fallback")
                fallback_vf = f"setpts=1.0*PTS,fps={target_fps}{scale_filter}"
                fb_cmd = [
                    ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
                    "-ss", str(start_time), "-t", str(orig_duration),
                    "-i", video_input_path,
                    "-filter:v", fallback_vf
                ] + enc_args + [
                    "-r", str(target_fps),
                    "-an",
                    "-video_track_timescale", "90000",
                    seg_v_file
                ]
                if has_audio and seg_a_file:
                    fb_cmd.extend([
                        "-vn",
                        "-filter:a", "atempo=1.0",
                        "-c:a", "aac", "-b:a", "192k",
                        seg_a_file
                    ])
                fb_proc = subprocess.Popen(
                    fb_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                self._active_process = fb_proc
                fb_stdout, fb_stderr = fb_proc.communicate(timeout=timeout)
                self._active_process = None

                fb_video_ok = (fb_proc.returncode == 0 and os.path.exists(seg_v_file) and os.path.getsize(seg_v_file) > 0)
                fb_audio_ok = (not has_audio) or (seg_a_file and os.path.exists(seg_a_file) and os.path.getsize(seg_a_file) > 0)

                if fb_video_ok and fb_audio_ok:
                    actual_duration = _probe_file_media_duration(
                        ffprobe_bin, seg_v_file) or orig_duration
                    if "row" in seg:
                        new_table_times.append({
                            "row": seg["row"],
                            "start": current_output_time,
                            "end": current_output_time + actual_duration,
                            "new_start": current_output_time,
                            "new_end": current_output_time + actual_duration,
                            "audio_tempo_factor": 1.0
                        })
                    current_output_time += actual_duration
                    temp_v_segments.append(seg_v_file)
                    if has_audio and seg_a_file:
                        temp_a_segments.append(seg_a_file)

        if not temp_v_segments:
            raise RuntimeError(
                f"No segments were successfully processed.\n\nLast FFmpeg error:\n{last_segment_error}")

        self.progress.emit("📦 Merging all adjusted segments...")
        self.progress_value.emit(88)

        v_concat_file = os.path.join(temp_dir, "v_concat_list.txt")
        with open(v_concat_file, "w", encoding="utf-8", newline="\n") as f:
            for s_file in temp_v_segments:
                norm_p = os.path.abspath(s_file).replace(
                    "\\", "/").replace("'", "'\\''")
                f.write(f"file '{norm_p}'\n")

        can_mux_audio = has_audio and (len(temp_a_segments) == len(temp_v_segments)) and len(temp_a_segments) > 0

        if can_mux_audio:
            a_concat_file = os.path.join(temp_dir, "a_concat_list.txt")
            with open(a_concat_file, "w", encoding="utf-8", newline="\n") as f:
                for a_file in temp_a_segments:
                    norm_a = os.path.abspath(a_file).replace(
                        "\\", "/").replace("'", "'\\''")
                    f.write(f"file '{norm_a}'\n")

            concat_cmd = [
                ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
                "-f", "concat", "-safe", "0", "-i", v_concat_file,
                "-f", "concat", "-safe", "0", "-i", a_concat_file,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "copy",
                "-video_track_timescale", "90000"
            ]
        else:
            concat_cmd = [
                ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-nostats",
                "-f", "concat", "-safe", "0", "-i", v_concat_file,
                "-c", "copy",
                "-video_track_timescale", "90000"
            ]

        if faststart:
            concat_cmd.extend(["-movflags", "+faststart"])
        concat_cmd.append(output_path)

        merge_timeout = max(60, min(420, int(video_duration * 2.0)))
        m_proc = subprocess.Popen(
            concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self._active_process = m_proc
        m_out, m_err = m_proc.communicate(timeout=merge_timeout)
        self._active_process = None

        if m_proc.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError(
                f"Failed to merge adjusted segments: {m_err or 'unknown concat error'}")

        self.progress.emit("✓ Video speed adjustment completed!")
        self.progress_value.emit(100)
        self.timeline_updated.emit(new_table_times)
        self.finished.emit(output_path)

    except Exception as e:
        op_cancelled = getattr(_mod, "OperationCancelled", None)
        if op_cancelled and isinstance(e, op_cancelled):
            self.error.emit(str(e))
        else:
            self.error.emit(f"Video speed adjustment error: {e}")
    finally:
        self._active_process = None
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


if hasattr(_mod, "VideoSpeedAdjustWorker"):
    _mod.VideoSpeedAdjustWorker.run = _enhanced_vspeed_run


if hasattr(_mod, "ExportWorker"):
    _orig_export_init = _mod.ExportWorker.__init__

    def _enhanced_export_init(self, *args, **kwargs):
        if "original_video" in kwargs:
            self.actual_source_video = kwargs["original_video"]
        elif len(args) > 1:
            self.actual_source_video = args[1]
        _orig_export_init(self, *args, **kwargs)

    _mod.ExportWorker.__init__ = _enhanced_export_init

    _orig_export_run_command = _mod.ExportWorker._run_command

    def _enhanced_export_run_command(self, cmd, timeout=None, **popen_kwargs):
        try:
            # Vocal removal audio extraction safeguard:
            # Ensure extraction does not fail if edited_video lacks an audio stream
            if isinstance(cmd, list) and "-vn" in cmd and "-acodec" in cmd and "libmp3lame" in cmd and "-i" in cmd:
                try:
                    i_idx = cmd.index("-i")
                    in_video = cmd[i_idx + 1]
                    ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
                    if not _probe_file_has_audio(ffprobe_bin, in_video):
                        src_candidate = (
                            _safe_get_worker_attr(self, "actual_source_video", None)
                            or _safe_get_worker_attr(self, "source_video", None)
                        )
                        if src_candidate and os.path.exists(src_candidate) and _probe_file_has_audio(ffprobe_bin, src_candidate):
                            cmd = list(cmd)
                            cmd[i_idx + 1] = src_candidate
                            print(
                                f"[VOCAL REMOVAL] Audio extraction redirected from audio-less '{in_video}' to source '{src_candidate}'")
                except Exception as ex_ext:
                    print(f"[VOCAL REMOVAL] Audio extraction intercept notice: {ex_ext}")

            if isinstance(cmd, list) and "-map" in cmd and "0:v" in cmd and "-c:v" in cmd:
                comp_enabled = _safe_get_worker_attr(
                    self, "compress_enabled", None)
                if comp_enabled is None:
                    v_cfg = settings_manager.get_export_video_config()
                    comp_enabled = v_cfg.get("compress_enabled", True)
                    v_quality = v_cfg.get("video_quality", "auto")
                    v_crf = v_cfg.get("video_crf", 25)
                    v_tb = v_cfg.get("target_bitrate", "3.2M")
                    v_mb = v_cfg.get("max_bitrate", "4.5M")
                    faststart = v_cfg.get("facebook_faststart", True)
                    allow_upscale = v_cfg.get("allow_upscale", False)
                    target_ab = v_cfg.get("audio_bitrate", "96k")
                else:
                    v_quality = _safe_get_worker_attr(
                        self, "video_quality", "auto")
                    v_crf = _safe_get_worker_attr(self, "video_crf", 25)
                    v_tb = _safe_get_worker_attr(
                        self, "target_bitrate", "3.2M")
                    v_mb = _safe_get_worker_attr(self, "max_bitrate", "4.5M")
                    faststart = _safe_get_worker_attr(
                        self, "facebook_faststart", True)
                    allow_upscale = _safe_get_worker_attr(
                        self, "allow_upscale", False)
                    target_ab = _safe_get_worker_attr(
                        self, "audio_bitrate", "96k")

                if comp_enabled:
                    cmd = list(cmd)
                    v_in = _safe_get_worker_attr(self, "edited_video", None) or _safe_get_worker_attr(
                        self, "original_video", None)
                    if "-i" in cmd:
                        v_in = cmd[cmd.index("-i") + 1]
                    w, h, fps, br = probe_video_dimensions(v_in)
                    tw, th = compute_target_dimensions(
                        w, h, v_quality, allow_upscale=allow_upscale)

                    # Optimize audio bitrate
                    if "-b:a" in cmd:
                        ba_idx = cmd.index("-b:a")
                        if ba_idx + 1 < len(cmd):
                            cmd[ba_idx + 1] = str(target_ab or "96k")

                    # Check if input video is already scaled and compressed
                    # or if it was already processed by VideoSpeedAdjustWorker
                    has_edited_video = bool(
                        _safe_get_worker_attr(self, "edited_video", None))
                    already_compact = (
                        w == tw and h == th and 0 < br <= 2800000)

                    if has_edited_video or already_compact:
                        # Keep -c:v copy and add faststart flag
                        if faststart and "-movflags" not in cmd:
                            out_idx = len(cmd) - 1
                            cmd[out_idx:out_idx] = ["-movflags", "+faststart"]
                    else:
                        hw_cfg = settings_manager.get_hardware_config()
                        enc_args = build_facebook_video_encoder_args(
                            video_encoder=hw_cfg.get("video_encoder", "cpu"),
                            target_w=tw, target_h=th, crf=v_crf,
                            target_bitrate=v_tb, max_bitrate=v_mb,
                            source_bitrate=br,
                            faststart=faststart,
                            fps=fps
                        )

                        cv_idx = cmd.index("-c:v")
                        if cv_idx + 1 < len(cmd) and cmd[cv_idx + 1] == "copy":
                            cmd.pop(cv_idx + 1)
                        cmd.pop(cv_idx)

                        if (tw, th) != (w, h) and tw > 0 and th > 0:
                            scale_filter = [
                                "-vf", f"scale={tw}:{th}:flags=bicubic,setsar=1"]
                            cmd[cv_idx:cv_idx] = scale_filter + enc_args
                        else:
                            cmd[cv_idx:cv_idx] = enc_args

                        print(
                            f"[EXPORT] Optimizing video for Facebook {v_quality} ({tw}x{th}) @ CRF {v_crf} / {v_tb} (faststart={faststart})")
            elif isinstance(cmd, list) and "-movflags" not in cmd and any(isinstance(c, str) and "_duration_fixed_" in c for c in cmd):
                v_cfg = settings_manager.get_export_video_config()
                if v_cfg.get("facebook_faststart", True):
                    cmd = list(cmd)
                    out_idx = len(cmd) - 1
                    cmd[out_idx:out_idx] = ["-movflags", "+faststart"]
        except Exception as ex:
            print(f"[EXPORT] Compression mux intercept notice: {ex}")

        return _orig_export_run_command(self, cmd, timeout=timeout, **popen_kwargs)

    _mod.ExportWorker._run_command = _enhanced_export_run_command


_mod.VOXCPM2_ENABLED = True
_mod.get_hardware_config = settings_manager.get_hardware_config
_mod.probe_video_dimensions = probe_video_dimensions
_mod.compute_target_dimensions = compute_target_dimensions
_mod.build_facebook_video_encoder_args = build_facebook_video_encoder_args

globals().update(_mod.__dict__)
sys.modules[__name__] = _mod
