# -*- coding: utf-8 -*-
"""
FunASR helper utilities for local (offline) video/audio transcription.

This module is intentionally import-light at import time so the app can run even if
the optional `funasr` dependency is not installed. Callers should handle ImportError
messages raised by `transcribe_audio_to_segments`.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


def wav_duration_seconds(wav_path: str) -> float:
    with contextlib.closing(wave.open(wav_path, "rb")) as wf:
        frames = wf.getnframes()
        rate = wf.getframerate() or 1
        return float(frames) / float(rate)


def _ms_to_s(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value) / 1000.0
    except Exception:
        return None


def _sanitize_text(text: Any) -> str:
    if text is None:
        return ""
    cleaned = str(text).replace("\uFEFF", "")
    # FunASR may emit "<unk>" tokens for unknown pieces; drop them for cleaner subtitles.
    cleaned = re.sub(r"<\s*unk\s*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


@dataclass(frozen=True)
class FunASRConfig:
    asr_model: str = "paraformer-zh"
    vad_model: Optional[str] = "fsmn-vad"
    punc_model: Optional[str] = "ct-punc"
    spk_model: Optional[str] = None
    device: str = "cpu"
    model_hub: Optional[str] = None  # e.g. "ms" (ModelScope) or "hf" (HuggingFace)
    download_dir: Optional[str] = None  # where to cache model repos (optional)
    vad_max_single_segment_ms: int = 30000  # VAD max segment length (ms)


_MODEL_CACHE: Dict[FunASRConfig, Any] = {}
_VAD_CACHE: Dict[Tuple[str, str, Optional[str], Optional[str]], Any] = {}


_HF_DEFAULT_REPO_PREFIX = "funasr/"
_HF_MODEL_NAME_TO_REPO = {
    "paraformer-zh": "funasr/paraformer-zh",
    "paraformer-en": "funasr/paraformer-en",
    "paraformer-zh-streaming": "funasr/paraformer-zh-streaming",
    "conformer-en": "funasr/conformer-en",
    "fsmn-vad": "funasr/fsmn-vad",
    "ct-punc": "funasr/ct-punc",
    "ct-punc-c": "funasr/ct-punc-c",
    "cam++": "funasr/cam++",
    "funasr_conformer-en": "funasr/conformer-en",
    "funasr_paraformer-en": "funasr/paraformer-en",
    "funasr_paraformer-zh": "funasr/paraformer-zh",
    "funasr_ct-punc": "funasr/ct-punc",
    "funasr_fsmn-vad": "funasr/fsmn-vad",
}


def _emit_progress(progress_callback, percent: int, message: str) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(int(max(0, min(100, percent))), message)
    except Exception:
        pass


def _is_probably_local_path(value: str) -> bool:
    if not value:
        return False
    if os.path.isabs(value):
        return True
    if os.path.exists(value):
        return True
    # Windows drive-like "C:\..."
    return bool(re.match(r"^[a-zA-Z]:[\\/]", value))


def _resolve_hf_repo_id(model_name_or_repo: str) -> str:
    raw = str(model_name_or_repo or "").strip()
    if not raw:
        return ""
    if "/" in raw:
        return raw
    return _HF_MODEL_NAME_TO_REPO.get(raw, f"{_HF_DEFAULT_REPO_PREFIX}{raw}")


def _snapshot_download_with_progress(repo_id: str, local_dir: str, progress_callback=None, label: str = "model") -> str:
    """
    Download a HuggingFace repo snapshot and emit a best-effort percentage based on file count.
    """
    try:
        from huggingface_hub import snapshot_download  # type: ignore
    except Exception as e:
        raise ImportError(
            "huggingface_hub is required for showing download progress. Install: `pip install -U huggingface_hub`."
        ) from e

    try:
        from tqdm.auto import tqdm as base_tqdm  # type: ignore
    except Exception:
        base_tqdm = object  # type: ignore

    class _ProgressTqdm(base_tqdm):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            self._last_percent = -1
            super().__init__(*args, **kwargs)

        def update(self, n=1):
            out = super().update(n)
            total = getattr(self, "total", None)
            current = getattr(self, "n", None)
            if total and current is not None and total > 0:
                percent = int(round((float(current) / float(total)) * 100.0))
                if percent != self._last_percent:
                    self._last_percent = percent
                    _emit_progress(progress_callback, percent, f"Downloading {label}: {percent}%")
            return out

    _emit_progress(progress_callback, 1, f"Preparing download for {label}: {repo_id}")

    token = os.environ.get("HF_TOKEN") or None
    path = snapshot_download(
        repo_id=repo_id,
        local_dir=local_dir,
        local_dir_use_symlinks=False,
        resume_download=True,
        token=token,
        tqdm_class=_ProgressTqdm,
    )

    _emit_progress(progress_callback, 100, f"Downloaded {label}.")
    return path


def _ensure_models_downloaded(cfg: FunASRConfig, progress_callback=None) -> None:
    """
    Best-effort pre-download of FunASR dependencies so we can show a download %.

    Only implemented for HuggingFace (`model_hub='hf'`). For other hubs, FunASR will
    download internally without a reliable progress hook.
    """
    if (cfg.model_hub or "").lower() != "hf":
        return

    download_root = (cfg.download_dir or "").strip()
    if not download_root:
        # Prefer an app-local cache folder when present (so packaged installers can bundle models).
        try:
            app_local = os.path.join(os.getcwd(), "models", "funasr_hf_cache")
            if os.path.isdir(app_local):
                download_root = app_local
        except Exception:
            download_root = ""
    if not download_root:
        download_root = os.path.join(tempfile.gettempdir(), "aidubber_funasr_models")
    os.makedirs(download_root, exist_ok=True)

    # Help downstream libraries (FunASR / HF hub / transformers) reuse the same cache.
    os.environ.setdefault("HF_HOME", download_root)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(download_root, "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(download_root, "transformers"))

    def needs_download(name: str) -> Tuple[bool, str, str]:
        if not name or _is_probably_local_path(name):
            return False, "", ""
        repo_id = _resolve_hf_repo_id(name)
        if not repo_id:
            return False, "", ""
        local_dir = os.path.join(download_root, repo_id.replace("/", "__"))
        if os.path.isdir(local_dir) and os.listdir(local_dir):
            return False, repo_id, local_dir
        return True, repo_id, local_dir

    candidates: List[Tuple[str, str]] = [(cfg.asr_model, "ASR model")]
    if cfg.vad_model:
        candidates.append((cfg.vad_model, "VAD model"))
    if cfg.punc_model:
        candidates.append((cfg.punc_model, "Punctuation model"))
    if cfg.spk_model:
        candidates.append((cfg.spk_model, "Speaker model"))

    downloads: List[Tuple[str, str, str]] = []
    for name, label in candidates:
        should, repo_id, local_dir = needs_download(name)
        if should:
            downloads.append((repo_id, local_dir, label))
        elif repo_id and progress_callback:
            _emit_progress(progress_callback, 5, f"{label} already cached.")

    if not downloads:
        _emit_progress(progress_callback, 25, "✅ Local TSB models already cached (download complete).")
        return

    base_percent = 0
    span_percent = 25  # reserve 0-25% for downloading/caching model repos
    per_download_span = max(1, int(span_percent / max(1, len(downloads))))

    def download_one(repo_id: str, local_dir: str, label: str, slot_index: int) -> None:
        slot_start = base_percent + (slot_index * per_download_span)
        slot_span = per_download_span

        def scaled_callback(pct, msg=None):
            try:
                pct_int = int(pct)
            except Exception:
                pct_int = 0
            pct_int = max(0, min(100, pct_int))
            overall = int(round(slot_start + (pct_int / 100.0) * slot_span))
            message = msg or f"Downloading {label}: {pct_int}%"
            _emit_progress(progress_callback, overall, message)

        _snapshot_download_with_progress(repo_id, local_dir, progress_callback=scaled_callback, label=label)

    for idx, (repo_id, local_dir, label) in enumerate(downloads):
        download_one(repo_id, local_dir, label, idx)

    _emit_progress(progress_callback, 25, "✅ Download complete. Initializing Local TSB...")


def _local_dir_for_repo(download_root: str, repo_id: str) -> str:
    return os.path.join(download_root, repo_id.replace("/", "__"))


def _resolve_to_cached_path(cfg: FunASRConfig, model_name_or_path: Optional[str]) -> Optional[str]:
    """If model_hub=hf and we have a cached snapshot, return the local path to use with AutoModel."""
    raw = str(model_name_or_path or "").strip()
    if not raw or _is_probably_local_path(raw):
        return raw or None

    if (cfg.model_hub or "").lower() != "hf":
        return raw

    download_root = (cfg.download_dir or "").strip()
    if not download_root:
        try:
            app_local = os.path.join(os.getcwd(), "models", "funasr_hf_cache")
            if os.path.isdir(app_local):
                download_root = app_local
        except Exception:
            download_root = ""
    if not download_root:
        download_root = os.path.join(tempfile.gettempdir(), "aidubber_funasr_models")

    repo_id = _resolve_hf_repo_id(raw)
    local_dir = _local_dir_for_repo(download_root, repo_id)
    if os.path.isdir(local_dir) and os.listdir(local_dir):
        return local_dir

    # Also check alternative folder naming conventions
    for alt in (
        raw.replace("/", "__"),
        raw.replace("/", "_"),
        f"funasr__{raw.replace('funasr_', '').replace('funasr/', '')}",
        f"funasr_{raw.replace('funasr_', '').replace('funasr/', '')}",
    ):
        cand = os.path.join(download_root, alt)
        if os.path.isdir(cand) and os.listdir(cand):
            return cand

    return raw


def _get_or_create_model(cfg: FunASRConfig, *, progress_callback=None) -> Any:
    cached = _MODEL_CACHE.get(cfg)
    if cached is not None:
        return cached

    try:
        _emit_progress(progress_callback, 26, "Local TSB: importing engine...")
        import_started = time.perf_counter()
        # Importing `funasr` top-level can be very slow because it eagerly scans/imports
        # many submodules. Prefer a narrower import path when available.
        try:
            from funasr.auto import AutoModel  # type: ignore
        except Exception:
            from funasr import AutoModel  # type: ignore
        import_seconds = int(round(time.perf_counter() - import_started))
        _emit_progress(progress_callback, 26, f"Local TSB: import ready ({import_seconds}s).")
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "FunASR is not installed. Install it in your environment first, e.g. `pip install -U funasr`."
        ) from e

    asr_model = _resolve_to_cached_path(cfg, cfg.asr_model) or cfg.asr_model
    vad_model = _resolve_to_cached_path(cfg, cfg.vad_model) if cfg.vad_model else None
    punc_model = _resolve_to_cached_path(cfg, cfg.punc_model) if cfg.punc_model else None
    spk_model = _resolve_to_cached_path(cfg, cfg.spk_model) if cfg.spk_model else None

    kwargs: Dict[str, Any] = {"model": asr_model}
    if vad_model:
        kwargs["vad_model"] = vad_model
    if punc_model:
        kwargs["punc_model"] = punc_model
    if spk_model:
        kwargs["spk_model"] = spk_model

    # These kwargs vary across FunASR versions; add them only if supported.
    if cfg.device:
        kwargs["device"] = cfg.device
    if cfg.model_hub:
        kwargs["model_hub"] = cfg.model_hub

    # FunASR may do an update check on every init which adds latency/noise.
    # Prefer disabling unless the user explicitly wants it.
    kwargs["disable_update"] = True

    try:
        _emit_progress(progress_callback, 26, "Local TSB: loading model weights...")
        model = AutoModel(**kwargs)
    except TypeError:
        # Fallback for older versions without `device`/`model_hub` kwargs.
        kwargs.pop("disable_update", None)
        kwargs.pop("device", None)
        kwargs.pop("model_hub", None)
        model = AutoModel(**kwargs)

    _MODEL_CACHE[cfg] = model
    _emit_progress(progress_callback, 28, "Local TSB: model ready.")
    return model


def _get_or_create_vad_model(cfg: FunASRConfig, *, progress_callback=None) -> Any:
    """Create a standalone VAD model (fsmn-vad) that returns [[beg_ms, end_ms], ...]."""
    vad_name = (cfg.vad_model or "").strip() or "fsmn-vad"
    cache_key = (vad_name, str(cfg.device or "cpu"), str(cfg.model_hub or ""), str(cfg.download_dir or ""))
    cached = _VAD_CACHE.get(cache_key)
    if cached is not None:
        return cached

    _emit_progress(progress_callback, 26, "Local TSB: initializing VAD...")
    try:
        import_started = time.perf_counter()
        try:
            from funasr.auto import AutoModel  # type: ignore
        except Exception:
            from funasr import AutoModel  # type: ignore
        import_seconds = int(round(time.perf_counter() - import_started))
        _emit_progress(progress_callback, 26, f"Local TSB: VAD ready ({import_seconds}s).")
    except Exception as e:
        raise ImportError("FunASR is not installed for VAD.") from e

    model_id = _resolve_to_cached_path(cfg, vad_name) or vad_name
    kwargs: Dict[str, Any] = {"model": model_id, "device": cfg.device, "disable_update": True}
    if cfg.model_hub:
        kwargs["model_hub"] = cfg.model_hub
    try:
        vad_model = AutoModel(**kwargs)
    except TypeError:
        kwargs.pop("disable_update", None)
        kwargs.pop("device", None)
        kwargs.pop("model_hub", None)
        vad_model = AutoModel(**kwargs)

    _VAD_CACHE[cache_key] = vad_model
    return vad_model


def _iter_sentence_items(result_item: Dict[str, Any]) -> Iterable[Tuple[Optional[float], Optional[float], str]]:
    # Preferred: sentence_info per utterance (ms timestamps).
    sentence_info = result_item.get("sentence_info")
    if isinstance(sentence_info, list) and sentence_info:
        for sent in sentence_info:
            if not isinstance(sent, dict):
                continue
            start_s = _ms_to_s(sent.get("start"))
            end_s = _ms_to_s(sent.get("end"))
            text = _sanitize_text(sent.get("text"))
            if text:
                yield start_s, end_s, text
        return

    # Fallback: item-level start/end (ms).
    start_s = _ms_to_s(result_item.get("start"))
    end_s = _ms_to_s(result_item.get("end"))
    text = _sanitize_text(result_item.get("text"))
    if text and (start_s is not None or end_s is not None):
        yield start_s, end_s, text
        return

    # Fallback: word timestamps -> derive segment bounds.
    timestamps = result_item.get("timestamp")
    if isinstance(timestamps, list) and timestamps:
        first = timestamps[0] if isinstance(timestamps[0], list) and len(timestamps[0]) >= 2 else None
        last = timestamps[-1] if isinstance(timestamps[-1], list) and len(timestamps[-1]) >= 2 else None
        start_s = _ms_to_s(first[0]) if first else None
        end_s = _ms_to_s(last[1]) if last else None
        text = _sanitize_text(result_item.get("text"))
        if text:
            yield start_s, end_s, text
        return

    # Final fallback: text without timestamps.
    text = _sanitize_text(result_item.get("text"))
    if text:
        yield None, None, text


def _has_valid_timing(start_s: Any, end_s: Any, min_duration: float = 0.05) -> bool:
    try:
        if start_s is None or end_s is None:
            return False
        return float(end_s) - float(start_s) >= float(min_duration)
    except Exception:
        return False


def _append_segments_with_boundary_fallback(
    output: List[Dict[str, Any]],
    result: Any,
    *,
    boundary_start: float,
    boundary_end: float,
) -> None:
    """Append FunASR result segments, using a known audio boundary when timestamps are missing."""
    boundary_start = max(0.0, float(boundary_start or 0.0))
    boundary_end = max(boundary_start + 0.1, float(boundary_end or 0.0))
    found_text = False

    if isinstance(result, list):
        for item in result:
            if not isinstance(item, dict):
                continue
            for start_s, end_s, text in _iter_sentence_items(item):
                cleaned = _sanitize_text(text)
                if not cleaned:
                    continue
                found_text = True
                if _has_valid_timing(start_s, end_s):
                    output.append(
                        {
                            "start": boundary_start + float(start_s),
                            "end": min(boundary_end, boundary_start + float(end_s)),
                            "text": cleaned,
                        }
                    )
                else:
                    output.append(
                        {
                            "start": boundary_start,
                            "end": boundary_end,
                            "text": cleaned,
                        }
                    )

    if not found_text and isinstance(result, list) and result and isinstance(result[0], dict):
        fallback_text = _sanitize_text(result[0].get("text"))
        if fallback_text:
            output.append({"start": boundary_start, "end": boundary_end, "text": fallback_text})


def transcribe_audio_to_segments(
    audio_path: str,
    *,
    config: Optional[FunASRConfig] = None,
    sentence_timestamp: bool = True,
    batch_size_s: int = 300,
    progress_callback=None,
    chunk_seconds: float = 30.0,
) -> List[Dict[str, Any]]:
    """
    Transcribe an audio file and return app-compatible segments:
      [{'start': float, 'end': float, 'text': str}, ...]

    Notes:
    - FunASR timestamps are typically in milliseconds.
    - If timestamps are missing, we fall back to one whole-audio segment.
    """
    cfg = config or FunASRConfig()
    if progress_callback:
        try:
            progress_callback(24, "Local TSB: initializing model...")
        except Exception:
            pass
    # If requested, pre-download model repos with progress so the UI doesn't look frozen.
    _ensure_models_downloaded(cfg, progress_callback=progress_callback)
    _emit_progress(progress_callback, 26, "Local TSB: preparing pipeline...")

    # FunASR doesn't expose a stable progress callback. For a responsive UI we
    # chunk wav audio and report progress by time processed.
    if str(audio_path).lower().endswith(".wav") and chunk_seconds and chunk_seconds > 0:
        # Prefer VAD-based segmentation for accurate SRT timing when enabled.
        if cfg.vad_model:
            try:
                return _transcribe_wav_with_vad_segments(
                    audio_path,
                    cfg,
                    batch_size_s=batch_size_s,
                    sentence_timestamp=sentence_timestamp,
                    progress_callback=progress_callback,
                )
            except Exception as e:
                # Fall back to coarse chunking when VAD path fails, but surface a hint for debugging.
                _emit_progress(progress_callback, 28, f"Local TSB: VAD timing failed; falling back to chunking ({type(e).__name__}).")

    stop_event = threading.Event()

    def heartbeat():
        ticks = 0
        while not stop_event.wait(4.0):
            ticks += 1
            _emit_progress(
                progress_callback,
                26,
                f"Local TSB: preparing pipeline... (still working {ticks*4}s)",
            )

    hb_thread = None
    try:
        hb_thread = threading.Thread(target=heartbeat, name="funasr-init-heartbeat", daemon=True)
        hb_thread.start()
    except Exception:
        hb_thread = None

    try:
        model = _get_or_create_model(cfg, progress_callback=progress_callback)
    finally:
        stop_event.set()
        if hb_thread is not None:
            with contextlib.suppress(Exception):
                hb_thread.join(timeout=0.2)
    if progress_callback:
        try:
            progress_callback(30, "Local TSB: starting transcription...")
        except Exception:
            pass

    if str(audio_path).lower().endswith(".wav") and chunk_seconds and chunk_seconds > 0:
        return _transcribe_wav_chunked(
            model,
            audio_path,
            config=cfg,
            batch_size_s=batch_size_s,
            sentence_timestamp=sentence_timestamp,
            chunk_seconds=float(chunk_seconds),
            progress_callback=progress_callback,
        )

    # Non-wav fallback: single-pass transcription (no % progress).
    if progress_callback:
        try:
            progress_callback(25, "Local TSB: transcribing...")
        except Exception:
            pass

    res, _model_used = _funasr_generate_with_fallback(
        model,
        cfg,
        audio_path,
        batch_size_s=batch_size_s,
        sentence_timestamp=sentence_timestamp,
        progress_callback=progress_callback,
    )

    segments: List[Dict[str, Any]] = []
    if isinstance(res, list):
        for item in res:
            if not isinstance(item, dict):
                continue
            for start_s, end_s, text in _iter_sentence_items(item):
                segments.append(
                    {
                        "start": float(start_s) if start_s is not None else 0.0,
                        "end": float(end_s) if end_s is not None else 0.0,
                        "text": text,
                    }
                )

    # If we got timestamps but some ends are 0, try to make them non-decreasing.
    if segments:
        last_end = 0.0
        for seg in segments:
            start = float(seg.get("start", 0.0) or 0.0)
            end = float(seg.get("end", 0.0) or 0.0)
            if start < last_end:
                start = last_end
            if end <= start:
                end = start + 1.0
            seg["start"] = start
            seg["end"] = end
            last_end = end
        return segments

    # Last resort: a single segment covering the whole wav duration.
    duration = wav_duration_seconds(audio_path)
    text = ""
    if isinstance(res, list) and res and isinstance(res[0], dict):
        text = _sanitize_text(res[0].get("text"))
    if not text:
        text = "(no speech detected)"
    return [{"start": 0.0, "end": max(0.1, float(duration)), "text": text}]


def _normalize_vad_segments(vad_output: Any) -> List[Tuple[int, int]]:
    """
    Normalize VAD output into a list of (beg_ms, end_ms).
    Expected formats seen in the wild:
      - [[beg, end], [beg, end], ...]
      - [{'value': [[beg,end], ...]}]
      - [{'segments': [[beg,end], ...]}]
    """
    segments = []

    def add_pair(pair):
        if not isinstance(pair, list) or len(pair) < 2:
            return
        try:
            beg = int(pair[0])
            end = int(pair[1])
        except Exception:
            return
        if end > beg:
            segments.append((beg, end))

    if isinstance(vad_output, list) and vad_output:
        if all(isinstance(x, list) for x in vad_output):
            for pair in vad_output:
                add_pair(pair)
        elif isinstance(vad_output[0], dict):
            payload = vad_output[0].get("value") or vad_output[0].get("segments") or vad_output[0].get("vad") or None
            if isinstance(payload, list):
                for pair in payload:
                    add_pair(pair)

    return segments


def _transcribe_wav_with_vad_segments(
    wav_path: str,
    cfg: FunASRConfig,
    *,
    batch_size_s: int,
    sentence_timestamp: bool,
    progress_callback=None,
) -> List[Dict[str, Any]]:
    """
    High-accuracy timing path:
      1) Run standalone VAD to get speech segment time ranges in ms
      2) Slice wav per speech segment
      3) Run ASR without VAD (avoid VAD pipeline timestamp KeyError)
      4) Offset timestamps by VAD begin time
    """
    _emit_progress(progress_callback, 26, "Local TSB: running VAD for timing...")
    vad_model = _get_or_create_vad_model(cfg, progress_callback=progress_callback)

    vad_res = vad_model.generate(input=wav_path)
    vad_segments = _normalize_vad_segments(vad_res)
    if not vad_segments:
        _emit_progress(progress_callback, 28, "Local TSB: no speech detected by VAD.")
        return []

    # Free VAD model before loading ASR model to prevent GPU VRAM exhaustion!
    try:
        import torch
        if torch.cuda.is_available():
            del vad_model
            _VAD_CACHE.clear()
            torch.cuda.empty_cache()
    except Exception:
        pass

    # Build an ASR-only model (no vad_model) but keep punctuation if requested.
    asr_only_cfg = FunASRConfig(
        asr_model=cfg.asr_model,
        vad_model=None,
        punc_model=cfg.punc_model,
        spk_model=cfg.spk_model,
        device=cfg.device,
        model_hub=cfg.model_hub,
        download_dir=cfg.download_dir,
        vad_max_single_segment_ms=cfg.vad_max_single_segment_ms,
    )
    asr_model = _get_or_create_model(asr_only_cfg, progress_callback=progress_callback)

    with contextlib.closing(wave.open(wav_path, "rb")) as wf:
        rate = wf.getframerate() or 16000

    tmp_dir = ensure_tmp_dir = os.path.join(os.path.dirname(wav_path), "temp_funasr_vad")
    os.makedirs(tmp_dir, exist_ok=True)

    out_segments: List[Dict[str, Any]] = []
    total = len(vad_segments)
    for idx, (beg_ms, end_ms) in enumerate(vad_segments):
        # Respect max_single_segment_time by splitting long VAD segments.
        max_ms = int(cfg.vad_max_single_segment_ms or 30000)
        sub_ranges = []
        cursor = beg_ms
        while cursor < end_ms:
            sub_end = min(end_ms, cursor + max_ms)
            sub_ranges.append((cursor, sub_end))
            cursor = sub_end

        for sub_idx, (sub_beg, sub_end) in enumerate(sub_ranges):
            percent = int(round(30 + (55.0 * ((idx + (sub_idx / max(1, len(sub_ranges)))) / max(1, total)))))
            _emit_progress(progress_callback, percent, f"Local TSB: segment {idx+1}/{total}...")

            start_frame = int((sub_beg / 1000.0) * rate)
            end_frame = int((sub_end / 1000.0) * rate)
            frame_count = max(0, end_frame - start_frame)
            slice_path = os.path.join(tmp_dir, f"vad_{idx:04d}_{sub_idx:02d}.wav")
            _write_wav_slice(wav_path, slice_path, start_frame=start_frame, frame_count=frame_count)

            try:
                try:
                    res, _used = _funasr_generate_with_fallback(
                        asr_model,
                        asr_only_cfg,
                        slice_path,
                        batch_size_s=batch_size_s,
                        sentence_timestamp=sentence_timestamp,
                        progress_callback=progress_callback,
                    )
                    _append_segments_with_boundary_fallback(
                        out_segments,
                        res,
                        boundary_start=float(sub_beg) / 1000.0,
                        boundary_end=float(sub_end) / 1000.0,
                    )
                except Exception as exc:
                    _emit_progress(
                        progress_callback,
                        percent,
                        f"Local TSB: skipped VAD segment {idx+1}/{total} ({type(exc).__name__}).",
                    )
            finally:
                with contextlib.suppress(Exception):
                    os.remove(slice_path)

    if not out_segments:
        return []

    out_segments.sort(key=lambda s: (float(s.get("start", 0.0) or 0.0), float(s.get("end", 0.0) or 0.0)))
    last_end = 0.0
    for seg in out_segments:
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", 0.0) or 0.0)
        if start < last_end:
            start = last_end
        if end <= start:
            end = start + 0.5
        seg["start"] = start
        seg["end"] = end
        seg["text"] = _sanitize_text(seg.get("text"))
        last_end = end

    return [seg for seg in out_segments if seg.get("text")]


def _write_wav_slice(
    src_path: str,
    dst_path: str,
    *,
    start_frame: int,
    frame_count: int,
) -> Tuple[int, int]:
    with contextlib.closing(wave.open(src_path, "rb")) as src:
        params = src.getparams()
        src.setpos(max(0, int(start_frame)))
        frames = src.readframes(max(0, int(frame_count)))

    with contextlib.closing(wave.open(dst_path, "wb")) as dst:
        dst.setparams(params)
        dst.writeframes(frames)

    return params.framerate or 16000, len(frames)


def _transcribe_wav_chunked(
    model: Any,
    wav_path: str,
    *,
    config: Optional[FunASRConfig] = None,
    batch_size_s: int,
    sentence_timestamp: bool,
    chunk_seconds: float,
    progress_callback=None,
) -> List[Dict[str, Any]]:
    duration = wav_duration_seconds(wav_path)
    if duration <= 0.05:
        return []

    chunk_seconds = max(5.0, float(chunk_seconds))
    total_chunks = max(1, int(math.ceil(duration / chunk_seconds)))

    out_segments: List[Dict[str, Any]] = []

    tmp_dir = os.path.join(os.path.dirname(wav_path), "temp_funasr_chunks")
    os.makedirs(tmp_dir, exist_ok=True)

    with contextlib.closing(wave.open(wav_path, "rb")) as wf:
        rate = wf.getframerate() or 16000
        total_frames = wf.getnframes()

    frames_per_chunk = int(rate * chunk_seconds)

    cfg = config or FunASRConfig()
    for chunk_index in range(total_chunks):
        chunk_start_frame = chunk_index * frames_per_chunk
        if chunk_start_frame >= total_frames:
            break

        chunk_end_frame = min(total_frames, (chunk_index + 1) * frames_per_chunk)
        chunk_frame_count = max(0, chunk_end_frame - chunk_start_frame)
        chunk_start_s = float(chunk_start_frame) / float(rate)
        chunk_end_s = float(chunk_end_frame) / float(rate)

        # Progress range reserved for chunk loop: ~30% -> ~85%
        percent = int(round(30 + (55.0 * (chunk_index / max(1, total_chunks)))))
        if progress_callback:
            try:
                progress_callback(percent, f"Local TSB: {chunk_index+1}/{total_chunks} chunks... ({percent}%)")
            except Exception:
                pass

        chunk_path = os.path.join(tmp_dir, f"chunk_{chunk_index:04d}.wav")
        _write_wav_slice(wav_path, chunk_path, start_frame=chunk_start_frame, frame_count=chunk_frame_count)

        try:
            res, model = _funasr_generate_with_fallback(
                model,
                cfg,
                chunk_path,
                batch_size_s=batch_size_s,
                sentence_timestamp=sentence_timestamp,
                progress_callback=progress_callback,
            )

            _append_segments_with_boundary_fallback(
                out_segments,
                res,
                boundary_start=chunk_start_s,
                boundary_end=chunk_end_s,
            )
        finally:
            with contextlib.suppress(Exception):
                os.remove(chunk_path)

    if progress_callback:
        try:
            progress_callback(90, "Local TSB: finalizing...")
        except Exception:
            pass

    # Normalize monotonic timings.
    if not out_segments:
        return []

    out_segments.sort(key=lambda s: (float(s.get("start", 0.0) or 0.0), float(s.get("end", 0.0) or 0.0)))
    last_end = 0.0
    for seg in out_segments:
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", 0.0) or 0.0)
        if start < last_end:
            start = last_end
        if end <= start:
            end = start + 1.0
        seg["start"] = start
        seg["end"] = end
        seg["text"] = _sanitize_text(seg.get("text"))
        last_end = end

    return [seg for seg in out_segments if seg.get("text")]


def _funasr_generate_with_fallback(
    model: Any,
    cfg: FunASRConfig,
    audio_path: str,
    *,
    batch_size_s: int,
    sentence_timestamp: bool,
    progress_callback=None,
) -> Tuple[Any, Any]:
    """
    Run `model.generate` but gracefully recover from known FunASR pipelines that
    crash when timestamp outputs are missing (e.g. VAD pipeline KeyError: 'timestamp').

    Returns `(result, model_used)` where model_used may switch to a fallback AutoModel.
    """
    try:
        try:
            return (
                model.generate(
                    input=audio_path,
                    batch_size_s=batch_size_s,
                    sentence_timestamp=bool(sentence_timestamp),
                ),
                model,
            )
        except TypeError:
            return (model.generate(input=audio_path, batch_size_s=batch_size_s), model)
    except KeyError as e:
        if str(e).strip("'\"") != "timestamp":
            raise

        # Fallback: disable VAD/PUNC if present to avoid inference_with_vad() path.
        if cfg.vad_model or cfg.punc_model:
            _emit_progress(progress_callback, 30, "Local TSB: VAD timestamps missing; retrying without VAD/PUNC...")
            fallback_cfg = FunASRConfig(
                asr_model=cfg.asr_model,
                vad_model=None,
                punc_model=None,
                spk_model=cfg.spk_model,
                device=cfg.device,
                model_hub=cfg.model_hub,
                download_dir=cfg.download_dir,
            )
            fallback_model = _get_or_create_model(fallback_cfg, progress_callback=progress_callback)
            try:
                return (
                    fallback_model.generate(
                        input=audio_path,
                        batch_size_s=batch_size_s,
                        sentence_timestamp=bool(sentence_timestamp),
                    ),
                    fallback_model,
                )
            except TypeError:
                return (fallback_model.generate(input=audio_path, batch_size_s=batch_size_s), fallback_model)

        raise
