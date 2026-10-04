# -*- coding: utf-8 -*-
"""
Standalone Batch Video Runner for AI Dubber Ultimate.
Executes an isolated video dubbing job (transcription, speech analysis, video speed sync,
TTS synthesis, Demucs vocal removal, background audio mixing, and video muxing)
in a dedicated subprocess and working directory with 100% parity to Single Video Export.
Streams real-time progress tokens (PROGRESS:pct:status, STATUS:msg, DONE:path, ERROR:msg)
and maintains persistent, millisecond-accurate job log files.
"""

import os
import sys
import json
import argparse
import re
import traceback
from datetime import datetime

# Ensure src directory is in sys.path
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(errors="replace", line_buffering=True)


class LogStreamTee:
    """Tees a stream (stdout/stderr) to both its original destination and a persistent log file."""

    def __init__(self, stream, log_path, prefix=""):
        self.stream = stream
        self.log_path = log_path
        self.prefix = prefix
        self.buffer = ""

    def write(self, text):
        if self.stream:
            try:
                self.stream.write(text)
                self.stream.flush()
            except Exception:
                pass
        if self.log_path:
            self.buffer += text
            if "\n" in self.buffer:
                lines = self.buffer.split("\n")
                self.buffer = lines[-1]
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                try:
                    with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                        for line in lines[:-1]:
                            if line.strip():
                                f.write(f"[{ts}] {self.prefix}{line}\n")
                except Exception:
                    pass

    def flush(self):
        if self.stream:
            try:
                self.stream.flush()
            except Exception:
                pass
        if self.log_path and self.buffer.strip():
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            try:
                with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                    f.write(f"[{ts}] {self.prefix}{self.buffer}\n")
            except Exception:
                pass
            self.buffer = ""

    def reconfigure(self, **kwargs):
        if hasattr(self.stream, "reconfigure"):
            self.stream.reconfigure(**kwargs)


class JobLogger:
    """Structured logger writing to both stdout and a persistent job log file."""

    def __init__(self, log_path=None):
        self.log_path = log_path
        if self.log_path:
            log_dir = os.path.dirname(os.path.abspath(self.log_path))
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)

    def _write_file(self, level, msg):
        if not self.log_path:
            return
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with open(self.log_path, "a", encoding="utf-8", errors="replace") as f:
                f.write(f"[{ts}] [{level}] {msg}\n")
        except Exception:
            pass

    def info(self, msg):
        self._write_file("INFO", msg)

    def warning(self, msg):
        self._write_file("WARN", msg)

    def error(self, msg):
        self._write_file("ERROR", msg)

    def progress(self, pct, msg):
        print(f"PROGRESS:{pct}:{msg}", flush=True)
        self._write_file(f"PROGRESS {pct}%", msg)

    def status(self, msg):
        print(f"STATUS:{msg}", flush=True)
        self._write_file("STATUS", msg)


def sanitize_tts_text(text: str) -> str:
    """Removes non-speech brackets and stray tags matching Single Video Export."""
    clean = re.sub(r'\[voice:[^\]]+\]', '', str(text or ''))
    clean = re.sub(r'\[char:[^\]]+\]', '', clean)
    clean = re.sub(r'[^\w\s\u1780-\u17FF.,!?។៕៖ៗ៘៙៚…\-]', '', clean)
    return clean.strip()


def parse_srt_timestamp(ts_str):
    try:
        ts_str = str(ts_str).strip().replace(",", ".")
        parts = ts_str.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(ts_str)
    except Exception:
        return 0.0


def parse_srt_file(srt_path):
    if not srt_path or not os.path.exists(srt_path):
        return []
    try:
        with open(srt_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        print(
            f"[RUNNER WARN] Failed to read SRT {srt_path}: {e}", file=sys.stderr)
        return []

    # Use core_app's parse_srt to properly detect [voice:...] tags and characters
    try:
        from core_app import DubbingApp
        app_dummy = DubbingApp.__new__(DubbingApp)
        segments = app_dummy.parse_srt(content)
        if segments:
            return segments
    except Exception as e:
        print(
            f"[RUNNER DEBUG] Fallback to regex srt parser: {e}", file=sys.stderr)

    text = content.replace("```srt", "").replace(
        "```", "").replace("\r\n", "\n").replace("\r", "\n").strip()
    segments = []
    pattern = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3})\s*[\r\n]+(.*?)(?=(?:\r?\n\s*(?:\d+\s+)?\d{1,2}:\d{2}:\d{2}[,\.]\d{1,3}\s*-->|\Z))",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        s_str, e_str, c_text = m.group(1), m.group(2), m.group(3).strip()
        if c_text:
            c_text = re.sub(r"\n+\d+$", "", c_text).strip()
            s_time = parse_srt_timestamp(s_str)
            e_time = parse_srt_timestamp(e_str)
            segments.append({
                "start": s_time,
                "end": e_time,
                "text": c_text,
            })
    return segments


def run_job(spec):
    job_id = spec.get("job_id", 1)
    video_path = spec.get("video_path", "")
    srt_path = spec.get("srt_path", None)
    timeline_segments = spec.get("timeline_segments", None)
    voice_id = spec.get(
        "voice_id", "km-KH-SreymomNeural") or "km-KH-SreymomNeural"
    pitch = spec.get("pitch", "0") or "0"
    rate = spec.get("rate", "0%") or "0%"
    eco_enabled = bool(spec.get("eco_enabled", False))
    echo_intensity = int(spec.get("echo_intensity", 50))
    output_path = spec.get("output_path", "")
    remove_vocal = bool(spec.get("remove_vocal", False))
    use_demucs = bool(spec.get("use_demucs", remove_vocal))
    background_percent = int(spec.get("background_percent", 30))
    ai_voice_percent = int(spec.get("ai_voice_percent", 100))
    auto_video_sync = bool(spec.get("auto_video_sync", True))
    preserve_speed = bool(spec.get("preserve_speed", False))
    fit_audio = bool(spec.get("fit_audio", not auto_video_sync))
    log_file = spec.get("log_file", None)
    video_quality = str(spec.get("video_quality", "auto") or "auto")
    video_crf = int(spec.get("video_crf", 25))
    compress_enabled = bool(spec.get("compress_enabled", True))
    facebook_faststart = bool(spec.get("facebook_faststart", True))
    allow_upscale = bool(spec.get("allow_upscale", False))
    audio_bitrate = str(spec.get("audio_bitrate", "96k") or "96k")

    # Initialize Logger
    if not log_file:
        out_dir = os.path.dirname(os.path.abspath(
            output_path)) if output_path else _src_dir
        logs_dir = os.path.join(out_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = os.path.join(logs_dir, f"batch_job_{job_id}_{ts_str}.log")

    logger = JobLogger(log_file)

    # Install Tee on stdout and stderr to capture everything into the log file
    sys.stdout = LogStreamTee(sys.stdout, log_file, prefix="")
    sys.stderr = LogStreamTee(sys.stderr, log_file, prefix="[STDERR] ")

    logger.info("=" * 60)
    logger.info(f"🚀 AI DUBBER BATCH RUNNER - JOB #{job_id}")
    logger.info(f"Video Input: {video_path}")
    logger.info(f"SRT Input: {srt_path}")
    logger.info(f"Output Target: {output_path}")
    logger.info(
        f"Voice: {voice_id} | Pitch: {pitch} | Rate: {rate} | Echo: {eco_enabled} ({echo_intensity}%)")
    logger.info(
        f"Demucs Vocal Removal: {remove_vocal} (BG: {background_percent}% | Voice: {ai_voice_percent}%)")
    logger.info(
        f"Auto Video Speed Sync: {auto_video_sync} | Preserve Speed: {preserve_speed} | Fit Audio: {fit_audio}")
    logger.info(
        f"Facebook Video Quality: {video_quality} | Compression: {'ON' if compress_enabled else 'OFF'} | CRF: {video_crf} | FastStart: {facebook_faststart}")
    logger.info(f"Log File: {log_file}")
    logger.info("=" * 60)

    if not video_path or not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        raise FileNotFoundError(f"Video file not found: {video_path}")

    logger.progress(5, "Initializing Qt and worker environment...")

    from PyQt5.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    from workers import ExportWorker, TranscriptionWorker, SegmentAudioAnalysisWorker, VideoSpeedAdjustWorker
    from utils import resolve_voice_and_pitch, get_balanced_tts_rate_details

    # Step 1: Subtitle segments
    segments = []
    if timeline_segments and isinstance(timeline_segments, list):
        segments = list(timeline_segments)
        logger.progress(10, f"Loaded {len(segments)} timeline segments...")
        logger.info(
            f"Loaded {len(segments)} timeline segments from specification.")
    elif srt_path and os.path.exists(srt_path):
        segments = parse_srt_file(srt_path)
        logger.progress(10, f"Parsed {len(segments)} SRT subtitles...")
        logger.info(
            f"Parsed {len(segments)} subtitle segments from {srt_path}.")
    else:
        # Need AI transcription
        logger.progress(10, "Transcribing speech with AI...")
        logger.info("Starting Gemini AI speech transcription...")
        tx_worker = TranscriptionWorker.__new__(TranscriptionWorker)
        tx_worker.model_name = "gemini-3.5-flash"

        class _DummySignal:
            def emit(self, val):
                logger.info(f"[TRANSCRIPTION] {val}")

        tx_worker.progress = _DummySignal()
        tx_worker.api_key = spec.get("api_key", None)
        segments = tx_worker.transcribe_with_gemini(
            video_path, tx_worker.api_key)
        logger.progress(
            15, f"AI Transcription complete ({len(segments)} segments)...")
        logger.info(
            f"AI Transcription completed with {len(segments)} segments.")

    if not segments:
        logger.error(
            f"No subtitle segments found for {os.path.basename(video_path)}")
        raise ValueError(
            f"No subtitle segments found for {os.path.basename(video_path)}")

    # Step 2: Build table data with text sanitization & adaptive speech rates
    table_data = []
    default_fallback_voice = "km-KH-SreymomNeural"
    effective_voice_id = voice_id if (
        voice_id and voice_id != "__BATCH_USE_SRT_TAGS__") else default_fallback_voice

    logger.info("--- SEGMENT TABLE & ADAPTIVE SPEECH RATE ANALYSIS ---")
    for idx, seg in enumerate(segments):
        s_start = float(seg.get("start", 0.0))
        s_end = float(seg.get("end", s_start + 2.0))
        s_raw_text = str(seg.get("text", "")).strip()
        if s_raw_text.endswith("..."):
            s_raw_text = s_raw_text[:-3].strip()

        # Sanitize text
        s_text = sanitize_tts_text(s_raw_text)
        if not s_text:
            s_text = s_raw_text

        s_raw_voice = seg.get("voice") or seg.get("character")
        if not s_raw_voice or s_raw_voice == "__BATCH_USE_SRT_TAGS__":
            s_raw_voice = effective_voice_id

        s_raw_pitch = seg.get("pitch")
        if s_raw_pitch is None or str(s_raw_pitch).strip() in ("", "0"):
            s_raw_pitch = pitch if (pitch and str(
                pitch).strip() not in ("", "0")) else "+0Hz"
        else:
            s_raw_pitch = str(s_raw_pitch).strip()
            if not s_raw_pitch.endswith("Hz") and not s_raw_pitch.endswith("%"):
                try:
                    val = int(s_raw_pitch)
                    s_raw_pitch = f"{val:+d}Hz"
                except ValueError:
                    pass

        s_resolved_voice, s_resolved_pitch = resolve_voice_and_pitch(
            s_raw_voice, s_raw_pitch)

        # Adaptive Balanced Speech Rate (matching Single Video Export)
        available_time = max(0.1, s_end - s_start - 0.1)
        base_rate_str = seg.get("rate") or rate or "+0%"
        rate_details = get_balanced_tts_rate_details(
            text=s_text,
            expected_duration=available_time,
            base_rate_str=base_rate_str,
            voice_id=s_resolved_voice
        )
        s_rate = rate_details["rate_str"]

        s_vol = float(seg.get("volume", 1.0))
        s_eco = seg.get("eco_enabled", eco_enabled)
        s_echo_int = seg.get("echo_intensity", echo_intensity)

        table_data.append({
            "start": s_start,
            "end": s_end,
            "text": s_text,
            "pitch": s_resolved_pitch,
            "rate": s_rate,
            "volume": s_vol,
            "voice": s_resolved_voice,
            "character": str(seg.get("character") or s_resolved_voice),
            "lock_speed_enabled": False,
            "locked_rate": "",
            "eco_enabled": s_eco,
            "echo_intensity": s_echo_int,
        })

        preview = s_text.replace("\n", " ")[:35]
        logger.info(
            f"  [Seg #{idx+1:03d}] {s_start:6.2f}s -> {s_end:6.2f}s ({s_end-s_start:4.2f}s) | "
            f"Chars: {len(s_text):3d} | Density: {rate_details['chars_per_second']:4.1f} c/s | "
            f"Rate: {s_rate:5s} | Voice: {s_resolved_voice.split('-')[-1][:12]} | Text: '{preview}'"
        )

    # Step 3: Audio Analysis & Video Speed Sync (Parity with Single Video Export)
    video_to_use = video_path
    if auto_video_sync:
        logger.progress(
            15, "Analyzing audio durations for video speed sync...")
        logger.info(
            "Initializing SegmentAudioAnalysisWorker for speech timing measurement...")

        rows_data = []
        for idx, row in enumerate(table_data):
            rows_data.append({
                "row": idx,
                "start": row["start"],
                "end": row["end"],
                "text": row["text"],
                "voice_id": row["voice"],
                "character": row.get("character") or row["voice"],
                "pitch_str": row["pitch"],
                "rate_str": row["rate"],
            })

        analysis_worker = SegmentAudioAnalysisWorker(
            rows_data=rows_data,
            tts_mode="EdgeTTS",
            temp_prefix="batch_speed_audio",
            locked_rate_str="",
            skip_voxcpm_analysis_generation=False
        )

        analysis_result = [None]
        analysis_error = [None]

        def on_analysis_progress(val):
            if isinstance(val, str) and val.strip():
                logger.info(f"[AUDIO-ANALYSIS] {val.strip()}")

        def on_analysis_progress_val(val):
            scaled = 15 + int(val * 0.08)
            logger.progress(scaled, f"Analyzing speech timing ({val}%)...")

        def on_analysis_done(data):
            analysis_result[0] = list(data) if data else []
            logger.info(
                f"[AUDIO-ANALYSIS] Completed! Analyzed {len(analysis_result[0])} segment clips.")
            app.quit()

        def on_analysis_err(err):
            analysis_error[0] = str(err)
            logger.warning(f"[AUDIO-ANALYSIS] Notice/Error: {err}")
            app.quit()

        analysis_worker.progress.connect(on_analysis_progress)
        analysis_worker.progress_value.connect(on_analysis_progress_val)
        analysis_worker.finished.connect(on_analysis_done)
        analysis_worker.error.connect(on_analysis_err)

        analysis_worker.start()
        app.exec_()

        if analysis_result[0]:
            segments_data = analysis_result[0]
            logger.progress(
                23, "Adjusting video speed to match speech cadence...")
            logger.info(
                "Initializing VideoSpeedAdjustWorker to adjust video playback speed...")

            speed_worker = VideoSpeedAdjustWorker(
                video_path=video_path,
                segments_with_audio_duration=segments_data
            )
            speed_worker.video_quality = video_quality
            speed_worker.video_crf = video_crf
            speed_worker.compress_enabled = compress_enabled
            speed_worker.facebook_faststart = facebook_faststart
            speed_worker.allow_upscale = allow_upscale
            speed_worker.audio_bitrate = audio_bitrate

            speed_result_video = [video_path]
            speed_updated_timeline = [None]
            speed_error = [None]

            def on_speed_progress(val):
                if isinstance(val, str) and val.strip():
                    logger.info(f"[VIDEO-SPEED] {val.strip()}")

            def on_speed_progress_val(val):
                scaled = 23 + int(val * 0.07)
                logger.progress(
                    scaled, f"Synchronizing video speed ({val}%)...")

            def on_speed_timeline_updated(new_times):
                speed_updated_timeline[0] = list(
                    new_times) if new_times else []
                logger.info(
                    f"[VIDEO-SPEED] Received synchronized timeline: {len(speed_updated_timeline[0])} rows updated.")

            def on_speed_done(adjusted_video):
                if adjusted_video and os.path.exists(adjusted_video):
                    speed_result_video[0] = adjusted_video
                    logger.info(
                        f"[VIDEO-SPEED] Created speed-adjusted video: {adjusted_video}")
                app.quit()

            def on_speed_err(err):
                speed_error[0] = str(err)
                logger.warning(f"[VIDEO-SPEED] Notice/Error: {err}")
                app.quit()

            speed_worker.progress.connect(on_speed_progress)
            speed_worker.progress_value.connect(on_speed_progress_val)
            speed_worker.timeline_updated.connect(on_speed_timeline_updated)
            speed_worker.finished.connect(on_speed_done)
            speed_worker.error.connect(on_speed_err)

            speed_worker.start()
            app.exec_()

            # Apply synchronized timeline to table_data
            if speed_updated_timeline[0]:
                for item in speed_updated_timeline[0]:
                    r = item.get("row")
                    if r is not None and 0 <= r < len(table_data):
                        s_val = item.get("start") if "start" in item else item.get("new_start")
                        e_val = item.get("end") if "end" in item else item.get("new_end")
                        if s_val is not None:
                            table_data[r]["start"] = float(s_val)
                        if e_val is not None:
                            table_data[r]["end"] = float(e_val)

            video_to_use = speed_result_video[0]
            preserve_speed = True
            fit_audio = False
            logger.info(
                f"✅ Auto Video Speed Sync successful! Video to mux: {video_to_use}")
            logger.info(
                f"   Speech will play at 100% natural unaltered speed (preserve_speed={preserve_speed}, fit_audio={fit_audio}).")
        else:
            logger.warning(
                "Audio analysis produced no data; falling back to speech retiming mode.")
            preserve_speed = False
            fit_audio = True
    else:
        logger.info(
            f"Auto video sync disabled by config; running direct speech retiming mode (fit_audio={fit_audio}).")
        preserve_speed = False
        fit_audio = True

    # Prepare output dir
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if remove_vocal:
        logger.progress(
            30, f"Exporting with Demucs vocal removal (BG: {background_percent}% | Voice: {ai_voice_percent}%)...")
        logger.info(
            f"[CONFIG] Demucs vocal removal ENABLED: Background={background_percent}%, AI Voice={ai_voice_percent}%, Sync={'ON' if fit_audio else 'OFF'}")
    elif fit_audio:
        logger.progress(
            30, f"Exporting {len(table_data)} clips with Speech Timing Sync...")
        logger.info(
            f"[CONFIG] Exporting {len(table_data)} clips with Speech Timing Sync (Auto-Retime: ON)...")
    else:
        logger.progress(
            30, f"Exporting {len(table_data)} clips at 100% natural speech rate...")
        logger.info(
            f"[CONFIG] Exporting {len(table_data)} clips at 100% natural speech rate (Auto-Retime: OFF, Video Sync: ACTIVE)...")

    # Step 4: Run ExportWorker
    worker = ExportWorker(
        table_data=table_data,
        original_video=video_path,
        output_path=output_path,
        voice_id=effective_voice_id,
        edited_video=video_to_use if video_to_use != video_path else None,
        remove_vocal_on_export=remove_vocal,
        use_demucs=use_demucs,
        background_volume_percent=background_percent,
        ai_voice_volume_percent=ai_voice_percent,
        preserve_table_speed=preserve_speed,
        fit_generated_audio_to_timeline=fit_audio,
    )
    worker.lock_speed_enabled = False
    worker.locked_rate = ""
    worker.video_quality = video_quality
    worker.video_crf = video_crf
    worker.compress_enabled = compress_enabled
    worker.facebook_faststart = facebook_faststart
    worker.allow_upscale = allow_upscale
    worker.audio_bitrate = audio_bitrate

    export_error = [None]

    def on_export_progress(*args):
        if not args:
            return
        val = args[0]
        if isinstance(val, (int, float)):
            # Scale 0-100 to 30-95
            scaled = 30 + int(val * 0.65)
            logger.progress(scaled, f"Dubbing audio & video ({int(val)}%)...")
        elif isinstance(val, str):
            clean_str = val.strip()
            if clean_str:
                logger.status(clean_str)

    def on_export_finished():
        logger.progress(98, "Finalizing video file...")
        logger.info(
            "[EXPORT] Worker finished synthesizing, mixing, and muxing.")
        app.quit()

    def on_export_error(err_msg):
        export_error[0] = str(err_msg)
        logger.error(f"[EXPORT ERROR] {err_msg}")
        app.quit()

    worker.progress.connect(on_export_progress)
    worker.finished.connect(on_export_finished)
    worker.error.connect(on_export_error)

    worker.start()
    app.exec_()

    if export_error[0]:
        raise RuntimeError(export_error[0])

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        logger.error(
            f"Export finished but output file is missing or empty: {output_path}")
        raise RuntimeError(
            f"Export finished but output file is missing or empty: {output_path}")

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(
        f"✅ EXPORT SUCCESSFUL! Target: {output_path} ({file_size_mb:.2f} MB)")
    logger.progress(100, "Export completed successfully!")
    print(f"DONE:{output_path}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="AI Dubber Batch Video Runner")
    parser.add_argument("--job-file", required=True,
                        help="Path to job specification JSON file")
    args = parser.parse_args()

    if not os.path.exists(args.job_file):
        print(f"ERROR:Job file not found: {args.job_file}", flush=True)
        sys.exit(1)

    try:
        with open(args.job_file, "r", encoding="utf-8") as f:
            spec = json.load(f)
        run_job(spec)
        sys.exit(0)
    except Exception as e:
        err_msg = str(e) or type(e).__name__
        print(f"ERROR:{err_msg}", flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
