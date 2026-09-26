"""Video Cutter and Merger tool for AI Dubber Ultimate.

Cross-platform video chunk cutting by duration or equal parts, hardware accelerated
video encoding (NVENC/AMF/QSV/CPU), audio extraction to MP3, and drag-and-drop
video merging with natural sorting.
"""

import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

try:
    from PyQt5.QtCore import QThread, QTimer, Qt, pyqtSignal
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QSpinBox,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    class QThread:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def quit(self): pass
        def wait(self): pass
    def pyqtSignal(*args, **kwargs):
        class _DummySig:
            def emit(self, *a, **k): pass
            def connect(self, slot): pass
        return _DummySig()
    class _DummyQt:
        AlignCenter = 0
        WindowContextHelpButtonHint = 0
        PointingHandCursor = 0
    Qt = _DummyQt()
    QApplication = None
    QDialog = object
    QWidget = object
    QMessageBox = None

from runtime_paths import app_path, resource_path
from settings_manager import get_cutter_config, get_hardware_config, save_cutter_config
from utils import get_ffmpeg_path

CUTTER_SCREEN_MARGIN = 32
DEFAULT_CHUNK_DURATION_SECONDS = 300
DEFAULT_AUTO_CONVERT_MP3 = True


def _windows_process_kwargs():
    startupinfo = None
    creationflags = 0
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = subprocess.CREATE_NO_WINDOW
    return {
        'startupinfo': startupinfo,
        'creationflags': creationflags,
    }


def format_ffmpeg_time(total_seconds):
    total_seconds = max(0, float(total_seconds))
    whole_seconds = int(total_seconds)
    milliseconds = int(round((total_seconds - whole_seconds) * 1000))
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    hours = whole_seconds // 3600
    minutes = (whole_seconds % 3600) // 60
    seconds = whole_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def parse_ffmpeg_time(time_text):
    try:
        parts = time_text.strip().split(':')
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        pass
    return None


def _get_available_screen_geometry(widget=None):
    app = QApplication.instance() if QApplication else None
    if app:
        try:
            desktop = app.desktop()
            if widget:
                return desktop.availableGeometry(widget)
            return desktop.availableGeometry()
        except Exception:
            pass
        try:
            screen = widget.screen() if widget else None
            if not screen:
                screen = app.primaryScreen()
            if screen:
                return screen.availableGeometry()
        except Exception:
            pass
    return None


class VideoCutterThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, input_path, output_dir, split_mode='chunks', split_value=300, auto_convert_mp3=True):
        super().__init__()
        self.input_path = str(input_path or '').strip()
        self.output_dir = str(output_dir or '').strip()
        self.split_mode = str(split_mode or 'chunks').strip().lower()
        self.split_value = max(1, int(split_value))
        self.auto_convert_mp3 = bool(auto_convert_mp3)
        self.output_files = []
        self.mp3_output_files = []
        self._available_encoder_names = None
        self._encoder_runtime_probe_cache = {}
        self._is_cancelled = False

    def _resolve_ffmpeg(self, exe_name):
        if exe_name == 'ffmpeg':
            return get_ffmpeg_path()
        candidates = [
            shutil.which(exe_name),
            resource_path(f"{exe_name}.exe" if os.name == 'nt' else exe_name),
            app_path(f"{exe_name}.exe" if os.name == 'nt' else exe_name),
            shutil.which(f"{exe_name}.exe" if os.name == 'nt' else exe_name),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return exe_name

    def _run_process(self, cmd):
        kwargs = _windows_process_kwargs()
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            **kwargs,
        )

    def _probe_video_info(self, video_path):
        ffprobe_bin = self._resolve_ffmpeg('ffprobe')
        cmd = [
            ffprobe_bin,
            '-v', 'error',
            '-show_entries', 'format=duration:stream=index,codec_type,codec_name,width,height',
            '-of', 'json',
            video_path,
        ]
        try:
            res = self._run_process(cmd)
            if res.returncode == 0 and res.stdout.strip():
                return json.loads(res.stdout)
        except Exception as e:
            self.log_signal.emit(f"[WARN] ffprobe failed: {e}")
        return {}

    def get_video_duration(self, video_path):
        info = self._probe_video_info(video_path)
        try:
            return float(info.get('format', {}).get('duration', 0.0))
        except Exception:
            pass
        # Fallback to simple duration query
        ffprobe_bin = self._resolve_ffmpeg('ffprobe')
        cmd = [
            ffprobe_bin,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path,
        ]
        try:
            res = self._run_process(cmd)
            if res.returncode == 0:
                return float(res.stdout.strip())
        except Exception:
            pass
        return 0.0

    def _has_audio_stream(self, video_info):
        for stream in video_info.get('streams', []):
            if stream.get('codec_type') == 'audio':
                return True
        return False

    def _get_video_dimensions(self, video_info):
        for stream in video_info.get('streams', []):
            if stream.get('codec_type') == 'video':
                w = stream.get('width', 0)
                h = stream.get('height', 0)
                return int(w or 0), int(h or 0)
        return 0, 0

    def _needs_padding_filter(self, video_info):
        w, h = self._get_video_dimensions(video_info)
        return (w > 0 and w % 2 != 0) or (h > 0 and h % 2 != 0)

    def _get_video_mode_codec(self, video_mode):
        codecs = {
            'cpu': 'libx264',
            'nvenc': 'h264_nvenc',
            'amf': 'h264_amf',
            'qsv': 'h264_qsv',
        }
        return codecs.get(video_mode, 'libx264')

    def _get_video_mode_label(self, video_mode):
        labels = {
            'cpu': 'CPU (libx264)',
            'nvenc': 'NVIDIA NVENC',
            'amf': 'AMD AMF',
            'qsv': 'Intel QuickSync',
        }
        return labels.get(video_mode, 'CPU (libx264)')

    def _get_available_encoder_names(self):
        if self._available_encoder_names is not None:
            return self._available_encoder_names
        ffmpeg_bin = self._resolve_ffmpeg('ffmpeg')
        cmd = [ffmpeg_bin, '-hide_banner', '-encoders']
        names = set()
        try:
            res = self._run_process(cmd)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0].startswith('V'):
                        names.add(parts[1])
        except Exception:
            pass
        self._available_encoder_names = names
        return names

    def _build_encoder_probe_command(self, video_mode):
        ffmpeg_bin = self._resolve_ffmpeg('ffmpeg')
        codec = self._get_video_mode_codec(video_mode)
        return [
            ffmpeg_bin,
            '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'nullsrc=s=128x128:d=0.1',
            '-c:v', codec,
            '-f', 'null', '-',
        ]

    def _probe_encoder_runtime_support(self, video_mode):
        if video_mode in self._encoder_runtime_probe_cache:
            return self._encoder_runtime_probe_cache[video_mode]
        if video_mode == 'cpu':
            self._encoder_runtime_probe_cache[video_mode] = True
            return True
        codec = self._get_video_mode_codec(video_mode)
        if codec not in self._get_available_encoder_names():
            self._encoder_runtime_probe_cache[video_mode] = False
            return False
        cmd = self._build_encoder_probe_command(video_mode)
        try:
            res = self._run_process(cmd)
            ok = (res.returncode == 0)
            self._encoder_runtime_probe_cache[video_mode] = ok
            return ok
        except Exception:
            self._encoder_runtime_probe_cache[video_mode] = False
            return False

    def _log_encoder_status(self, requested_mode):
        supported = self._probe_encoder_runtime_support(requested_mode)
        label = self._get_video_mode_label(requested_mode)
        if supported:
            self.log_signal.emit(f"Using video encoder: {label}")
            return requested_mode
        self.log_signal.emit(f"Encoder '{label}' not available on this system. Falling back to CPU (libx264).")
        return 'cpu'

    def _resolve_initial_video_mode(self):
        hw = get_hardware_config()
        mode = hw.get('video_encoder', 'cpu').lower()
        return self._log_encoder_status(mode)

    def _build_video_args(self, video_mode, video_info):
        args = []
        if self._needs_padding_filter(video_info):
            args.extend(['-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2'])
        if video_mode == 'nvenc':
            args.extend(['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '18', '-b:v', '0', '-pix_fmt', 'yuv420p'])
        elif video_mode == 'amf':
            args.extend(['-c:v', 'h264_amf', '-quality', 'quality', '-pix_fmt', 'yuv420p'])
        elif video_mode == 'qsv':
            args.extend(['-c:v', 'h264_qsv', '-global_quality', '18', '-look_ahead', '0'])
        else:
            args.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p'])
        return args

    def _build_audio_args(self, video_info):
        return ['-c:a', 'aac', '-b:a', '192k']

    def _cleanup_old_outputs(self, base_name):
        try:
            pattern = re.compile(rf"^{re.escape(base_name)}_chunk_\d+\.(mp4|mkv|mov|mp3)$", re.IGNORECASE)
            for f in os.listdir(self.output_dir):
                if pattern.match(f):
                    try:
                        os.remove(os.path.join(self.output_dir, f))
                    except Exception:
                        pass
        except Exception:
            pass

    def _build_chunk_command(self, start_time, chunk_duration, output_path, video_info, video_mode, accurate_seek=True):
        ffmpeg_bin = self._resolve_ffmpeg('ffmpeg')
        cmd = [ffmpeg_bin, '-y', '-hide_banner', '-loglevel', 'error', '-nostdin']
        if accurate_seek:
            cmd.extend(['-ss', f"{start_time:.3f}", '-t', f"{chunk_duration:.3f}", '-i', self.input_path])
        else:
            cmd.extend(['-ss', f"{start_time:.3f}", '-i', self.input_path, '-t', f"{chunk_duration:.3f}"])
        cmd.extend(self._build_video_args(video_mode, video_info))
        cmd.extend(self._build_audio_args(video_info))
        cmd.append(output_path)
        return cmd

    def _build_direct_mp3_command(self, start_time, chunk_duration, output_path):
        ffmpeg_bin = self._resolve_ffmpeg('ffmpeg')
        return [
            ffmpeg_bin, '-y', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-ss', f"{start_time:.3f}", '-i', self.input_path, '-t', f"{chunk_duration:.3f}",
            '-map', '0:a:0?', '-vn', '-c:a', 'libmp3lame', '-b:a', '192k',
            output_path,
        ]

    def _build_mp3_command(self, chunk_path, output_path):
        ffmpeg_bin = self._resolve_ffmpeg('ffmpeg')
        return [
            ffmpeg_bin, '-y', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-i', chunk_path,
            '-map', '0:a:0?', '-vn', '-c:a', 'libmp3lame', '-b:a', '192k',
            output_path,
        ]

    def _convert_chunk_to_mp3(self, chunk_path, output_path, start_time, chunk_duration):
        cmd = self._build_mp3_command(chunk_path, output_path)
        res = self._run_process(cmd)
        if res.returncode != 0:
            direct_cmd = self._build_direct_mp3_command(start_time, chunk_duration, output_path)
            res = self._run_process(direct_cmd)
        return os.path.exists(output_path)

    def _is_chunk_duration_valid(self, actual_duration, expected_duration):
        if expected_duration <= 0:
            return True
        return actual_duration >= min(expected_duration * 0.8, max(0.5, expected_duration - 1.0))

    def _did_source_end_prematurely(self, recent_lines):
        text = ' '.join(recent_lines).lower()
        return any(k in text for k in ('end of file', 'eof', 'invalid data', 'corrupt'))

    def _run_chunk_process(self, cmd, start_time, chunk_duration, total_duration, process_kwargs):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore',
            **process_kwargs,
        )
        recent_lines = []
        for line in iter(proc.stdout.readline, ''):
            if self._is_cancelled:
                proc.kill()
                return False
            stripped = line.strip()
            if stripped:
                recent_lines.append(stripped)
                if len(recent_lines) > 20:
                    recent_lines.pop(0)
            if 'time=' in stripped:
                parts = stripped.split('time=')
                if len(parts) > 1:
                    time_str = parts[1].split()[0]
                    t = parse_ffmpeg_time(time_str)
                    if t is not None and total_duration > 0:
                        overall_progress = min(99, int((start_time + t) / total_duration * 100))
                        self.progress_signal.emit(overall_progress)
        proc.wait()
        return proc.returncode == 0

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            total_duration = self.get_video_duration(self.input_path)
            if total_duration <= 0:
                self.finished_signal.emit(False, f"Could not determine video duration for '{self.input_path}'.")
                return

            os.makedirs(self.output_dir, exist_ok=True)
            stem = Path(self.input_path).stem
            self._cleanup_old_outputs(stem)

            if self.split_mode == 'parts':
                num_parts = max(1, self.split_value)
                chunk_duration = total_duration / num_parts
            else:
                chunk_duration = max(1.0, float(self.split_value))
                num_parts = math.ceil(total_duration / chunk_duration)

            self.log_signal.emit(f"Input video duration: {format_ffmpeg_time(total_duration)}")
            self.log_signal.emit(f"Splitting into {num_parts} chunk(s) of ~{format_ffmpeg_time(chunk_duration)} each.")

            video_info = self._probe_video_info(self.input_path)
            video_mode = self._resolve_initial_video_mode()
            kwargs = _windows_process_kwargs()

            self.output_files = []
            self.mp3_output_files = []

            for i in range(num_parts):
                if self._is_cancelled:
                    self.finished_signal.emit(False, "Cutting was cancelled by user.")
                    return

                start_time = i * chunk_duration
                cur_duration = min(chunk_duration, total_duration - start_time)
                if cur_duration <= 0.05:
                    break

                out_name = f"{stem}_chunk_{i + 1:03d}.mp4"
                out_path = os.path.join(self.output_dir, out_name)

                self.log_signal.emit(f"Cutting chunk {i + 1}/{num_parts}: {out_name} [{format_ffmpeg_time(start_time)} -> {format_ffmpeg_time(start_time + cur_duration)}]")

                cmd = self._build_chunk_command(start_time, cur_duration, out_path, video_info, video_mode, accurate_seek=True)
                success = self._run_chunk_process(cmd, start_time, cur_duration, total_duration, kwargs)

                if not success and video_mode != 'cpu':
                    self.log_signal.emit(f"Hardware encoder failed for chunk {i + 1}. Retrying with CPU encoder...")
                    video_mode = 'cpu'
                    cmd = self._build_chunk_command(start_time, cur_duration, out_path, video_info, video_mode, accurate_seek=True)
                    success = self._run_chunk_process(cmd, start_time, cur_duration, total_duration, kwargs)

                if not success or not os.path.exists(out_path):
                    self.finished_signal.emit(False, f"Failed to cut chunk {i + 1}.")
                    return

                self.output_files.append(out_path)

                if self.auto_convert_mp3 and self._has_audio_stream(video_info):
                    mp3_name = f"{stem}_chunk_{i + 1:03d}.mp3"
                    mp3_path = os.path.join(self.output_dir, mp3_name)
                    self._convert_chunk_to_mp3(out_path, mp3_path, start_time, cur_duration)
                    if os.path.exists(mp3_path):
                        self.mp3_output_files.append(mp3_path)

                progress = min(99, int((i + 1) / num_parts * 100))
                self.progress_signal.emit(progress)

            self.progress_signal.emit(100)
            msg = f"Successfully cut {len(self.output_files)} video chunk(s)."
            if self.mp3_output_files:
                msg += f" Generated {len(self.mp3_output_files)} MP3 audio file(s)."
            self.log_signal.emit(msg)
            self.finished_signal.emit(True, msg)
        except Exception as e:
            self.finished_signal.emit(False, f"Unexpected error during video cutting: {e}")


class VideoMergeThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, input_files, output_path):
        super().__init__()
        self.input_files = [str(f).strip() for f in input_files if f]
        self.output_path = str(output_path).strip()
        self._is_cancelled = False

    def _resolve_ffmpeg(self, exe_name):
        if exe_name == 'ffmpeg':
            return get_ffmpeg_path()
        for c in (
            shutil.which(exe_name),
            resource_path(f"{exe_name}.exe" if os.name == 'nt' else exe_name),
            app_path(f"{exe_name}.exe" if os.name == 'nt' else exe_name),
        ):
            if c and os.path.exists(c):
                return c
        return exe_name

    def _run_process(self, cmd):
        kwargs = _windows_process_kwargs()
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore',
            **kwargs,
        )

    def _get_video_duration(self, video_path):
        ffprobe_bin = self._resolve_ffmpeg('ffprobe')
        cmd = [
            ffprobe_bin,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path,
        ]
        try:
            res = self._run_process(cmd)
            if res.returncode == 0:
                return float(res.stdout.strip())
        except Exception:
            pass
        return 0.0

    def _write_concat_file(self):
        tmp = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='_merge_list.txt', prefix='ffmpeg_', delete=False)
        with tmp as f:
            for path in self.input_files:
                escaped = path.replace('\\', '/').replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
        return tmp.name

    def _build_merge_command(self, concat_list_path, reencode=False):
        ffmpeg_bin = self._resolve_ffmpeg('ffmpeg')
        cmd = [
            ffmpeg_bin, '-y', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-f', 'concat', '-safe', '0', '-i', concat_list_path,
        ]
        if reencode:
            cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-c:a', 'aac', '-b:a', '192k'])
        else:
            cmd.extend(['-c', 'copy'])
        cmd.extend(['-movflags', '+faststart', '-progress', 'pipe:1', '-nostats', self.output_path])
        return cmd

    def _run_merge_process(self, cmd, total_duration):
        kwargs = _windows_process_kwargs()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore',
            bufsize=1,
            universal_newlines=True,
            **kwargs,
        )
        for line in iter(proc.stdout.readline, ''):
            if self._is_cancelled:
                proc.kill()
                return False
            stripped = line.strip()
            if stripped.startswith('out_time='):
                val = stripped.split('out_time=')[1].strip()
                t = parse_ffmpeg_time(val)
                if t is not None and total_duration > 0:
                    prog = min(99, int(t / total_duration * 100))
                    self.progress_signal.emit(prog)
            elif stripped.startswith(('out_time_ms=', 'out_time_us=')):
                try:
                    val = float(stripped.split('=')[1].strip()) / 1000000.0
                    if total_duration > 0:
                        prog = min(99, int(val / total_duration * 100))
                        self.progress_signal.emit(prog)
                except Exception:
                    pass
        proc.wait()
        return proc.returncode == 0

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if len(self.input_files) < 2:
            self.finished_signal.emit(False, "Please select at least 2 video files to merge.")
            return

        concat_file = None
        try:
            total_duration = sum(self._get_video_duration(f) for f in self.input_files)
            concat_file = self._write_concat_file()

            # Attempt stream copy first (fast, lossless)
            self.log_signal.emit(f"Merging {len(self.input_files)} videos using fast stream copy...")
            cmd = self._build_merge_command(concat_file, reencode=False)
            success = self._run_merge_process(cmd, total_duration)

            # If copy failed, fall back to re-encode
            if not success or not os.path.exists(self.output_path) or os.path.getsize(self.output_path) == 0:
                self.log_signal.emit("Stream copy failed (codecs may differ). Falling back to re-encoding...")
                cmd = self._build_merge_command(concat_file, reencode=True)
                success = self._run_merge_process(cmd, total_duration)

            if success and os.path.exists(self.output_path) and os.path.getsize(self.output_path) > 0:
                self.progress_signal.emit(100)
                msg = f"Merged {len(self.input_files)} videos successfully.\nOutput: {self.output_path}"
                self.log_signal.emit(msg)
                self.finished_signal.emit(True, msg)
            else:
                self.finished_signal.emit(False, "Could not merge the selected videos. Please make sure files are valid and compatible.")
        except Exception as e:
            self.finished_signal.emit(False, f"Error during video merge: {e}")
        finally:
            if concat_file and os.path.exists(concat_file):
                try:
                    os.remove(concat_file)
                except Exception:
                    pass


class MergeOrderDialog(QDialog):
    def __init__(self, initial_files=None, last_dir='', parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge Videos - Order")
        self.setMinimumSize(720, 520)
        self._last_dir = str(last_dir or '')

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        desc = QLabel("Add video files, then drag items up/down to change the merge order.\nWhen the order looks correct, click Merge.")
        desc.setStyleSheet("font-weight: bold;")
        layout.addWidget(desc)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setDefaultDropAction(Qt.MoveAction)
        layout.addWidget(self.list_widget)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        add_btn = QPushButton("➕ Add Videos")
        add_btn.setObjectName("secondaryBtn")
        add_btn.clicked.connect(self._add_files)
        btn_row.addWidget(add_btn)

        remove_btn = QPushButton("🗑 Remove")
        remove_btn.setObjectName("dangerBtn")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("secondaryBtn")
        clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(clear_btn)

        sort_btn = QPushButton("↕ Auto Sort")
        sort_btn.setObjectName("secondaryBtn")
        sort_btn.clicked.connect(self._auto_sort)
        btn_row.addWidget(sort_btn)

        btn_row.addStretch()

        ok_btn = QPushButton("✅ Merge")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.clicked.connect(self._accept_if_valid)
        btn_row.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("secondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

        if initial_files:
            self._set_files(initial_files)

    def _normalize_path(self, file_path):
        return os.path.normpath(str(file_path or ''))

    def _iter_current_paths(self):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            path = item.data(Qt.UserRole)
            if path:
                yield path

    def _set_files(self, file_paths):
        self.list_widget.clear()
        for p in file_paths:
            norm = self._normalize_path(p)
            item = QListWidgetItem(os.path.basename(norm))
            item.setData(Qt.UserRole, norm)
            item.setToolTip(norm)
            self.list_widget.addItem(item)
        self._refresh_labels()

    def _refresh_labels(self):
        count = self.list_widget.count()
        pad = max(2, len(str(count)))
        for i in range(count):
            item = self.list_widget.item(i)
            path = item.data(Qt.UserRole)
            base = os.path.basename(path)
            item.setText(f"{i + 1:0{pad}d}. {base}")

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Add Video Files",
            self._last_dir,
            "Video files (*.mp4 *.mkv *.mov *.ts *.avi *.wmv *.flv);;All files (*)",
        )
        if files:
            self._last_dir = os.path.dirname(files[0])
            current = set(self._iter_current_paths())
            for f in files:
                norm = self._normalize_path(f)
                if norm not in current:
                    current.add(norm)
                    item = QListWidgetItem(os.path.basename(norm))
                    item.setData(Qt.UserRole, norm)
                    item.setToolTip(norm)
                    self.list_widget.addItem(item)
            self._refresh_labels()

    def _remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))
        self._refresh_labels()

    def _clear_all(self):
        self.list_widget.clear()

    def _natural_sort_key(self, value):
        return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', str(value or ''))]

    def _auto_sort(self):
        paths = list(self._iter_current_paths())
        paths.sort(key=lambda p: self._natural_sort_key(os.path.basename(p)))
        self._set_files(paths)

    def _accept_if_valid(self):
        if self.list_widget.count() < 2:
            if QMessageBox:
                QMessageBox.warning(self, "Merge Videos", "Please add at least 2 video files.")
            return
        self.accept()

    def get_ordered_files(self):
        return list(self._iter_current_paths())

    def last_dir(self):
        return self._last_dir


class VideoCutterApp(QWidget):
    def __init__(self, default_input_path=''):
        super().__init__()
        self.setObjectName("videoCutterRoot")
        self.setWindowTitle("AI Dubber Ultimate - Video Cutter")
        self.setMinimumSize(720, 420)
        self.resize(760, 884)

        for name in ('icon.png', 'icon.ico'):
            icon_path = resource_path('resources', name)
            if not os.path.exists(icon_path):
                icon_path = resource_path(name)
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                break

        self.default_input_path = str(default_input_path or '')
        self._cutter_thread = None
        self._merge_thread = None

        self._apply_cutter_theme()
        self.init_ui()
        self._load_cutter_preferences()
        self._refresh_summary()
        self._update_action_states()

    def _apply_cutter_theme(self):
        try:
            from theme_manager import get_theme_mode
            is_dark = get_theme_mode() == 'dark'
        except Exception:
            is_dark = True

        try:
            from ui_theme_tokens import (
                FONT_FAMILY,
                COLOR_CANVAS, COLOR_SURFACE, COLOR_SURFACE_INPUT, COLOR_SURFACE_HOVER,
                COLOR_BORDER, COLOR_BORDER_ELEVATED, COLOR_ACCENT, COLOR_ACCENT_HOVER, COLOR_ACCENT_GRADIENT,
                COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_TEXT_MUTED,
                LIGHT_COLOR_CANVAS, LIGHT_COLOR_SURFACE, LIGHT_COLOR_SURFACE_INPUT, LIGHT_COLOR_SURFACE_HOVER,
                LIGHT_COLOR_BORDER, LIGHT_COLOR_BORDER_ELEVATED, LIGHT_COLOR_ACCENT, LIGHT_COLOR_ACCENT_HOVER,
                LIGHT_COLOR_TEXT_PRIMARY, LIGHT_COLOR_TEXT_SECONDARY, LIGHT_COLOR_TEXT_MUTED,
                RADIUS_CONTROL, RADIUS_INPUT, RADIUS_CARD, RADIUS_PILL,
            )

            canvas = COLOR_CANVAS if is_dark else LIGHT_COLOR_CANVAS
            surface = COLOR_SURFACE if is_dark else LIGHT_COLOR_SURFACE
            input_bg = COLOR_SURFACE_INPUT if is_dark else LIGHT_COLOR_SURFACE_INPUT
            surface_hover = COLOR_SURFACE_HOVER if is_dark else LIGHT_COLOR_SURFACE_HOVER
            border = COLOR_BORDER if is_dark else LIGHT_COLOR_BORDER
            border_elevated = COLOR_BORDER_ELEVATED if is_dark else LIGHT_COLOR_BORDER_ELEVATED
            accent = COLOR_ACCENT if is_dark else LIGHT_COLOR_ACCENT
            accent_hover = COLOR_ACCENT_HOVER if is_dark else LIGHT_COLOR_ACCENT_HOVER
            accent_grad = COLOR_ACCENT_GRADIENT
            text_primary = COLOR_TEXT_PRIMARY if is_dark else LIGHT_COLOR_TEXT_PRIMARY
            text_secondary = COLOR_TEXT_SECONDARY if is_dark else LIGHT_COLOR_TEXT_SECONDARY
            text_muted = COLOR_TEXT_MUTED if is_dark else LIGHT_COLOR_TEXT_MUTED
            btn_sec_bg = '#1E293B' if is_dark else '#F1F5F9'
            btn_sec_border = border_elevated

            self.setStyleSheet(f"""
                QWidget {{
                    color: {text_primary};
                    font-family: {FONT_FAMILY};
                    font-size: 13px;
                }}
                QWidget#videoCutterRoot {{
                    background-color: {canvas};
                }}
                QLabel {{
                    background: transparent;
                    color: {text_primary};
                }}
                QFrame#card {{
                    background-color: {surface};
                    border: 1px solid {border};
                    border-radius: {RADIUS_CARD};
                }}
                QLabel#bodyLabel {{
                    color: {text_muted};
                    font-size: 12px;
                    padding-top: 1px;
                    padding-bottom: 1px;
                }}
                QLabel#sectionLabel {{
                    color: {text_primary};
                    font-size: 15px;
                    font-weight: 700;
                    min-height: 20px;
                }}
                QLabel#fieldLabel {{
                    color: {text_secondary};
                    font-size: 11px;
                    font-weight: 600;
                    min-height: 18px;
                }}
                QLabel#statusBadge {{
                    background-color: {accent};
                    color: white;
                    border-radius: 999px;
                    padding: 4px 10px;
                    font-size: 11px;
                    font-weight: 700;
                }}
                QLabel#summaryLabel {{
                    background-color: {surface_hover};
                    border: 1px solid {border_elevated};
                    border-radius: {RADIUS_CONTROL};
                    padding: 10px 14px;
                    color: {text_secondary};
                }}
                QLineEdit, QTextEdit, QSpinBox, QComboBox {{
                    background: {input_bg};
                    color: {text_primary};
                    border: 1px solid {border_elevated};
                    border-radius: {RADIUS_INPUT};
                    padding: 7px 10px;
                    selection-background-color: {accent};
                }}
                QLineEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
                    border: 1.5px solid {accent};
                }}
                QComboBox {{
                    min-width: 150px;
                    padding-right: 24px;
                }}
                QCheckBox {{
                    color: {text_secondary};
                    spacing: 8px;
                    min-height: 22px;
                }}
                QPushButton, QPushButton#secondaryButton, QPushButton#secondaryBtn {{
                    background-color: {btn_sec_bg};
                    color: {text_primary};
                    border: 1px solid {btn_sec_border};
                    border-radius: {RADIUS_CONTROL};
                    padding: 7px 14px;
                    font-weight: 700;
                }}
                QPushButton:hover, QPushButton#secondaryButton:hover, QPushButton#secondaryBtn:hover {{
                    border-color: {accent};
                    background-color: {surface_hover};
                }}
                QPushButton#primaryButton, QPushButton#primaryBtn {{
                    background-color: {accent_grad};
                    color: white;
                    border: none;
                    border-radius: {RADIUS_PILL};
                    font-weight: 800;
                    padding: 7px 18px;
                }}
                QPushButton#primaryButton:hover, QPushButton#primaryBtn:hover {{
                    background-color: {accent_hover};
                }}
                QProgressBar {{
                    background-color: {input_bg};
                    color: {text_primary};
                    border: 1px solid {border_elevated};
                    border-radius: 6px;
                    min-height: 18px;
                    text-align: center;
                    font-weight: bold;
                    font-size: 11px;
                }}
                QProgressBar::chunk {{
                    background-color: {accent};
                    border-radius: 5px;
                }}
            """)
        except Exception as e:
            print(f"[VideoCutterApp] _apply_cutter_theme notice: {e}")

    def _create_card(self, object_name="card"):
        card = QFrame()
        card.setObjectName(object_name)
        return card

    def _make_section_header(self, title, description):
        box = QVBoxLayout()
        box.setSpacing(2)
        lbl_title = QLabel(title)
        lbl_title.setObjectName("sectionLabel")
        lbl_desc = QLabel(description)
        lbl_desc.setObjectName("bodyLabel")
        box.addWidget(lbl_title)
        box.addWidget(lbl_desc)
        return box

    def _make_field_label(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("fieldLabel")
        return lbl

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        # Card 1: Source & Output
        card1 = self._create_card()
        card1_layout = QVBoxLayout(card1)
        card1_layout.setContentsMargins(16, 16, 16, 16)
        card1_layout.setSpacing(10)
        card1_layout.addLayout(self._make_section_header("Source & Output", "Choose the video and save location."))

        # Input Video Row
        card1_layout.addWidget(self._make_field_label("Input Video"))
        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select a video file...")
        if self.default_input_path:
            self.input_edit.setText(self.default_input_path)
        self.input_edit.textChanged.connect(self._on_form_state_changed)
        input_row.addWidget(self.input_edit)

        browse_video_btn = QPushButton("Browse Video")
        browse_video_btn.setObjectName("secondaryButton")
        browse_video_btn.clicked.connect(self.browse_input_file)
        input_row.addWidget(browse_video_btn)
        card1_layout.addLayout(input_row)

        # Output Folder Row
        card1_layout.addWidget(self._make_field_label("Output Folder"))
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Select output folder...")
        self.output_edit.textChanged.connect(self._on_form_state_changed)
        output_row.addWidget(self.output_edit)

        choose_folder_btn = QPushButton("Choose Folder")
        choose_folder_btn.setObjectName("secondaryButton")
        choose_folder_btn.clicked.connect(self.browse_output_dir)
        output_row.addWidget(choose_folder_btn)
        card1_layout.addLayout(output_row)

        main_layout.addWidget(card1)

        # Card 2: Cut Settings
        card2 = self._create_card()
        card2_layout = QVBoxLayout(card2)
        card2_layout.setContentsMargins(16, 16, 16, 16)
        card2_layout.setSpacing(10)
        card2_layout.addLayout(self._make_section_header("Cut Settings", "Cut by duration or let the app split by number of parts."))

        settings_row = QHBoxLayout()
        settings_row.setSpacing(12)

        # Split Mode Combo
        mode_box = QVBoxLayout()
        mode_box.addWidget(self._make_field_label("Split Mode"))
        self.split_mode_combo = QComboBox()
        self.split_mode_combo.addItem("By Duration", "duration")
        self.split_mode_combo.addItem("By Number of Parts", "count")
        self.split_mode_combo.currentIndexChanged.connect(self._on_split_mode_changed)
        mode_box.addWidget(self.split_mode_combo)
        settings_row.addLayout(mode_box)

        # Spinner
        self.spinner_box = QVBoxLayout()
        self.spinner_label = self._make_field_label("Chunk Length (seconds)")
        self.spinner_box.addWidget(self.spinner_label)
        self.split_spin = QSpinBox()
        self.split_spin.setRange(1, 86400)
        self.split_spin.setValue(DEFAULT_CHUNK_DURATION_SECONDS)
        self.split_spin.valueChanged.connect(self._on_form_state_changed)
        self.spinner_box.addWidget(self.split_spin)
        settings_row.addLayout(self.spinner_box)

        card2_layout.addLayout(settings_row)

        # Auto Convert MP3 Checkbox
        self.mp3_check = QCheckBox("Auto Convert Chunks to MP3")
        self.mp3_check.setChecked(DEFAULT_AUTO_CONVERT_MP3)
        self.mp3_check.stateChanged.connect(self._on_form_state_changed)
        card2_layout.addWidget(self.mp3_check)

        # Summary Label
        self.summary_label = QLabel("Shorter chunks are easier to review.")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_label.setWordWrap(True)
        card2_layout.addWidget(self.summary_label)

        main_layout.addWidget(card2)

        # Action Buttons Row
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.cut_btn = QPushButton("Start Cutting")
        self.cut_btn.setObjectName("primaryButton")
        self.cut_btn.clicked.connect(self.cut_video)
        action_row.addWidget(self.cut_btn)

        self.merge_btn = QPushButton("Merge Videos")
        self.merge_btn.setObjectName("secondaryButton")
        self.merge_btn.clicked.connect(self.merge_videos)
        action_row.addWidget(self.merge_btn)

        self.preview_btn = QPushButton("Preview First Chunk")
        self.preview_btn.setObjectName("secondaryButton")
        self.preview_btn.clicked.connect(self.play_first_output)
        action_row.addWidget(self.preview_btn)

        self.open_folder_btn = QPushButton("Open Output Folder")
        self.open_folder_btn.setObjectName("secondaryButton")
        self.open_folder_btn.clicked.connect(self.open_output_folder)
        action_row.addWidget(self.open_folder_btn)

        main_layout.addLayout(action_row)

        # Card 3: Progress
        card3 = self._create_card()
        card3_layout = QVBoxLayout(card3)
        card3_layout.setContentsMargins(16, 16, 16, 16)
        card3_layout.setSpacing(8)

        prog_hdr = QHBoxLayout()
        prog_hdr.addLayout(self._make_section_header("Progress", "Live feedback while the cutter works."))
        prog_hdr.addStretch()
        self.status_badge = QLabel("Ready")
        self.status_badge.setObjectName("statusBadge")
        prog_hdr.addWidget(self.status_badge)
        card3_layout.addLayout(prog_hdr)

        self.status_detail_label = QLabel("Waiting for a video selection.")
        self.status_detail_label.setObjectName("bodyLabel")
        card3_layout.addWidget(self.status_detail_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        card3_layout.addWidget(self.progress_bar)

        main_layout.addWidget(card3)

        # Card 4: Activity Log
        card4 = self._create_card()
        card4_layout = QVBoxLayout(card4)
        card4_layout.setContentsMargins(16, 16, 16, 16)
        card4_layout.setSpacing(6)
        card4_layout.addLayout(self._make_section_header("Activity Log", "FFmpeg and cutting messages appear here."))

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("Your cut session logs will appear here.")
        self.log_edit.setStyleSheet("min-height: 82px;")
        card4_layout.addWidget(self.log_edit)

        main_layout.addWidget(card4)

    def _current_split_mode(self):
        return self.split_mode_combo.currentData() or 'duration'

    def _apply_split_mode_ui(self):
        mode = self._current_split_mode()
        if mode == 'count':
            self.spinner_label.setText("Number of Equal Parts")
            self.split_spin.setRange(2, 500)
            if self.split_spin.value() > 500:
                self.split_spin.setValue(4)
        else:
            self.spinner_label.setText("Chunk Length (seconds)")
            self.split_spin.setRange(5, 86400)
            if self.split_spin.value() < 5:
                self.split_spin.setValue(DEFAULT_CHUNK_DURATION_SECONDS)

    def _on_split_mode_changed(self, _index=0):
        self._apply_split_mode_ui()
        self._on_form_state_changed()

    def _on_form_state_changed(self):
        self._refresh_summary()
        self._update_action_states()

    def _load_cutter_preferences(self):
        cfg = get_cutter_config()
        if not isinstance(cfg, dict):
            return
        out_dir = cfg.get('output_dir', '')
        if out_dir and os.path.exists(out_dir):
            self.output_edit.setText(out_dir)
        mode = cfg.get('split_mode', 'duration')
        idx = self.split_mode_combo.findData(mode)
        if idx != -1:
            self.split_mode_combo.setCurrentIndex(idx)
        val = cfg.get('split_value', DEFAULT_CHUNK_DURATION_SECONDS)
        try:
            self.split_spin.setValue(int(val))
        except Exception:
            pass
        self.mp3_check.setChecked(bool(cfg.get('auto_convert_mp3', DEFAULT_AUTO_CONVERT_MP3)))

    def _save_cutter_preferences(self):
        save_cutter_config({
            'output_dir': self.output_edit.text().strip(),
            'split_mode': self._current_split_mode(),
            'split_value': self.split_spin.value(),
            'auto_convert_mp3': self.mp3_check.isChecked(),
        })

    def _set_status(self, title, detail="", mode="idle"):
        self.status_badge.setText(title)
        self.status_detail_label.setText(detail)
        colors = {
            'idle': '#16A085',
            'working': '#F39C12',
            'error': '#E74C3C',
            'success': '#27AE60',
        }
        col = colors.get(mode, '#16A085')
        self.status_badge.setStyleSheet(f"background-color: {col}; color: white; border-radius: 999px; padding: 6px 12px; font-size: 11px; font-weight: 700;")

    def _refresh_summary(self):
        inp = self.input_edit.text().strip()
        out = self.output_edit.text().strip()
        mode = self._current_split_mode()
        val = self.split_spin.value()
        mode_desc = f"split into chunks of {val}s" if mode == 'duration' else f"split into {val} equal parts"
        mp3_desc = " + extract MP3" if self.mp3_check.isChecked() else ""
        if inp:
            self.summary_label.setText(f"Source: <b>{os.path.basename(inp)}</b> | Action: {mode_desc}{mp3_desc}")
        else:
            self.summary_label.setText(f"Select a video to {mode_desc}{mp3_desc}.")

    def _update_action_states(self):
        has_input = bool(self.input_edit.text().strip()) and os.path.exists(self.input_edit.text().strip())
        is_busy = (self._cutter_thread is not None and self._cutter_thread.isRunning()) or (self._merge_thread is not None and self._merge_thread.isRunning())
        self.cut_btn.setEnabled(has_input and not is_busy)
        self.merge_btn.setEnabled(not is_busy)

    def browse_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Video File",
            os.path.dirname(self.input_edit.text().strip()) or "",
            "Video files (*.mp4 *.mkv *.mov *.ts *.avi *.wmv *.flv);;All files (*)",
        )
        if file_path:
            self.input_edit.setText(file_path)
            if not self.output_edit.text().strip():
                default_out = os.path.join(os.path.dirname(file_path), f"{Path(file_path).stem}_chunks")
                self.output_edit.setText(default_out)

    def browse_output_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.output_edit.text().strip() or "")
        if folder:
            self.output_edit.setText(folder)

    def log_message(self, message):
        self.log_edit.append(str(message))

    def cut_video(self):
        inp = self.input_edit.text().strip()
        out = self.output_edit.text().strip()
        if not inp or not os.path.exists(inp):
            if QMessageBox:
                QMessageBox.warning(self, "Missing Video", "Please select a valid video file.")
            return
        if not out:
            out = os.path.join(os.path.dirname(inp), f"{Path(inp).stem}_chunks")
            self.output_edit.setText(out)

        self._save_cutter_preferences()
        self._set_status("Cutting...", "Splitting video into chunks.", "working")
        self.progress_bar.setValue(0)
        self.log_edit.clear()

        split_mode = 'parts' if self._current_split_mode() == 'count' else 'chunks'
        self._cutter_thread = VideoCutterThread(
            inp,
            out,
            split_mode=split_mode,
            split_value=self.split_spin.value(),
            auto_convert_mp3=self.mp3_check.isChecked(),
        )
        self._cutter_thread.log_signal.connect(self.log_message)
        self._cutter_thread.progress_signal.connect(self.progress_bar.setValue)
        self._cutter_thread.finished_signal.connect(self.on_cut_finished)
        self._cutter_thread.start()
        self._update_action_states()

    def on_cut_finished(self, success, msg):
        self._set_status("Completed" if success else "Error", msg, "success" if success else "error")
        if success:
            if QMessageBox:
                QMessageBox.information(self, "Cutting Finished", msg)
        else:
            if QMessageBox:
                QMessageBox.critical(self, "Cutting Error", msg)
        self._update_action_states()

    def merge_videos(self):
        last_dir = self.output_edit.text().strip() or os.path.dirname(self.input_edit.text().strip()) or ""
        dialog = MergeOrderDialog(last_dir=last_dir, parent=self)
        if dialog.exec_() != QDialog.Accepted:
            return

        files = dialog.get_ordered_files()
        if len(files) < 2:
            return

        out_file, _ = QFileDialog.getSaveFileName(
            self,
            "Save Merged Video As",
            os.path.join(dialog.last_dir() or last_dir, "merged_video.mp4"),
            "MP4 video (*.mp4);;MKV video (*.mkv);;All files (*)",
        )
        if not out_file:
            return

        self._set_status("Merging...", "Joining video files into one.", "working")
        self.progress_bar.setValue(0)
        self.log_edit.clear()

        self._merge_thread = VideoMergeThread(files, out_file)
        self._merge_thread.log_signal.connect(self.log_message)
        self._merge_thread.progress_signal.connect(self.progress_bar.setValue)
        self._merge_thread.finished_signal.connect(self.on_merge_finished)
        self._merge_thread.start()
        self._update_action_states()

    def on_merge_finished(self, success, msg):
        self._set_status("Completed" if success else "Error", msg, "success" if success else "error")
        if success:
            if QMessageBox:
                QMessageBox.information(self, "Merge Finished", msg)
        else:
            if QMessageBox:
                QMessageBox.critical(self, "Merge Error", msg)
        self._update_action_states()

    def play_first_output(self):
        out_dir = self.output_edit.text().strip()
        if not out_dir or not os.path.exists(out_dir):
            return
        files = sorted([os.path.join(out_dir, f) for f in os.listdir(out_dir) if f.endswith(('.mp4', '.mkv', '.mov'))])
        if files:
            first = files[0]
            if sys.platform == 'win32':
                os.startfile(first)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', first])
            else:
                subprocess.Popen(['xdg-open', first])

    def open_output_folder(self):
        out_dir = self.output_edit.text().strip()
        if not out_dir or not os.path.exists(out_dir):
            return
        if sys.platform == 'win32':
            os.startfile(out_dir)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', out_dir])
        else:
            subprocess.Popen(['xdg-open', out_dir])

    def closeEvent(self, event):
        self._save_cutter_preferences()
        if self._cutter_thread and self._cutter_thread.isRunning():
            self._cutter_thread.cancel()
            self._cutter_thread.wait(2000)
        if self._merge_thread and self._merge_thread.isRunning():
            self._merge_thread.cancel()
            self._merge_thread.wait(2000)
        event.accept()
