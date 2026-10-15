# -*- coding: utf-8 -*-
"""
core_app module wrapper.
Loads native compiled bytecode from core_app.pyc with cross-platform runtime support.
Includes native Linux/macOS/Windows dependency resolution and installer workers.
"""

from batch_loader import create_enhanced_batch_mapping_dialog_class, scan_folder_for_media
import settings_manager
import voice_clone
import voxcpm_support
import os
import sys
import marshal
import types
import shutil
import subprocess

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QDialog, QMessageBox, QVBoxLayout

try:
    from utils import apply_khmer_font_patch
    apply_khmer_font_patch()
except Exception:
    pass

_CP1252_TO_BYTE = {}
for _b in range(256):
    try:
        _ch = bytes([_b]).decode('cp1252')
        _CP1252_TO_BYTE[_ch] = _b
    except Exception:
        # The 5 unassigned bytes in Windows-1252: 0x81, 0x8d, 0x8f, 0x90, 0x9d
        _CP1252_TO_BYTE[chr(_b)] = _b


def _fix_mojibake(s):
    if not isinstance(s, str):
        return s
    for _ in range(4):
        try:
            barr = bytearray()
            for ch in s:
                if ch in _CP1252_TO_BYTE:
                    barr.append(_CP1252_TO_BYTE[ch])
                elif ord(ch) < 256:
                    barr.append(ord(ch))
                else:
                    raise ValueError('Non-byte char: ' + ch)
            s_cand = barr.decode('utf-8')
            s = s_cand
        except Exception:
            break
    return s


def _sanitize_code(co):
    new_consts = []
    for c in co.co_consts:
        if isinstance(c, str):
            fixed = _fix_mojibake(c)
            if fixed == 'Arial':
                fixed = 'Noto Sans Khmer'
            new_consts.append(fixed)
        elif hasattr(c, 'co_code'):
            new_consts.append(_sanitize_code(c))
        else:
            new_consts.append(c)
    try:
        return co.replace(co_consts=tuple(new_consts))
    except Exception:
        return co


def _find_pyc(filename: str) -> str:
    candidates = [
        os.path.join(os.path.dirname(__file__), filename),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), filename),
        os.path.join(getattr(sys, '_MEIPASS', ''), 'src', filename),
        os.path.join(getattr(sys, '_MEIPASS', ''), filename),
        os.path.join(os.path.dirname(sys.executable), '_internal', 'src', filename),
        os.path.join(os.path.dirname(sys.executable), '_internal', filename),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return os.path.join(os.path.dirname(__file__), filename)


_pyc_path = _find_pyc('core_app.pyc')
if not os.path.exists(_pyc_path):
    raise FileNotFoundError(f"Missing compiled bytecode module: {_pyc_path}")

with open(_pyc_path, 'rb') as _f:
    _f.read(16)
    _raw_code = marshal.load(_f)

_cleaned_code = _sanitize_code(_raw_code)
_mod = types.ModuleType(__name__)
_mod.__file__ = _pyc_path
sys.modules[__name__] = _mod
exec(_cleaned_code, _mod.__dict__)


def pick_funasr_python():
    """
    Cross-platform resolution for FunASR Python executable.
    Never returns non-executable Windows .exe stubs on Linux/macOS.
    """
    from runtime_paths import get_app_dir, get_bundle_dir
    from settings_manager import get_local_tsb_config

    def _is_runnable(p):
        if not p or not isinstance(p, str):
            return False
        p = p.strip().strip('"').strip("'")
        if not p:
            return False
        if os.name != 'nt' and p.lower().endswith('.exe'):
            return False
        if os.path.isfile(p):
            if os.name == 'nt' or os.access(p, os.X_OK):
                return True
        return False

    def _has_funasr(p):
        if not _is_runnable(p):
            return False
        try:
            if os.path.samefile(p, sys.executable):
                import importlib.util as _u
                return bool(_u.find_spec('funasr') and _u.find_spec('torch'))
        except Exception:
            pass
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            res = subprocess.run(
                [p, '-c',
                    'import importlib.util as u, sys; sys.exit(0 if (u.find_spec("funasr") and u.find_spec("torch")) else 1)'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=6,
                creationflags=flags
            )
            return res.returncode == 0
        except Exception:
            return False

    # 1. FUNASR_PYTHON environment variable
    env_py = os.environ.get('FUNASR_PYTHON', '').strip().strip('"').strip("'")
    if env_py and _is_runnable(env_py):
        return env_py

    # 2. Configured python_path in settings
    try:
        cfg = get_local_tsb_config() or {}
        saved = cfg.get('python_path', '').strip().strip('"').strip("'")
        if saved and _has_funasr(saved):
            return saved
    except Exception:
        pass

    # 3. Active interpreter (sys.executable) if ready
    if _has_funasr(sys.executable):
        return sys.executable

    # 4. Project-local virtual environments
    app_dir = get_app_dir()
    bundle_dir = get_bundle_dir()
    bases = [b for b in (app_dir, bundle_dir, os.getcwd()) if b]
    candidate_subpaths = []
    if os.name == 'nt':
        candidate_subpaths = [
            os.path.join('.venv', 'Scripts', 'python.exe'),
            os.path.join('data_venv', 'Scripts', 'python.exe'),
            os.path.join('funasr_venv', 'Scripts', 'python.exe'),
            os.path.join('_internal', 'data_venv', 'Scripts', 'python.exe'),
            os.path.join('data_venv', 'python.exe'),
        ]
    else:
        candidate_subpaths = [
            os.path.join('.venv', 'bin', 'python3'),
            os.path.join('.venv', 'bin', 'python'),
            os.path.join('data_venv', 'bin', 'python3'),
            os.path.join('data_venv', 'bin', 'python'),
            os.path.join('funasr_venv', 'bin', 'python3'),
            os.path.join('funasr_venv', 'bin', 'python'),
        ]

    for base in bases:
        for sub in candidate_subpaths:
            cand = os.path.normpath(os.path.join(base, sub))
            if _has_funasr(cand):
                return cand

    # 5. System PATH python if ready
    for cmd in (['python3', 'python'] if os.name != 'nt' else ['python', 'py']):
        found = shutil.which(cmd)
        if found and _has_funasr(found):
            return found

    # 6. Fallback target to install into (prefer active venv sys.executable)
    if _is_runnable(sys.executable):
        return sys.executable
    for base in bases:
        for sub in candidate_subpaths:
            cand = os.path.normpath(os.path.join(base, sub))
            if _is_runnable(cand):
                return cand

    return shutil.which('python3') or shutil.which('python') or 'python'


class CrossPlatformPythonFunASRInstallWorker(QThread):
    """
    Cross-platform worker for installing FunASR, PyTorch (CUDA/CPU), and dependencies.
    Eliminates Windows-only batch scripts on Linux/macOS while providing full real-time progress.
    """
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            self.progress.emit("Starting setup: Python, FunASR & PyTorch...")
            self.progress_value.emit(5)

            target_python = pick_funasr_python()
            if not target_python or target_python == 'python':
                target_python = sys.executable

            self.progress.emit(f"Found compatible Python at: {target_python}")
            self.progress_value.emit(10)

            # Detect GPU
            self.progress.emit("Detecting NVIDIA GPU...")
            self.progress_value.emit(15)

            gpu_name = ""
            driver_version = ""
            cuda_label = "CPU only"
            torch_index = None

            nvidia_smi = shutil.which("nvidia-smi")
            if nvidia_smi:
                try:
                    res = subprocess.run(
                        [nvidia_smi, "--query-gpu=name,driver_version",
                            "--format=csv,noheader"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        first_line = res.stdout.strip().splitlines()[0]
                        parts = [p.strip() for p in first_line.split(",")]
                        if len(parts) >= 2:
                            gpu_name, driver_version = parts[0], parts[1]
                        elif len(parts) == 1:
                            gpu_name = parts[0]
                except Exception:
                    pass

            if gpu_name:
                self.progress.emit(
                    f"Found GPU: {gpu_name} - Driver Version: {driver_version}")
                driver_major = 0
                try:
                    driver_major = int(driver_version.split(".")[0])
                except Exception:
                    pass

                if driver_major >= 528:
                    torch_index = "https://download.pytorch.org/whl/cu126"
                    cuda_label = "CUDA 12.6"
                else:
                    torch_index = "https://download.pytorch.org/whl/cu118"
                    cuda_label = "CUDA 11.8"

                self.progress.emit(f"Selected CUDA Backend: {cuda_label}")
            else:
                self.progress.emit(
                    "No NVIDIA GPU/driver detected. PyTorch will be installed for CPU execution.")
                torch_index = "https://download.pytorch.org/whl/cpu"
                cuda_label = "CPU only"

            self.progress_value.emit(20)

            uv_bin = shutil.which("uv")
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

            def _run_cmd(cmd, base_val, max_val, title):
                self.progress.emit(title)
                self.progress_value.emit(base_val)
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=flags
                )
                curr = base_val
                for line in iter(proc.stdout.readline, ''):
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    self.progress.emit(line_clean[:120])
                    if curr < max_val:
                        curr = min(max_val, curr + 1)
                        self.progress_value.emit(curr)
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"Installation failed (code {proc.returncode}): {' '.join(cmd)}")

            # [1/2] Install PyTorch
            if uv_bin:
                cmd_torch = [uv_bin, "pip", "install", "--python",
                             target_python, "torch", "torchaudio"]
                if torch_index:
                    cmd_torch += ["--index-url", torch_index]
            else:
                cmd_torch = [target_python, "-m", "pip",
                             "install", "torch", "torchaudio"]
                if torch_index:
                    cmd_torch += ["--index-url", torch_index]

            _run_cmd(cmd_torch, 25, 60,
                     f"[1/2] Installing FunASR + PyTorch ({cuda_label})")

            # [2/2] Install FunASR, HuggingFace Hub, & Pydantic
            if uv_bin:
                cmd_funasr = [uv_bin, "pip", "install", "--python",
                              target_python, "funasr", "huggingface_hub", "pydantic"]
            else:
                cmd_funasr = [target_python, "-m", "pip",
                              "install", "funasr", "huggingface_hub", "pydantic"]

            _run_cmd(cmd_funasr, 65, 88,
                     "Installing FunASR and HuggingFace Hub...")

            # Verification
            self.progress.emit("Final Verification...")
            self.progress_value.emit(92)
            verify_cmd = [
                target_python,
                "-c",
                "import torch, funasr; print('PyTorch:', torch.__version__, 'CUDA:', torch.cuda.is_available())"
            ]
            verify_res = subprocess.run(verify_cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, timeout=20, creationflags=flags)
            if verify_res.returncode == 0:
                self.progress.emit("[OK] FunASR + PyTorch installed.")
                self.progress_value.emit(95)
            else:
                raise RuntimeError(
                    f"Verification failed: {verify_res.stderr or verify_res.stdout}")

            # Persist configuration
            try:
                from settings_manager import save_local_tsb_config
                save_local_tsb_config(device='auto', python_path=target_python)
            except Exception:
                pass

            self.progress.emit("Setup Completed Successfully")
            self.progress_value.emit(100)
            self.finished.emit(True)

        except Exception as e:
            self.error.emit(str(e))


def _dl_python_funasr_cross_platform(self):
    """Seamless in-dialog download and installation for Python & FunASR."""
    reply = QMessageBox.question(
        self,
        "Install Python & FunASR",
        "Would you like to automatically install FunASR and PyTorch for local speech recognition?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes
    )
    if reply == QMessageBox.Yes:
        self.install_queue = ['python']
        self.btn_check.setEnabled(False)
        self.btn_autoinstall.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.progress_widget.show()
        self.run_next_install()


def _on_python_install_finished_cross_platform(self):
    """Handle successful installation of Python/FunASR, configure path, and continue queue."""
    from settings_manager import save_local_tsb_config
    target_py = pick_funasr_python()
    if not target_py or target_py == 'python':
        target_py = sys.executable

    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        res = subprocess.run([target_py, '-c', 'import funasr, torch'], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, timeout=5, creationflags=flags)
        if res.returncode == 0:
            save_local_tsb_config(device='auto', python_path=target_py)
    except Exception:
        pass

    self.run_next_install()


_orig_run_step_check = _mod.DependencyCheckDialog.run_step_check


def _run_step_check_cross_platform(self, step):
    """Platform-aware dependency step check (FFmpeg in step 0, FunASR in step 1)."""
    if step == 0:
        self.step_frame_count = 0
        has_ffmpeg = False
        try:
            from utils import get_ffmpeg_path
            ff = get_ffmpeg_path()
            if ff and (os.path.isfile(ff) or shutil.which(ff)):
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                res = subprocess.run([ff, '-version'], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, timeout=5, creationflags=flags)
                if res.returncode == 0:
                    has_ffmpeg = True
        except Exception:
            pass

        if has_ffmpeg:
            self.c0_status.setText("Ready")
            self.c0_status.setStyleSheet("color: #48BB78;")
            self.btn_dl0.setEnabled(False)
            self.btn_dl0.setText("Ready")
        else:
            self.c0_status.setText("Missing")
            self.c0_status.setStyleSheet("color: #F56565;")
            self.btn_dl0.setEnabled(True)
            self.btn_dl0.setText("Download FFmpeg")

        self.scan_step = 1
        return

    return _orig_run_step_check(self, step)


def check_system_components(fast=True):
    """
    Checks the status of all 4 required system components:
    1. FFmpeg: binary exists and runs.
    2. FunASR Python: python executable with funasr and torch.
    3. Demucs: runtime available and importable.
    4. VoxCPM2: runtime and model files available.
    Returns:
        (all_ready: bool, missing_components: list[str])
    """
    missing = []

    # 1. FFmpeg
    has_ffmpeg = False
    try:
        from utils import get_ffmpeg_path
        ff = get_ffmpeg_path()
        if ff and (os.path.isfile(ff) or shutil.which(ff)):
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            res = subprocess.run([ff, '-version'], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=5, creationflags=flags)
            if res.returncode == 0:
                has_ffmpeg = True
    except Exception:
        pass
    if not has_ffmpeg:
        missing.append('ffmpeg')

    # 2. FunASR Python
    has_funasr = False
    try:
        py = pick_funasr_python()
        if py and os.path.isfile(py):
            try:
                if os.path.samefile(py, sys.executable):
                    import importlib.util as _u
                    has_funasr = bool(_u.find_spec('funasr')
                                      and _u.find_spec('torch'))
            except Exception:
                pass
            if not has_funasr:
                flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                res = subprocess.run(
                    [py, '-c',
                        'import importlib.util as u, sys; sys.exit(0 if (u.find_spec("funasr") and u.find_spec("torch")) else 1)'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=6,
                    creationflags=flags
                )
                if res.returncode == 0:
                    has_funasr = True
    except Exception:
        pass
    if not has_funasr:
        missing.append('python')

    # 3. Demucs
    has_demucs = False
    try:
        import demucs_support
        info = demucs_support.get_demucs_runtime_info()
        if info and info.get('ok') and info.get('source') not in ('demucs_path_fallback', '', None):
            has_demucs = True
    except Exception:
        pass
    if not has_demucs:
        missing.append('demucs')

    # 4. VoxCPM2 (checked if VoxCPM2 is enabled)
    if getattr(_mod, 'VOXCPM2_UI_ENABLED', True):
        has_voxcpm = False
        try:
            import voxcpm_support
            status = voxcpm_support.get_voxcpm_install_status()
            if status and (status.get('ready') or status.get('installed')):
                has_voxcpm = True
        except Exception:
            pass
        if not has_voxcpm:
            missing.append('voxcpm')

    return (len(missing) == 0, missing)


_orig_check_dependencies_on_startup = _mod.DubbingApp.check_dependencies_on_startup


def _check_dependencies_on_startup_patched(self, force_missing=None):
    """
    Startup dependency verification:
    - Auto-checks all system components.
    - If all installed -> does not popup any dialog.
    - If any missing -> pops up DependencyCheckDialog and automatically installs them.
    """
    if force_missing is not None:
        all_ready = (len(force_missing) == 0)
        missing = list(force_missing)
    else:
        all_ready, missing = check_system_components()

    if all_ready:
        print('[INFO] All system components (FFmpeg, FunASR, Demucs, VoxCPM2) are installed and ready. Skipping startup dialog.')
        return

    print(
        f'[INFO] Missing system components detected: {missing}. Opening auto-installer...')
    dialog = _mod.DependencyCheckDialog(
        self, auto_install=True, missing_items=missing)
    dialog.exec_()


# Apply patches to core_app
_mod.PythonFunASRInstallWorker = CrossPlatformPythonFunASRInstallWorker  # type: ignore
_mod.DependencyCheckDialog.dl_python_funasr = _dl_python_funasr_cross_platform
_mod.DependencyCheckDialog._pick_funasr_python = lambda self: pick_funasr_python()
_mod.DependencyCheckDialog.on_python_install_finished = _on_python_install_finished_cross_platform
_mod.DependencyCheckDialog.run_step_check = _run_step_check_cross_platform
_mod.TranscriptionWorker._pick_funasr_python = lambda self: pick_funasr_python()
_mod.DubbingApp.check_dependencies_on_startup = _check_dependencies_on_startup_patched

# Ensure window icons and responsive layout on DubbingApp and DependencyCheckDialog
_orig_dubbing_init = _mod.DubbingApp.__init__


def _dubbing_init_patched(self, *args, **kwargs):
    _orig_dubbing_init(self, *args, **kwargs)
    self.setStyleSheet("")
    from runtime_paths import resource_path
    from PyQt5.QtGui import QIcon
    for name in ('icon.png', 'icon.ico'):
        ip = resource_path(name)
        if os.path.exists(ip):
            self.setWindowIcon(QIcon(ip))
            break

    # Clean window title
    try:
        cur_title = self.windowTitle()
        if cur_title:
            self.setWindowTitle(_fix_mojibake(cur_title))
    except Exception:
        pass

    # Responsive layout reorganization (eliminate bottom horizontal scrollbar on 1920x1080)
    try:
        from PyQt5.QtWidgets import QHBoxLayout, QGridLayout, QWidget, QGroupBox
        cw = self.centralWidget()
        if cw and hasattr(cw, 'widget') and cw.widget():
            content = cw.widget()
            c_layout = content.layout()
            if c_layout and c_layout.count() >= 2:
                right_item = c_layout.itemAt(1)
                right_col = right_item.layout() if right_item else None

                if right_col and right_col.count() >= 2:
                    tb_item = right_col.itemAt(1)
                    toolbar = tb_item.layout() if tb_item else None

                    if toolbar and toolbar.count() > 6:
                        tools_widgets = []
                        while toolbar.count() > 6:
                            it = toolbar.takeAt(6)
                            if it and it.widget():
                                tools_widgets.append(it.widget())
                        if tools_widgets:
                            row2 = QHBoxLayout()
                            row2.setSpacing(6)
                            for w in tools_widgets:
                                row2.addWidget(w)

                            # Theme toggle button
                            try:
                                from PyQt5.QtWidgets import QPushButton
                                from theme_manager import get_theme_mode, toggle_theme

                                current_theme = get_theme_mode()
                                btn_text = "☀️ Light Mode" if current_theme == "dark" else "🌙 Dark Mode"
                                self.btn_theme_toggle = QPushButton(btn_text)
                                self.btn_theme_toggle.setObjectName(
                                    "btn_theme_toggle")
                                self.btn_theme_toggle.setToolTip(
                                    "Toggle Dark / Light Mode")

                                def _on_toggle_theme():
                                    new_theme = toggle_theme(self)
                                    self.btn_theme_toggle.setText(
                                        "☀️ Light Mode" if new_theme == "dark" else "🌙 Dark Mode")

                                self.btn_theme_toggle.clicked.connect(
                                    _on_toggle_theme)
                                row2.addWidget(self.btn_theme_toggle)
                            except Exception as _th_e:
                                print(
                                    '[WARN] Theme toggle button init error:', _th_e)

                            # Social Post button near toggle theme button
                            try:
                                self.btn_social_post = QPushButton("📢 Social Post")
                                self.btn_social_post.setObjectName("btn_social_post")
                                self.btn_social_post.setToolTip("Publish video to Facebook Page, YouTube, TikTok")
                                self.btn_social_post.clicked.connect(lambda: self._open_social_post_window())
                                row2.addWidget(self.btn_social_post)
                            except Exception as _sp_e:
                                print('[WARN] Social post button init error:', _sp_e)

                            # VoxCPM TTS Generation button in toolbar
                            try:
                                self.btn_voxcpm_tts = QPushButton("🎙️ VoxCPM TTS")
                                self.btn_voxcpm_tts.setObjectName("btn_voxcpm_tts")
                                self.btn_voxcpm_tts.setToolTip("Generate TTS audio for all segments using VoxCPM2")
                                self.btn_voxcpm_tts.clicked.connect(lambda: self.generate_all_segments_tts_with_voxcpm())
                                row2.addWidget(self.btn_voxcpm_tts)
                            except Exception as _vx_e:
                                print('[WARN] VoxCPM TTS button init error:', _vx_e)

                            row2.addStretch()
                            right_col.insertLayout(2, row2)

                # Wrap Table, Timeline Editor, and Video Effects into a unified 3-pane resizable vertical QSplitter
                try:
                    from PyQt5.QtWidgets import QSplitter, QTableWidget, QScrollArea, QFrame, QPushButton
                    from PyQt5.QtCore import Qt
                    from settings_manager import (
                        get_main_splitter_sizes, save_main_splitter_sizes,
                        get_video_effects_collapsed, save_video_effects_collapsed
                    )

                    table_widget = None
                    timeline_widget = None
                    ve_gb = None
                    table_idx = -1

                    for idx in range(right_col.count()):
                        it = right_col.itemAt(idx)
                        if it and it.widget():
                            w = it.widget()
                            if isinstance(w, QTableWidget):
                                table_widget = w
                                table_idx = idx
                            elif isinstance(w, QGroupBox) and 'Timeline' in w.title():
                                timeline_widget = w
                            elif isinstance(w, QGroupBox) and 'Video Effects' in w.title():
                                ve_gb = w

                    if not ve_gb:
                        for gb in self.findChildren(QGroupBox):
                            if 'Video Effects' in gb.title():
                                ve_gb = gb
                                break

                    # 1. Reorganize Video Effects into a scrollable, compact 2x2 container
                    ve_scroll = None
                    if ve_gb:
                        ve_layout = ve_gb.layout()
                        if ve_layout and ve_layout.count() >= 7:
                            blur_item = ve_layout.takeAt(0)
                            div1 = ve_layout.takeAt(0)
                            text_item = ve_layout.takeAt(0)
                            div2 = ve_layout.takeAt(0)
                            logo_item = ve_layout.takeAt(0)
                            div3 = ve_layout.takeAt(0)
                            burn_item = ve_layout.takeAt(0)

                            grid = QGridLayout()
                            grid.setSpacing(8)
                            grid.setContentsMargins(4, 4, 4, 4)

                            if blur_item:
                                if blur_item.layout():
                                    grid.addLayout(blur_item.layout(), 0, 0)
                                elif blur_item.widget():
                                    grid.addWidget(blur_item.widget(), 0, 0)
                            if text_item:
                                if text_item.layout():
                                    grid.addLayout(text_item.layout(), 0, 1)
                                elif text_item.widget():
                                    grid.addWidget(text_item.widget(), 0, 1)
                            if logo_item:
                                if logo_item.layout():
                                    grid.addLayout(logo_item.layout(), 1, 0)
                                elif logo_item.widget():
                                    grid.addWidget(logo_item.widget(), 1, 0)
                            if burn_item:
                                if burn_item.layout():
                                    grid.addLayout(burn_item.layout(), 1, 1)
                                elif burn_item.widget():
                                    grid.addWidget(burn_item.widget(), 1, 1)

                            # Clean old layout
                            QWidget().setLayout(ve_layout)

                            # Create scrollable wrapper
                            grid_container = QWidget()
                            grid_container.setLayout(grid)

                            ve_scroll = QScrollArea()
                            ve_scroll.setObjectName("ve_scroll_area")
                            ve_scroll.setWidgetResizable(True)
                            ve_scroll.setFrameShape(QFrame.NoFrame)
                            ve_scroll.setHorizontalScrollBarPolicy(
                                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                            ve_scroll.setVerticalScrollBarPolicy(
                                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
                            ve_scroll.setWidget(grid_container)
                            ve_scroll.setStyleSheet(
                                "QScrollArea { background: transparent; border: none; }")

                            # Build new header and scroll layout for ve_gb
                            ve_new_layout = QVBoxLayout(ve_gb)
                            ve_new_layout.setContentsMargins(6, 2, 6, 4)
                            ve_new_layout.setSpacing(2)

                            hdr_layout = QHBoxLayout()
                            hdr_layout.setContentsMargins(0, 0, 0, 0)
                            hdr_layout.setSpacing(8)

                            btn_toggle_effects = QPushButton(
                                "▼ Collapse Effects")
                            btn_toggle_effects.setObjectName(
                                "btn_toggle_effects")
                            btn_toggle_effects.setToolTip(
                                "Collapse or expand the Video Effects panel")
                            btn_toggle_effects.setStyleSheet("""
                                QPushButton#btn_toggle_effects {
                                    background-color: #1a2230;
                                    color: #f1f5f9;
                                    border: 1px solid #2b394f;
                                    font-size: 11px;
                                    font-weight: bold;
                                    border-radius: 6px;
                                    padding: 2px 10px;
                                }
                                QPushButton#btn_toggle_effects:hover {
                                    border-color: #f97316;
                                    background-color: #1e293b;
                                    color: #ffffff;
                                }
                            """)
                            btn_toggle_effects.setFixedHeight(24)
                            hdr_layout.addStretch()
                            hdr_layout.addWidget(btn_toggle_effects)

                            ve_new_layout.addLayout(hdr_layout)
                            ve_new_layout.addWidget(ve_scroll, 1)

                            ve_gb.setMinimumHeight(44)
                            ve_gb._scroll = ve_scroll
                            ve_gb._btn_toggle = btn_toggle_effects
                            ve_gb._is_collapsed = False
                            ve_gb._last_expanded_height = 160

                    # 2. Assemble 3-pane QSplitter
                    if table_widget and timeline_widget and table_idx >= 0:
                        right_col.removeWidget(table_widget)
                        right_col.removeWidget(timeline_widget)
                        if ve_gb:
                            right_col.removeWidget(ve_gb)

                        splitter = QSplitter(Qt.Orientation.Vertical)
                        splitter.setObjectName('main_vertical_splitter')
                        splitter.addWidget(table_widget)
                        splitter.addWidget(timeline_widget)
                        if ve_gb:
                            splitter.addWidget(ve_gb)

                        splitter.setChildrenCollapsible(False)
                        splitter.setHandleWidth(8)

                        table_widget.setMinimumHeight(100)
                        timeline_widget.setMinimumHeight(100)

                        # Set split vertical cursor on both handles
                        h1 = splitter.handle(1)
                        if h1:
                            h1.setCursor(Qt.CursorShape.SplitVCursor)
                        if ve_gb:
                            h2 = splitter.handle(2)
                            if h2:
                                h2.setCursor(Qt.CursorShape.SplitVCursor)

                        splitter.setStyleSheet("""
                            QSplitter::handle:vertical {
                                background-color: #212936;
                                height: 6px;
                                margin: 1px 0px;
                                border-radius: 3px;
                            }
                            QSplitter::handle:vertical:hover {
                                background-color: #f97316;
                            }
                        """)

                        right_col.insertWidget(table_idx, splitter)
                        right_col.setStretch(table_idx, 1)
                        self.main_vertical_splitter = splitter

                        # Splitter stretch factors (prioritize Table and Timeline)
                        splitter.setStretchFactor(0, 3)
                        splitter.setStretchFactor(1, 2)
                        if ve_gb:
                            splitter.setStretchFactor(2, 0)

                        # Wire collapse/expand button if present
                        if ve_gb and hasattr(ve_gb, '_btn_toggle') and ve_scroll:
                            def _toggle_effects_action():
                                is_col = getattr(ve_gb, '_is_collapsed', False)
                                cur_sizes = splitter.sizes()
                                if is_col:
                                    # Expand
                                    ve_scroll.show()
                                    ve_gb._btn_toggle.setText(
                                        "▼ Collapse Effects")
                                    ve_gb._is_collapsed = False
                                    save_video_effects_collapsed(False)
                                    target_h = getattr(
                                        ve_gb, '_last_expanded_height', 160)
                                    if target_h < 60:
                                        target_h = 160
                                    if len(cur_sizes) >= 3:
                                        total = sum(cur_sizes)
                                        rem = max(150, total - target_h)
                                        t_h = int(rem * 0.58)
                                        tl_h = rem - t_h
                                        splitter.setSizes(
                                            [t_h, tl_h, target_h])
                                else:
                                    # Collapse
                                    if len(cur_sizes) >= 3 and cur_sizes[2] > 50:
                                        ve_gb._last_expanded_height = cur_sizes[2]
                                    ve_scroll.hide()
                                    ve_gb._btn_toggle.setText(
                                        "▲ Expand Effects")
                                    ve_gb._is_collapsed = True
                                    save_video_effects_collapsed(True)
                                    if len(cur_sizes) >= 3:
                                        total = sum(cur_sizes)
                                        collapsed_h = 48
                                        rem = total - collapsed_h
                                        t_h = int(rem * 0.58)
                                        tl_h = rem - t_h
                                        splitter.setSizes(
                                            [t_h, tl_h, collapsed_h])

                            ve_gb._btn_toggle.clicked.connect(
                                _toggle_effects_action)

                            # Handle splitter movement persistence
                            def _on_splitter_moved(pos, index):
                                if not getattr(ve_gb, '_is_collapsed', False):
                                    sizes = splitter.sizes()
                                    if len(sizes) >= 3 and sizes[2] > 50:
                                        ve_gb._last_expanded_height = sizes[2]
                                        save_main_splitter_sizes(sizes)

                            splitter.splitterMoved.connect(_on_splitter_moved)

                            # Restore saved state or apply sensible default
                            saved_collapsed = get_video_effects_collapsed()
                            saved_sizes = get_main_splitter_sizes()

                            if saved_collapsed:
                                ve_scroll.hide()
                                ve_gb._btn_toggle.setText("▲ Expand Effects")
                                ve_gb._is_collapsed = True
                                splitter.setSizes([340, 240, 48])
                            else:
                                if saved_sizes and len(saved_sizes) == 3 and saved_sizes[2] > 40:
                                    splitter.setSizes(saved_sizes)
                                    ve_gb._last_expanded_height = saved_sizes[2]
                                else:
                                    splitter.setSizes([280, 200, 160])
                                    ve_gb._last_expanded_height = 160
                        else:
                            splitter.setSizes([280, 200])

                except Exception as _sp_e:
                    print('[WARN] Unified splitter layout error:', _sp_e)

                content.layout().invalidate()
                content.updateGeometry()
    except Exception as e:
        print('[WARN] Layout reorganization error:', e)

    # Ensure VoxCPM2, RVC, and Voice Clone buttons are visible
    try:
        if hasattr(self, 'btn_voxcpm2_tester') and self.btn_voxcpm2_tester:
            self.btn_voxcpm2_tester.setVisible(True)
        if hasattr(self, 'combo_voice_all') and self.combo_voice_all:
            try:
                import voxcpm_support
                for label, vid, _ in voxcpm_support.VOXCPM_BUILTIN_VOICES:
                    if self.combo_voice_all.findData(vid) < 0:
                        self.combo_voice_all.addItem(label, vid)
            except Exception:
                pass
        if hasattr(self, 'btn_rvc') and self.btn_rvc:
            self.btn_rvc.setVisible(True)
        if hasattr(self, 'chk_voice_clone') and self.chk_voice_clone:
            self.chk_voice_clone.setVisible(True)
        if hasattr(self, 'btn_voice_clone_settings') and self.btn_voice_clone_settings:
            self.btn_voice_clone_settings.setVisible(True)
        if hasattr(self, 'btn_transcribe') and self.btn_transcribe:
            try:
                self.btn_transcribe.clicked.disconnect()
            except Exception:
                pass
            self.btn_transcribe.clicked.connect(
                lambda checked=False: self.start_transcription())
    except Exception:
        pass

    # Apply 3-color design system layout margins, typography & semantic button classification
    try:
        from PyQt5.QtGui import QFont

        # 1. Main layout margins and spacing
        cw = self.centralWidget()
        if cw and hasattr(cw, 'widget') and cw.widget():
            content = cw.widget()
            if content.layout():
                content.layout().setContentsMargins(14, 14, 14, 14)
                content.layout().setSpacing(12)

        # 2. Universal font stack enforcement (including emoji fonts)
        main_font = QFont('Segoe UI', 10)
        main_font.setStyleHint(QFont.SansSerif)
        if hasattr(main_font, 'setFamilies'):
            main_font.setFamilies([
                'Segoe UI', 'Noto Sans Khmer', 'Khmer OS Battambang',
                'Noto Color Emoji', 'Segoe UI Emoji', 'Apple Color Emoji',
                'Khmer OS System', 'PingFang SC', 'sans-serif'
            ])
        self.setFont(main_font)

        # 3. Apply comprehensive design system theme
        self.apply_dialog_theme()
    except Exception as _ui_rule_e:
        print('[WARN] UI pattern rule application error:', _ui_rule_e)


def apply_dubbing_theme(self, mode=None):
    """
    Applies 3-Color Design System theme (dark/light) to the main application window,
    including central scroll area, timeline editor, buttons, and combo boxes.
    """
    try:
        from theme_manager import get_theme_mode
        from ui_theme_tokens import (
            COLOR_CANVAS, COLOR_SURFACE, COLOR_SURFACE_INPUT, COLOR_BORDER,
            LIGHT_COLOR_CANVAS, LIGHT_COLOR_SURFACE, LIGHT_COLOR_SURFACE_INPUT, LIGHT_COLOR_BORDER
        )
        from PyQt5.QtGui import QColor
        from PyQt5.QtWidgets import QScrollArea, QPushButton, QComboBox, QCheckBox, QTableWidget
        from PyQt5.QtCore import Qt
        import ui_widgets

        if mode is None:
            mode = get_theme_mode()
        is_dark = str(mode).strip().lower() == "dark"

        # 1. Clear hardcoded QMainWindow light stylesheet so application QSS takes precedence
        self.setStyleSheet("")

        # 2. Prevent system palette gray leak on central widget and all scroll areas
        cw = self.centralWidget()
        if cw:
            cw.setAutoFillBackground(False)
            cw.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if hasattr(cw, 'widget') and cw.widget():
                cw.widget().setAutoFillBackground(False)
                cw.widget().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if hasattr(cw, 'viewport') and cw.viewport():
                cw.viewport().setAutoFillBackground(False)
                cw.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        for sa in self.findChildren(QScrollArea):
            sa.setAutoFillBackground(False)
            sa.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if sa.viewport():
                sa.viewport().setAutoFillBackground(False)
                sa.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            if sa.widget():
                sa.widget().setAutoFillBackground(False)
                sa.widget().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        # 3. Theme TimelineWidget colors
        surface_hex = COLOR_SURFACE if is_dark else LIGHT_COLOR_SURFACE
        input_hex = COLOR_SURFACE_INPUT if is_dark else LIGHT_COLOR_SURFACE_INPUT
        border_hex = COLOR_BORDER if is_dark else LIGHT_COLOR_BORDER

        for tw in self.findChildren(ui_widgets.TimelineWidget):
            tw.bg_color = QColor(surface_hex)
            tw.grid_color = QColor(border_hex)
            tw.waveform_bg_color = QColor(input_hex)
            tw.update()

        # 4. Semantic button styling - clear inline hardcoded colors so QSS tokens apply
        hero_ctas = {"Export Video", "Transcribe", "Translate", "Load Video", "Batch Load"}
        player_cmds = {"Play", "Stop", "Auto-Sync", "Auto-Speed", "Video Sync", "Cutter", "Lock Speed"}
        for btn in self.findChildren(QPushButton):
            obj_name = btn.objectName()
            if obj_name in {"btn_theme_toggle", "btn_toggle_effects", "btn_social_post"}:
                continue
            txt = btn.text().strip()
            if any(h in txt for h in hero_ctas):
                btn.setObjectName("primaryBtn")
                btn.setStyleSheet("")
            elif any(p in txt for p in player_cmds):
                btn.setObjectName("playerBtn")
                btn.setStyleSheet("")
            else:
                if not obj_name or obj_name in {"secondaryBtn", "playerBtn", "primaryBtn"}:
                    btn.setObjectName("secondaryBtn")
                    btn.setStyleSheet("")

        # 5. Polish QTableWidget headers & alternate row colors
        for tbl in self.findChildren(QTableWidget):
            tbl.setAlternatingRowColors(True)
            if hasattr(tbl, 'verticalHeader') and tbl.verticalHeader():
                tbl.verticalHeader().setDefaultSectionSize(28)
            if hasattr(tbl, 'horizontalHeader') and tbl.horizontalHeader():
                tbl.horizontalHeader().setHighlightSections(False)
            tbl.setShowGrid(True)

        # 6. Sanitize select boxes (QComboBox) to eliminate hardcoded white backgrounds
        for combo in self.findChildren(QComboBox):
            ss = combo.styleSheet()
            if 'background-color: white' in ss or '#BDC3C7' in ss:
                combo.setStyleSheet("")

        # 7. Theme Cambodian Voice Clone checkbox for high contrast
        for chk in self.findChildren(QCheckBox):
            if any(k in chk.text() for k in ["Clon", "ក្លូន", "សំឡេង"]):
                col = "#F87171" if is_dark else "#DC2626"
                chk.setStyleSheet(f"font-weight: bold; color: {col};")

        # 8. Update theme toggle button text if present
        if hasattr(self, 'btn_theme_toggle') and self.btn_theme_toggle:
            self.btn_theme_toggle.setText("☀️ Light Mode" if is_dark else "🌙 Dark Mode")
        if hasattr(self, 'btn_social_post') and self.btn_social_post:
            self.btn_social_post.setStyleSheet("")
    except Exception as _th_e:
        print('[WARN] apply_dubbing_theme error:', _th_e)


def _open_social_post_window(self):
    try:
        from social_post_window import SocialPostWindow
        existing = getattr(self, '_social_post_window', None)
        if existing and hasattr(existing, 'isVisible') and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return

        candidate = getattr(self, '_last_exported_video', None) or getattr(self, 'video_path', None)
        win = SocialPostWindow(parent=self, initial_video=candidate)
        self._social_post_window = win
        win.show()
    except Exception as e:
        print(f"[ERROR] Failed to open Social Post window: {e}")
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(self, "Social Post", f"Failed to open Social Post window:\n{e}")


_mod.DubbingApp.apply_dialog_theme = apply_dubbing_theme
if 'DubbingApp' in globals():
    globals()['DubbingApp'].apply_dialog_theme = apply_dubbing_theme
_mod.DubbingApp._open_social_post_window = _open_social_post_window
if 'DubbingApp' in globals():
    globals()['DubbingApp']._open_social_post_window = _open_social_post_window
_mod.DubbingApp.__init__ = _dubbing_init_patched

# Cross-platform VoxCPM package worker and enhanced path detection
class VoxCPMPackageInstallWorker(QThread):
    """
    Background worker for installing the official 'voxcpm' Python package
    and ensuring the VoxCPM2 model weights are available.
    """
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, target_python=None, install_dir=None, parent=None):
        super().__init__(parent)
        self.target_python = target_python
        self.install_dir = install_dir or os.getcwd()

    def run(self):
        try:
            self.progress.emit("Starting VoxCPM2 package and model setup...")
            self.progress_value.emit(5)

            py_exe = self.target_python
            if not py_exe or not os.path.exists(py_exe):
                py_exe = voxcpm_support._find_python_executable()
            if not py_exe or not os.path.exists(py_exe):
                py_exe = sys.executable

            self.progress.emit(f"Using Python runtime: {py_exe}")
            self.progress_value.emit(10)

            uv_bin = shutil.which("uv")
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

            def _run_cmd(cmd, base_val, max_val, title):
                self.progress.emit(title)
                self.progress_value.emit(base_val)
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    creationflags=flags
                )
                curr = base_val
                for line in iter(proc.stdout.readline, ''):
                    if self.isInterruptionRequested():
                        proc.terminate()
                        raise RuntimeError("Installation cancelled.")
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    self.progress.emit(line_clean[:120])
                    if curr < max_val:
                        curr = min(max_val, curr + 1)
                        self.progress_value.emit(curr)
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError(f"Command failed (code {proc.returncode}): {' '.join(cmd)}")

            # Step 1: Install voxcpm package via pip / uv pip
            if uv_bin:
                install_cmd = [uv_bin, "pip", "install", "--python", py_exe, "voxcpm>=2.0.0"]
            else:
                install_cmd = [py_exe, "-m", "pip", "install", "voxcpm>=2.0.0"]

            _run_cmd(install_cmd, 15, 65, "[1/2] Installing 'voxcpm' package from PyPI...")

            # Step 2: Verify voxcpm package import
            self.progress.emit("Verifying voxcpm package installation...")
            self.progress_value.emit(70)
            verify_cmd = [py_exe, "-c", "import voxcpm; print('voxcpm imported successfully')"]
            verify_res = subprocess.run(
                verify_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                creationflags=flags
            )
            if verify_res.returncode != 0:
                err_detail = (verify_res.stderr or verify_res.stdout or "").strip()
                raise RuntimeError(f"voxcpm verification failed: {err_detail}")

            self.progress.emit("voxcpm package verified successfully.")
            self.progress_value.emit(75)

            # Step 3: Verify or download VoxCPM2 model
            self.progress.emit("[2/2] Checking VoxCPM2 model weights...")
            self.progress_value.emit(80)

            model_dir = os.path.join(self.install_dir, "models", "openbmb__VoxCPM2")
            if not os.path.exists(os.path.join(model_dir, "config.json")):
                for cand in ("models/openbmb__VoxCPM2", "models/VoxCPM2", "_internal/models/openbmb__VoxCPM2"):
                    full_cand = os.path.abspath(cand)
                    if os.path.exists(os.path.join(full_cand, "config.json")):
                        model_dir = full_cand
                        break

            if not os.path.exists(os.path.join(model_dir, "config.json")):
                self.progress.emit("Downloading VoxCPM2 model weights from Hugging Face...")
                self.progress_value.emit(85)
                dl_script = f"""
import sys, os
from huggingface_hub import snapshot_download
target = {repr(model_dir)}
os.makedirs(target, exist_ok=True)
print("Downloading openbmb/VoxCPM2...")
snapshot_download(repo_id="openbmb/VoxCPM2", local_dir=target, resume_download=True)
print("SUCCESS")
"""
                _run_cmd([py_exe, "-c", dl_script], 85, 95, "Downloading openbmb/VoxCPM2 weights...")

            # Step 4: Save paths to settings
            settings_manager.save_voxcpm_install_config(
                source_dir="",  # package mode: no source_dir needed
                model_path=model_dir if os.path.exists(os.path.join(model_dir, "config.json")) else "openbmb/VoxCPM2",
                python_path=py_exe
            )

            self.progress.emit("[OK] VoxCPM2 package and models ready!")
            self.progress_value.emit(100)
            self.finished.emit(True)

        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.error.emit(str(e))


_orig_detect_voxcpm = _mod.DubbingApp._detect_voxcpm_install_paths_in_folder


def _detect_voxcpm_cross_platform(self, folder_path):
    source, model, py_exe = _orig_detect_voxcpm(self, folder_path)
    if not py_exe:
        for root, dirs, files in os.walk(folder_path):
            for name in ('python3', 'python', 'python.exe'):
                candidate = os.path.join(root, name)
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    py_exe = candidate
                    break
            if py_exe:
                break
    if not py_exe and os.path.exists(sys.executable):
        py_exe = sys.executable

    # Detect model folder directly if config.json exists
    if not model:
        if os.path.isfile(os.path.join(folder_path, "config.json")):
            model = os.path.abspath(folder_path)
        else:
            for root, dirs, files in os.walk(folder_path):
                if "config.json" in files:
                    model = os.path.abspath(root)
                    break
    return source, model, py_exe


def _ensure_voxcpm2_ready_or_prompt_enhanced(self):
    status = voxcpm_support.get_voxcpm_install_status()
    if status.get("ready"):
        return True

    dialog = QDialog(self)
    dialog.setWindowTitle("VoxCPM2 Setup")
    dialog.setMinimumWidth(560)
    dialog.setModal(True)
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(22, 22, 22, 22)
    layout.setSpacing(14)

    from PyQt5.QtWidgets import QLabel, QPushButton, QHBoxLayout
    title = QLabel("VoxCPM2 Setup Required", dialog)
    t_font = title.font()
    t_font.setBold(True)
    t_font.setPointSize(max(14, t_font.pointSize() + 2))
    title.setFont(t_font)
    layout.addWidget(title)

    msg = status.get("message", "VoxCPM2 is not installed yet.")
    details = QLabel(
        f"{msg}\n\n"
        "VoxCPM2 provides high-fidelity voice synthesis and cloning using the official 'voxcpm' Python package.\n"
        "You can install the voxcpm package and models automatically, select an existing model folder, continue anyway, or cancel.",
        dialog
    )
    details.setWordWrap(True)
    layout.addWidget(details)

    btn_row = QHBoxLayout()
    btn_install = QPushButton("📦 Install voxcpm Package & Models", dialog)
    btn_install.setStyleSheet("background-color: #0F766E; color: white; padding: 8px 16px; font-weight: bold;")
    btn_choose = QPushButton("📂 Select Model Folder", dialog)
    btn_choose.setStyleSheet("padding: 8px 16px;")

    btn_row.addWidget(btn_install)
    btn_row.addWidget(btn_choose)
    btn_row.addStretch()
    layout.addLayout(btn_row)

    bottom_row = QHBoxLayout()
    btn_continue = QPushButton("Continue Anyway", dialog)
    btn_cancel = QPushButton("Cancel", dialog)
    bottom_row.addStretch()
    bottom_row.addWidget(btn_continue)
    bottom_row.addWidget(btn_cancel)
    layout.addLayout(bottom_row)

    dialog.action = None

    def _on_install():
        dialog.action = "install"
        dialog.accept()

    def _on_choose():
        dialog.action = "choose"
        dialog.accept()

    def _on_continue():
        dialog.action = "continue"
        dialog.accept()

    btn_install.clicked.connect(_on_install)
    btn_choose.clicked.connect(_on_choose)
    btn_continue.clicked.connect(_on_continue)
    btn_cancel.clicked.connect(dialog.reject)

    if dialog.exec_() != QDialog.Accepted:
        return False

    if dialog.action == "install":
        return self._download_voxcpm2_package(dialog)
    elif dialog.action == "choose":
        return self._choose_existing_voxcpm_install_folder(dialog)
    elif dialog.action == "continue":
        return True
    return False


def _download_voxcpm2_package_enhanced(self, parent_dialog=None):
    from runtime_paths import get_app_dir
    from PyQt5.QtWidgets import QProgressBar, QDialogButtonBox
    config = settings_manager.get_voxcpm_install_config()
    py_path = config.get("python_path", "")
    install_dir = get_app_dir()

    progress_dialog = QDialog(parent_dialog or self)
    progress_dialog.setWindowTitle("Installing VoxCPM2 Package & Models")
    progress_dialog.setMinimumWidth(540)
    p_layout = QVBoxLayout(progress_dialog)
    p_layout.setContentsMargins(20, 20, 20, 20)
    p_layout.setSpacing(12)

    from PyQt5.QtWidgets import QLabel
    status_label = QLabel("Preparing VoxCPM2 package and models installation...", progress_dialog)
    status_label.setWordWrap(True)
    p_layout.addWidget(status_label)

    p_bar = QProgressBar(progress_dialog)
    p_bar.setRange(0, 100)
    p_bar.setValue(5)
    p_layout.addWidget(p_bar)

    btn_box = QDialogButtonBox(QDialogButtonBox.Cancel, progress_dialog)
    p_layout.addWidget(btn_box)

    worker = VoxCPMPackageInstallWorker(target_python=py_path, install_dir=install_dir, parent=progress_dialog)

    def on_progress(text):
        status_label.setText(text)

    def on_val(val):
        p_bar.setValue(val)

    def on_finished(ok):
        btn_box.clear()
        btn_box.addButton(QDialogButtonBox.Ok)
        status = voxcpm_support.get_voxcpm_install_status()
        if status.get("ready"):
            status_label.setText("✅ VoxCPM2 package and model setup completed successfully!")
            progress_dialog.accept()
        else:
            status_label.setText(f"Setup finished with notice: {status.get('message', '')}")

    def on_err(err_text):
        status_label.setText(f"❌ Error: {err_text}")
        btn_box.clear()
        btn_box.addButton(QDialogButtonBox.Close)

    btn_box.rejected.connect(progress_dialog.reject)
    progress_dialog.rejected.connect(lambda: worker.requestInterruption())

    worker.progress.connect(on_progress)
    worker.progress_value.connect(on_val)
    worker.finished.connect(on_finished)
    worker.error.connect(on_err)

    worker.start()
    accepted = (progress_dialog.exec_() == QDialog.Accepted)
    if worker.isRunning():
        worker.requestInterruption()
        worker.wait(1500)

    status = voxcpm_support.get_voxcpm_install_status()
    if status.get("ready"):
        QMessageBox.information(self, "VoxCPM2", "VoxCPM2 package and model are ready.")
        return True
    elif accepted:
        QMessageBox.warning(
            self,
            "VoxCPM2",
            f"VoxCPM2 setup finished, but setup is still incomplete:\n\n{status.get('message', '')}"
        )
    return False


def _choose_existing_voxcpm_install_folder_enhanced(self, parent_dialog=None):
    from runtime_paths import get_app_dir
    from PyQt5.QtWidgets import QFileDialog
    folder = QFileDialog.getExistingDirectory(self, "Choose VoxCPM2 Model / Data Folder", get_app_dir())
    if not folder:
        return False

    source_dir, model_path, python_path = self._detect_voxcpm_install_paths_in_folder(folder)
    self._save_voxcpm_install_paths(source_dir, model_path, python_path)
    status = voxcpm_support.get_voxcpm_install_status()
    if status.get("ready"):
        QMessageBox.information(self, "VoxCPM2", "VoxCPM2 model and runtime are ready.")
        return True
    else:
        QMessageBox.warning(
            self,
            "VoxCPM2",
            "I saved what I could find, but VoxCPM2 is still incomplete.\n\n"
            + status.get("message", "")
            + "\n\nDetected Model: " + (model_path or "None")
            + "\nDetected Python: " + (python_path or "None")
            + "\n\nTip: Click 'Install voxcpm Package & Models' to install the package automatically."
        )
        return False


_mod._detect_voxcpm_cross_platform = _detect_voxcpm_cross_platform
globals()['_detect_voxcpm_cross_platform'] = _detect_voxcpm_cross_platform
_mod.DubbingApp._detect_voxcpm_install_paths_in_folder = _detect_voxcpm_cross_platform
_mod.DubbingApp._ensure_voxcpm2_ready_or_prompt = _ensure_voxcpm2_ready_or_prompt_enhanced
_mod.DubbingApp._download_voxcpm2_package = _download_voxcpm2_package_enhanced
_mod.DubbingApp._choose_existing_voxcpm_install_folder = _choose_existing_voxcpm_install_folder_enhanced
_mod.VoxCPM2PackageInstallWorker = VoxCPMPackageInstallWorker
_mod.VoxCPMPackageInstallWorker = VoxCPMPackageInstallWorker

if 'DubbingApp' in globals():
    globals()['DubbingApp']._detect_voxcpm_install_paths_in_folder = _detect_voxcpm_cross_platform
    globals()['DubbingApp']._ensure_voxcpm2_ready_or_prompt = _ensure_voxcpm2_ready_or_prompt_enhanced
    globals()['DubbingApp']._download_voxcpm2_package = _download_voxcpm2_package_enhanced
    globals()['DubbingApp']._choose_existing_voxcpm_install_folder = _choose_existing_voxcpm_install_folder_enhanced

globals()['VoxCPM2PackageInstallWorker'] = VoxCPMPackageInstallWorker
globals()['VoxCPMPackageInstallWorker'] = VoxCPMPackageInstallWorker

_orig_dialog_init = _mod.DependencyCheckDialog.__init__


def _dialog_init_patched(self, *args, **kwargs):
    auto_install = kwargs.pop('auto_install', False)
    missing_items = kwargs.pop('missing_items', None)
    _orig_dialog_init(self, *args, **kwargs)

    self._auto_install_mode = auto_install
    self._missing_items_override = missing_items

    from runtime_paths import resource_path
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QTimer

    app_icon = QApplication.windowIcon()
    if app_icon and not app_icon.isNull():
        self.setWindowIcon(app_icon)
    else:
        for name in ('icon.png', 'icon.ico'):
            ip = resource_path(name)
            if os.path.exists(ip):
                self.setWindowIcon(QIcon(ip))
                break

    if self._auto_install_mode:
        def _trigger_auto():
            if self._missing_items_override:
                self.install_queue = list(self._missing_items_override)
            else:
                self.install_queue = []
                if hasattr(self, 'btn_dl0') and self.btn_dl0.isEnabled():
                    self.install_queue.append('ffmpeg')
                if hasattr(self, 'btn_dl1') and self.btn_dl1.isEnabled():
                    self.install_queue.append('python')
                if hasattr(self, 'btn_dl2') and self.btn_dl2.isEnabled():
                    self.install_queue.append('demucs')
                if hasattr(self, 'btn_dl3') and self.btn_dl3.isEnabled():
                    self.install_queue.append('voxcpm')

            if self.install_queue:
                if hasattr(self, 'btn_check'):
                    self.btn_check.setEnabled(False)
                if hasattr(self, 'btn_autoinstall'):
                    self.btn_autoinstall.setEnabled(False)
                if hasattr(self, 'btn_close'):
                    self.btn_close.setEnabled(False)
                if hasattr(self, 'progress_widget'):
                    self.progress_widget.show()
                self.run_next_install()

        QTimer.singleShot(150, _trigger_auto)


_mod.DependencyCheckDialog.__init__ = _dialog_init_patched

_orig_run_next_install = _mod.DependencyCheckDialog.run_next_install


def _run_next_install_patched(self):
    _orig_run_next_install(self)
    if not self.install_queue and getattr(self, '_auto_install_mode', False):
        from PyQt5.QtCore import QTimer

        def _auto_close():
            try:
                self.accept()
            except Exception:
                pass
        QTimer.singleShot(1500, _auto_close)


_mod.DependencyCheckDialog.run_next_install = _run_next_install_patched
_mod.check_system_components = check_system_components
_mod.pick_funasr_python = pick_funasr_python
_mod.CrossPlatformPythonFunASRInstallWorker = CrossPlatformPythonFunASRInstallWorker

_mod._fix_mojibake = _fix_mojibake
_mod.VOXCPM2_UI_ENABLED = True
_mod.VOXCPM2_ENABLED = True
_mod.RVC_WORKSPACE_ENABLED = True
_mod.VOICE_CLONE_UI_ENABLED = True


_mod.VOXCPM_PROMPT_PRESETS = voxcpm_support.VOXCPM_PROMPT_PRESETS
_mod.generate_voxcpm_audio = voxcpm_support.generate_voxcpm_audio
_mod.get_voxcpm_install_status = voxcpm_support.get_voxcpm_install_status
_mod.get_voxcpm_reference_settings = voxcpm_support.get_voxcpm_reference_settings
_mod.is_voxcpm_reference_voice = voxcpm_support.is_voxcpm_reference_voice
_mod.is_voxcpm_reference_voice_id = voxcpm_support.is_voxcpm_reference_voice_id
_mod.is_voxcpm_voice = voxcpm_support.is_voxcpm_voice
_mod.is_voxcpm_voice_id = voxcpm_support.is_voxcpm_voice_id
_mod.make_voxcpm_reference_voice_id = voxcpm_support.make_voxcpm_reference_voice_id

# Voice Clone module exports
for _vc_attr in [
    'scan_available_voice_clone_models',
    'get_voice_clone_model_display_name',
    'get_voice_clone_model_for_voice',
    'get_voxcpm_voice_for_clone',
    'get_voice_clone_character_key_for_voice',
    'get_voice_clone_cache_marker',
    'apply_voice_clone_to_audio',
]:
    if hasattr(voice_clone, _vc_attr):
        setattr(_mod, _vc_attr, getattr(voice_clone, _vc_attr))

# Settings manager voice clone exports
for _sm_attr in [
    'get_voice_clone_config',
    'save_voice_clone_config',
    'get_voxcpm_character_keys',
    'save_voxcpm_character_keys',
    'normalize_voxcpm_character_keys',
]:
    if hasattr(settings_manager, _sm_attr):
        setattr(_mod, _sm_attr, getattr(settings_manager, _sm_attr))

globals().update(_mod.__dict__)
globals()['PythonFunASRInstallWorker'] = CrossPlatformPythonFunASRInstallWorker
globals()['pick_funasr_python'] = pick_funasr_python
globals()['check_system_components'] = check_system_components
globals()['_fix_mojibake'] = _fix_mojibake
globals()['VOXCPM2_UI_ENABLED'] = True
globals()['VOXCPM2_ENABLED'] = True
globals()['RVC_WORKSPACE_ENABLED'] = True
globals()['VOICE_CLONE_UI_ENABLED'] = True
globals()['VOXCPM_PROMPT_PRESETS'] = voxcpm_support.VOXCPM_PROMPT_PRESETS
globals()['generate_voxcpm_audio'] = voxcpm_support.generate_voxcpm_audio
globals()['get_voxcpm_install_status'] = voxcpm_support.get_voxcpm_install_status
globals()[
    'get_voxcpm_reference_settings'] = voxcpm_support.get_voxcpm_reference_settings
globals()['is_voxcpm_reference_voice'] = voxcpm_support.is_voxcpm_reference_voice
globals()['is_voxcpm_reference_voice_id'] = voxcpm_support.is_voxcpm_reference_voice_id
globals()['is_voxcpm_voice'] = voxcpm_support.is_voxcpm_voice
globals()['is_voxcpm_voice_id'] = voxcpm_support.is_voxcpm_voice_id
globals()[
    'make_voxcpm_reference_voice_id'] = voxcpm_support.make_voxcpm_reference_voice_id

for _vc_attr in [
    'scan_available_voice_clone_models',
    'get_voice_clone_model_display_name',
    'get_voice_clone_model_for_voice',
    'get_voxcpm_voice_for_clone',
    'get_voice_clone_character_key_for_voice',
    'get_voice_clone_cache_marker',
    'apply_voice_clone_to_audio',
]:
    if hasattr(voice_clone, _vc_attr):
        globals()[_vc_attr] = getattr(voice_clone, _vc_attr)

for _sm_attr in [
    'get_voice_clone_config',
    'save_voice_clone_config',
    'get_voxcpm_character_keys',
    'save_voxcpm_character_keys',
    'normalize_voxcpm_character_keys',
]:
    if hasattr(settings_manager, _sm_attr):
        globals()[_sm_attr] = getattr(settings_manager, _sm_attr)

# Batch Loader enhancements

EnhancedBatchSrtMappingDialog = create_enhanced_batch_mapping_dialog_class(
    _mod.BatchSrtMappingDialog)
_mod.EnhancedBatchSrtMappingDialog = EnhancedBatchSrtMappingDialog
_mod.BatchSrtMappingDialog = EnhancedBatchSrtMappingDialog
globals()['EnhancedBatchSrtMappingDialog'] = EnhancedBatchSrtMappingDialog
globals()['BatchSrtMappingDialog'] = EnhancedBatchSrtMappingDialog


def _enhanced_start_batch_processing(self, mode=None):
    from PyQt5.QtWidgets import QFileDialog, QMessageBox, QMenu
    from PyQt5.QtGui import QCursor
    from PyQt5.QtCore import Qt

    existing_dialog = getattr(self, '_batch_mapping_dialog', None)
    if existing_dialog is not None:
        try:
            if existing_dialog.isVisible():
                existing_dialog.showNormal()
                existing_dialog.raise_()
                existing_dialog.activateWindow()
                return
        except RuntimeError:
            self._batch_mapping_dialog = None

    start_dir = getattr(self, 'current_dir', '') or os.path.expanduser('~')
    video_files = []

    if mode == 'folder':
        folder = QFileDialog.getExistingDirectory(
            self, "Select Video Folder for Batch Load", start_dir)
        if not folder:
            return
        video_files, srt_files = scan_folder_for_media(folder, recursive=True)
        if not video_files:
            QMessageBox.information(
                self, "No Videos Found", f"No supported video files found in:\n{folder}")
            return
    elif mode == 'files':
        vid_filter = getattr(_mod, 'VIDEO_FILE_DIALOG_FILTER',
                             "Video Files (*.mp4 *.mkv *.avi *.mov *.flv *.webm *.ts *.wmv *.m4v);;All Files (*.*)")
        video_files, _ = QFileDialog.getOpenFileNames(
            self, "Select Videos for Batch Load", start_dir, vid_filter)
        if not video_files:
            return
    elif mode == 'empty':
        video_files = []
    else:
        btn = getattr(self, 'btn_load_batch', None)
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                color: #2c3e50;
                font-size: 13px;
                font-weight: 500;
                padding: 6px;
                border: 1px solid #bdc3c7;
                border-radius: 8px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #3498db;
                color: white;
            }
        """)
        act_files = menu.addAction("📁 Load Video Files...")
        act_folder = menu.addAction("📂 Load Video Folder...")
        menu.addSeparator()
        act_dialog = menu.addAction(
            "⚡ Open Batch Manager (Empty / Drag & Drop)...")

        pos = btn.mapToGlobal(btn.rect().bottomLeft()
                              ) if btn else QCursor.pos()
        chosen = menu.exec_(pos)
        if chosen == act_files:
            return _enhanced_start_batch_processing(self, mode='files')
        elif chosen == act_folder:
            return _enhanced_start_batch_processing(self, mode='folder')
        elif chosen == act_dialog:
            video_files = []
        else:
            return

    sort_fn = getattr(_mod, '_sort_file_paths_naturally', lambda x: sorted(x))
    video_files = sort_fn(video_files)
    mapping_dialog = EnhancedBatchSrtMappingDialog(video_files, self)
    mapping_dialog.setModal(False)
    mapping_dialog.setWindowModality(Qt.WindowModality.NonModal)
    mapping_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    self._batch_mapping_dialog = mapping_dialog

    mapping_dialog.finished.connect(
        lambda result, d=mapping_dialog, b=start_dir: self._handle_batch_mapping_dialog_finished(
            d, result, b)
    )
    mapping_dialog.destroyed.connect(
        lambda *args: setattr(self, '_batch_mapping_dialog', None))
    mapping_dialog.showMaximized()
    mapping_dialog.raise_()
    mapping_dialog.activateWindow()


_mod.DubbingApp.start_batch_processing = _enhanced_start_batch_processing
globals()['DubbingApp'].start_batch_processing = _enhanced_start_batch_processing
_mod._enhanced_start_batch_processing = _enhanced_start_batch_processing
globals()['_enhanced_start_batch_processing'] = _enhanced_start_batch_processing

_orig_handle_batch_finished = _mod.DubbingApp._handle_batch_mapping_dialog_finished


def _handle_batch_mapping_dialog_finished_patched(self, mapping_dialog, result, start_dir=None):
    if getattr(mapping_dialog, '_batch_processed_parallel', False):
        return None
    return _orig_handle_batch_finished(self, mapping_dialog, result, start_dir)


_mod.DubbingApp._handle_batch_mapping_dialog_finished = _handle_batch_mapping_dialog_finished_patched
globals()['DubbingApp']._handle_batch_mapping_dialog_finished = _handle_batch_mapping_dialog_finished_patched


class _GeminiTranslationSentinel:
    """
    Lightweight truthy sentinel placed at worker.translator to signal that
    translation should proceed via run_translation_pipeline() using Gemini AI.

    This replaces GoogleTranslator (deep_translator) as the translator object.
    Unlike GoogleTranslator, this never makes an HTTP request — Gemini translation
    is handled entirely inside run_translation_pipeline() which reads the
    'translation_engine' config key set to 'gemini'.
    """

    def __repr__(self):
        return "<_GeminiTranslationSentinel: Gemini AI translation>"

    def translate(self, text):
        # Should never be called directly — run_translation_pipeline() handles all translation.
        return text

    def __bool__(self):
        return True


class TargetLanguageDialog(QDialog):
    """
    Modal dialog prompting the user to select the target language for AI transcription
    and subtitle translation, defaulting to Khmer ('km').
    """
    LANGUAGES = [
        ("Khmer (ភាសាខ្មែរ) [km] - Default", "km"),
        ("English [en]", "en"),
        ("Chinese (中文) [zh-CN]", "zh-CN"),
        ("Japanese (日本語) [ja]", "ja"),
        ("Korean (한국어) [ko]", "ko"),
        ("Thai (ไทย) [th]", "th"),
        ("Vietnamese (Tiếng Việt) [vi]", "vi"),
        ("French (Français) [fr]", "fr"),
        ("Spanish (Español) [es]", "es"),
        ("Original Language (No Translation)", "original"),
    ]

    def __init__(self, current_default='km', parent=None):
        from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QCheckBox
        from PyQt5.QtCore import Qt

        super().__init__(parent)
        self.setWindowTitle("Select Target Language")
        self.setFixedWidth(440)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl_title = QLabel("🎙️ Transcription & Subtitle Language")
        lbl_title.setObjectName("dialogTitleLabel")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Select the target language to transcribe and translate audio speech into:")
        lbl_desc.setWordWrap(True)
        lbl_desc.setObjectName("dialogDescLabel")
        lbl_desc.setStyleSheet("font-size: 12.5px; opacity: 0.85;")
        layout.addWidget(lbl_desc)

        self.cmb_lang = QComboBox()
        self.cmb_lang.setObjectName("targetLangComboBox")
        default_idx = 0
        for i, (label, code) in enumerate(self.LANGUAGES):
            self.cmb_lang.addItem(label, code)
            if code == current_default:
                default_idx = i
        self.cmb_lang.setCurrentIndex(default_idx)
        layout.addWidget(self.cmb_lang)

        self.chk_remember = QCheckBox("Remember this language as default")
        self.chk_remember.setChecked(True)
        self.chk_remember.setObjectName("targetLangRememberChk")
        layout.addWidget(self.chk_remember)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_start = QPushButton("🎙️ Transcribe")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_start)

        layout.addLayout(btn_layout)

    def get_selection(self):
        code = self.cmb_lang.currentData()
        auto_translate = (code != 'original')
        target_lang = 'km' if code == 'original' else code
        remember = self.chk_remember.isChecked()
        return target_lang, auto_translate, remember


_orig_start_transcription = _mod.DubbingApp.start_transcription


def _start_transcription_enhanced(self, target_lang=None):
    from PyQt5.QtWidgets import QMessageBox

    # Qt button signals emit clicked(bool checked). If passed a bool, treat as None (prompt user)
    if isinstance(target_lang, bool):
        target_lang = None

    # Check video loaded
    if not getattr(self, 'video_path', None):
        QMessageBox.warning(self, "⚠️ No Video", "Please load a video first!")
        return

    # Check already running
    existing_worker = getattr(self, 'transcription_worker', None)
    if existing_worker is not None and hasattr(existing_worker, 'isRunning') and existing_worker.isRunning():
        QMessageBox.warning(
            self,
            "⏳ Transcription Running",
            "A transcription is already running. Please wait for it to finish (or restart the app to cancel)."
        )
        return

    # If target_lang not provided, prompt the user
    auto_translate = True
    if target_lang is None:
        try:
            import settings_manager
            cfg = settings_manager.read_config()
            default_lang = cfg.get('transcribe_target_language', cfg.get(
                'gemini_target_language', 'km'))
        except Exception:
            default_lang = 'km'

        dlg = TargetLanguageDialog(current_default=default_lang, parent=self)
        if dlg.exec_() != TargetLanguageDialog.Accepted:
            print("[TRANSCRIBE] Cancelled by user in Target Language dialog.")
            return

        target_lang, auto_translate, remember = dlg.get_selection()

        if remember:
            try:
                import settings_manager
                settings_manager.write_config({
                    'transcribe_target_language': target_lang,
                    'gemini_target_language': target_lang,
                    'gemini_auto_translate': bool(auto_translate),
                    'openai_target_language': target_lang,
                    'deepinfra_target_language': target_lang,
                    'groq_target_language': target_lang,
                    'assemblyai_target_language': target_lang,
                })
            except Exception as e:
                print(
                    f"[TRANSCRIBE] Failed to save target language preference: {e}")
    else:
        auto_translate = (target_lang != 'original')
        if target_lang == 'original':
            target_lang = 'km'

    # Ensure configs reflect the chosen target_lang before base method runs
    try:
        import settings_manager
        settings_manager.write_config({
            'gemini_target_language': target_lang,
            'gemini_auto_translate': bool(auto_translate),
            'openai_target_language': target_lang,
            'deepinfra_target_language': target_lang,
            'groq_target_language': target_lang,
            'assemblyai_target_language': target_lang,
            # Use Gemini AI for translation (replaces GoogleTranslator)
            'translation_engine': 'gemini',
        })
    except Exception:
        pass

    # Call original method to construct worker and start thread
    orig_question = QMessageBox.question
    try:
        QMessageBox.question = lambda *args, **kwargs: QMessageBox.Yes
        _orig_start_transcription(self)
    finally:
        QMessageBox.question = orig_question

    # Synchronize worker properties directly
    worker = getattr(self, 'transcription_worker', None)
    if worker:
        worker.target_language = target_lang
        worker.auto_translate = bool(auto_translate)
        if not auto_translate:
            worker.translator = None
        else:
            # Use _GeminiTranslationSentinel as a truthy sentinel.
            # This satisfies the bool(self.translator) guard in TranscriptionWorker.run()
            # without importing or calling GoogleTranslator (deep_translator).
            # run_translation_pipeline() reads 'translation_engine'='gemini' from config
            # and handles all actual translation via Gemini API.
            worker.translator = _GeminiTranslationSentinel()
            print(
                f"[TRANSCRIBE] Translation engine: Gemini AI (sentinel={worker.translator!r})")

        print(
            f"[TRANSCRIBE] Started transcription with target_language={target_lang!r}, auto_translate={auto_translate}")


_mod.DubbingApp.start_transcription = _start_transcription_enhanced
globals()['DubbingApp'].start_transcription = _start_transcription_enhanced
_mod._start_transcription_enhanced = _start_transcription_enhanced
globals()['_start_transcription_enhanced'] = _start_transcription_enhanced
_mod.TargetLanguageDialog = TargetLanguageDialog
globals()['TargetLanguageDialog'] = TargetLanguageDialog
_mod._GeminiTranslationSentinel = _GeminiTranslationSentinel
globals()['_GeminiTranslationSentinel'] = _GeminiTranslationSentinel

# ── Patch open_settings_dialog to inject extra settings tabs ──────────────────
try:
    import settings_window as _settings_window_mod
    _orig_open_settings_dialog = _mod.DubbingApp.open_settings_dialog

    def _open_settings_dialog_enhanced(self):
        """
        Wraps the compiled open_settings_dialog to inject 5 additional tabs
        (More APIs, Translation, Appearance, Export, Advanced) from
        settings_window.py into the existing compiled QTabWidget.
        """
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QApplication, QDialog, QTabWidget

        _injected = [False]

        def _inject():
            if _injected[0]:
                return
            for widget in QApplication.allWidgets():
                if (
                    isinstance(widget, QDialog)
                    and widget.isVisible()
                    and '⚙️ Settings' in (widget.windowTitle() or '')
                ):
                    tab_widgets = widget.findChildren(QTabWidget)
                    if tab_widgets:
                        _settings_window_mod.inject_extra_settings_tabs(
                            widget, tab_widgets[0])
                        _settings_window_mod.apply_settings_dialog_theme(widget)
                        _injected[0] = True
                        return
                    else:
                        _settings_window_mod.apply_settings_dialog_theme(widget)
            # Retry until the dialog appears (max ~2s)
            if not _injected[0]:
                QTimer.singleShot(30, _inject)

        QTimer.singleShot(10, _inject)
        _orig_open_settings_dialog(self)

    _mod.DubbingApp.open_settings_dialog = _open_settings_dialog_enhanced
    globals()['DubbingApp'].open_settings_dialog = _open_settings_dialog_enhanced
    _mod._open_settings_dialog_enhanced = _open_settings_dialog_enhanced
    globals()['_open_settings_dialog_enhanced'] = _open_settings_dialog_enhanced
    print("[CORE] open_settings_dialog patched with extended tabs injection.")
except Exception as _settings_patch_err:
    import traceback as _tb
    print(
        f"[CORE] WARNING: settings_window patch failed: {_settings_patch_err}")
    _tb.print_exc()

# ── Patch convert_video_to_mp3 to use parallel multi-worker engine ───────────
try:
    from video_to_mp3 import convert_video_to_mp3_enhanced, VideoToMp3WorkerAdapter, VideoToMp3Dialog
    _orig_convert_video_to_mp3 = getattr(
        _mod.DubbingApp, "convert_video_to_mp3", None)

    _mod.DubbingApp.convert_video_to_mp3 = convert_video_to_mp3_enhanced
    globals()['DubbingApp'].convert_video_to_mp3 = convert_video_to_mp3_enhanced
    _mod.VideoToMp3Worker = VideoToMp3WorkerAdapter
    globals()['VideoToMp3Worker'] = VideoToMp3WorkerAdapter
    _mod.VideoToMp3Dialog = VideoToMp3Dialog
    globals()['VideoToMp3Dialog'] = VideoToMp3Dialog
    print("[CORE] convert_video_to_mp3 patched with parallel multi-worker monitor.")
except Exception as _v2mp3_err:
    import traceback as _tb
    print(f"[CORE] WARNING: video_to_mp3 patch failed: {_v2mp3_err}")
    _tb.print_exc()

# ── Multi-Voice Export & Table Synchronization Patch ─────────────────────────
try:
    from utils import normalize_voice_id, resolve_voice_and_pitch

    # 1. Patch resolve_khmer_special_voice
    def _resolve_khmer_special_voice_enhanced(self, voice_str, pitch_str="+0Hz"):
        return resolve_voice_and_pitch(voice_str, pitch_str)

    _mod.DubbingApp.resolve_khmer_special_voice = _resolve_khmer_special_voice_enhanced
    if "DubbingApp" in globals():
        globals()[
            "DubbingApp"].resolve_khmer_special_voice = _resolve_khmer_special_voice_enhanced

    # 2. Patch _normalize_gender_result
    def _normalize_gender_result_enhanced(self, result):
        echo_enabled = False
        gender = "female"
        if isinstance(result, dict):
            raw_gender = result.get("gender", "female")
            echo_enabled = bool(result.get("echo", False))
        else:
            raw_gender = result

        vid = normalize_voice_id(raw_gender)
        if vid in ("km-KH-PisethNeural_Boy", "km-KH-PisethNeural-Boy"):
            gender = "boy"
        elif vid in ("km-KH-SreymomNeural_Girl", "km-KH-SreymomNeural-Girl"):
            gender = "girl"
        elif vid in ("km-KH-PisethNeural_Old", "km-KH-PisethNeural-OldMan", "km-KH-PisethNeural-Old"):
            gender = "old_man"
        elif vid in ("km-KH-SreymomNeural_Old", "km-KH-SreymomNeural-OldWoman", "km-KH-SreymomNeural-Old"):
            gender = "old_woman"
        elif vid in ("km-KH-PisethNeural",):
            gender = "male"
        else:
            gender = "female"

        return gender, bool(echo_enabled)

    _mod.DubbingApp._normalize_gender_result = _normalize_gender_result_enhanced
    if "DubbingApp" in globals():
        globals()[
            "DubbingApp"]._normalize_gender_result = _normalize_gender_result_enhanced

    # 3. Patch _apply_gender_result_to_row
    _orig_apply_gender_result_to_row = _mod.DubbingApp._apply_gender_result_to_row

    def _apply_gender_result_to_row_enhanced(self, row_index, result, enable_echo=False):
        gender, echo_enabled = self._normalize_gender_result(result)
        ret = _orig_apply_gender_result_to_row(
            self, row_index, result, enable_echo)

        voice_data_map = {
            "boy": "km-KH-PisethNeural_Boy",
            "girl": "km-KH-SreymomNeural_Girl",
            "male": "km-KH-PisethNeural",
            "female": "km-KH-SreymomNeural",
            "old_man": "km-KH-PisethNeural_Old",
            "old_woman": "km-KH-SreymomNeural_Old",
        }
        target_voice = voice_data_map.get(gender, "km-KH-SreymomNeural")
        if hasattr(self, "segments") and 0 <= row_index < len(self.segments):
            self.segments[row_index]["voice"] = target_voice
            self.segments[row_index]["character"] = gender
            if echo_enabled or enable_echo:
                self.segments[row_index]["eco_enabled"] = True
        return ret

    _mod.DubbingApp._apply_gender_result_to_row = _apply_gender_result_to_row_enhanced
    if "DubbingApp" in globals():
        globals()[
            "DubbingApp"]._apply_gender_result_to_row = _apply_gender_result_to_row_enhanced

    # 4. Patch _populate_table_row
    _orig_populate_table_row = _mod.DubbingApp._populate_table_row

    def _populate_table_row_enhanced(self, r, seg):
        if isinstance(seg, dict):
            raw_v = seg.get("voice")
            char_v = seg.get("character")
            if (not raw_v or raw_v == "km-KH-SreymomNeural") and char_v:
                norm_char = normalize_voice_id(char_v, default=None)
                if norm_char:
                    seg["voice"] = norm_char
                    raw_v = norm_char
            if raw_v:
                seg["voice"] = normalize_voice_id(raw_v)

        _orig_populate_table_row(self, r, seg)

        # Ensure combobox has VoxCPM voices and the exact expected voice selected
        try:
            if hasattr(self, "table") and r < self.table.rowCount():
                combo = self.table.cellWidget(r, 6)
                if combo:
                    import voxcpm_support
                    for label, vid, _ in voxcpm_support.VOXCPM_BUILTIN_VOICES:
                        if combo.findData(vid) < 0:
                            combo.addItem(label, vid)
                    if isinstance(seg, dict):
                        v_target = normalize_voice_id(
                            seg.get("voice") or seg.get("character"))
                        idx = combo.findData(v_target)
                        if idx < 0:
                            idx = combo.findText(str(seg.get("voice") or ""))
                        if idx >= 0 and combo.currentIndex() != idx:
                            combo.blockSignals(True)
                            combo.setCurrentIndex(idx)
                            combo.blockSignals(False)
        except Exception:
            pass

    _mod.DubbingApp._populate_table_row = _populate_table_row_enhanced
    if "DubbingApp" in globals():
        globals()["DubbingApp"]._populate_table_row = _populate_table_row_enhanced

    # 5. Patch _collect_table_row_state
    _orig_collect_table_row_state = _mod.DubbingApp._collect_table_row_state

    def _collect_table_row_state_enhanced(self, row):
        state = _orig_collect_table_row_state(self, row)
        try:
            voice_combo = self.table.cellWidget(
                row, 6) if hasattr(self, "table") else None
            voice_val = None
            if voice_combo:
                voice_val = voice_combo.currentData()
                if not voice_val:
                    voice_val = voice_combo.currentText()
            if (not voice_val or voice_val == "km-KH-SreymomNeural") and hasattr(self, "segments") and 0 <= row < len(self.segments):
                seg = self.segments[row]
                seg_v = seg.get("voice")
                if not seg_v or seg_v == "km-KH-SreymomNeural":
                    seg_char = seg.get("character")
                    if seg_char:
                        norm_c = normalize_voice_id(seg_char, default=None)
                        if norm_c and norm_c != "km-KH-SreymomNeural":
                            seg_v = norm_c
                if seg_v:
                    voice_val = seg_v
            if (not voice_val or voice_val == "km-KH-SreymomNeural") and state.get("character"):
                norm_c = normalize_voice_id(
                    state.get("character"), default=None)
                if norm_c and norm_c != "km-KH-SreymomNeural":
                    voice_val = norm_c
            if voice_val:
                state["voice"] = normalize_voice_id(voice_val)
        except Exception:
            pass
        return state

    _mod.DubbingApp._collect_table_row_state = _collect_table_row_state_enhanced
    if "DubbingApp" in globals():
        globals()[
            "DubbingApp"]._collect_table_row_state = _collect_table_row_state_enhanced

    # 6. Patch _collect_segment_analysis_rows
    _orig_collect_segment_analysis_rows = _mod.DubbingApp._collect_segment_analysis_rows

    def _collect_segment_analysis_rows_enhanced(self):
        rows_data = _orig_collect_segment_analysis_rows(self)
        try:
            for r_data in rows_data:
                r_idx = r_data.get("row", 0)
                v = r_data.get("voice_id")
                if not v or v == "km-KH-SreymomNeural":
                    if hasattr(self, "table") and r_idx < self.table.rowCount():
                        combo = self.table.cellWidget(r_idx, 6)
                        if combo:
                            cand = combo.currentData() or combo.currentText()
                            if cand and cand != "km-KH-SreymomNeural":
                                v = cand
                    if (not v or v == "km-KH-SreymomNeural") and hasattr(self, "segments") and r_idx < len(self.segments):
                        seg = self.segments[r_idx]
                        seg_v = seg.get("voice")
                        if not seg_v or seg_v == "km-KH-SreymomNeural":
                            seg_char = seg.get("character")
                            if seg_char:
                                norm_c = normalize_voice_id(
                                    seg_char, default='')
                                if norm_c and norm_c != "km-KH-SreymomNeural":
                                    seg_v = norm_c
                        if seg_v:
                            v = seg_v
                r_data["voice_id"] = normalize_voice_id(v)
        except Exception:
            pass
        return rows_data

    _mod.DubbingApp._collect_segment_analysis_rows = _collect_segment_analysis_rows_enhanced
    if "DubbingApp" in globals():
        globals()[
            "DubbingApp"].QCoreApplication = _collect_segment_analysis_rows_enhanced

    # 7. Patch _start_export_worker
    _orig_start_export_worker = _mod.DubbingApp._start_export_worker

    def _start_export_worker_enhanced(self, table_data, path, video_to_use, remove_vocal, use_demucs, export_audio_mix):
        self._last_exported_video = path
        print(
            f"[EXPORT] Validating multi-voice integrity for {len(table_data)} clips...")
        for i, row in enumerate(table_data):
            v_val = row.get("voice")
            if not v_val or v_val == "km-KH-SreymomNeural":
                # 1. Check combobox widget in table
                if hasattr(self, "table") and i < self.table.rowCount():
                    combo = self.table.cellWidget(i, 6)
                    if combo:
                        cand = combo.currentData() or combo.currentText()
                        if cand and cand != "km-KH-SreymomNeural":
                            v_val = cand
                # 2. Check backing segments (voice and character)
                if (not v_val or v_val == "km-KH-SreymomNeural") and hasattr(self, "segments") and i < len(self.segments):
                    seg = self.segments[i]
                    seg_v = seg.get("voice")
                    if not seg_v or seg_v == "km-KH-SreymomNeural":
                        seg_char = seg.get("character")
                        if seg_char:
                            norm_c = normalize_voice_id(seg_char, default='')
                            if norm_c and norm_c != "km-KH-SreymomNeural":
                                seg_v = norm_c
                    if seg_v and seg_v != "km-KH-SreymomNeural":
                        v_val = seg_v
                # 3. Check character on row itself
                if (not v_val or v_val == "km-KH-SreymomNeural") and row.get("character"):
                    norm_c = normalize_voice_id(
                        row.get("character"), default='')
                    if norm_c and norm_c != "km-KH-SreymomNeural":
                        v_val = norm_c

            resolved_voice, resolved_pitch = resolve_voice_and_pitch(
                v_val, row.get("pitch", "+0Hz"))
            row["voice"] = resolved_voice
            row["pitch"] = resolved_pitch

            expected_cache = self._get_existing_row_audio_cache_for_export(
                i, row.get("text", ""), resolved_voice, resolved_pitch,
                row.get("rate", "+0%"), row.get("start",
                                                0.0), row.get("end", 1.0)
            )
            row["cached_audio_path"] = expected_cache
            print(
                f"  [EXPORT CLIP {i+1}] voice={resolved_voice} pitch={resolved_pitch} cache={'hit' if expected_cache else 'tts'}")

        res = _orig_start_export_worker(self, table_data, path, video_to_use, remove_vocal, use_demucs, export_audio_mix)
        try:
            if hasattr(self, "export_worker") and self.export_worker:
                import settings_manager
                v_cfg = settings_manager.get_export_video_config()
                self.export_worker.video_quality = v_cfg.get("video_quality", "auto")
                self.export_worker.video_crf = v_cfg.get("video_crf", 25)
                self.export_worker.compress_enabled = v_cfg.get("compress_enabled", True)
                self.export_worker.facebook_faststart = v_cfg.get("facebook_faststart", True)
                self.export_worker.allow_upscale = v_cfg.get("allow_upscale", False)
                self.export_worker.audio_bitrate = v_cfg.get("audio_bitrate", "96k")
        except Exception as _cfg_err:
            print(f"[EXPORT] Worker config notice: {_cfg_err}")
        return res

    _mod.DubbingApp._start_export_worker = _start_export_worker_enhanced
    if "DubbingApp" in globals():
        globals()["DubbingApp"]._start_export_worker = _start_export_worker_enhanced
    _mod._orig_start_export_worker = _orig_start_export_worker
    _mod._start_export_worker_enhanced = _start_export_worker_enhanced

    if hasattr(_mod.DubbingApp, "_start_video_speed_adjust_worker"):
        _orig_start_vspeed_worker = _mod.DubbingApp._start_video_speed_adjust_worker
        def _start_vspeed_worker_enhanced(self, *args, **kwargs):
            res = _orig_start_vspeed_worker(self, *args, **kwargs)
            try:
                if hasattr(self, "video_speed_worker") and self.video_speed_worker:
                    import settings_manager
                    v_cfg = settings_manager.get_export_video_config()
                    self.video_speed_worker.video_quality = v_cfg.get("video_quality", "auto")
                    self.video_speed_worker.video_crf = v_cfg.get("video_crf", 25)
                    self.video_speed_worker.compress_enabled = v_cfg.get("compress_enabled", True)
                    self.video_speed_worker.facebook_faststart = v_cfg.get("facebook_faststart", True)
                    self.video_speed_worker.allow_upscale = v_cfg.get("allow_upscale", False)
                    self.video_speed_worker.audio_bitrate = v_cfg.get("audio_bitrate", "96k")
            except Exception as _vsp_err:
                print(f"[VIDEO-SPEED] Worker config notice: {_vsp_err}")
            return res
        _mod.DubbingApp._start_video_speed_adjust_worker = _start_vspeed_worker_enhanced
        if "DubbingApp" in globals():
            globals()["DubbingApp"]._start_video_speed_adjust_worker = _start_vspeed_worker_enhanced

    print("[CORE] Multi-voice export & timeline table synchronization patched successfully.")
except Exception as _mvoice_err:
    import traceback as _tb
    print(f"[CORE] WARNING: Multi-voice export patch failed: {_mvoice_err}")
    _tb.print_exc()

# ── AV1 Hardware Decoding Compatibility & Auto-Transcode ─────────────────────
_COMPATIBLE_VIDEO_CACHE = {}


def probe_video_codec(video_path: str) -> str:
    """Return video stream codec (e.g. 'h264', 'av1', 'vp9') or empty string."""
    if not video_path or not os.path.isfile(video_path):
        return ""
    from runtime_paths import resolve_binary_path
    ffprobe = resolve_binary_path("ffprobe")
    if not ffprobe or not (shutil.which(ffprobe) or os.path.exists(ffprobe)):
        ffprobe = "ffprobe"
    try:
        cmd = [
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=flags)
        if res.returncode == 0:
            return res.stdout.strip().lower()
    except Exception:
        pass
    return ""


def ensure_compatible_video(video_path: str, parent=None) -> str:
    """
    Check if video is AV1 (which causes hardware accelerated decoding errors on OpenCV / older GPUs).
    If AV1, auto-transcodes to a clean H.264 proxy and returns its path.
    """
    if not video_path or not os.path.isfile(video_path):
        return video_path

    if video_path in _COMPATIBLE_VIDEO_CACHE:
        cached = _COMPATIBLE_VIDEO_CACHE[video_path]
        if os.path.isfile(cached) and os.path.getsize(cached) > 0:
            return cached

    codec = probe_video_codec(video_path)
    if codec not in ("av1", "av01"):
        return video_path

    base, ext = os.path.splitext(video_path)
    h264_candidate = f"{base}_h264.mp4"
    if os.path.isfile(h264_candidate) and os.path.getsize(h264_candidate) > 0:
        _COMPATIBLE_VIDEO_CACHE[video_path] = h264_candidate
        return h264_candidate

    from runtime_paths import resolve_binary_path, ensure_app_subdir
    temp_dir = ensure_app_subdir("temp_audio")
    import hashlib
    h = hashlib.md5(video_path.encode("utf-8")).hexdigest()[:8]
    cached_proxy = os.path.join(temp_dir, f"{os.path.basename(base)}_{h}_h264.mp4")
    if os.path.isfile(cached_proxy) and os.path.getsize(cached_proxy) > 0:
        _COMPATIBLE_VIDEO_CACHE[video_path] = cached_proxy
        return cached_proxy

    target_out = h264_candidate if os.access(os.path.dirname(video_path), os.W_OK) else cached_proxy
    ffmpeg = resolve_binary_path("ffmpeg") or "ffmpeg"

    print(f"[VIDEO COMPAT] Detected AV1 codec in '{os.path.basename(video_path)}'. Converting to universal H.264 for hardware playback compatibility...")
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cmd = [
            ffmpeg, "-y", "-v", "error",
            "-i", video_path,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-c:a", "copy",
            target_out,
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=300, creationflags=flags)
        if res.returncode == 0 and os.path.isfile(target_out) and os.path.getsize(target_out) > 0:
            print(f"[VIDEO COMPAT] Successfully converted to H.264: {target_out}")
            _COMPATIBLE_VIDEO_CACHE[video_path] = target_out
            return target_out
    except Exception as e:
        print(f"[VIDEO COMPAT] AV1 transcode warning: {e}")

    return video_path


try:
    if hasattr(_mod, "DubbingApp"):
        # 1. Patch _load_video_path_silent
        if hasattr(_mod.DubbingApp, "_load_video_path_silent"):
            _orig_load_video_path_silent = _mod.DubbingApp._load_video_path_silent
            def _load_video_path_silent_patched(self, f: str):
                compat_f = ensure_compatible_video(f, parent=self)
                return _orig_load_video_path_silent(self, compat_f)
            _mod.DubbingApp._load_video_path_silent = _load_video_path_silent_patched
            if "DubbingApp" in globals():
                globals()["DubbingApp"]._load_video_path_silent = _load_video_path_silent_patched

        # 2. Patch load_video
        if hasattr(_mod.DubbingApp, "load_video"):
            _orig_load_video = _mod.DubbingApp.load_video
            def _load_video_patched(self):
                _orig_load_video(self)
                if hasattr(self, "video_path") and self.video_path:
                    compat_path = ensure_compatible_video(self.video_path, parent=self)
                    if compat_path != self.video_path:
                        self.video_path = compat_path
                        if hasattr(self, "extract_thumbnail"):
                            self.extract_thumbnail(compat_path)
            _mod.DubbingApp.load_video = _load_video_patched
            if "DubbingApp" in globals():
                globals()["DubbingApp"].load_video = _load_video_patched

        # 3. Patch _get_shared_video_capture
        if hasattr(_mod.DubbingApp, "_get_shared_video_capture"):
            _orig_get_shared_video_capture = _mod.DubbingApp._get_shared_video_capture
            def _get_shared_video_capture_patched(self, video_path):
                compat_path = ensure_compatible_video(video_path, parent=self)
                return _orig_get_shared_video_capture(self, compat_path)
            _mod.DubbingApp._get_shared_video_capture = _get_shared_video_capture_patched
            if "DubbingApp" in globals():
                globals()["DubbingApp"]._get_shared_video_capture = _get_shared_video_capture_patched

        # 4. Patch extract_thumbnail
        if hasattr(_mod.DubbingApp, "extract_thumbnail"):
            _orig_extract_thumbnail = _mod.DubbingApp.extract_thumbnail
            def _extract_thumbnail_patched(self, video_path):
                compat_path = ensure_compatible_video(video_path, parent=self)
                return _orig_extract_thumbnail(self, compat_path)
            _mod.DubbingApp.extract_thumbnail = _extract_thumbnail_patched
            if "DubbingApp" in globals():
                globals()["DubbingApp"].extract_thumbnail = _extract_thumbnail_patched

        # 5. Patch _display_preview_frame_from_video
        if hasattr(_mod.DubbingApp, "_display_preview_frame_from_video"):
            _orig_display_preview = _mod.DubbingApp._display_preview_frame_from_video
            def _display_preview_frame_from_video_patched(self, video_path, time_seconds=0.0):
                compat_path = ensure_compatible_video(video_path, parent=self)
                return _orig_display_preview(self, compat_path, time_seconds)
            _mod.DubbingApp._display_preview_frame_from_video = _display_preview_frame_from_video_patched
            if "DubbingApp" in globals():
                globals()["DubbingApp"]._display_preview_frame_from_video = _display_preview_frame_from_video_patched

        print("[CORE] AV1 hardware decoding protection & auto-transcode patched successfully.")
except Exception as _av1_err:
    print(f"[CORE] WARNING: AV1 compatibility patch notice: {_av1_err}")

_mod.probe_video_codec = probe_video_codec
_mod.ensure_compatible_video = ensure_compatible_video
globals()['probe_video_codec'] = probe_video_codec
globals()['ensure_compatible_video'] = ensure_compatible_video


# ---------------------------------------------------------------------------
# VoxCPM2 Segment TTS Generation Worker & UI Integration
# ---------------------------------------------------------------------------

class BatchVoxCPMTTSWorker(QThread):
    progress = pyqtSignal(int, int, str)
    clip_done = pyqtSignal(int, str, float)
    finished = pyqtSignal(int, int)
    cancelled = pyqtSignal()

    def __init__(self, rows_to_process, parent=None):
        super().__init__(parent)
        self.rows_to_process = rows_to_process
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        import voxcpm_support
        completed = 0
        failed = 0
        total = len(self.rows_to_process)

        for idx, item in enumerate(self.rows_to_process):
            if self._is_cancelled:
                self.cancelled.emit()
                return

            row = item['row']
            text = item['text']
            voice_id = item['voice_id']
            dest_path = item['dest_path']
            row_label = f"clip {row + 1}/{total}"

            # If cached audio already exists and is valid, skip generation
            if os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000:
                completed += 1
                self.progress.emit(idx + 1, total, f"✓ Cached {row_label}")
                self.clip_done.emit(row, dest_path, 0.0)
                continue

            self.progress.emit(idx + 1, total, f"🎙️ Generating {row_label} with VoxCPM2...")
            try:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                voxcpm_support.generate_voxcpm_audio(
                    text=text,
                    voice_id=voice_id,
                    output_path=dest_path,
                    progress_callback=lambda msg, pct=None: self.progress.emit(idx + 1, total, f"{row_label}: {msg}")
                )
                completed += 1
                self.clip_done.emit(row, dest_path, 0.0)
            except Exception as e:
                failed += 1
                print(f"[VOXCPM BATCH] Error on {row_label}: {e}")

        self.finished.emit(completed, failed)


def generate_segment_tts_with_voxcpm(self, row, voice_override=None):
    """
    Generates TTS for a single segment row using VoxCPM2.
    """
    import voxcpm_support
    st = voxcpm_support.get_voxcpm_install_status()
    if not st.get("ready"):
        if hasattr(self, "_ensure_voxcpm2_ready_or_prompt"):
            self._ensure_voxcpm2_ready_or_prompt()
        return

    if not hasattr(self, "table") or row < 0 or row >= self.table.rowCount():
        return

    text_item = self.table.item(row, 2)
    text = (text_item.text() if text_item else "").strip()
    if not text:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self, "អត្ថបទទំនេរ (Empty Text)", f"Segment {row + 1} does not have any text.")
        return

    # Determine voice
    target_voice = voice_override
    if not target_voice:
        combo = self.table.cellWidget(row, 6)
        curr = combo.currentData() if combo else None
        if curr and voxcpm_support.is_voxcpm_voice(curr):
            target_voice = curr
        else:
            char_key = ""
            if hasattr(self, "segments") and row < len(self.segments):
                char_key = str(self.segments[row].get("character") or "").lower()
            if any(k in char_key for k in ("male", "man", "piseth")):
                target_voice = "voxcpm:male:normal" if "boy" not in char_key else "voxcpm:boy:normal"
            elif any(k in char_key for k in ("old", "grandpa", "ta", "grandma", "yeay")):
                target_voice = "voxcpm:old_woman:normal"
            elif "girl" in char_key:
                target_voice = "voxcpm:girl:normal"
            else:
                target_voice = "voxcpm:female:normal"

    # Update row combo to target_voice
    combo = self.table.cellWidget(row, 6)
    if combo:
        idx = combo.findData(target_voice)
        if idx >= 0 and combo.currentIndex() != idx:
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)

    pitch = self.table.item(row, 3).text() if self.table.item(row, 3) else "+0Hz"
    rate = self.table.item(row, 4).text() if self.table.item(row, 4) else "+0%"
    dest_path = self._get_row_tts_cache_path(row, text, target_voice, rate, pitch)

    if hasattr(self, "progress_bar") and hasattr(self.progress_bar, "set_status"):
        self.progress_bar.set_status(f"Generating segment {row + 1} with VoxCPM2...")
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()

    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        voxcpm_support.generate_voxcpm_audio(
            text=text,
            voice_id=target_voice,
            output_path=dest_path,
            progress_callback=lambda msg, pct=None: (
                self.progress_bar.set_status(f"VoxCPM2 [Row {row+1}]: {msg}")
                if hasattr(self, "progress_bar") and hasattr(self.progress_bar, "set_status") else None
            )
        )
        dur = self._get_media_duration_seconds(dest_path) if hasattr(self, "_get_media_duration_seconds") else 0.0
        if hasattr(self, "segments") and row < len(self.segments):
            self.segments[row]["voice"] = target_voice
            self.segments[row]["cached_audio_path"] = dest_path

        if hasattr(self, "progress_bar") and hasattr(self.progress_bar, "set_status"):
            self.progress_bar.set_status(f"✅ Segment {row + 1} TTS generated with VoxCPM2 ({dur:.2f}s).")

        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "VoxCPM2 TTS",
            f"Segment {row + 1} audio generated successfully!\n\nVoice: {target_voice}\nDuration: {dur:.2f}s\nCache: {os.path.basename(dest_path)}"
        )
    except Exception as ex:
        if hasattr(self, "progress_bar") and hasattr(self.progress_bar, "set_status"):
            self.progress_bar.set_status(f"❌ Segment {row + 1} VoxCPM2 TTS failed: {ex}")
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(self, "VoxCPM2 Error", f"Failed to generate audio for segment {row + 1}:\n\n{ex}")


def generate_all_segments_tts_with_voxcpm(self):
    """
    Batch generates TTS for all segments in the project using VoxCPM2.
    """
    import voxcpm_support
    st = voxcpm_support.get_voxcpm_install_status()
    if not st.get("ready"):
        if hasattr(self, "_ensure_voxcpm2_ready_or_prompt"):
            self._ensure_voxcpm2_ready_or_prompt()
        return

    if not hasattr(self, "table") or self.table.rowCount() == 0:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self, "គ្មានទិន្នន័យ (No Data)", "There are no segments in the timeline table.")
        return

    rows_to_process = []
    total = self.table.rowCount()

    for r in range(total):
        txt_it = self.table.item(r, 2)
        txt = (txt_it.text() if txt_it else "").strip()
        if not txt:
            continue

        combo = self.table.cellWidget(r, 6)
        v = combo.currentData() if combo else None
        if not v or not voxcpm_support.is_voxcpm_voice(v):
            char_key = ""
            if hasattr(self, "segments") and r < len(self.segments):
                char_key = str(self.segments[r].get("character") or "").lower()
            if any(k in char_key for k in ("male", "man", "piseth")):
                target_v = "voxcpm:male:normal" if "boy" not in char_key else "voxcpm:boy:normal"
            elif any(k in char_key for k in ("old", "grandpa", "ta", "grandma")):
                target_v = "voxcpm:old_woman:normal"
            elif "girl" in char_key:
                target_v = "voxcpm:girl:normal"
            else:
                target_v = "voxcpm:female:normal"
            if combo:
                idx = combo.findData(target_v)
                if idx >= 0:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
        else:
            target_v = v

        pitch = self.table.item(r, 3).text() if self.table.item(r, 3) else "+0Hz"
        rate = self.table.item(r, 4).text() if self.table.item(r, 4) else "+0%"
        dest = self._get_row_tts_cache_path(r, txt, target_v, rate, pitch)
        rows_to_process.append({
            'row': r,
            'text': txt,
            'voice_id': target_v,
            'pitch': pitch,
            'rate': rate,
            'dest_path': dest,
        })

    if not rows_to_process:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self, "No Text", "No text segments found to synthesize.")
        return

    from PyQt5.QtWidgets import QProgressDialog
    from PyQt5.QtCore import Qt

    prog_dlg = QProgressDialog(f"Initializing VoxCPM2 synthesis for {len(rows_to_process)} segments...", "Cancel", 0, len(rows_to_process), self)
    prog_dlg.setWindowTitle("🎙️ VoxCPM2 Batch TTS Generation")
    prog_dlg.setWindowModality(Qt.WindowModal)
    prog_dlg.setMinimumWidth(480)
    prog_dlg.show()

    worker = BatchVoxCPMTTSWorker(rows_to_process, self)

    def on_prog(curr, tot, msg):
        prog_dlg.setValue(curr)
        prog_dlg.setLabelText(f"[{curr}/{tot}] {msg}")
        if hasattr(self, "progress_bar") and hasattr(self.progress_bar, "set_status"):
            self.progress_bar.set_status(f"VoxCPM2 [{curr}/{tot}]: {msg}")

    def on_clip_done(r, p, d):
        if hasattr(self, "segments") and r < len(self.segments):
            self.segments[r]["cached_audio_path"] = p

    def on_fin(completed, failed):
        prog_dlg.close()
        from PyQt5.QtWidgets import QMessageBox
        msg = f"VoxCPM2 generation complete!\n\n✅ Successfully generated: {completed}\n"
        if failed > 0:
            msg += f"❌ Errors: {failed}\n"
        msg += "\nAll generated audio clips are cached and will be reused instantly during Video Export."
        QMessageBox.information(self, "VoxCPM2 Batch TTS Complete", msg)

    prog_dlg.canceled.connect(worker.cancel)
    worker.progress.connect(on_prog)
    worker.clip_done.connect(on_clip_done)
    worker.finished.connect(on_fin)
    self._batch_voxcpm_worker = worker
    worker.start()


def _enhanced_show_segment_actions_menu(self, global_pos, row, clicked_time=None, allow_play=True):
    from PyQt5.QtWidgets import QMenu
    import voxcpm_support

    menu = QMenu(self)
    play_action = None
    vox_single_action = None
    vox_all_action = None
    edit_action = None
    delete_action = None
    sub_actions = []

    if row is not None and 0 <= row < self.table.rowCount():
        if allow_play:
            play_action = menu.addAction("▶ Play Segment Audio")

        vox_single_action = menu.addAction("🎙️ Generate TTS Segment with VoxCPM")
        vox_all_action = menu.addAction("🎙️ Generate All TTS Segments with VoxCPM")

        voice_sub = menu.addMenu("🔄 Switch Voice to VoxCPM...")
        for label, vid, _ in voxcpm_support.VOXCPM_BUILTIN_VOICES[:6]:
            act = voice_sub.addAction(label)
            act.setData(vid)
            sub_actions.append(act)

        menu.addSeparator()
        edit_action = menu.addAction("Edit Segment...")
        delete_action = menu.addAction("Delete Segment")
        menu.addSeparator()

    add_action = menu.addAction("Add Segment...")
    chosen = menu.exec_(global_pos)
    if not chosen:
        return

    if chosen == edit_action:
        self.edit_segment_via_dialog(row)
    elif chosen == play_action and row is not None:
        self.table.selectRow(row)
        self.play_translated_audio_with_video(row)
    elif chosen == vox_single_action and row is not None:
        self.generate_segment_tts_with_voxcpm(row)
    elif chosen == vox_all_action:
        self.generate_all_segments_tts_with_voxcpm()
    elif chosen in sub_actions:
        vox_id = chosen.data()
        self.generate_segment_tts_with_voxcpm(row, voice_override=vox_id)
    elif chosen == delete_action and row is not None:
        self.delete_segment(row)
    elif chosen == add_action:
        self.add_segment_via_dialog(row=row if row is not None else None, clicked_time=clicked_time if row is None else None)


_mod.BatchVoxCPMTTSWorker = BatchVoxCPMTTSWorker
_mod.DubbingApp.generate_segment_tts_with_voxcpm = generate_segment_tts_with_voxcpm
_mod.DubbingApp.generate_all_segments_tts_with_voxcpm = generate_all_segments_tts_with_voxcpm
_mod.DubbingApp._show_segment_actions_menu = _enhanced_show_segment_actions_menu
if "DubbingApp" in globals():
    globals()["DubbingApp"].generate_segment_tts_with_voxcpm = generate_segment_tts_with_voxcpm
    globals()["DubbingApp"].generate_all_segments_tts_with_voxcpm = generate_all_segments_tts_with_voxcpm
    globals()["DubbingApp"]._show_segment_actions_menu = _enhanced_show_segment_actions_menu
    globals()["BatchVoxCPMTTSWorker"] = BatchVoxCPMTTSWorker

print("[CORE] VoxCPM segment TTS generation & context menu options patched successfully.")

sys.modules[__name__] = _mod
