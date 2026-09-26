import os
import sys
import time
import subprocess
import json
import shutil
import ssl
from datetime import datetime
try:
    from PyQt5.QtCore import QCoreApplication
except ImportError:
    class QCoreApplication:
        @staticmethod
        def addLibraryPath(path):
            pass
from runtime_paths import app_path, get_bundle_dir, resource_path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(errors="replace")


def _is_startup_verbose():
    return (
        str(os.environ.get("AI_DUBBER_VERBOSE_STARTUP", "")).strip().lower()
        in frozenset({"1", "on", "yes", "true"})
    )


def _startup_log(message):
    if _is_startup_verbose():
        print(message)


def setup_qt_plugins():
    """Setup Qt plugin paths for PyInstaller EXE to fix multimedia playback."""
    if not getattr(sys, "frozen", False):
        return
    if not hasattr(sys, "_MEIPASS"):
        return
    base_path = get_bundle_dir()
    plugin_path = os.path.join(base_path, "PyQt5", "Qt5", "plugins")
    if os.path.exists(plugin_path):
        QCoreApplication.addLibraryPath(plugin_path)
        os.environ["QT_PLUGIN_PATH"] = plugin_path
        _startup_log(f"Qt plugin path: {plugin_path}")
        return
    alt_plugin_path = os.path.join(base_path, "plugins")
    if os.path.exists(alt_plugin_path):
        QCoreApplication.addLibraryPath(alt_plugin_path)
        os.environ["QT_PLUGIN_PATH"] = alt_plugin_path
        _startup_log(f"Qt plugin path: {alt_plugin_path}")


setup_qt_plugins()


def apply_khmer_font_patch():
    """
    Patches PyQt5.QtGui.QFont to transparently replace 'Arial' and 'Helvetica'
    with the best available Khmer-compatible font (e.g. 'Khmer OS System',
    'Noto Sans Khmer', 'Khmer OS', 'Segoe UI', 'DejaVu Sans').

    This eliminates Qt HarfBuzz engine warnings:
    'OpenType support missing for "Arial", script 32'
    and ensures proper Khmer script shaping across all UI widgets and previews.
    """
    try:
        import PyQt5.QtGui

        _orig_qfont = PyQt5.QtGui.QFont
        if getattr(_orig_qfont, "_khmer_patched", False):
            return

        def _get_preferred_font():
            try:
                from PyQt5.QtGui import QFontDatabase

                db = QFontDatabase()
                available = set(db.families())
                for f in (
                    "Khmer OS System",
                    "Noto Sans Khmer",
                    "Khmer OS",
                    "Khmer UI",
                    "Leelawadee UI",
                    "Segoe UI",
                    "DejaVu Sans"

                ):
                    if f in available:
                        return f
            except Exception:
                pass
            return "sans-serif"

        _preferred_font = None

        def _resolve_family(family):
            nonlocal _preferred_font
            if isinstance(family, str) and family.lower() in ("arial", "helvetica"):
                if _preferred_font is None:
                    _preferred_font = _get_preferred_font()
                return _preferred_font
            return family

        class _SafeQFont(_orig_qfont):
            def __init__(self, *args, **kwargs):
                if args and isinstance(args[0], str):
                    args = list(args)
                    args[0] = _resolve_family(args[0])
                super().__init__(*args, **kwargs)

        _orig_setFamily = _orig_qfont.setFamily

        def _safe_setFamily(self, family):
            return _orig_setFamily(self, _resolve_family(family))

        _orig_qfont.setFamily = _safe_setFamily
        _SafeQFont._khmer_patched = True
        PyQt5.QtGui.QFont = _SafeQFont
    except Exception as e:
        _startup_log(f"Failed to apply khmer font patch: {e}")


apply_khmer_font_patch()


def get_days_used():
    try:
        from settings_manager import get_config_file_path

        config_file = get_config_file_path()
    except Exception:
        config_file = app_path(".app_config.json")

    try:
        if os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as file_obj:
                config = json.load(file_obj)
                first_launch = datetime.fromisoformat(
                    config.get("first_launch", datetime.now().isoformat())
                )
        else:
            first_launch = datetime.now()
            config = {"first_launch": first_launch.isoformat()}
            with open(config_file, "w", encoding="utf-8") as file_obj:
                json.dump(config, file_obj)

        days_used = (datetime.now() - first_launch).days + 1
        return days_used
    except Exception as exc:
        print(f"Error tracking days used: {exc}")
        return 1


def reset_days_used():
    try:
        from settings_manager import get_config_file_path

        config_file = get_config_file_path()
    except Exception:
        config_file = app_path(".app_config.json")

    try:
        first_launch = datetime.now()
        config = {"first_launch": first_launch.isoformat()}
        with open(config_file, "w", encoding="utf-8") as file_obj:
            json.dump(config, file_obj)
        return True
    except Exception as exc:
        print(f"Error resetting days used: {exc}")
        return False


def get_ffmpeg_path():
    # Cross-platform first: check system PATH (on Linux/macOS, this finds /usr/bin/ffmpeg)
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        _startup_log(f"Using system FFmpeg: {system_ffmpeg}")
        return system_ffmpeg
    for candidate in [
        resource_path("ffmpeg.exe"),
        app_path("ffmpeg.exe"),
        resource_path("ffmpeg"),
        app_path("ffmpeg"),
    ]:
        if os.path.exists(candidate):
            _startup_log(f"Using local FFmpeg: {candidate}")
            return candidate
    return "ffmpeg"


FFMPEG_PATH = get_ffmpeg_path()


def setup_ssl_bypass():
    try:
        import aiohttp

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        original_tcp_connector = aiohttp.TCPConnector

        class PatchedTCPConnector(original_tcp_connector):
            def __init__(self, *args, **kwargs):
                kwargs["ssl"] = ssl_context
                super().__init__(*args, **kwargs)

        aiohttp.TCPConnector = PatchedTCPConnector
        _startup_log(
            "Configured edge-tts to bypass SSL certificate verification"
        )
    except Exception as exc:
        _startup_log(f"Could not setup SSL bypass: {exc}")


try:
    setup_ssl_bypass()
except Exception as exc:
    _startup_log(f"Could not setup SSL bypass: {exc}")


def is_khmer_text(text):
    text = str(text or "").strip()
    if not text:
        return False
    khmer_chars = sum(1 for char in text if "\u1780" <= char <= "\u17ff")
    return (khmer_chars / max(1, len(text))) > 0.3


def is_khmer_voice(voice_id):
    return "km-KH" in str(voice_id or "")


def parse_rate_percent(rate_str, default=0):
    try:
        cleaned = (
            str(rate_str or "").replace("%", "").replace("+", "").strip()
        )
        if not cleaned:
            return int(default)
        return int(cleaned)
    except Exception:
        return int(default)


def format_rate_percent(rate_value):
    try:
        rate_value = int(round(float(rate_value)))
    except Exception:
        rate_value = 0
    rate_value = max(-50, min(100, rate_value))
    if rate_value >= 0:
        return f"+{rate_value}%"
    return f"{rate_value}%"


def get_balanced_tts_rate_details(
    text, expected_duration, base_rate_str="+0%", voice_id=None
):
    text = str(text or "").strip()
    base_rate = parse_rate_percent(base_rate_str, 0)
    try:
        expected_duration = float(expected_duration or 0.0)
    except Exception:
        expected_duration = 0.0

    if not text or expected_duration <= 0:
        rate = max(-50, min(100, base_rate))
        return {
            "is_khmer": is_khmer_voice(voice_id),
            "chars_per_second": 0.0,
            "base_rate": rate,
            "desired_rate": rate,
            "final_rate": rate,
            "rate_str": format_rate_percent(rate),
        }

    chars_per_second = len(text) / max(0.1, expected_duration)
    khmer_mode = is_khmer_text(text) or is_khmer_voice(voice_id)

    if khmer_mode:
        if chars_per_second < 8.5:
            desired_rate = 0
        elif chars_per_second < 10.5:
            desired_rate = 4
        elif chars_per_second < 12.5:
            desired_rate = 8
        elif chars_per_second < 14.5:
            desired_rate = 12
        elif chars_per_second < 16.5:
            desired_rate = 15
        elif chars_per_second < 18.5:
            desired_rate = 18
        else:
            desired_rate = 20
        min_rate, max_rate = 0, 20
    else:
        if chars_per_second < 8.0:
            desired_rate = -4
        elif chars_per_second < 10.0:
            desired_rate = 0
        elif chars_per_second < 12.0:
            desired_rate = 4
        elif chars_per_second < 14.0:
            desired_rate = 8
        elif chars_per_second < 16.0:
            desired_rate = 12
        elif chars_per_second < 18.0:
            desired_rate = 16
        else:
            desired_rate = 18
        min_rate, max_rate = -20, 22

    if abs(base_rate) >= 25 and abs(base_rate - desired_rate) > 12:
        final_rate = round(base_rate * 0.7 + desired_rate * 0.3)
    elif abs(base_rate - desired_rate) <= 8:
        final_rate = desired_rate
    elif abs(base_rate) <= 5:
        final_rate = desired_rate
    else:
        final_rate = round(base_rate * 0.45 + desired_rate * 0.55)

    final_rate = max(min_rate, min(max_rate, final_rate))
    if khmer_mode:
        final_rate = max(0, final_rate)

    return {
        "is_khmer": khmer_mode,
        "chars_per_second": chars_per_second,
        "base_rate": base_rate,
        "desired_rate": desired_rate,
        "final_rate": final_rate,
        "rate_str": format_rate_percent(final_rate),
    }


def get_balanced_tts_rate(
    text, expected_duration, base_rate_str="+0%", voice_id=None
):
    return get_balanced_tts_rate_details(
        text, expected_duration, base_rate_str, voice_id
    )["rate_str"]


def normalize_voice_id(voice_str, default: None | str = "km-KH-SreymomNeural"):
    """
    Normalizes any voice representation (display name, role string, case-insensitive ID,
    or Khmer tag) into a valid canonical Azure/Edge Neural Voice ID or VoxCPM reference voice ID.
    """
    if not voice_str:
        return default
    s = str(voice_str).strip()
    if not s:
        return default
    low = s.lower()

    canonical = {
        "km-kh-sreymomneural": "km-KH-SreymomNeural",
        "km-kh-sreymomneural_girl": "km-KH-SreymomNeural_Girl",
        "km-kh-sreymomneural-girl": "km-KH-SreymomNeural_Girl",
        "km-kh-sreymomneural_old": "km-KH-SreymomNeural_Old",
        "km-kh-sreymomneural-old": "km-KH-SreymomNeural_Old",
        "km-kh-sreymomneural-oldwoman": "km-KH-SreymomNeural_Old",
        "km-kh-sreymomneural_oldwoman": "km-KH-SreymomNeural_Old",
        "km-kh-pisethneural": "km-KH-PisethNeural",
        "km-kh-pisethneural_boy": "km-KH-PisethNeural_Boy",
        "km-kh-pisethneural-boy": "km-KH-PisethNeural_Boy",
        "km-kh-pisethneural_old": "km-KH-PisethNeural_Old",
        "km-kh-pisethneural-old": "km-KH-PisethNeural_Old",
        "km-kh-pisethneural-oldman": "km-KH-PisethNeural_Old",
        "km-kh-pisethneural_oldman": "km-KH-PisethNeural_Old",
        "en-us-arianeural": "en-US-AriaNeural",
        "en-us-christopherneural": "en-US-ChristopherNeural",
        "en-us-jennyneural": "en-US-JennyNeural",
        "en-us-ericneural": "en-US-EricNeural",
        "ko-kr-sunhineural": "ko-KR-SunHiNeural",
        "ko-kr-injoonneural": "ko-KR-InJoonNeural",
        "ja-jp-nanamineural": "ja-JP-NanamiNeural",
        "ja-jp-keitaneural": "ja-JP-KeitaNeural",
        "zh-cn-xiaoxiaoneural": "zh-CN-XiaoxiaoNeural",
        "zh-cn-yunxineural": "zh-CN-YunxiNeural",
        "th-th-premwadeeneural": "th-TH-PremwadeeNeural",
        "th-th-niwatneural": "th-TH-NiwatNeural",
        "vi-vn-hoaimyneural": "vi-VN-HoaiMyNeural",
        "vi-vn-namminhneural": "vi-VN-NamMinhNeural",
        "fr-fr-deniseneural": "fr-FR-DeniseNeural",
        "fr-fr-henrineural": "fr-FR-HenriNeural",
    }
    if low in canonical:
        return canonical[low]

    # VoxCPM or custom audio models
    if "voxcpm" in low or "custom_" in low:
        return s

    # Khmer text matches
    if any(k in s for k in ["មនុស្សចាស់ស្រី", "ស្រីចាស់", "យាយ"]):
        return "km-KH-SreymomNeural_Old"
    if any(k in s for k in ["មនុស្សចាស់ប្រុស", "ប្រុសចាស់", "តា"]):
        return "km-KH-PisethNeural_Old"
    if any(k in s for k in ["ក្មេងស្រី", "កូនស្រី"]):
        return "km-KH-SreymomNeural_Girl"
    if any(k in s for k in ["ក្មេងប្រុស", "កូនប្រុស"]):
        return "km-KH-PisethNeural_Boy"
    if any(k in s for k in ["មនុស្សស្រី", "ស្រី"]):
        return "km-KH-SreymomNeural"
    if any(k in s for k in ["មនុស្សប្រុស", "ប្រុស"]):
        return "km-KH-PisethNeural"

    # Old Woman vs Old Man (MUST check female/woman before male/man)
    if "old" in low:
        if any(w in low for w in ["woman", "female", "sreymom", "lady", "grandma", "mother", "mom"]):
            return "km-KH-SreymomNeural_Old"
        if any(m in low for m in ["man", "male", "piseth", "piset", "guy", "grandpa", "father", "dad", "pa"]):
            return "km-KH-PisethNeural_Old"
        return "km-KH-SreymomNeural_Old"

    # Boy vs Girl
    if "boy" in low:
        return "km-KH-PisethNeural_Boy"
    if "girl" in low:
        return "km-KH-SreymomNeural_Girl"

    # Female vs Male (MUST check female/woman before male/man)
    if any(f in low for f in ["female", "woman", "sreymom", "srey", "girl", "lady"]):
        return "km-KH-SreymomNeural"
    if any(m in low for m in ["male", "piseth", "piset", "man", "proh", "boy", "guy"]):
        return "km-KH-PisethNeural"

    return default


def resolve_voice_and_pitch(voice_str, pitch_str="+0Hz"):
    """
    Normalizes voice_str and resolves custom Khmer voices (Boy, Girl, Old Man, Old Woman)
    into the underlying base neural voice + modified pitch offset.
    """
    vid = normalize_voice_id(voice_str)

    pitch_val = 0
    if pitch_str is not None:
        p_clean = str(pitch_str).replace("Hz", "").replace(
            "hz", "").replace("+", "").strip()
        try:
            pitch_val = int(p_clean)
        except Exception:
            pitch_val = 0

    if vid in ("km-KH-PisethNeural_Boy", "km-KH-PisethNeural-Boy"):
        vid = "km-KH-PisethNeural"
        pitch_val += 25
    elif vid in ("km-KH-PisethNeural_Old", "km-KH-PisethNeural-OldMan", "km-KH-PisethNeural-Old"):
        vid = "km-KH-PisethNeural"
        pitch_val -= 20
    elif vid in ("km-KH-SreymomNeural_Girl", "km-KH-SreymomNeural-Girl"):
        vid = "km-KH-SreymomNeural"
        pitch_val += 20
    elif vid in ("km-KH-SreymomNeural_Old", "km-KH-SreymomNeural-OldWoman", "km-KH-SreymomNeural-Old"):
        vid = "km-KH-SreymomNeural"
        pitch_val -= 20

    pitch_val = max(-100, min(100, pitch_val))
    final_pitch = f"+{pitch_val}Hz" if pitch_val >= 0 else f"{pitch_val}Hz"
    return vid, final_pitch
