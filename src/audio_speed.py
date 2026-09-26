import os
import subprocess
import tempfile

VOXCPM_SAFE_TAIL_SECONDS = 0.8


def rate_to_tempo_factor(rate_str):
    try:
        cleaned = str(rate_str or "").replace("%", "").replace("+", "").strip()
        value = int(cleaned) if cleaned else 0
    except Exception:
        return 1.0

    value = max(-50, min(100, value))
    return max(0.5, min(2.0, 1.0 + (value / 100.0)))


def build_atempo_filter(tempo_factor):
    try:
        remaining = float(tempo_factor or 1.0)
    except Exception:
        return "atempo=1.0"

    if remaining <= 0:
        return "atempo=1.0"

    filters = []
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5

    filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters)


def apply_audio_tempo(file_path, rate_str, ffmpeg_path="ffmpeg", label=""):
    tempo_factor = rate_to_tempo_factor(rate_str)
    if abs(tempo_factor - 1.0) < 0.01:
        return False
    if not file_path or not os.path.exists(file_path):
        return False

    output_dir = os.path.dirname(os.path.abspath(file_path)) or os.getcwd()
    suffix = os.path.splitext(file_path)[1] or ".mp3"

    temp_fd, temp_path = tempfile.mkstemp(
        prefix="tempo_", suffix=suffix, dir=output_dir
    )
    os.close(temp_fd)

    try:
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            file_path,
            "-af",
            build_atempo_filter(tempo_factor),
            "-q:a",
            "2",
            temp_path,
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=flags,
            timeout=120,
        )
        if (
            result.returncode == 0
            and os.path.exists(temp_path)
            and os.path.getsize(temp_path) > 100
        ):
            os.replace(temp_path, file_path)
            print(
                f"[VOXCPM SPEED] Applied {rate_str} ({tempo_factor:.2f}x) to {label}"
            )
            return True
        else:
            error_text = (
                result.stderr.decode("utf-8", errors="ignore")[:200]
                if result.stderr
                else ""
            )
            print(
                f"[VOXCPM SPEED] Failed to apply {rate_str} to {label}: {error_text or 'unknown ffmpeg error'}"
            )
            return False
    except Exception as exc:
        print(f"[VOXCPM SPEED] Error applying {rate_str} to {label}: {exc}")
        return False
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def pad_audio_tail(file_path, ffmpeg_path="ffmpeg", pad_seconds=0.35, label=""):
    """Append a short silent tail so players do not clip the last spoken word."""
    if not file_path or not os.path.exists(file_path):
        return False

    try:
        pad_seconds = max(0.05, min(2.0, float(pad_seconds or 0.35)))
    except Exception:
        pad_seconds = 0.35

    output_dir = os.path.dirname(os.path.abspath(file_path)) or os.getcwd()
    suffix = os.path.splitext(file_path)[1] or ".mp3"

    temp_fd, temp_path = tempfile.mkstemp(
        prefix="tailpad_", suffix=suffix, dir=output_dir
    )
    os.close(temp_fd)

    try:
        cmd = [
            ffmpeg_path,
            "-y",
            "-i",
            file_path,
            "-af",
            f"apad=pad_dur={pad_seconds:.3f}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            temp_path,
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=flags,
            timeout=120,
        )
        if (
            result.returncode == 0
            and os.path.exists(temp_path)
            and os.path.getsize(temp_path) > 100
        ):
            os.replace(temp_path, file_path)
            print(f"[AUDIO TAIL] Added {pad_seconds:.2f}s safe tail to {label}")
            return True
        else:
            error_text = (
                result.stderr.decode("utf-8", errors="ignore")[:200]
                if result.stderr
                else ""
            )
            print(
                f"[AUDIO TAIL] Failed to add tail to {label}: {error_text or 'unknown ffmpeg error'}"
            )
            return False
    except Exception as exc:
        print(f"[AUDIO TAIL] Error adding tail to {label}: {exc}")
        return False
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
