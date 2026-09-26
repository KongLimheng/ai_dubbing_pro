"""Settings and configuration management for AI Dubber Ultimate.

Cross-platform configuration manager supporting per-user config directories,
fallback migration from legacy locations, and unified configuration IO for
all AI engines, voice clone models, subtitle styles, and GUI preferences.
"""

import json
import os
import sys

APP_CONFIG_FILENAME = '.app_config.json'
APP_CONFIG_DIRNAME = 'AI Dubbing Tool'

GEMINI_DEFAULT_FREE_LIMITS = {
    'gemini-2.5-pro': {
        'label': 'Gemini 2.5 Pro',
        'rpm': 5,
        'rpd': 100,
        'tpm': 250000,
    },
    'gemini-2.5-flash': {
        'label': 'Gemini 2.5 Flash',
        'rpm': 10,
        'rpd': 250,
        'tpm': 250000,
    },
}


def _iter_legacy_config_paths():
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), APP_CONFIG_FILENAME))
        bundle_dir = getattr(sys, '_MEIPASS', '')
        if bundle_dir:
            candidates.append(os.path.join(bundle_dir, APP_CONFIG_FILENAME))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), APP_CONFIG_FILENAME))

    seen = set()
    for candidate in candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        yield candidate


def _migrate_legacy_config(target_path):
    if os.path.exists(target_path):
        return
    target_normalized = os.path.normcase(os.path.abspath(target_path))
    for legacy_path in _iter_legacy_config_paths():
        legacy_normalized = os.path.normcase(os.path.abspath(legacy_path))
        if legacy_normalized == target_normalized or not os.path.exists(legacy_path):
            continue
        try:
            with open(legacy_path, 'r', encoding='utf-8-sig') as src_file:
                config_data = json.load(src_file)
            with open(target_path, 'w', encoding='utf-8') as dst_file:
                json.dump(config_data, dst_file, indent=2, ensure_ascii=False)
            return
        except Exception as e:
            print(f"[WARN] Failed to migrate settings from {legacy_path}: {e}")


def get_config_file_path():
    config_roots = [
        os.environ.get('LOCALAPPDATA'),
        os.environ.get('APPDATA'),
        os.path.expanduser('~'),
    ]
    for root in config_roots:
        if not root:
            continue
        config_dir = os.path.join(root, APP_CONFIG_DIRNAME)
        try:
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, APP_CONFIG_FILENAME)
            _migrate_legacy_config(config_path)
            return config_path
        except Exception:
            continue

    for legacy_path in _iter_legacy_config_paths():
        legacy_dir = os.path.dirname(legacy_path)
        try:
            os.makedirs(legacy_dir, exist_ok=True)
        except Exception:
            pass
        return legacy_path

    return os.path.join(os.path.expanduser('~'), APP_CONFIG_FILENAME)


def get_app_data_dir():
    """Return the shared per-user app data directory used by this app."""
    return os.path.dirname(get_config_file_path())


def get_runtime_package_config():
    """Get runtime package download/install configuration."""
    config = read_config()
    packages = config.get('runtime_packages', {})
    if not isinstance(packages, dict):
        packages = {}
    return {
        'auto_download': bool(config.get('runtime_packages_auto_download', True)),
        'packages': packages,
    }


def save_runtime_package_config(packages, auto_download=True):
    """Save runtime package download/install configuration."""
    if not isinstance(packages, dict):
        packages = {}
    return write_config({
        'runtime_packages_auto_download': bool(auto_download),
        'runtime_packages': packages,
    })


def read_config():
    """Read the full JSON application configuration."""
    config_path = get_config_file_path()
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"[WARN] Error reading config file {config_path}: {e}")
    return {}


def write_config(config_data):
    """Persist dictionary keys into the JSON configuration file."""
    if not isinstance(config_data, dict):
        return False
    config_path = get_config_file_path()
    existing = read_config()
    existing.update(config_data)
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to write config to {config_path}: {e}")
        return False


def get_ui_feature_flags():
    """Get optional UI feature toggles."""
    config = read_config()
    flags = config.get('ui_feature_flags')
    if isinstance(flags, dict):
        return {
            'enable_voxcpm2': bool(flags.get('enable_voxcpm2', True)),
            'enable_rvc': bool(flags.get('enable_rvc', True)),
            'enable_voice_clone': bool(flags.get('enable_voice_clone', True)),
        }
    return {
        'enable_voxcpm2': True,
        'enable_rvc': True,
        'enable_voice_clone': True,
    }


def save_ui_feature_flags(enable_voxcpm2=None, enable_rvc=None, enable_voice_clone=None):
    """Save UI feature toggles."""
    config = read_config()
    flags = dict(config.get('ui_feature_flags', {}) or {})
    if enable_voxcpm2 is not None:
        flags['enable_voxcpm2'] = bool(enable_voxcpm2)
    if enable_rvc is not None:
        flags['enable_rvc'] = bool(enable_rvc)
    if enable_voice_clone is not None:
        flags['enable_voice_clone'] = bool(enable_voice_clone)
    config['ui_feature_flags'] = flags
    if write_config(config):
        return flags

    for legacy_path in _iter_legacy_config_paths():
        try:
            legacy_dir = os.path.dirname(legacy_path)
            os.makedirs(legacy_dir, exist_ok=True)
            existing = {}
            if os.path.exists(legacy_path):
                with open(legacy_path, 'r', encoding='utf-8-sig') as f:
                    existing = json.load(f) or {}
            existing['ui_feature_flags'] = flags
            with open(legacy_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            return flags
        except Exception:
            continue
    return flags


def normalize_gemini_api_keys(api_key, api_keys):
    candidates = []
    if api_key:
        candidates.append(str(api_key).strip())
    if isinstance(api_keys, str):
        normalized_text = api_keys.replace(',', '\n').replace(';', '\n')
        candidates.extend(line.strip() for line in normalized_text.splitlines())
    elif isinstance(api_keys, (list, tuple)):
        candidates.extend(str(item or '').strip() for item in api_keys)

    cleaned = []
    seen = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        cleaned.append(candidate)
    return cleaned


def mask_api_key(api_key):
    api_key = str(api_key or '').strip()
    if len(api_key) <= 10:
        return api_key or '(empty)'
    return f"{api_key[:6]}...{api_key[-4:]}"


def get_gemini_model_limits(model_name):
    normalized = str(model_name or '').strip()
    if 'models/' in normalized:
        normalized = normalized.split('models/')[-1]
    limits = GEMINI_DEFAULT_FREE_LIMITS.get(normalized, {})
    return {
        'model': normalized,
        'label': limits.get('label', normalized or 'Gemini'),
        'rpm': limits.get('rpm'),
        'rpd': limits.get('rpd'),
        'tpm': limits.get('tpm'),
    }


def normalize_api_keys(primary_key, api_keys):
    seen = set()
    values = []

    def _push(value):
        text = str(value or '').strip()
        if not text or text in seen:
            return
        seen.add(text)
        values.append(text)

    if isinstance(api_keys, str):
        api_keys = api_keys.splitlines()
    for item in (api_keys or []):
        _push(item)
    _push(primary_key)
    return values


def get_azure_api_config():
    """Get Azure API configuration."""
    config = read_config()
    return {
        'api_key': config.get('azure_api_key', ''),
        'region': config.get('azure_region', ''),
    }


def save_azure_api_config(api_key, region):
    """Save Azure API configuration."""
    return write_config({
        'azure_api_key': str(api_key or '').strip(),
        'azure_region': str(region or '').strip(),
    })


def get_openai_api_config():
    """Get OpenAI API configuration."""
    config = read_config()
    return {
        'api_key': config.get('openai_api_key', ''),
        'auto_translate': config.get('openai_auto_translate', False),
        'target_language': config.get('openai_target_language', 'km'),
        'model': config.get('openai_model', 'gpt-4o-mini'),
    }


def save_openai_api_config(api_key, auto_translate, target_language, model):
    """Save OpenAI API configuration."""
    return write_config({
        'openai_api_key': str(api_key or '').strip(),
        'openai_auto_translate': bool(auto_translate),
        'openai_target_language': str(target_language or 'km'),
        'openai_model': str(model or 'gpt-4o-mini'),
    })


def get_translation_config():
    """Get current translation engine setting.

    Smart default: if no engine is explicitly configured, uses Gemini AI when
    a Gemini API key is present, otherwise falls back to Google Translate.
    """
    config = read_config()
    engine = config.get('translation_engine', None)
    if not engine:
        # Smart default: prefer Gemini if an API key is configured
        gemini_key = str(config.get('gemini_api_key', '') or '').strip()
        engine = 'gemini' if gemini_key else 'google'
    return {
        'engine': engine,
    }


def save_translation_config(engine):
    """Save translation engine setting."""
    return write_config({
        'translation_engine': str(engine or 'google').strip().lower(),
    })


def get_gladia_api_config():
    """Get Gladia transcription API configuration."""
    config = read_config()
    primary_key = str(config.get('gladia_api_key', '') or '').strip()
    raw_keys = config.get('gladia_api_keys', [])
    api_keys = normalize_api_keys(primary_key, raw_keys)
    return {
        'api_key': primary_key or (api_keys[0] if api_keys else ''),
        'api_keys': api_keys,
        'rotate_keys': bool(config.get('gladia_rotate_keys', True)),
        'target_language': str(config.get('gladia_target_language', 'km')),
    }


def save_gladia_api_config(api_key, api_keys=None, rotate_keys=True, target_language='km'):
    """Save Gladia transcription API configuration."""
    existing = read_config()
    existing_keys = existing.get('gladia_api_keys', [])
    normalized = normalize_api_keys(api_key, api_keys if api_keys is not None else existing_keys)
    primary = normalized[0] if normalized else str(api_key or '').strip()
    return write_config({
        'gladia_api_key': primary,
        'gladia_api_keys': normalized,
        'gladia_rotate_keys': bool(rotate_keys),
        'gladia_target_language': str(target_language or 'km'),
    })


def get_gemini_api_config():
    """Get Gemini API configuration and rotation preferences."""
    config = read_config()
    api_keys = normalize_gemini_api_keys(config.get('gemini_api_key', ''), config.get('gemini_api_keys', []))
    gender_model = config.get('gemini_gender_model') or config.get('gemini_model', 'gemini-2.5-flash')
    translate_model = config.get('gemini_translate_model') or config.get('gemini_model', 'gemini-2.5-flash')
    return {
        'api_key': api_keys[0] if api_keys else '',
        'api_keys': api_keys,
        'api_keys_text': '\n'.join(api_keys),
        'auto_translate': bool(config.get('gemini_auto_translate', False)),
        'target_language': config.get('gemini_target_language', 'km'),
        'model': config.get('gemini_model', 'gemini-2.5-flash'),
        'gender_model': gender_model,
        'translate_model': translate_model,
        'translate_rotate_keys': bool(config.get('gemini_translate_rotate_keys', True)),
        'auto_label_speakers': bool(config.get('gemini_auto_label_speakers', False)),
        'full_detect_enabled': bool(config.get('full_detect_enabled', False)),
        'key_usage': config.get('gemini_key_usage', {}),
    }


def save_gemini_api_config(api_key, auto_translate, target_language, model, api_keys=None, gender_model=None, key_usage=None):
    """Save Gemini API settings and key list."""
    existing_config = read_config()
    existing_keys = existing_config.get('gemini_api_keys', [])
    normalized_keys = normalize_gemini_api_keys(api_key, api_keys if api_keys is not None else existing_keys)
    primary_key = normalized_keys[0] if normalized_keys else str(api_key or '').strip()
    payload = {
        'gemini_api_key': primary_key,
        'gemini_api_keys': normalized_keys,
        'gemini_auto_translate': bool(auto_translate),
        'gemini_target_language': target_language,
        'gemini_model': model,
    }
    if gender_model is not None:
        payload['gemini_gender_model'] = gender_model
    elif 'gemini_gender_model' in existing_config:
        payload['gemini_gender_model'] = existing_config.get('gemini_gender_model')

    if 'gemini_translate_model' in existing_config:
        payload['gemini_translate_model'] = existing_config.get('gemini_translate_model')

    if key_usage is not None:
        payload['gemini_key_usage'] = key_usage
    return write_config(payload)


def save_gemini_translate_model(model_name):
    """Save Gemini translation model name."""
    return write_config({
        'gemini_translate_model': str(model_name or '').strip(),
    })


def save_gemini_translate_rotation(enabled):
    """Save Gemini translation key rotation toggle."""
    return write_config({
        'gemini_translate_rotate_keys': bool(enabled),
    })


def save_gemini_auto_label_speakers(enabled):
    """Save auto label speakers with Gemini toggle."""
    return write_config({
        'gemini_auto_label_speakers': bool(enabled),
    })


def save_full_detect_enabled(enabled):
    """Save Full Detect (face detection) toggle."""
    return write_config({
        'full_detect_enabled': bool(enabled),
    })


def save_gemini_key_usage(key_usage):
    """Save Gemini API key usage metadata."""
    return write_config({
        'gemini_key_usage': dict(key_usage or {}),
    })


def get_groq_api_config():
    """Get Groq API configuration."""
    config = read_config()
    return {
        'api_key': config.get('groq_api_key', ''),
        'auto_translate': config.get('groq_auto_translate', False),
        'target_language': config.get('groq_target_language', 'km'),
    }


def save_groq_api_config(api_key, auto_translate, target_language):
    """Save Groq API configuration."""
    return write_config({
        'groq_api_key': str(api_key or '').strip(),
        'groq_auto_translate': bool(auto_translate),
        'groq_target_language': str(target_language or 'km'),
    })


def get_deepinfra_api_config():
    """Get DeepInfra API configuration."""
    config = read_config()
    return {
        'api_key': config.get('deepinfra_api_key', ''),
        'auto_translate': config.get('deepinfra_auto_translate', False),
        'target_language': config.get('deepinfra_target_language', 'km'),
        'source_language': config.get('deepinfra_source_language', 'auto'),
    }


def save_deepinfra_api_config(api_key, auto_translate, target_language, source_language='auto'):
    """Save DeepInfra API configuration."""
    return write_config({
        'deepinfra_api_key': str(api_key or '').strip(),
        'deepinfra_auto_translate': bool(auto_translate),
        'deepinfra_target_language': str(target_language or 'km'),
        'deepinfra_source_language': str(source_language or 'auto'),
    })


def get_assemblyai_api_config():
    """Get AssemblyAI API configuration."""
    config = read_config()
    return {
        'api_key': config.get('assemblyai_api_key', ''),
        'auto_translate': config.get('assemblyai_auto_translate', False),
        'target_language': config.get('assemblyai_target_language', 'km'),
    }


def save_assemblyai_api_config(api_key, auto_translate, target_language):
    """Save AssemblyAI API configuration."""
    return write_config({
        'assemblyai_api_key': str(api_key or '').strip(),
        'assemblyai_auto_translate': bool(auto_translate),
        'assemblyai_target_language': str(target_language or 'km'),
    })


def get_deepseek_api_config():
    """Get DeepSeek API configuration."""
    config = read_config()
    return {
        'api_key': config.get('deepseek_api_key', ''),
        'auto_translate': config.get('deepseek_auto_translate', False),
        'target_language': config.get('deepseek_target_language', 'km'),
        'model': config.get('deepseek_model', 'deepseek-chat'),
    }


def save_deepseek_api_config(api_key, auto_translate, target_language, model='deepseek-chat'):
    """Save DeepSeek API configuration."""
    return write_config({
        'deepseek_api_key': str(api_key or '').strip(),
        'deepseek_auto_translate': bool(auto_translate),
        'deepseek_target_language': str(target_language or 'km'),
        'deepseek_model': str(model or 'deepseek-chat'),
    })


def get_hardware_config():
    """Get hardware acceleration configuration."""
    config = read_config()
    return {
        'video_encoder': config.get('video_encoder', 'cpu'),
    }


def save_hardware_config(video_encoder):
    """Save hardware acceleration configuration."""
    return write_config({
        'video_encoder': str(video_encoder or 'cpu'),
    })


def get_local_tsb_config():
    """Get local FunASR inference device and Python interpreter path."""
    config = read_config()
    device = str(config.get('funasr_device', 'auto') or 'auto').strip().lower()
    if device not in {'cpu', 'cuda', 'cuda:0', 'cuda:1', 'cuda:2', 'cuda:3', 'auto'}:
        device = 'auto'
    return {
        'device': device,
        'python_path': str(config.get('funasr_python_path', '') or '').strip(),
    }


def save_local_tsb_config(device, python_path):
    """Save local FunASR inference configuration."""
    device = str(device or 'auto').strip().lower()
    if device not in {'cpu', 'cuda', 'cuda:0', 'cuda:1', 'cuda:2', 'cuda:3', 'auto'}:
        device = 'auto'
    python_path = str(python_path or '').strip().strip('"').strip("'").strip()
    try:
        low = python_path.replace('/', '\\').lower()
        if low.endswith('\\data_venv\\scripts\\python.exe') or low.endswith('\\funasr_venv\\scripts\\python.exe'):
            root_py = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(python_path)), 'python.exe'))
            if os.path.exists(root_py):
                python_path = root_py
    except Exception:
        pass
    return write_config({
        'funasr_device': device,
        'funasr_python_path': str(python_path or '').strip(),
    })


def get_voice_clone_config():
    """Get Voice Clone configuration."""
    config = read_config()
    flags = get_ui_feature_flags() or {}
    voice_clone_enabled = bool(flags.get('enable_voice_clone', False)) and bool(config.get('voice_clone_enabled', False))
    return {
        'enabled': voice_clone_enabled,
        'piseth_model': str(config.get('voice_clone_piseth_model', '') or '').strip(),
        'sreymom_model': str(config.get('voice_clone_sreymom_model', '') or '').strip(),
        'piseth_boy_model': str(config.get('voice_clone_piseth_boy_model', '') or '').strip(),
        'sreymom_girl_model': str(config.get('voice_clone_sreymom_girl_model', '') or '').strip(),
        'piseth_old_model': str(config.get('voice_clone_piseth_old_model', '') or '').strip(),
        'sreymom_old_model': str(config.get('voice_clone_sreymom_old_model', '') or '').strip(),
        'piseth_character_key': str(config.get('voice_clone_piseth_character_key', '') or '').strip(),
        'sreymom_character_key': str(config.get('voice_clone_sreymom_character_key', '') or '').strip(),
    }


def save_voice_clone_config(enabled, piseth_model, sreymom_model, piseth_character_key='', sreymom_character_key='', piseth_boy_model='', sreymom_girl_model='', piseth_old_model='', sreymom_old_model=''):
    """Save Voice Clone configuration."""
    return write_config({
        'voice_clone_enabled': bool(enabled),
        'voice_clone_piseth_model': str(piseth_model or '').strip(),
        'voice_clone_sreymom_model': str(sreymom_model or '').strip(),
        'voice_clone_piseth_boy_model': str(piseth_boy_model or '').strip(),
        'voice_clone_sreymom_girl_model': str(sreymom_girl_model or '').strip(),
        'voice_clone_piseth_old_model': str(piseth_old_model or '').strip(),
        'voice_clone_sreymom_old_model': str(sreymom_old_model or '').strip(),
        'voice_clone_piseth_character_key': str(piseth_character_key or '').strip(),
        'voice_clone_sreymom_character_key': str(sreymom_character_key or '').strip(),
    })


def normalize_voxcpm_character_keys(character_keys):
    """Normalize VoxCPM2 character lock keys into a unique ordered list."""
    keys = []
    seen = set()
    if isinstance(character_keys, str):
        character_keys = character_keys.splitlines()
    for key in (character_keys or []):
        key_text = str(key or '').strip()
        if not key_text:
            continue
        normalized = key_text.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        keys.append(key_text)
    return keys


def get_voxcpm_character_keys():
    """Get saved VoxCPM2 character voice lock keys."""
    config = read_config()
    return normalize_voxcpm_character_keys(config.get('voxcpm2_character_keys', []))


def save_voxcpm_character_keys(character_keys):
    """Save VoxCPM2 character voice lock keys."""
    return write_config({
        'voxcpm2_character_keys': normalize_voxcpm_character_keys(character_keys),
    })


def get_voxcpm_install_config():
    """Get saved VoxCPM2 external install paths."""
    config = read_config()
    return {
        'source_dir': str(config.get('voxcpm_source_dir', '') or '').strip(),
        'model_path': str(config.get('voxcpm_model_path', '') or '').strip(),
        'python_path': str(config.get('voxcpm_python_path', '') or '').strip(),
        'package_url': str(config.get('voxcpm_package_url', '') or '').strip(),
        'runtime_package_url': str(config.get('voxcpm_runtime_package_url', '') or '').strip(),
    }


def save_voxcpm_install_config(source_dir, model_path, python_path, package_url='', runtime_package_url=''):
    """Save VoxCPM2 external install paths."""
    return write_config({
        'voxcpm_source_dir': str(source_dir or '').strip(),
        'voxcpm_model_path': str(model_path or '').strip(),
        'voxcpm_python_path': str(python_path or '').strip(),
        'voxcpm_package_url': str(package_url or '').strip(),
        'voxcpm_runtime_package_url': str(runtime_package_url or '').strip(),
    })


def get_export_audio_mix_config():
    """Get export audio mix percentages for background and AI voice."""
    config = read_config()
    try:
        bg = int(config.get('export_background_volume_percent', 30))
    except Exception:
        bg = 30
    try:
        ai = int(config.get('export_ai_voice_volume_percent', 100))
    except Exception:
        ai = 100
    return {
        'background_percent': max(0, min(500, bg)),
        'ai_voice_percent': max(0, min(500, ai)),
    }


def save_export_audio_mix_config(background_percent, ai_voice_percent):
    """Save export audio mix percentages for background and AI voice."""
    try:
        bg = max(0, min(500, int(background_percent)))
    except Exception:
        bg = 30
    try:
        ai = max(0, min(500, int(ai_voice_percent)))
    except Exception:
        ai = 100
    return write_config({
        'export_background_volume_percent': bg,
        'export_ai_voice_volume_percent': ai,
    })


def get_batch_output_dir():
    """Get Batch mode output directory from saved settings."""
    config = read_config()
    return config.get('batch_output_dir', '')


def save_batch_output_dir(output_dir_path):
    """Save Batch mode output directory configuration."""
    return write_config({
        'batch_output_dir': str(output_dir_path or ''),
    })


def get_cutter_config():
    """Get saved cutter window preferences and form state."""
    config = read_config()
    cutter_config = config.get('cutter_config', {})
    if isinstance(cutter_config, dict):
        return cutter_config
    return {}


def save_cutter_config(cutter_config):
    """Save cutter window preferences and form state."""
    payload = cutter_config if isinstance(cutter_config, dict) else {}
    return write_config({
        'cutter_config': payload,
    })


def get_burn_subtitle_config():
    """Get burn subtitle style configuration from saved settings."""
    config = read_config()
    try:
        font_size = int(config.get('burn_subtitle_font_size', 10) or 10)
    except Exception:
        font_size = 10
    try:
        font_opacity = int(config.get('burn_subtitle_font_opacity', 100) or 100)
    except Exception:
        font_opacity = 100
    return {
        'font_family': str(config.get('burn_subtitle_font_family', '') or ''),
        'font_size': max(1, font_size),
        'font_color': str(config.get('burn_subtitle_font_color', '#FFFFFF') or '#FFFFFF'),
        'font_opacity': max(0, min(100, font_opacity)),
        'background_color': str(config.get('burn_subtitle_bg_color', '#9B000000') or '#9B000000'),
        'shadow_enabled': bool(config.get('burn_subtitle_shadow_enabled', False)),
    }


def save_burn_subtitle_config(font_family, font_size, font_color, background_color, font_opacity, shadow_enabled):
    """Save burn subtitle style configuration."""
    try:
        font_size = max(1, int(font_size))
    except Exception:
        font_size = 10
    try:
        font_opacity = max(0, min(100, int(font_opacity)))
    except Exception:
        font_opacity = 100
    return write_config({
        'burn_subtitle_font_family': str(font_family or ''),
        'burn_subtitle_font_size': font_size,
        'burn_subtitle_font_color': str(font_color or '#FFFFFF'),
        'burn_subtitle_bg_color': str(background_color or '#9B000000'),
        'burn_subtitle_font_opacity': font_opacity,
        'burn_subtitle_shadow_enabled': bool(shadow_enabled),
    })


def get_overlay_effects_config():
    """Get saved blur/text/logo overlay state and geometry."""
    config = read_config()
    overlay_config = config.get('overlay_effects_config', {})
    if isinstance(overlay_config, dict):
        return overlay_config
    return {}


def save_overlay_effects_config(overlay_config):
    """Persist blur/text/logo overlay state and geometry."""
    return write_config({
        'overlay_effects_config': overlay_config if isinstance(overlay_config, dict) else {},
    })


def get_telegram_bot_config():
    """Get Telegram bot configuration (stubbed - disabled)."""
    return {
        'token': '',
        'enabled': False,
        'notify_chat_id': '',
    }


def save_telegram_bot_config(token, enabled):
    """Save Telegram bot configuration (stubbed - no-op)."""
    return True


def save_telegram_bot_notify_chat_id(chat_id):
    """Save Telegram bot notify chat id (stubbed - no-op)."""
    return True


def get_batch_auto_dub_config():
    """Get configuration for batch auto dubbing."""
    config = read_config()
    return {
        'api_keys': list(config.get('batch_auto_gemini_keys', []) or []),
        'target_language': str(config.get('batch_auto_target_lang', 'km')),
        'remove_vocal': bool(config.get('batch_auto_remove_vocal', False)),
        'output_dir': str(config.get('batch_auto_output_dir', '') or ''),
        'voice_mode': str(config.get('batch_auto_voice_mode', 'km-KH-SreymomNeural')),
        'video_list': list(config.get('batch_auto_video_list', []) or []),
    }


def save_batch_auto_dub_config(api_keys, target_language, remove_vocal, output_dir, voice_mode, video_list):
    """Save configuration for batch auto dubbing."""
    return write_config({
        'batch_auto_gemini_keys': list(api_keys or []),
        'batch_auto_target_lang': str(target_language or 'km'),
        'batch_auto_remove_vocal': bool(remove_vocal),
        'batch_auto_output_dir': str(output_dir or ''),
        'batch_auto_voice_mode': str(voice_mode or 'km-KH-SreymomNeural'),
        'batch_auto_video_list': list(video_list or []),
    })


def get_theme_mode():
    """Get the saved UI theme mode ('dark' or 'light'). Default is 'dark'."""
    config = read_config()
    return str(config.get('theme_mode', 'dark') or 'dark').strip().lower()


def save_theme_mode(theme_mode):
    """Save the UI theme mode ('dark' or 'light')."""
    mode = 'light' if str(theme_mode).strip().lower() == 'light' else 'dark'
    return write_config({'theme_mode': mode})


def get_main_splitter_sizes():
    """Get the saved main vertical splitter sizes [table_h, timeline_h, effects_h]."""
    config = read_config()
    sizes = config.get('main_splitter_sizes', None)
    if isinstance(sizes, list) and len(sizes) == 3:
        try:
            return [int(s) for s in sizes]
        except (ValueError, TypeError):
            pass
    return None


def save_main_splitter_sizes(sizes):
    """Save the main vertical splitter sizes [table_h, timeline_h, effects_h]."""
    if isinstance(sizes, (list, tuple)) and len(sizes) == 3:
        try:
            int_sizes = [int(s) for s in sizes]
            return write_config({'main_splitter_sizes': int_sizes})
        except (ValueError, TypeError):
            pass
    return False


def get_video_effects_collapsed():
    """Get whether Video Effects block is saved as collapsed. Default is False."""
    config = read_config()
    return bool(config.get('video_effects_collapsed', False))


def save_video_effects_collapsed(collapsed):
    """Save whether Video Effects block is collapsed."""
    return write_config({'video_effects_collapsed': bool(collapsed)})

