# -*- coding: utf-8 -*-
"""
workers module wrapper.
Loads native compiled bytecode from workers.pyc with cross-platform runtime support.
"""

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
    _GEMINI_TRANSCRIBE_PROMPT = (
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
    return _GEMINI_TRANSCRIBE_PROMPT


def _enhanced_transcribe_with_gemini(self, audio_path, api_key):
    from ai_clients import genai

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

        genai.configure(api_key=current_key, transport="rest")

        # Discover available models
        self.progress.emit("🔍 Checking available models...")
        try:
            available_models = [
                m.name for m in genai.list_models()
                if "generateContent" in getattr(m, "supported_generation_methods", [])
            ]
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
            audio_file = genai.upload_file(audio_path)

            while getattr(audio_file, "state", None) and getattr(audio_file.state, "name", "") == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)

            if getattr(audio_file, "state", None) and getattr(audio_file.state, "name", "") == "FAILED":
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
                    model = genai.GenerativeModel(candidate)
                    response = model.generate_content(
                        [audio_file, _GEMINI_TRANSCRIBE_PROMPT],
                        request_options={"timeout": 120, "retry": None}
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
            if audio_file:
                try:
                    genai.delete_file(audio_file.name)
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
        setattr(getattr(_mod, _w_cls_name), "_resolve_special_voice", _enhanced_resolve_special_voice)

_mod.VOXCPM2_ENABLED = True

globals().update(_mod.__dict__)
sys.modules[__name__] = _mod
