"""Demucs audio separation runtime resolution and execution support.

Cross-platform support for managed Python Demucs runtimes (CPU/CUDA/Metal/XPU),
bundled model weights repository discovery, device auto-detection, and execution
with automatic fallback from GPU to CPU on out-of-memory or driver error.
"""

from functools import lru_cache
import json
import os
import shutil
import subprocess
import sys

from runtime_paths import app_path, get_bundle_dir, resource_path
from settings_manager import get_app_data_dir

MANAGED_DEMUCS_VARIANTS = ('cuda', 'cpu')
MANAGED_DEMUCS_VARIANT_LABELS = {
    'cuda': 'NVIDIA CUDA',
    'cpu': 'CPU',
}

_DEMUCS_PROBE_SCRIPT = """
import json

payload = {
    "ok": False,
    "demucs_importable": False,
    "torch_importable": False,
    "gpu_available": False,
    "cuda_available": False,
    "cuda_device_count": 0,
    "cuda_device_name": None,
    "preferred_device": "cpu",
    "device_backend": "cpu",
    "torch_version": None,
    "torch_cuda_version": None,
    "torch_hip_version": None,
    "torch_xpu_available": False,
    "torch_mps_available": False,
}

try:
    import demucs
    payload["demucs_importable"] = True
    payload["demucs_version"] = getattr(demucs, "__version__", "")
except Exception as exc:
    payload["error"] = f"demucs import failed: {exc}"

try:
    import torch
    payload["torch_importable"] = True
    payload["torch_version"] = getattr(torch, "__version__", "")
    payload["torch_cuda_version"] = getattr(torch.version, "cuda", None)
    payload["torch_hip_version"] = getattr(torch.version, "hip", None)
    if hasattr(torch, "cuda") and torch.cuda.is_available():
        try:
            # Verify that CUDA kernels can actually execute on this GPU architecture
            # (prevents false positives on older GPUs like Pascal sm_61 when modern torch lacks kernels)
            _test_cuda = torch.zeros(1, device="cuda")
            payload["gpu_available"] = True
            payload["cuda_available"] = True
            payload["preferred_device"] = "cuda"
            payload["device_backend"] = "hip" if payload["torch_hip_version"] else "cuda"
            payload["cuda_device_count"] = int(torch.cuda.device_count())
            try:
                payload["cuda_device_name"] = torch.cuda.get_device_name(0)
            except Exception as exc:
                payload["cuda_name_error"] = str(exc)
        except Exception as _cuda_exec_err:
            payload["gpu_available"] = False
            payload["cuda_available"] = False
            payload["preferred_device"] = "cpu"
            payload["device_backend"] = "cpu"
            payload["cuda_arch_unsupported"] = True
            payload["cuda_error"] = str(_cuda_exec_err)
            try:
                payload["cuda_device_name"] = torch.cuda.get_device_name(0)
            except Exception:
                pass
    else:
        xpu = getattr(torch, "xpu", None)
        if xpu and hasattr(xpu, "is_available") and xpu.is_available():
            payload["gpu_available"] = True
            payload["cuda_available"] = True
            payload["torch_xpu_available"] = True
            payload["preferred_device"] = "xpu"
            payload["device_backend"] = "xpu"
            if hasattr(xpu, "device_count"):
                payload["cuda_device_count"] = int(xpu.device_count())
            try:
                if hasattr(xpu, "get_device_name"):
                    payload["cuda_device_name"] = xpu.get_device_name(0)
            except Exception as exc:
                payload["xpu_name_error"] = str(exc)
        elif (
            hasattr(torch, "backends")
            and hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            payload["gpu_available"] = True
            payload["cuda_available"] = True
            payload["torch_mps_available"] = True
            payload["preferred_device"] = "mps"
            payload["device_backend"] = "mps"
            payload["cuda_device_count"] = 1
            payload["cuda_device_name"] = "Apple Metal"
except Exception as exc:
    payload["torch_error"] = str(exc)

payload["ok"] = bool(payload["demucs_importable"] and payload["torch_importable"])
print(json.dumps(payload))
"""


def get_runtime_base_dir():
    """Return the app base directory in dev and PyInstaller modes."""
    return get_bundle_dir()


def get_demucs_wrapper_path():
    """Return the local Demucs wrapper script if it exists."""
    for candidate in (
        resource_path('demucs_wrapper.py'),
        app_path('src', 'demucs_wrapper.py'),
        resource_path('src', 'demucs_wrapper.py'),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def get_demucs_wrapper_executable_path():
    """Return the bundled Demucs helper executable when packaged."""
    for candidate in (
        app_path('demucs_helper', 'demucs_wrapper.exe'),
        resource_path('demucs_helper', 'demucs_wrapper.exe'),
        app_path('artifacts', 'dist', 'dist_helper', 'demucs_wrapper.exe'),
        app_path('artifacts', 'dist', 'dist_helper', 'demucs_wrapper', 'demucs_wrapper.exe'),
        app_path('artifacts', 'build', 'build_assets', 'demucs_helper', 'demucs_wrapper.exe'),
        app_path('build_assets', 'demucs_helper', 'demucs_wrapper.exe'),
        resource_path('build_assets', 'demucs_helper', 'demucs_wrapper.exe'),
        app_path('demucs_wrapper.exe'),
        resource_path('demucs_wrapper.exe'),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def get_demucs_model_repo_path():
    """Return a bundled local Demucs model repo when available."""
    def _has_model_assets(repo_dir):
        try:
            with os.scandir(repo_dir) as entries:
                for entry in entries:
                    if entry.is_file():
                        lower_name = entry.name.lower()
                        if lower_name.endswith(('.th', '.yaml', '.pt', '.pth')):
                            return True
                    elif entry.is_dir() and _has_model_assets(entry.path):
                        return True
        except Exception:
            pass
        return False

    candidates = (
        resource_path('demucs_repo'),
        resource_path('models', 'demucs'),
        resource_path('build_assets', 'demucs_repo'),
        app_path('demucs_repo'),
        app_path('models', 'demucs'),
        app_path('artifacts', 'build', 'build_assets', 'demucs_repo'),
        app_path('build_assets', 'demucs_repo'),
    )

    for candidate in candidates:
        if os.path.isdir(candidate) and _has_model_assets(candidate):
            return candidate
    return None


def get_managed_demucs_runtime_root(create=True):
    """Return the base directory for managed Demucs virtualenvs."""
    runtime_root = os.path.join(get_app_data_dir(), 'demucs_runtimes')
    if create:
        os.makedirs(runtime_root, exist_ok=True)
    return runtime_root


def get_managed_demucs_runtime_dir(variant):
    """Return the installation directory for a managed Demucs variant."""
    variant_norm = str(variant or 'cpu').strip().lower()
    return os.path.join(get_managed_demucs_runtime_root(create=False), variant_norm)


def remove_managed_demucs_runtime(variant):
    """Remove a managed Demucs virtualenv."""
    runtime_dir = get_managed_demucs_runtime_dir(variant)
    if os.path.isdir(runtime_dir):
        shutil.rmtree(runtime_dir, ignore_errors=True)
    refresh_demucs_runtime_cache()


def get_managed_demucs_python_command(variant):
    """Return the Python executable path for a managed Demucs variant."""
    runtime_dir = get_managed_demucs_runtime_dir(variant)
    for sub, name in (('Scripts', 'python.exe'), ('bin', 'python'), ('bin', 'python3')):
        candidate = os.path.join(runtime_dir, sub, name)
        if os.path.exists(candidate):
            return [candidate]
    return None


def _iter_managed_demucs_python_commands():
    for variant in MANAGED_DEMUCS_VARIANTS:
        cmd = get_managed_demucs_python_command(variant)
        if cmd:
            yield cmd


def _iter_bundled_demucs_python_commands():
    roots = [app_path(), get_bundle_dir(), os.getcwd()]
    for root in list(roots):
        if not root:
            continue
        try:
            parent = os.path.dirname(os.path.abspath(root))
            if parent not in roots:
                roots.append(parent)
        except Exception:
            pass

    relative_dirs = (
        ('demucs_runtime',),
        ('runtime',),
        ('python',),
        ('Python',),
        ('env',),
        ('venv',),
        ('demucs_env',),
    )

    for root in roots:
        for rdir in relative_dirs:
            base = os.path.join(root, *rdir)
            for sub, name in (('Scripts', 'python.exe'), ('bin', 'python'), ('bin', 'python3'), ('', 'python.exe')):
                candidate = os.path.join(base, sub, name) if sub else os.path.join(base, name)
                if os.path.isfile(candidate):
                    yield [candidate]


def _no_window_flag():
    return subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def get_host_python_command():
    """Find a system/host Python interpreter that can create venvs."""
    candidates = []
    if sys.executable and os.path.basename(sys.executable).lower().startswith('python') and os.path.exists(sys.executable):
        candidates.append([sys.executable])
    for py in ('python3', 'python'):
        found = shutil.which(py)
        if found:
            candidates.append([found])
    py_launcher = shutil.which('py')
    if py_launcher:
        candidates.append([py_launcher, '-3'])

    seen = set()
    for candidate in candidates:
        key = tuple(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            kwargs = {'capture_output': True, 'text': True, 'timeout': 15}
            flags = _no_window_flag()
            if flags:
                kwargs['creationflags'] = flags
            result = subprocess.run(candidate + ['-c', 'import sys, venv; print(sys.version)'], **kwargs)
            if result.returncode == 0:
                return candidate
        except Exception:
            continue
    return None


def detect_nvidia_gpu():
    """Probe for NVIDIA GPU via nvidia-smi."""
    payload = {
        'nvidia_gpu_available': False,
        'gpu_name': None,
        'driver_version': None,
    }
    nvidia_smi = shutil.which('nvidia-smi')
    if not nvidia_smi:
        return payload

    try:
        kwargs = {'capture_output': True, 'text': True, 'timeout': 10}
        flags = _no_window_flag()
        if flags:
            kwargs['creationflags'] = flags
        result = subprocess.run([nvidia_smi, '--query-gpu=name,driver_version', '--format=csv,noheader,nounits'], **kwargs)
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(',')]
            payload['nvidia_gpu_available'] = True
            payload['gpu_name'] = parts[0] if parts else 'NVIDIA GPU'
            payload['driver_version'] = parts[1] if len(parts) > 1 else None
    except Exception:
        pass
    return payload


def get_demucs_install_support_info():
    """Inspect environment to advise whether CPU or GPU Demucs runtime is recommended."""
    host_python_cmd = get_host_python_command()
    nvidia_info = detect_nvidia_gpu()
    bundled_runtime = get_bundled_demucs_runtime_info()
    recommended_variant = 'cuda' if nvidia_info.get('nvidia_gpu_available') else 'cpu'

    return {
        'host_python_available': bool(host_python_cmd),
        'host_python_command': host_python_cmd,
        'nvidia_info': nvidia_info,
        'recommended_variant': recommended_variant,
        'recommended_variant_label': MANAGED_DEMUCS_VARIANT_LABELS.get(recommended_variant, recommended_variant),
        'bundled_runtime': bundled_runtime,
    }


def _probe_demucs_python(python_cmd):
    try:
        kwargs = {'capture_output': True, 'text': True, 'timeout': 20}
        flags = _no_window_flag()
        if flags:
            kwargs['creationflags'] = flags
        result = subprocess.run(python_cmd + ['-c', _DEMUCS_PROBE_SCRIPT], **kwargs)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip().splitlines()[-1])
            return data
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    return {'ok': False}


def _probe_bundled_helper(helper_path):
    try:
        kwargs = {'capture_output': True, 'text': True, 'timeout': 20}
        flags = _no_window_flag()
        if flags:
            kwargs['creationflags'] = flags
        result = subprocess.run([helper_path, '--probe-runtime'], **kwargs)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip().splitlines()[-1])
            return data
    except Exception as e:
        return {'ok': False, 'error': str(e)}
    return {'ok': False}


def _build_wrapper_command(python_cmd):
    wrapper_path = get_demucs_wrapper_path()
    if not wrapper_path:
        return None
    return list(python_cmd) + [wrapper_path]


def _runtime_priority(runtime_info):
    score = 0
    if runtime_info.get('ok'):
        score += 100
    if runtime_info.get('gpu_available'):
        score += 50
    if runtime_info.get('source') == 'managed':
        score += 20
    elif runtime_info.get('source') == 'bundled':
        score += 10
    return score


def _runtime_info_from_probe(probe, command, command_type, source, python_cmd=None):
    info = dict(probe or {})
    info.update({
        'command': command,
        'command_type': command_type,
        'source': source,
        'python_cmd': python_cmd,
        'model_repo_path': get_demucs_model_repo_path(),
    })
    return info


@lru_cache(maxsize=1)
def get_bundled_demucs_runtime_info():
    """Inspect whether a pre-packaged Demucs helper binary is bundled with the application."""
    helper = get_demucs_wrapper_executable_path()
    if helper:
        probe = _probe_bundled_helper(helper)
        return _runtime_info_from_probe(probe, [helper], 'executable', 'bundled_helper')
    return {'ok': False, 'path': None}


def _iter_demucs_python_commands():
    yield from _iter_managed_demucs_python_commands()
    yield from _iter_bundled_demucs_python_commands()
    host_cmd = get_host_python_command()
    if host_cmd:
        yield host_cmd


@lru_cache(maxsize=1)
def get_demucs_runtime_info():
    """Find the highest-priority operational Demucs runtime available."""
    runtimes = []

    # 1. Bundled helper
    bundled = get_bundled_demucs_runtime_info()
    if bundled.get('ok'):
        runtimes.append(bundled)

    # 2. Python commands
    seen_cmds = set()
    for py_cmd in _iter_demucs_python_commands():
        key = tuple(py_cmd)
        if key in seen_cmds:
            continue
        seen_cmds.add(key)
        wrapper_cmd = _build_wrapper_command(py_cmd)
        if not wrapper_cmd:
            continue
        probe = _probe_demucs_python(py_cmd)
        if probe.get('ok'):
            source = 'managed' if any('demucs_runtimes' in p for p in py_cmd) else 'python'
            runtimes.append(_runtime_info_from_probe(probe, wrapper_cmd, 'python_wrapper', source, py_cmd))

    if runtimes:
        runtimes.sort(key=_runtime_priority, reverse=True)
        return runtimes[0]

    # Fallback to direct python wrapper if available
    host_cmd = get_host_python_command() or [sys.executable]
    wrapper_cmd = _build_wrapper_command(host_cmd)
    if wrapper_cmd:
        return {
            'ok': True,
            'command': wrapper_cmd,
            'command_type': 'python_wrapper',
            'preferred_device': 'auto',
            'gpu_available': False,
            'model_repo_path': get_demucs_model_repo_path(),
        }

    return {
        'ok': False,
        'command': [sys.executable, '-m', 'demucs'],
        'command_type': 'module',
        'preferred_device': 'cpu',
        'gpu_available': False,
        'model_repo_path': get_demucs_model_repo_path(),
    }


def refresh_demucs_runtime_cache():
    """Clear cached runtime discoveries."""
    get_bundled_demucs_runtime_info.cache_clear()
    get_demucs_runtime_info.cache_clear()


def get_demucs_runtime_manager_state():
    """Return dictionary summarizing runtime state for UI."""
    return {
        'info': get_demucs_runtime_info(),
        'install_support': get_demucs_install_support_info(),
        'model_repo': get_demucs_model_repo_path(),
    }


def get_demucs_command():
    """Return base command array for launching Demucs."""
    return list(get_demucs_runtime_info().get('command', [sys.executable, '-m', 'demucs']))


def get_demucs_execution_profile():
    """Return profile info for current Demucs execution environment."""
    info = get_demucs_runtime_info()
    pref = str(info.get('preferred_device', 'cpu') or 'cpu').lower()
    return {
        'preferred_device': pref,
        'gpu_available': bool(info.get('gpu_available', False)),
        'device_backend': info.get('device_backend', 'cpu'),
        'model_repo': get_demucs_model_repo_path(),
    }


def build_demucs_command(extra_args=None, device=None):
    """Build the final CLI command argument list for Demucs inference."""
    runtime_info = get_demucs_runtime_info()
    command = list(runtime_info.get('command', [sys.executable, '-m', 'demucs']))
    args = list(extra_args or [])

    # Inject model repository path if available
    has_repo_arg = any(arg == '--repo' or arg.startswith('--repo=') for arg in args)
    repo_path = get_demucs_model_repo_path()
    if repo_path and not has_repo_arg:
        command.extend(['--repo', repo_path])

    # Inject device flag
    has_device_arg = any(arg in ('-d', '--device') or arg.startswith('--device=') for arg in args)
    selected_device = device or runtime_info.get('preferred_device', 'auto')
    if selected_device and selected_device != 'auto' and not has_device_arg:
        command.extend(['-d', selected_device])

    command.extend(args)
    return command


def _result_text(result):
    chunks = []
    for name in ('stdout', 'stderr'):
        val = getattr(result, name, None)
        if isinstance(val, bytes):
            chunks.append(val.decode('utf-8', errors='ignore'))
        elif isinstance(val, str):
            chunks.append(val)
    return '\n'.join(chunks)


def _should_retry_on_cpu(result):
    output = _result_text(result).lower()
    if not output:
        return True
    cuda_markers = (
        'cuda', 'cudnn', 'cublas', 'nvidia', 'xpu', 'oneapi', 'sycl',
        'out of memory', 'device-side assert', 'not compiled with cuda',
        'no kernel image', 'hip', 'mps'
    )
    return any(marker in output for marker in cuda_markers)


def _run_demucs_process(command, process_callback=None, **run_kwargs):
    popen_kwargs = dict(run_kwargs)
    capture_output = bool(popen_kwargs.pop('capture_output', False))
    timeout = popen_kwargs.pop('timeout', None)
    check = bool(popen_kwargs.pop('check', False))
    input_data = popen_kwargs.pop('input', None)

    process_env = dict(os.environ)
    process_env.update(popen_kwargs.pop('env', {}) or {})
    process_env.setdefault('PYTHONIOENCODING', 'utf-8')
    process_env.setdefault('PYTHONUTF8', '1')

    flags = _no_window_flag()
    if flags:
        popen_kwargs.setdefault('creationflags', flags)

    if capture_output:
        popen_kwargs['stdout'] = subprocess.PIPE
        popen_kwargs['stderr'] = subprocess.PIPE

    proc = subprocess.Popen(command, env=process_env, **popen_kwargs)
    if process_callback and callable(process_callback):
        process_callback(proc)

    try:
        stdout_data, stderr_data = proc.communicate(input=input_data, timeout=timeout)
        ret = subprocess.CompletedProcess(command, proc.returncode, stdout_data, stderr_data)
        if check and ret.returncode != 0:
            raise subprocess.CalledProcessError(ret.returncode, command, output=ret.stdout, stderr=ret.stderr)
        return ret
    except Exception:
        proc.kill()
        raise


def run_demucs_command(extra_args=None, retry_on_cpu=True, cancel_check=None, process_callback=None, **run_kwargs):
    """Run Demucs separation, automatically retrying with CPU on GPU out-of-memory or driver errors."""
    runtime_info = get_demucs_runtime_info()
    initial_device = runtime_info.get('preferred_device', 'auto')
    initial_command = build_demucs_command(extra_args, device=initial_device)

    result = _run_demucs_process(initial_command, process_callback=process_callback, **run_kwargs)

    metadata = {
        'runtime': runtime_info,
        'attempts': [{
            'device': initial_device or 'auto',
            'command': initial_command,
            'returncode': result.returncode,
        }],
        'cpu_fallback_used': False,
    }

    if cancel_check and cancel_check():
        return result, metadata

    if retry_on_cpu and initial_device not in ('', 'cpu', None) and result.returncode != 0 and _should_retry_on_cpu(result):
        cpu_command = build_demucs_command(extra_args, device='cpu')
        cpu_result = _run_demucs_process(cpu_command, process_callback=process_callback, **run_kwargs)
        metadata['attempts'].append({
            'device': 'cpu',
            'command': cpu_command,
            'returncode': cpu_result.returncode,
        })
        metadata['cpu_fallback_used'] = True
        return cpu_result, metadata

    return result, metadata
