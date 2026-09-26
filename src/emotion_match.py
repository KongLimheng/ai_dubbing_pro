import os
import subprocess
import numpy as np

EMOTION_STYLE_PROMPTS = {
    "angry": "angry, intense, firm, sharp, emotional",
    "happy": "happy, cheerful, bright, energetic, smiling tone",
    "sad": "sad, soft, emotional, slightly slow, gentle",
    "gentle": "gentle, warm, calm, tender, soft",
    "calm": "calm, natural, steady, relaxed",
}

EMOTION_STYLE_TOKENS = {
    "smiling tone",
    "slightly deep",
    "slightly slow",
    "sad",
    "calm",
    "firm",
    "soft",
    "warm",
    "angry",
    "clear",
    "happy",
    "sharp",
    "sweet",
    "bright",
    "gentle",
    "steady",
    "tender",
    "intense",
    "relaxed",
    "cheerful",
    "confident",
    "emotional",
    "energetic",
}


def _split_prompt_parts(prompt_text):
    if not prompt_text:
        return []
    return [p.strip() for p in str(prompt_text).split(",") if p.strip()]


def _remove_style_parts(prompt_text):
    parts = _split_prompt_parts(prompt_text)
    return [p for p in parts if p.lower() not in EMOTION_STYLE_TOKENS]


def apply_voxcpm_emotion_style(voice_id, style_prompt):
    voice_text = str(voice_id or "").strip()
    style_text = str(style_prompt or "").strip().strip(",")

    if not style_text or not voice_text.lower().startswith("voxcpm2:"):
        return voice_id

    prefix, control = voice_text.split(":", 1)
    identity_parts = _remove_style_parts(control)
    style_parts = _split_prompt_parts(style_text)

    merged_parts = []
    seen = set()
    for part in identity_parts + style_parts:
        key = part.lower()
        if key not in seen:
            seen.add(key)
            merged_parts.append(part)

    final_control = ", ".join(merged_parts).strip() or "natural Khmer voice"
    return f"{prefix}:{final_control}"


def strip_voxcpm_emotion_style(voice_id):
    voice_text = str(voice_id or "").strip()
    if not voice_text.lower().startswith("voxcpm2:"):
        return voice_id

    prefix, control = voice_text.split(":", 1)
    kept_parts = _remove_style_parts(control)
    neutral_control = ", ".join(kept_parts).strip() or "natural Khmer voice"
    return f"{prefix}:{neutral_control}"


def _extract_pcm_segment(
    video_path, start_time, end_time, ffmpeg_path="ffmpeg"
):
    try:
        start_s = max(0.0, float(start_time or 0.0))
        end_s = float(end_time or 0.0)
        duration = max(0.1, end_s - start_s)
    except Exception:
        return None, 16000

    cmd = [
        ffmpeg_path,
        "-ss",
        f"{start_s:.3f}",
        "-i",
        video_path,
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-f",
        "s16le",
        "-",
    ]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout:
            return None, 16000
        audio = (
            np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32)
            / 32768.0
        )
        if audio.size < 800:
            return None, 16000
        return audio, 16000
    except Exception:
        return None, 16000


def _zero_crossing_rate(audio):
    if audio.size < 2:
        return 0.0
    signs = np.signbit(audio)
    return float(np.mean(signs[1:] != signs[:-1]))


def _spectral_centroid(audio, sample_rate):
    if audio.size < 512:
        return 0.0
    frame = audio[: min(audio.size, sample_rate * 6)]
    window = np.hanning(frame.size)
    spectrum = np.abs(np.fft.rfft(frame * window))
    total = float(np.sum(spectrum))
    if total <= 1e-9:
        return 0.0
    freqs = np.fft.rfftfreq(frame.size, d=1.0 / sample_rate)
    return float(np.sum(freqs * spectrum) / total)


def analyze_segment_emotion(
    video_path, start_time, end_time, ffmpeg_path="ffmpeg"
):
    audio, sample_rate = _extract_pcm_segment(
        video_path, start_time, end_time, ffmpeg_path
    )
    if audio is None:
        return {
            "emotion": "calm",
            "style_prompt": EMOTION_STYLE_PROMPTS["calm"],
            "confidence": 0.0,
            "reason": "audio extraction failed",
        }

    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio))))
    zcr = _zero_crossing_rate(audio)
    centroid = _spectral_centroid(audio, sample_rate)
    active_ratio = float(np.mean(np.abs(audio) > max(0.015, rms * 0.45)))

    if peak < 0.015 or rms < 0.004:
        emotion = "calm"
        confidence = 0.35
    elif rms > 0.075 and (centroid > 1500 or zcr > 0.105):
        emotion = "angry"
        confidence = 0.72
    elif rms > 0.045 and active_ratio > 0.42 and centroid > 1000:
        emotion = "happy"
        confidence = 0.62
    elif rms < 0.022 and centroid < 950:
        emotion = "sad"
        confidence = 0.58
    elif rms < 0.040 and zcr < 0.085:
        emotion = "gentle"
        confidence = 0.55
    else:
        emotion = "calm"
        confidence = 0.45

    return {
        "emotion": emotion,
        "style_prompt": EMOTION_STYLE_PROMPTS[emotion],
        "confidence": confidence,
        "reason": f"rms={rms:.3f}, peak={peak:.3f}, zcr={zcr:.3f}, centroid={centroid:.0f}, active={active_ratio:.2f}",
    }
