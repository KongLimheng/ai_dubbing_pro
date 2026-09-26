from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request as urllib
import zipfile
from pathlib import Path
from typing import Callable
from runtime_paths import app_path, ensure_app_subdir, get_app_dir, resource_path
from settings_manager import get_runtime_package_config

RUNTIME_PACKAGE_DEFS = {
    "ai_runtime": {
        "label": "AI Runtime (Python + FunASR + Demucs)",
        "archive_name": "ai_runtime.zip",
        "local_path": os.path.join("runtime_packages", "ai_runtime.zip"),
        "required_paths": [
            os.path.join("_internal", "data_venv", "python.exe")
            if sys.platform == "win32"
            else sys.executable
        ],
        "ready_any_paths": [
            sys.executable,  # On Linux/macOS, current python env
            os.path.join("_internal", "data_venv", "python.exe"),
            os.path.join("data_venv", "python.exe"),
            os.path.join("_internal", "data_venv", "Scripts", "python.exe"),
            os.path.join("data_venv", "Scripts", "python.exe"),
            os.path.join("_internal", "funasr_venv", "Scripts", "python.exe"),
            os.path.join("funasr_venv", "Scripts", "python.exe"),
        ],
    },
    "funasr_models": {
        "label": "FunASR Models",
        "archive_name": "funasr_models.zip",
        "local_path": os.path.join("runtime_packages", "funasr_models.zip"),
        "required_paths": [os.path.join("models", "funasr_hf_cache")],
        "ready_any_paths": [os.path.join("models", "funasr_hf_cache")],
    },
    "demucs_models": {
        "label": "Demucs Models",
        "archive_name": "demucs_models.zip",
        "local_path": os.path.join("runtime_packages", "demucs_models.zip"),
        "required_paths": [os.path.join("demucs_repo")],
        "ready_any_paths": [os.path.join("demucs_repo")],
    },
}

FEATURE_PACKAGE_REQUIREMENTS = {
    "funasr": ["ai_runtime"],
    "demucs": ["ai_runtime"],
}


def _normalize_path(value):
    if not value:
        return ""
    return str(value).replace("\\", os.sep).replace("/", os.sep).strip()


def get_runtime_manifest_path():
    for candidate in [
        resource_path("runtime_packages.json"),
        app_path("runtime_packages.json"),
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
            next(os.scandir(path_value))
            return True
        except Exception:
            return False
    return False


def is_runtime_package_ready(package_key):
    # If running on Linux/macOS and checking ai_runtime, current python has the environment
    if package_key == "ai_runtime" and sys.platform != "win32":
        return True

    entry = get_runtime_package_entry(package_key)
    ready_any_paths = list(entry.get("ready_any_paths") or [])
    if ready_any_paths:
        for rel_path in ready_any_paths:
            candidate = app_path(_normalize_path(rel_path))
            if _path_has_content(candidate):
                return True

    required_paths = list(entry.get("required_paths") or [])
    if not required_paths:
        return False

    for rel_path in required_paths:
        candidate = app_path(_normalize_path(rel_path))
        if not _path_has_content(candidate):
            return False

    return True


def get_missing_runtime_packages(feature_key):
    missing = []
    requirements = FEATURE_PACKAGE_REQUIREMENTS.get(
        str(feature_key or "").strip().lower(), []
    )
    for package_key in requirements:
        if not is_runtime_package_ready(package_key):
            missing.append(package_key)
    return missing


def describe_runtime_packages(package_keys):
    labels = []
    for package_key in package_keys:
        entry = get_runtime_package_entry(package_key)
        labels.append(str(entry.get("label") or package_key))
    return ", ".join(labels)


def resolve_runtime_package_source(package_key):
    entry = get_runtime_package_entry(package_key)
    local_candidates = []
    explicit_local_path = str(entry.get("local_path") or "").strip()
    if explicit_local_path:
        if os.path.isabs(explicit_local_path):
            local_candidates.append(explicit_local_path)
        else:
            local_candidates.append(app_path(explicit_local_path))
            local_candidates.append(resource_path(explicit_local_path))

    archive_name = str(entry.get("archive_name") or "").strip()
    if archive_name:
        downloads_dir = ensure_app_subdir("downloads", "runtime_packages")
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

    return ("", "")


def _emit(progress_callback, percent, message):
    if not progress_callback:
        return
    try:
        pct = int(max(0, min(100, percent)))
        msg = str(message or "").strip()
        progress_callback(pct, msg)
    except Exception:
        pass


def _download_url_to_file(url, target_path, package_label, progress_callback):
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    _emit(progress_callback, 0, f"Downloading {package_label}...")

    with (
        urllib.request.urlopen(url) as response,
        open(target_path, "wb") as out_file,
    ):
        try:
            total = int(response.headers.get("Content-Length", 0) or 0)
        except Exception:
            total = 0

        downloaded = 0
        while True:
            chunk = response.read(262144)
            if not chunk:
                break
            out_file.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                percent = int(float(downloaded) / float(total) * 100)
                _emit(
                    progress_callback,
                    percent,
                    f"Downloading {package_label}... {percent}%",
                )

    _emit(progress_callback, 100, f"Downloaded {package_label}.")
    return target_path


def _safe_extract_zip(zip_path, dest_dir):
    dest_root = Path(dest_dir).resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_path = dest_root / member.filename
            resolved = member_path.resolve()
            if (
                os.path.commonpath([str(dest_root), str(resolved)])
                != str(dest_root)
            ):
                raise RuntimeError(
                    f"Refusing to extract unsafe path: {member.filename}"
                )
        zf.extractall(dest_dir)


def install_runtime_packages(package_keys, progress_callback=None):
    app_dir = get_app_dir()
    downloads_dir = ensure_app_subdir("downloads", "runtime_packages")
    installed = []
    total_packages = len(package_keys)

    for idx, package_key in enumerate(package_keys):
        entry = get_runtime_package_entry(package_key)
        package_label = str(entry.get("label") or package_key)
        source_type, source_value = resolve_runtime_package_source(package_key)

        if not source_type:
            raise RuntimeError(
                f"No local archive or download URL for {package_label}."
            )

        package_start = int(idx / total_packages * 100)
        package_end = int((idx + 1) / total_packages * 100)

        def scoped_progress(inner_percent: int, message: str) -> None:
            overall = package_start + int(
                max(0, min(100, inner_percent))
                / 100.0
                * (package_end - package_start)
            )
            _emit(progress_callback, overall, message)

        if source_type == "local":
            archive_path = source_value
            scoped_progress(
                5, f"Using local package: {os.path.basename(archive_path)}"
            )
        else:
            archive_name = str(entry.get("archive_name") or "").strip() or f"{package_key}.zip"
            archive_path = os.path.join(downloads_dir, archive_name)
            _download_url_to_file(
                source_value, archive_path, package_label, scoped_progress
            )

        scoped_progress(75, f"Extracting {package_label}...")
        _safe_extract_zip(archive_path, app_dir)

        if not is_runtime_package_ready(package_key):
            raise RuntimeError(
                f"{package_label} extracted, but required files are still missing."
            )

        scoped_progress(100, f"{package_label} ready.")
        installed.append(package_key)

    return {"installed": installed, "app_dir": app_dir}
