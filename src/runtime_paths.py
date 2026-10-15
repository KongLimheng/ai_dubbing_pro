import os
import sys
import shutil


def is_frozen():
    return getattr(sys, "frozen", False)


def get_bundle_dir():
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_app_dir():
    if is_frozen():
        return os.path.dirname(sys.executable)
    # When running from source, app dir is project root
    here = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(here) == "src":
        return os.path.dirname(here)
    return here


def resource_path(*parts):
    # Check bundle_dir (e.g. src/)
    candidate = os.path.join(get_bundle_dir(), *parts)
    if os.path.exists(candidate):
        return candidate
    # Check app_dir/resources/
    res_cand = os.path.join(get_app_dir(), 'resources', *parts)
    if os.path.exists(res_cand):
        return res_cand
    # Check app_dir/ (project root)
    app_cand = os.path.join(get_app_dir(), *parts)
    if os.path.exists(app_cand):
        return app_cand
    # Check bundle_dir/resources/
    res_cand2 = os.path.join(get_bundle_dir(), 'resources', *parts)
    if os.path.exists(res_cand2):
        return res_cand2
    return candidate



def app_path(*parts):
    return os.path.join(get_app_dir(), *parts)


def ensure_app_subdir(*parts):
    path = app_path(*parts)
    os.makedirs(path, exist_ok=True)
    return path


def is_app_dir_writable() -> bool:
    """Check if the application root directory is writable."""
    app_dir = get_app_dir()
    try:
        test_file = os.path.join(app_dir, f".write_test_{os.getpid()}")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False


def get_user_data_dir(*parts) -> str:
    """
    Return platform-standard writable application data directory.
    - Linux: ~/.local/share/ai-dubber-ultimate
    - Windows: %LOCALAPPDATA%/AI_Dubber_Ultimate
    - macOS: ~/Library/Application Support/AI_Dubber_Ultimate
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        data_dir = os.path.join(base, "AI_Dubber_Ultimate")
    elif sys.platform == "darwin":
        data_dir = os.path.join(os.path.expanduser("~/Library/Application Support"), "AI_Dubber_Ultimate")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        data_dir = os.path.join(base, "ai-dubber-ultimate")

    target = os.path.join(data_dir, *parts) if parts else data_dir
    os.makedirs(target, exist_ok=True)
    return target


def get_user_cache_dir(*parts) -> str:
    """
    Return platform-standard cache directory for downloads and temp files.
    - Linux: ~/.cache/ai-dubber-ultimate
    - Windows: %LOCALAPPDATA%/AI_Dubber_Ultimate/cache (or %TEMP%)
    - macOS: ~/Library/Caches/AI_Dubber_Ultimate
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or os.path.expanduser("~\\AppData\\Local")
        cache_dir = os.path.join(base, "AI_Dubber_Ultimate", "cache")
    elif sys.platform == "darwin":
        cache_dir = os.path.join(os.path.expanduser("~/Library/Caches"), "AI_Dubber_Ultimate")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        cache_dir = os.path.join(base, "ai-dubber-ultimate")

    target = os.path.join(cache_dir, *parts) if parts else cache_dir
    os.makedirs(target, exist_ok=True)
    return target


def get_user_models_dir(*parts) -> str:
    """Return user-writable models directory."""
    return get_user_data_dir("models", *parts)


def get_user_bin_dir(*parts) -> str:
    """Return user-writable binaries directory for downloaded tools (e.g. FFmpeg)."""
    return get_user_data_dir("bin", *parts)


def resolve_binary_path(binary_name):
    """
    Resolve executable binary searching in priority order:
    1. System PATH
    2. User data binary directory (downloaded binaries)
    3. Bundled resource directory (portable / pre-bundled)
    4. Application root directory
    """
    base_name = os.path.splitext(binary_name)[0]
    ext = ".exe" if sys.platform == "win32" else ""
    target_names = [binary_name]
    if base_name != binary_name:
        target_names.append(base_name)
    if ext and not binary_name.endswith(ext):
        target_names.append(binary_name + ext)

    if sys.platform != "win32":
        # On Linux/macOS, prefer native system binary first
        which_bin = shutil.which(base_name) or shutil.which(binary_name)
        if which_bin:
            return which_bin

        # Check user-downloaded binary dir
        for name in target_names:
            candidate = os.path.join(get_user_bin_dir(), name)
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                return candidate

        # Check bundled resources and app directory
        for candidate in (resource_path(base_name), app_path(base_name), resource_path(binary_name), app_path(binary_name)):
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                return candidate
    else:
        # On Windows, check user-downloaded and bundled binaries first
        for name in target_names:
            candidate = os.path.join(get_user_bin_dir(), name)
            if os.path.exists(candidate):
                return candidate

        for candidate in (resource_path(binary_name), app_path(binary_name), resource_path(base_name + ".exe"), app_path(base_name + ".exe")):
            if os.path.exists(candidate):
                return candidate

        which_bin = shutil.which(binary_name) or shutil.which(base_name)
        if which_bin:
            return which_bin

    # Universal fallback
    which_bin = shutil.which(binary_name) or shutil.which(base_name)
    if which_bin:
        return which_bin
    return binary_name

