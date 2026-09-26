# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _progress_writer(percent: Any, message: str | None = None) -> None:
    try:
        pct = int(percent)
    except Exception:
        pct = 0
    pct = max(0, min(100, pct))
    msg = (message or "").replace("\r", " ").replace("\n", " ").strip()
    sys.stdout.write(f"PROGRESS|{pct}|{msg}\n")
    sys.stdout.flush()


def main() -> int:
    # Ensure stdout can carry Unicode JSON back to the GUI even on Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", required=True)
    parser.add_argument("--model", default="paraformer-zh")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--hub", default="hf")
    parser.add_argument("--vad", default="1")
    parser.add_argument("--punc", default="1")
    parser.add_argument("--chunk", default="30")
    parser.add_argument("--max-segment-ms", default="30000")
    args = parser.parse_args()

    # When packaged with PyInstaller, helper scripts may land under `_internal/`.
    # Ensure we can import the sibling `FunASR.py` from either the script directory
    # or the app root.
    try:
        script_dir = os.path.abspath(os.path.dirname(__file__))
        parent_dir = os.path.abspath(os.path.join(script_dir, os.pardir))
        funasr_py_here = os.path.join(script_dir, "FunASR.py")
        if os.path.exists(funasr_py_here) and script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        funasr_py = os.path.join(parent_dir, "FunASR.py")
        if os.path.exists(funasr_py) and parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
    except Exception:
        pass

    wav_path = args.wav
    if not os.path.exists(wav_path):
        sys.stderr.write(f"ERROR: wav not found: {wav_path}\n")
        return 2

    try:
        chunk_seconds = float(args.chunk)
    except Exception:
        chunk_seconds = 30.0
    try:
        vad_max_single_segment_ms = int(float(args.max_segment_ms))
    except Exception:
        vad_max_single_segment_ms = 30000
    vad_max_single_segment_ms = max(1000, vad_max_single_segment_ms)

    vad_enabled = str(args.vad).strip().lower() not in {"0", "false", "no", "off"}
    punc_enabled = str(args.punc).strip().lower() not in {"0", "false", "no", "off"}

    # Resolve device 'auto' to 'cuda:0' or 'cpu' to prevent PyTorch parse error
    device = str(args.device or "cpu").strip().lower()
    if device in ("auto", ""):
        try:
            import torch
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    elif device == "cuda":
        device = "cuda:0"

    # Normalize model name (e.g. 'funasr_conformer-en' -> 'conformer-en')
    model_name = str(args.model or "paraformer-zh").strip()
    if model_name.startswith("funasr_"):
        model_name = model_name[7:]
    elif model_name.startswith("funasr:"):
        model_name = model_name[7:]

    # Warm up CUDA context early (first CUDA init can take ~1 minute on some systems).
    if device.startswith("cuda"):
        try:
            import torch  # type: ignore

            gpu_name = ""
            if torch.cuda.is_available():
                try:
                    gpu_name = str(torch.cuda.get_device_name(0) or "")
                except Exception:
                    gpu_name = ""
            _progress_writer(18, f"CUDA warmup... {'GPU=' + gpu_name if gpu_name else ''}".strip())
            # Initialize CUDA context and do a tiny allocation.
            if torch.cuda.is_available():
                _ = torch.empty((1,), device="cuda")
            _progress_writer(22, "CUDA warmup done.")
        except Exception as e:
            _progress_writer(22, f"CUDA warmup skipped: {type(e).__name__}: {e}")

    try:
        from FunASR import FunASRConfig, transcribe_audio_to_segments
    except Exception as e:
        sys.stderr.write(f"ERROR: failed to import FunASR.py: {e}\n")
        return 3

    cfg = FunASRConfig(
        asr_model=model_name,
        vad_model="fsmn-vad" if vad_enabled else None,
        punc_model="ct-punc" if punc_enabled else None,
        device=device,
        model_hub=str(args.hub or "hf"),
        vad_max_single_segment_ms=vad_max_single_segment_ms,
        # Prefer app-local HF cache so offline installers / portable builds can reuse
        # pre-fetched models (including VAD/PUNC) and avoid permission issues.
        download_dir=(
            os.path.join(os.getcwd(), "models", "funasr_hf_cache")
            if os.path.isdir(os.path.join(os.getcwd(), "models", "funasr_hf_cache"))
            else None
        ),
    )

    _progress_writer(5, f"Starting Local TSB subprocess ({cfg.asr_model})...")
    segments = transcribe_audio_to_segments(
        wav_path,
        config=cfg,
        progress_callback=_progress_writer,
        chunk_seconds=chunk_seconds,
    )

    sys.stdout.write("RESULT|" + json.dumps(segments, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
