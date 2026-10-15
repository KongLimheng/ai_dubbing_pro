from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request as urllib
import zipfile
from pathlib import Path
from typing import Callable, Optional

from runtime_paths import (
    app_path,
    ensure_app_subdir,
    get_app_dir,
    get_user_cache_dir,
    get_user_data_dir,
    is_app_dir_writable,
    resource_path,
)
from settings_manager import get_runtime_package_config

RUNTIME_PACKAGE_DEFS = {
    "funasr_models": {
        "label": "FunASR Speech-to-Text Models",
        "description": "Offline speech recognition models (Paraformer, VAD, CT-Punc)",
        "archive_name": "funasr_models.zip",
        "local_path": os.path.join("runtime_packages", "funasr_models.zip"),
        "target_subfolder": os.path.join("models", "funasr_hf_cache"),
        "approx_size_mb": 850,
        "required_paths": [os.path.join("models", "funasr_hf_cache")],
        "ready_any_paths": [os.path.join("models", "funasr_hf_cache")],
        "url": "https://github.com/heng-dev/ai-dubber-assets/releases/download/v1.0.0/funasr_models.zip",
        "mirrors": [],
    },
    "demucs_models": {
        "label": "Demucs Vocal Isolation Models",
        "description": "High-quality deep learning audio separation weights (HTDemucs)",
        "archive_name": "demucs_models.zip",
        "local_path": os.path.join("runtime_packages", "demucs_models.zip"),
        "target_subfolder": os.path.join("models", "demucs"),
        "approx_size_mb": 1200,
        "required_paths": [
            os.path.join("models", "demucs"),
            os.path.join("demucs_repo"),
        ],
        "ready_any_paths": [
            os.path.join("models", "demucs"),
            os.path.join("demucs_repo"),
        ],
        "url": "https://github.com/heng-dev/ai-dubber-assets/releases/download/v1.0.0/demucs_models.zip",
        "mirrors": [],
    },
    "ffmpeg_binaries": {
        "label": "FFmpeg Multimedia Engine",
        "description": "Standalone FFmpeg and FFprobe binary utilities",
        "archive_name": "ffmpeg_binaries.zip",
        "local_path": os.path.join("runtime_packages", "ffmpeg_binaries.zip"),
        "target_subfolder": "bin",
        "approx_size_mb": 65,
        "required_paths": [
            os.path.join("bin", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        ],
        "ready_any_paths": [
            os.path.join("bin", "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
        ],
        "url": "https://github.com/heng-dev/ai-dubber-assets/releases/download/v1.0.0/ffmpeg_binaries.zip",
        "mirrors": [],
    },
    "ai_runtime": {
        "label": "AI Runtime (Python + FunASR + Demucs)",
        "description": "Optional isolated Python environment for Demucs and offline models",
        "archive_name": "ai_runtime.zip",
        "local_path": os.path.join("runtime_packages", "ai_runtime.zip"),
        "approx_size_mb": 1500,
        "required_paths": [
            os.path.join("_internal", "data_venv", "python.exe")
            if sys.platform == "win32"
            else sys.executable
        ],
        "ready_any_paths": [
            sys.executable,  # On Linux/macOS, current python env is ready
            os.path.join("_internal", "data_venv", "python.exe"),
            os.path.join("data_venv", "python.exe"),
            os.path.join("_internal", "data_venv", "Scripts", "python.exe"),
            os.path.join("data_venv", "Scripts", "python.exe"),
            os.path.join("_internal", "funasr_venv", "Scripts", "python.exe"),
            os.path.join("funasr_venv", "Scripts", "python.exe"),
        ],
        "url": "",
        "mirrors": [],
    },
}

FEATURE_PACKAGE_REQUIREMENTS = {
    "funasr": ["funasr_models"],
    "demucs": ["demucs_models"],
}


def _normalize_path(value):
    if not value:
        return ""
    return str(value).replace("\\", os.sep).replace("/", os.sep).strip()


def get_runtime_extract_root() -> str:
    """Return extraction root path. Uses app_dir if writable (portable mode), else user data dir."""
    if is_app_dir_writable():
        return get_app_dir()
    return get_user_data_dir()


def get_runtime_downloads_dir() -> str:
    """Return directory for caching downloaded package zip archives."""
    if is_app_dir_writable():
        return ensure_app_subdir("downloads", "runtime_packages")
    return get_user_cache_dir("downloads", "runtime_packages")


def get_runtime_manifest_path():
    for candidate in [
        resource_path("runtime_packages.json"),
        app_path("runtime_packages.json"),
        get_user_data_dir("runtime_packages.json"),
        resource_path("config", "runtime_packages.json"),
        app_path("config", "runtime_packages.json"),
    ]:
        if os.path.isfile(candidate):
            return candidate
    return app_path("runtime_packages.json")


def load_runtime_package_manifest():
    manifest = {"packages": {}}
    manifest_path = get_runtime_manifest_path()
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh) or {}
            if isinstance(loaded, dict):
                manifest.update(loaded)
        except Exception:
            pass

    manifest_packages = dict(manifest.get("packages") or {})
    merged = {}
    for key, defaults in RUNTIME_PACKAGE_DEFS.items():
        item = dict(defaults)
        item.update(dict(manifest_packages.get(key) or {}))
        merged[key] = item
    manifest["packages"] = merged
    return manifest


def get_runtime_package_entry(package_key):
    manifest = load_runtime_package_manifest()
    saved = dict(get_runtime_package_config().get("packages") or {})
    entry = dict(manifest.get("packages", {}).get(package_key) or {})
    entry.update(dict(saved.get(package_key) or {}))
    entry.setdefault("key", package_key)
    return entry


def _path_has_content(path_value):
    if not path_value:
        return False
    if os.path.isfile(path_value):
        try:
            return os.path.getsize(path_value) > 0
        except Exception:
            return False
    if os.path.isdir(path_value):
        try:
            with os.scandir(path_value) as it:
                next(it)
                return True
        except Exception:
            return False
    return False


def _find_candidate_path(rel_path: str) -> Optional[str]:
    """Search for a relative path in user data dir, app dir, and resource dir."""
    norm = _normalize_path(rel_path)
    if os.path.isabs(norm):
        return norm if _path_has_content(norm) else None

    for candidate in [
        get_user_data_dir(norm),
        app_path(norm),
        resource_path(norm),
    ]:
        if _path_has_content(candidate):
            return candidate
    return None


def is_runtime_package_ready(package_key: str) -> bool:
    """Check if all required paths for a package exist and are non-empty."""
    if package_key == "ai_runtime" and sys.platform != "win32":
        return True

    if package_key == "ffmpeg_binaries":
        # Check system PATH first
        if shutil.which("ffmpeg"):
            return True

    entry = get_runtime_package_entry(package_key)

    # If any path in ready_any_paths is found, package is ready
    ready_any_paths = list(entry.get("ready_any_paths") or [])
    if ready_any_paths:
        for rel_path in ready_any_paths:
            if _find_candidate_path(rel_path):
                return True

    required_paths = list(entry.get("required_paths") or [])
    if not required_paths:
        return False

    for rel_path in required_paths:
        if not _find_candidate_path(rel_path):
            return False

    return True


def get_missing_runtime_packages(feature_key: str) -> list[str]:
    missing = []
    requirements = FEATURE_PACKAGE_REQUIREMENTS.get(
        str(feature_key or "").strip().lower(), []
    )
    for package_key in requirements:
        if not is_runtime_package_ready(package_key):
            missing.append(package_key)
    return missing


def describe_runtime_packages(package_keys: list[str]) -> str:
    labels = []
    for package_key in package_keys:
        entry = get_runtime_package_entry(package_key)
        labels.append(str(entry.get("label") or package_key))
    return ", ".join(labels)


def resolve_runtime_package_source(package_key: str) -> tuple[str, str]:
    entry = get_runtime_package_entry(package_key)
    local_candidates = []
    explicit_local_path = str(entry.get("local_path") or "").strip()
    if explicit_local_path:
        if os.path.isabs(explicit_local_path):
            local_candidates.append(explicit_local_path)
        else:
            local_candidates.append(get_user_data_dir(explicit_local_path))
            local_candidates.append(app_path(explicit_local_path))
            local_candidates.append(resource_path(explicit_local_path))

    archive_name = str(entry.get("archive_name") or "").strip()
    if archive_name:
        downloads_dir = get_runtime_downloads_dir()
        local_candidates.append(os.path.join(downloads_dir, archive_name))

    seen = set()
    for candidate in local_candidates:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(candidate) and os.path.getsize(candidate) > 0:
            return ("local", candidate)

    url = str(entry.get("url") or "").strip()
    if url:
        return ("url", url)

    # Check mirror URLs
    mirrors = entry.get("mirrors") or []
    for mirror in mirrors:
        if mirror and str(mirror).strip():
            return ("url", str(mirror).strip())

    return ("", "")


def _format_size(bytes_val: int) -> str:
    if bytes_val < 1024 * 1024:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024 * 1024 * 1024:
        return f"{bytes_val / (1024 * 1024):.1f} MB"
    return f"{bytes_val / (1024 * 1024 * 1024):.2f} GB"


def _format_time(seconds: float) -> str:
    if seconds <= 0 or seconds > 36000:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _download_url_to_file(
    url: str,
    target_path: str,
    package_label: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    expected_sha256: str = "",
) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    temp_download_path = target_path + ".part"

    req = urllib.Request(url, headers={"User-Agent": "AI-Dubber-Ultimate/1.2.9"})
    start_time = time.time()
    last_ui_update = 0.0

    with (
        urllib.urlopen(req) as response,
        open(temp_download_path, "wb") as out_file,
    ):
        try:
            total = int(response.headers.get("Content-Length", 0) or 0)
        except Exception:
            total = 0

        downloaded = 0
        sha = hashlib.sha256() if expected_sha256 else None

        while True:
            if cancel_check and cancel_check():
                raise RuntimeError("Download cancelled by user.")

            chunk = response.read(262144)  # 256KB chunks
            if not chunk:
                break
            out_file.write(chunk)
            if sha:
                sha.update(chunk)
            downloaded += len(chunk)

            now = time.time()
            if now - last_ui_update >= 0.2:
                last_ui_update = now
                elapsed = max(0.1, now - start_time)
                speed = downloaded / elapsed  # bytes/sec
                speed_str = f"{speed / (1024 * 1024):.1f} MB/s"

                if total > 0:
                    percent = int(float(downloaded) / float(total) * 100)
                    remaining = (total - downloaded) / speed if speed > 0 else 0
                    msg = (
                        f"Downloading {package_label}: {_format_size(downloaded)} / {_format_size(total)} "
                        f"({speed_str}, {_format_time(remaining)} remaining)"
                    )
                else:
                    percent = 50
                    msg = f"Downloading {package_label}: {_format_size(downloaded)} ({speed_str})"

                if progress_callback:
                    progress_callback(percent, msg)

    if expected_sha256 and sha:
        actual_hash = sha.hexdigest().lower()
        if actual_hash != expected_sha256.lower().strip():
            try:
                os.remove(temp_download_path)
            except Exception:
                pass
            raise RuntimeError(
                f"SHA-256 integrity check failed for {package_label}.\n"
                f"Expected: {expected_sha256}\nGot: {actual_hash}"
            )

    if os.path.exists(target_path):
        os.remove(target_path)
    os.rename(temp_download_path, target_path)

    if progress_callback:
        progress_callback(100, f"Downloaded {package_label} successfully.")
    return target_path


def _safe_extract_zip(zip_path: str, dest_dir: str, cancel_check: Optional[Callable[[], bool]] = None):
    dest_root = Path(dest_dir).resolve()
    os.makedirs(dest_root, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        total = len(members)
        for idx, member in enumerate(members):
            if cancel_check and cancel_check():
                raise RuntimeError("Extraction cancelled.")
            member_path = dest_root / member.filename
            resolved = member_path.resolve()
            if (
                os.path.commonpath([str(dest_root), str(resolved)])
                != str(dest_root)
            ):
                raise RuntimeError(
                    f"Refusing to extract unsafe path: {member.filename}"
                )
            zf.extract(member, dest_root)


def install_runtime_packages(
    package_keys: list[str],
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> dict:
    extract_root = get_runtime_extract_root()
    downloads_dir = get_runtime_downloads_dir()
    installed = []
    total_packages = len(package_keys)

    for idx, package_key in enumerate(package_keys):
        if cancel_check and cancel_check():
            raise RuntimeError("Operation cancelled.")

        entry = get_runtime_package_entry(package_key)
        package_label = str(entry.get("label") or package_key)
        source_type, source_value = resolve_runtime_package_source(package_key)

        if not source_type:
            raise RuntimeError(
                f"No local package file or download URL available for {package_label}."
            )

        package_start = int(idx / total_packages * 100)
        package_end = int((idx + 1) / total_packages * 100)

        def scoped_progress(inner_percent: int, message: str) -> None:
            overall = package_start + int(
                max(0, min(100, inner_percent))
                / 100.0
                * (package_end - package_start)
            )
            if progress_callback:
                progress_callback(overall, message)

        if source_type == "local":
            archive_path = source_value
            scoped_progress(5, f"Using local package: {os.path.basename(archive_path)}")
        else:
            archive_name = str(entry.get("archive_name") or "").strip() or f"{package_key}.zip"
            archive_path = os.path.join(downloads_dir, archive_name)
            expected_sha = str(entry.get("sha256") or "").strip()
            _download_url_to_file(
                source_value,
                archive_path,
                package_label,
                progress_callback=scoped_progress,
                cancel_check=cancel_check,
                expected_sha256=expected_sha,
            )

        scoped_progress(80, f"Extracting {package_label}...")
        _safe_extract_zip(archive_path, extract_root, cancel_check=cancel_check)

        if not is_runtime_package_ready(package_key):
            raise RuntimeError(
                f"{package_label} extracted, but required files are still missing."
            )

        scoped_progress(100, f"{package_label} is ready.")
        installed.append(package_key)

    return {"installed": installed, "extract_root": extract_root}


def get_runtime_package_disk_usage(package_key: str) -> int:
    """Calculate the total size in bytes consumed by this package on disk."""
    entry = get_runtime_package_entry(package_key)
    paths_to_check = set(list(entry.get("required_paths") or []) + list(entry.get("ready_any_paths") or []))
    total_bytes = 0

    for rel_path in paths_to_check:
        found = _find_candidate_path(rel_path)
        if found:
            if os.path.isfile(found):
                total_bytes += os.path.getsize(found)
            elif os.path.isdir(found):
                for root, _, files in os.walk(found):
                    for f in files:
                        try:
                            total_bytes += os.path.getsize(os.path.join(root, f))
                        except Exception:
                            pass
    return total_bytes


def uninstall_runtime_package(package_key: str) -> bool:
    """Remove installed files for a package to reclaim disk space."""
    entry = get_runtime_package_entry(package_key)
    required_paths = list(entry.get("required_paths") or [])
    success = False

    for rel_path in required_paths:
        norm = _normalize_path(rel_path)
        # Check both user data dir and app dir
        for base in [get_user_data_dir(), get_app_dir()]:
            target = os.path.join(base, norm)
            if os.path.isfile(target):
                try:
                    os.remove(target)
                    success = True
                except Exception:
                    pass
            elif os.path.isdir(target):
                try:
                    shutil.rmtree(target, ignore_errors=True)
                    success = True
                except Exception:
                    pass

    # Also clean cached download archive if present
    archive_name = str(entry.get("archive_name") or "").strip()
    if archive_name:
        cached_zip = os.path.join(get_runtime_downloads_dir(), archive_name)
        if os.path.isfile(cached_zip):
            try:
                os.remove(cached_zip)
            except Exception:
                pass

    return success


def ensure_feature_ready(feature_key: str, parent=None) -> bool:
    """
    On-demand dependency verification. Checks if required packages for a feature
    are ready. If not, prompts the user to download them via PackageDownloadDialog.
    """
    missing = get_missing_runtime_packages(feature_key)
    if not missing:
        return True

    from ui_download_dialog import prompt_and_download_missing_packages

    labels = {
        "funasr": "Local FunASR Speech Recognition",
        "demucs": "Demucs Vocal Isolation",
    }
    feature_label = labels.get(feature_key.lower(), feature_key)
    return prompt_and_download_missing_packages(
        missing, parent=parent, feature_label=feature_label
    )
