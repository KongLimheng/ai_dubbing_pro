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


def resolve_binary_path(binary_name):
    base_name = os.path.splitext(binary_name)[0]
    if sys.platform != "win32":
        # On Linux/macOS, prefer native system binary over bundled Windows .exe
        which_base = shutil.which(base_name) or shutil.which(binary_name)
        if which_base:
            return which_base
        for candidate in (resource_path(base_name), app_path(base_name)):
            if os.path.exists(candidate) and os.access(candidate, os.X_OK):
                return candidate
    else:
        # On Windows, check local bundled binaries first
        for candidate in (resource_path(binary_name), app_path(binary_name)):
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
