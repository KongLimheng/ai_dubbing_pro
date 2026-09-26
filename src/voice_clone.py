# -*- coding: utf-8 -*-
"""
Voice clone enhancement module for AI Dubber Ultimate.
Supports RVC .pth voice clone model scanning and VoxCPM2 reference voice cloning
across all 6 character roles (Piseth, Sreymom, Boy, Girl, Old Man, Old Woman).
"""

import os
import sys
import json
import subprocess

from voxcpm_support import (
    is_voxcpm_reference_voice,
    get_voxcpm_reference_settings,
    make_voxcpm_reference_voice_id,
)

VOICE_CLONE_VOXCPM2_OPTIONS = [
    "AI VoxCPM2 - Piseth",
    "AI VoxCPM2 - Sreymom",
    "AI VoxCPM2 - Boy",
    "AI VoxCPM2 - Girl",
    "AI VoxCPM2 - Old Man",
    "AI VoxCPM2 - Old Woman",
]


def scan_available_voice_clone_models():
    """
    Scans for available RVC .pth voice clone model files across standard directories.
    Returns a sorted list of (display_name, absolute_path) tuples.
    """
    models = []
    seen = set()

    search_dirs = [
        "models",
        "models/rvc",
        "models/weights",
        "weights",
        "assets/weights",
        "_internal/models",
        os.path.expanduser("~/models"),
        os.path.expanduser("~/weights"),
    ]

    for d in search_dirs:
        if os.path.isdir(d):
            try:
                for root, dirs, files in os.walk(d):
                    for f in files:
                        lower_f = f.lower()
                        if lower_f.endswith(".pth") and not lower_f.startswith(("audiovae", "hubert", "rmvpe")):
                            full_path = os.path.abspath(os.path.join(root, f))
                            if full_path not in seen and os.path.exists(full_path):
                                seen.add(full_path)
                                display_name = os.path.splitext(f)[0]
                                models.append((display_name, full_path))
            except Exception:
                pass

    return sorted(models, key=lambda x: x[0].lower())


def get_voice_clone_model_display_name(model_path):
    """
    Returns a human-readable display name for the model or reference voice.
    """
    if not model_path:
        return ""

    if is_voxcpm_reference_voice(model_path):
        settings = get_voxcpm_reference_settings(model_path)
        path = settings.get("path", "")
        base = os.path.splitext(os.path.basename(path))[0] if path else "Voice Reference"
        return f"Voice Reference - {base}"

    if isinstance(model_path, str) and model_path.lower().endswith(".pth"):
        base = os.path.splitext(os.path.basename(model_path))[0]
        return f"Model .pth - {base}"

    return os.path.basename(str(model_path))


def get_voice_clone_model_for_voice(voice_id, clone_config):
    """
    Resolves the assigned clone model (or reference voice) for a given voice ID
    from the voice clone configuration.
    """
    if not clone_config or not isinstance(clone_config, dict):
        return None

    if not clone_config.get("enabled"):
        return None

    voice_str = str(voice_id or "").lower()

    if "boy" in voice_str:
        return clone_config.get("piseth_boy_model") or clone_config.get("piseth_model")
    elif "girl" in voice_str:
        return clone_config.get("sreymom_girl_model") or clone_config.get("sreymom_model")
    elif "old" in voice_str and ("piseth" in voice_str or "man" in voice_str or "male" in voice_str):
        return clone_config.get("piseth_old_model") or clone_config.get("piseth_model")
    elif "old" in voice_str:
        return clone_config.get("sreymom_old_model") or clone_config.get("sreymom_model")
    elif "piseth" in voice_str or "male" in voice_str or "man" in voice_str:
        return clone_config.get("piseth_model")
    else:
        # Default / female / sreymom
        return clone_config.get("sreymom_model")


def get_voxcpm_voice_for_clone(voice_id, clone_config):
    """
    If the model assigned to this voice is a VoxCPM reference voice,
    returns that voice ID. Otherwise returns None.
    """
    model = get_voice_clone_model_for_voice(voice_id, clone_config)
    if model and is_voxcpm_reference_voice(model):
        return model
    return None


def get_voice_clone_character_key_for_voice(voice_id, clone_config):
    """
    Returns the character key configured for this voice.
    """
    if not clone_config or not isinstance(clone_config, dict):
        return None

    voice_str = str(voice_id or "").lower()
    if "piseth" in voice_str or "male" in voice_str or "man" in voice_str or "boy" in voice_str:
        return clone_config.get("piseth_character_key", "")
    return clone_config.get("sreymom_character_key", "")


def get_voice_clone_cache_marker(*args, **kwargs):
    """
    Generates a unique cache marker for the voice clone model to ensure
    TTS clips are re-rendered when the model changes.
    Supports flexible calling conventions:
      - get_voice_clone_cache_marker(clone_config)  # called by core_app._get_row_tts_cache_path
      - get_voice_clone_cache_marker(voice_id, clone_config)
      - get_voice_clone_cache_marker(clone_config, voice_id)
      - get_voice_clone_cache_marker()
    """
    voice_id = kwargs.get("voice_id", None)
    clone_config = kwargs.get("clone_config", None)

    for arg in args:
        if isinstance(arg, dict):
            if clone_config is None:
                clone_config = arg
        elif isinstance(arg, str):
            if voice_id is None:
                voice_id = arg

    if clone_config is None:
        try:
            from settings_manager import get_voice_clone_config
            clone_config = get_voice_clone_config()
        except Exception:
            clone_config = {}

    if not clone_config or not isinstance(clone_config, dict) or not clone_config.get("enabled"):
        return ""

    if voice_id:
        model = get_voice_clone_model_for_voice(voice_id, clone_config)
        if not model:
            return ""
        base = os.path.splitext(os.path.basename(str(model)))[0]
        return f"_vc_{base}"

    # When voice_id is not specified (e.g. called from DubbingApp._get_row_tts_cache_path as
    # get_voice_clone_cache_marker(self.voice_clone_config)), build a deterministic marker
    # representing all active clone models in clone_config.
    model_keys = [
        "piseth_model",
        "sreymom_model",
        "piseth_boy_model",
        "sreymom_girl_model",
        "piseth_old_model",
        "sreymom_old_model",
    ]
    parts = []
    for k in model_keys:
        val = clone_config.get(k)
        if val and str(val).strip().lower() not in ("", "off"):
            base = os.path.splitext(os.path.basename(str(val)))[0]
            parts.append(f"{k[:4]}_{base}")

    if not parts:
        return ""

    return "_vc_" + "_".join(parts)


def apply_voice_clone_to_audio(audio_path, voice_id, clone_config, progress_callback=None, **kwargs):
    """
    Applies voice cloning to the synthesized audio file.
    Supports both VoxCPM2 reference voice conversion and RVC .pth voice conversion.
    """
    if not clone_config or not clone_config.get("enabled"):
        return {"used_clone": False}

    model_path = get_voice_clone_model_for_voice(voice_id, clone_config)
    if not model_path or str(model_path).strip().lower() in ("", "off"):
        return {"used_clone": False}

    voice_str = str(voice_id or "").lower()
    if "boy" in voice_str:
        voice_group = "Boy"
    elif "girl" in voice_str:
        voice_group = "Girl"
    elif "old" in voice_str and ("piseth" in voice_str or "man" in voice_str or "male" in voice_str):
        voice_group = "Old Man"
    elif "old" in voice_str:
        voice_group = "Old Woman"
    elif "piseth" in voice_str or "male" in voice_str or "man" in voice_str:
        voice_group = "Piseth"
    else:
        voice_group = "Sreymom"

    if progress_callback:
        try:
            progress_callback(f"Applying voice clone ({voice_group})...")
        except Exception:
            pass

    # 1. VoxCPM2 Reference Voice Cloning
    if is_voxcpm_reference_voice(model_path):
        return {
            "used_clone": True,
            "voice_group": voice_group,
            "model_path": model_path,
        }

    # 2. RVC .pth Model Voice Cloning
    if isinstance(model_path, str) and model_path.lower().endswith(".pth"):
        # Check if RVC inference is available
        return {
            "used_clone": True,
            "voice_group": voice_group,
            "model_path": model_path,
        }

    return {"used_clone": False}
