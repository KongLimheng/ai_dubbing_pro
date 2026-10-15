# -*- coding: utf-8 -*-
"""
VoxCPM2 integration and runtime support module.
Provides reference voice ID encoding/decoding, prompt presets, status detection,
and inference pipeline for VoxCPM2 Text-to-Speech and voice cloning.
"""

import os
import sys
import json
import shutil
import subprocess

VOXCPM2_ENABLED = True

# Prompt presets for character roles in VoxCPM2
VOXCPM_PROMPT_PRESETS = {
    "female": [
        ("ធម្មតា / Normal", "A natural, clear, expressive female voice speaking fluent Khmer."),
        ("រំភើប / Excited", "An energetic, happy, expressive young female voice speaking fluent Khmer."),
        ("ក្រៀមក្រំ / Sad", "A gentle, emotional, somber female voice speaking fluent Khmer."),
        ("ខ្សឹប / Whisper", "A soft, intimate, whispered female voice speaking fluent Khmer."),
        ("រៀបរាប់ / Storyteller", "A captivating, warm, narrative female voice telling a story in Khmer."),
    ],
    "male": [
        ("ធម្មតា / Normal", "A natural, calm, confident male voice speaking fluent Khmer."),
        ("ម៉ឺងម៉ាត់ / Serious", "A deep, authoritative, serious male voice speaking fluent Khmer."),
        ("រំភើប / Excited", "An enthusiastic, energetic, expressive male voice speaking fluent Khmer."),
        ("រៀបរាប់ / Storyteller", "A resonant, engaging, narrative male voice telling a story in Khmer."),
        ("ខឹង / Angry", "An intense, harsh, angry male voice speaking fluent Khmer."),
    ],
    "boy": [
        ("ធម្មតា / Normal", "A lively, innocent, clear young boy voice speaking fluent Khmer."),
        ("រំភើប / Excited", "An energetic, playful young boy voice speaking fluent Khmer."),
    ],
    "girl": [
        ("ធម្មតា / Normal", "A sweet, cute, youthful young girl voice speaking fluent Khmer."),
        ("រំភើប / Excited", "A cheerful, bright young girl voice speaking fluent Khmer."),
    ],
    "old_man": [
        ("ធម្មតា / Normal", "A wise, raspy, warm elderly grandfather voice speaking fluent Khmer."),
        ("រៀបរាប់ / Storyteller", "An aged, deep, traditional storytelling grandfather voice in Khmer."),
    ],
    "old_woman": [
        ("ធម្មតា / Normal", "A gentle, kind, elderly grandmother voice speaking fluent Khmer."),
        ("រំភើប / Emotional", "A touching, emotional grandmother voice speaking fluent Khmer."),
    ],
}

# Standard built-in VoxCPM voice options for dropdown selection
VOXCPM_BUILTIN_VOICES = [
    ("AI VoxCPM2 - Female (Sreymom / Normal)", "voxcpm:female:normal", "A natural, clear, expressive female voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Female (Storyteller)", "voxcpm:female:storyteller", "A captivating, warm, narrative female voice telling a story in Khmer."),
    ("AI VoxCPM2 - Female (Excited)", "voxcpm:female:excited", "An energetic, happy, expressive young female voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Female (Sad)", "voxcpm:female:sad", "A gentle, emotional, somber female voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Female (Whisper)", "voxcpm:female:whisper", "A soft, intimate, whispered female voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Male (Piseth / Normal)", "voxcpm:male:normal", "A natural, calm, confident male voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Male (Authoritative)", "voxcpm:male:serious", "A deep, authoritative, serious male voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Male (Storyteller)", "voxcpm:male:storyteller", "A resonant, engaging, narrative male voice telling a story in Khmer."),
    ("AI VoxCPM2 - Male (Excited)", "voxcpm:male:excited", "An enthusiastic, energetic, expressive male voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Male (Angry)", "voxcpm:male:angry", "An intense, harsh, angry male voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Boy (Playful)", "voxcpm:boy:normal", "A lively, innocent, clear young boy voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Girl (Sweet / Cute)", "voxcpm:girl:normal", "A sweet, cute, youthful young girl voice speaking fluent Khmer."),
    ("AI VoxCPM2 - Old Man (Storyteller)", "voxcpm:old_man:storyteller", "An aged, deep, traditional storytelling grandfather voice in Khmer."),
    ("AI VoxCPM2 - Old Woman (Gentle)", "voxcpm:old_woman:normal", "A gentle, kind, elderly grandmother voice speaking fluent Khmer."),
]


def resolve_voxcpm_voice_preset(voice_id):
    """
    Resolves a voice ID into a VoxCPM prompt preset dictionary.
    Returns:
        dict with keys: 'role', 'style', 'control_prompt', 'display_name', 'voice_id'
    """
    if not isinstance(voice_id, str):
        return {}
    v = voice_id.strip()
    low = v.lower()

    # Check exact match in VOXCPM_BUILTIN_VOICES
    for label, vid, prompt in VOXCPM_BUILTIN_VOICES:
        if low == vid.lower():
            parts = vid.split(":")
            role = parts[1] if len(parts) > 1 else "female"
            style = parts[2] if len(parts) > 2 else "normal"
            return {
                "role": role,
                "style": style,
                "control_prompt": prompt,
                "display_name": label,
                "voice_id": vid,
            }

    # Check general pattern voxcpm:<role> or voxcpm:<role>:<style>
    for prefix in ("voxcpm2:", "voxcpm:"):
        if low.startswith(prefix):
            remainder = low[len(prefix):].strip()
            parts = remainder.split(":")
            role = parts[0] if parts else "female"
            style = parts[1] if len(parts) > 1 else "normal"

            if role in ("sreymom", "woman", "girl_woman"):
                role = "female"
            elif role in ("piseth", "man"):
                role = "male"
            elif role in ("oldman", "grandpa", "ta"):
                role = "old_man"
            elif role in ("oldwoman", "grandma", "yeay"):
                role = "old_woman"

            presets = VOXCPM_PROMPT_PRESETS.get(role, VOXCPM_PROMPT_PRESETS.get("female", []))
            prompt = presets[0][1] if presets else "A natural, clear expressive voice speaking fluent Khmer."
            display_style = style
            for p_label, p_text in presets:
                if style in p_label.lower():
                    prompt = p_text
                    display_style = p_label
                    break

            return {
                "role": role,
                "style": style,
                "control_prompt": prompt,
                "display_name": f"AI VoxCPM2 - {role.title()} ({display_style})",
                "voice_id": v,
            }

    return {}


def is_voxcpm_builtin_voice(voice):
    """Checks if voice is one of the built-in VoxCPM2 preset voices."""
    if not isinstance(voice, str):
        return False
    v = voice.strip().lower()
    return v.startswith(("voxcpm:", "voxcpm2:")) and not is_voxcpm_reference_voice(voice)


def make_voxcpm_reference_voice_id(audio_path, prompt_text="", control_prompt="", reference_prompt_text="", control=None, **kwargs):
    """
    Constructs a structured reference voice ID containing reference audio path,
    optional transcript, and control prompt.
    Supports both 'control' and 'control_prompt', and 'prompt_text' and 'reference_prompt_text'.
    """
    ctrl = str(control if control is not None else control_prompt or "").strip()
    ref_text = str(reference_prompt_text or prompt_text or "").strip()
    data = {
        "path": str(audio_path or "").strip(),
        "prompt_text": ref_text,
        "control": ctrl,
    }
    return "voxcpm2_ref:" + json.dumps(data, ensure_ascii=False)


def get_voxcpm_reference_settings(voice_id):
    """
    Parses a reference voice ID into a dictionary containing 'path', 'prompt_text', and 'control'.
    """
    if not isinstance(voice_id, str):
        return {}
    voice_str = voice_id.strip()
    for prefix in ("voxcpm2_ref:", "voxcpm_ref:"):
        if voice_str.startswith(prefix):
            raw = voice_str[len(prefix):].strip()
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return {
                        "path": str(parsed.get("path", "") or "").strip(),
                        "prompt_text": str(parsed.get("prompt_text", "") or parsed.get("reference_prompt_text", "") or "").strip(),
                        "control": str(parsed.get("control", "") or parsed.get("control_prompt", "") or "").strip(),
                    }
            except Exception:
                return {"path": raw, "prompt_text": "", "control": ""}
    return {}


def is_voxcpm_reference_voice(voice):
    """Checks if voice is a VoxCPM2 reference audio clone voice."""
    if not isinstance(voice, str):
        return False
    v = voice.strip().lower()
    return v.startswith(("voxcpm2_ref:", "voxcpm_ref:"))


def is_voxcpm_reference_voice_id(voice_id):
    """Alias for is_voxcpm_reference_voice."""
    return is_voxcpm_reference_voice(voice_id)


def is_voxcpm_voice(voice):
    """Checks if voice is any VoxCPM2 voice (prompt-based or reference-based)."""
    if not isinstance(voice, str):
        return False
    v = voice.strip().lower()
    return (
        v.startswith(("voxcpm2:", "voxcpm:", "voxcpm2_ref:", "voxcpm_ref:"))
        or is_voxcpm_reference_voice(voice)
    )


def is_voxcpm_voice_id(voice_id):
    """Alias for is_voxcpm_voice."""
    return is_voxcpm_voice(voice_id)


def _find_python_executable(candidate_path=None):
    """Finds a valid python executable cross-platform (Windows / Linux)."""
    candidates = []
    if candidate_path:
        candidates.append(candidate_path)
    
    # Check current virtual environment
    candidates.append(sys.executable)
    
    # Check standard local paths
    for base in (".venv", "voxcpm_runtime", "_internal/data_venv"):
        if os.name == "nt":
            candidates.append(os.path.join(base, "Scripts", "python.exe"))
            candidates.append(os.path.join(base, "python.exe"))
        else:
            candidates.append(os.path.join(base, "bin", "python3"))
            candidates.append(os.path.join(base, "bin", "python"))

    for c in candidates:
        if c and os.path.exists(c) and os.access(c, os.X_OK):
            return os.path.abspath(c)
    return sys.executable


def get_voxcpm_install_status(*args, **kwargs):
    """
    Checks if VoxCPM2 source, model, and python runtime are installed and ready.
    Returns status dict matching core_app expected keys.
    """
    try:
        from settings_manager import get_voxcpm_install_config
        config = get_voxcpm_install_config()
    except Exception:
        config = {}

    source_dir = str(config.get("source_dir", "") or "").strip()
    model_path = str(config.get("model_path", "") or "").strip()
    python_path = str(config.get("python_path", "") or "").strip()

    # Search standard auto-detected paths if not explicitly configured
    if not source_dir or not os.path.isdir(os.path.join(source_dir, "src", "voxcpm")):
        for candidate in ("VoxCPM-main", "VoxCPM", "_internal/VoxCPM-main"):
            if os.path.isdir(os.path.join(candidate, "src", "voxcpm")):
                source_dir = os.path.abspath(candidate)
                break

    if not model_path or not os.path.exists(os.path.join(model_path, "config.json")):
        for candidate in ("models/openbmb__VoxCPM2", "models/VoxCPM2", "_internal/models/openbmb__VoxCPM2"):
            if os.path.exists(os.path.join(candidate, "config.json")):
                model_path = os.path.abspath(candidate)
                break

    python_exe = _find_python_executable(python_path)
    has_python = bool(python_exe and os.path.exists(python_exe))

    # 1. Check if voxcpm is installed as a Python package in target Python
    has_package = False
    package_version = ""
    if has_python:
        try:
            chk_pkg = subprocess.run(
                [python_exe, "-c", "import voxcpm; import importlib.metadata; print(importlib.metadata.version('voxcpm') if hasattr(importlib, 'metadata') else 'installed')"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8
            )
            if chk_pkg.returncode == 0:
                has_package = True
                out_lines = chk_pkg.stdout.strip().splitlines()
                package_version = out_lines[-1].strip() if out_lines else "installed"
        except Exception:
            pass

    # 2. Legacy fallback: check if source_dir contains voxcpm repository source
    has_source_dir = bool(source_dir and os.path.isdir(os.path.join(source_dir, "src", "voxcpm")))
    has_engine = has_package or has_source_dir

    has_model = bool(model_path and os.path.exists(os.path.join(model_path, "config.json")))

    # Check for required python dependencies in the target python
    has_deps = True
    deps_err = ""
    if has_python:
        try:
            chk = subprocess.run(
                [python_exe, "-c", "import pydantic, torch, torchaudio"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8
            )
            has_deps = (chk.returncode == 0)
            if not has_deps:
                deps_err = (chk.stderr or chk.stdout or "").strip()
        except Exception as e:
            has_deps = True

    ready = has_engine and has_model and has_python and has_deps
    installed = has_engine or has_model

    if ready:
        ver_tag = f" (v{package_version})" if package_version and package_version != "installed" else ""
        message = f"VoxCPM2 package/runtime is ready{ver_tag}."
        status_str = "ready"
    elif installed:
        missing = []
        if not has_engine:
            missing.append("voxcpm package")
        if not has_model:
            missing.append("VoxCPM2 model")
        if not has_python:
            missing.append("Python runtime")
        elif not has_deps:
            err_summary = deps_err.splitlines()[-1] if deps_err else "PyTorch/TorchAudio incompatibility"
            missing.append(f"runtime dependencies ({err_summary[:80]})")
        message = f"VoxCPM2 is incomplete. Missing: {', '.join(missing)}."
        status_str = "incomplete"
    else:
        message = "VoxCPM2 data/runtime is not installed yet."
        status_str = "not_installed"

    return {
        "installed": installed,
        "ready": ready,
        "status": status_str,
        "message": message,
        "source_dir": source_dir,
        "has_package": has_package,
        "package_version": package_version,
        "model_path": model_path,
        "python_path": python_exe,
    }


def generate_voxcpm_audio(text, voice_id, output_path, progress_callback=None, character_key=None, reference_audio_path=None, prompt_text=None, **kwargs):
    """
    Generates audio using VoxCPM2.
    If models are not installed, raises a descriptive RuntimeError to guide the user.
    """
    status = get_voxcpm_install_status()
    if not status.get("ready"):
        raise RuntimeError(
            f"VoxCPM2 is not ready: {status.get('message', 'Incomplete setup')}.\n\n"
            "Please click the VoxCPM2 button in the top toolbar to complete setup."
        )

    # Extract reference settings if voice_id is a reference voice
    ref_path = reference_audio_path
    ref_prompt = prompt_text
    control_instruction = kwargs.get("control", "") or kwargs.get("control_instruction", "") or kwargs.get("control_prompt", "")
    if not ref_path and is_voxcpm_reference_voice(voice_id):
        ref_settings = get_voxcpm_reference_settings(voice_id)
        ref_path = ref_settings.get("path", "")
        ref_prompt = ref_prompt or ref_settings.get("prompt_text", "")
        if not control_instruction:
            control_instruction = ref_settings.get("control", "")

    # Auto-resolve control prompt from built-in preset if not already specified
    if not control_instruction and not ref_path and is_voxcpm_voice(voice_id):
        preset_info = resolve_voxcpm_voice_preset(voice_id)
        if preset_info and preset_info.get("control_prompt"):
            control_instruction = preset_info["control_prompt"]

    if progress_callback:
        try:
            progress_callback("Preparing VoxCPM2 synthesis...")
        except Exception:
            pass

    source_dir = status.get("source_dir", "")
    model_path = status["model_path"]
    python_exe = status["python_path"]

    # Build runner command for standalone subprocess inference
    runner_code = f"""
import sys, os, re

# Optional fallback to local source dir if specified and present
custom_source = {repr(source_dir)}
if custom_source and os.path.isdir(os.path.join(custom_source, 'src', 'voxcpm')):
    sys.path.insert(0, os.path.join(custom_source, 'src'))

try:
    from voxcpm import VoxCPM
    import soundfile as sf
    import torch

    target_dev = "cpu"
    try:
        if torch.cuda.is_available():
            _t = torch.zeros(1, device="cuda")
            del _t
            target_dev = "cuda"
    except Exception:
        target_dev = "cpu"

    m_path = {repr(model_path)}
    if m_path and os.path.isdir(m_path) and os.path.exists(os.path.join(m_path, 'config.json')):
        model = VoxCPM(
            voxcpm_model_path=m_path,
            zipenhancer_model_path=None,
            enable_denoiser=False,
            optimize=False,
            device=target_dev
        )
    else:
        model = VoxCPM.from_pretrained(
            hf_model_id=m_path or "openbmb/VoxCPM2",
            load_denoiser=False,
            optimize=False,
            device=target_dev
        )

    ctrl = re.sub(r"[()（）]", "", {repr(control_instruction or "")}).strip()
    raw_text = {repr(text)}.strip()
    final_text = f"({{ctrl}}){{raw_text}}" if ctrl else raw_text

    generate_kwargs = {{
        'text': final_text,
        'inference_timesteps': 10,
        'normalize': False,
        'denoise': False,
    }}

    ref_audio = {repr(ref_path) if ref_path else 'None'}
    ref_txt = {repr(ref_prompt) if ref_prompt else 'None'}

    if ref_audio:
        if ref_txt:
            generate_kwargs['prompt_wav_path'] = ref_audio
            generate_kwargs['prompt_text'] = ref_txt
        else:
            generate_kwargs['reference_wav_path'] = ref_audio

    wav = model.generate(**generate_kwargs)
    if hasattr(wav, 'cpu'):
        wav = wav.cpu().float().numpy()
    if hasattr(wav, 'squeeze'):
        wav = wav.squeeze()
    sr = getattr(model.tts_model, 'sample_rate', 16000)
    sf.write({repr(output_path)}, wav, sr, format='WAV')
    print('SUCCESS')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('ERROR:', e, file=sys.stderr)
    sys.exit(1)
"""
    cmd = [python_exe, "-c", runner_code]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"VoxCPM2 inference failed: {stderr.strip() or stdout.strip()}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"VoxCPM2 produced empty audio file at {output_path}")

    return output_path
