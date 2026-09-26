# -*- coding: utf-8 -*-
"""
Parallel Video-to-MP3 Conversion Module with Real-Time Progress Monitoring.
Provides multi-threaded extraction of MP3 audio from videos with individual
per-file progress bars, speed metrics, status badges, and concurrency controls.
"""

import os
import sys
import shutil
import subprocess
import time
from typing import List, Optional

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QUrl, QTimer
from PyQt5.QtGui import QDesktopServices, QColor, QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QSpinBox, QComboBox, QFrame, QFileDialog, QMessageBox,
    QWidget, QApplication
)

from runtime_paths import resolve_binary_path
from utils import get_ffmpeg_path


def format_seconds(seconds: float) -> str:
    """Format total seconds into HH:MM:SS or MM:SS."""
    if seconds <= 0:
        return "--:--"
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_file_size(size_bytes: int) -> str:
    """Format bytes into readable string (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def probe_media_duration(file_path: str) -> float:
    """Extract media duration in seconds using ffprobe."""
    ffprobe_bin = resolve_binary_path("ffprobe")
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=8,
            **kwargs
        )
        if res.returncode == 0 and res.stdout.strip():
            return max(0.0, float(res.stdout.strip()))
    except Exception:
        pass
    return 0.0


class VideoToMp3Item:
    """Data item representing a single video-to-MP3 conversion task."""
    def __init__(self, job_id: int, video_path: str, output_dir: Optional[str] = None):
        self.job_id = job_id
        self.video_path = video_path
        self.video_name = os.path.basename(video_path)
        stem, _ = os.path.splitext(self.video_name)

        if output_dir:
            self.output_path = os.path.join(output_dir, f"{stem}.mp3")
        else:
            self.output_path = os.path.join(os.path.dirname(video_path), f"{stem}.mp3")

        self.duration = probe_media_duration(video_path)
        self.duration_str = format_seconds(self.duration)

        # State tracking
        self.status = "queued"  # queued, converting, completed, failed, cancelled
        self.progress = 0
        self.speed = "--"
        self.output_size = 0
        self.error_msg = ""
        self.start_time = 0.0
        self.finish_time = 0.0


class VideoToMp3WorkerThread(QThread):
    """
    Dedicated background worker thread for converting a single video to MP3
    using FFmpeg with real-time stream progress monitoring.
    """
    progress_signal = pyqtSignal(int, int, str)       # job_id, percent, speed
    completed_signal = pyqtSignal(int, str, int)      # job_id, output_path, size_bytes
    failed_signal = pyqtSignal(int, str)              # job_id, error_message

    def __init__(self, item: VideoToMp3Item, bitrate: str = "192k", parent=None):
        super().__init__(parent)
        self.item = item
        self.bitrate = bitrate
        self._is_cancelled = False
        self._process: Optional[subprocess.Popen] = None

    def cancel(self):
        """Safely terminate the underlying ffmpeg subprocess."""
        self._is_cancelled = True
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass

    def run(self):
        if self._is_cancelled:
            self.failed_signal.emit(self.item.job_id, "Cancelled before start")
            return

        ffmpeg_bin = get_ffmpeg_path()
        out_dir = os.path.dirname(self.item.output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # Build ffmpeg command with progress output
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", self.item.video_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-b:a", self.bitrate,
            "-ar", "44100",
            "-progress", "pipe:1",
            "-nostats",
            self.item.output_path,
        ]

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        duration_sec = self.item.duration
        cur_speed = "--"
        last_pct = 0

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                **kwargs
            )

            # Read progress key-value pairs from stdout
            for line in self._process.stdout:
                if self._is_cancelled:
                    break
                line = line.strip()
                if not line:
                    continue

                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()

                    if k == "speed":
                        cur_speed = v.strip()
                    elif k in ("out_time_us", "out_time_ms"):
                        try:
                            # out_time_us is microseconds (1,000,000 per sec)
                            us = float(v)
                            sec = us / 1_000_000.0 if k == "out_time_us" else us / 1000.0
                            if duration_sec > 0:
                                pct = min(99, max(0, int((sec / duration_sec) * 100)))
                                if pct != last_pct:
                                    last_pct = pct
                                    self.progress_signal.emit(self.item.job_id, pct, cur_speed)
                        except Exception:
                            pass
                    elif k == "progress" and v == "end":
                        last_pct = 100
                        self.progress_signal.emit(self.item.job_id, 100, cur_speed)

            self._process.wait()

            if self._is_cancelled:
                # Cleanup partial file
                if os.path.exists(self.item.output_path):
                    try:
                        os.remove(self.item.output_path)
                    except Exception:
                        pass
                self.failed_signal.emit(self.item.job_id, "Cancelled by user")
                return

            if self._process.returncode == 0 and os.path.exists(self.item.output_path):
                file_size = os.path.getsize(self.item.output_path)
                self.progress_signal.emit(self.item.job_id, 100, cur_speed)
                self.completed_signal.emit(self.item.job_id, self.item.output_path, file_size)
            else:
                self.failed_signal.emit(
                    self.item.job_id,
                    f"FFmpeg returned code {self._process.returncode}"
                )
        except Exception as exc:
            self.failed_signal.emit(self.item.job_id, str(exc))


class VideoToMp3ParallelManager(QObject):
    """
    Coordinates multi-worker parallel conversion queue.
    Controls concurrency, tracks real-time progress, and notifies listeners.
    """
    item_started = pyqtSignal(int)                         # job_id
    item_progress = pyqtSignal(int, int, str)              # job_id, pct, speed
    item_completed = pyqtSignal(int, str, int)             # job_id, output_path, size
    item_failed = pyqtSignal(int, str)                     # job_id, error_msg
    overall_progress = pyqtSignal(int, int, int)           # completed, total, overall_pct
    all_finished = pyqtSignal(int, int, list)              # success_count, fail_count, successful_paths

    def __init__(self, items: List[VideoToMp3Item], max_workers: int = 4, bitrate: str = "192k", parent=None):
        super().__init__(parent)
        self.items: List[VideoToMp3Item] = list(items)
        self.max_workers = max(1, min(16, int(max_workers)))
        self.bitrate = bitrate
        self.active_workers: dict = {}   # job_id -> VideoToMp3WorkerThread
        self.is_paused = False
        self.is_cancelled = False
        self.completed_count = 0
        self.failed_count = 0
        self.successful_paths: List[str] = []

    def start(self):
        """Start or resume processing."""
        self.is_paused = False
        self.is_cancelled = False
        self._dispatch_next()

    def pause(self):
        """Pause scheduling new tasks."""
        self.is_paused = True

    def resume(self):
        """Resume task dispatching."""
        self.is_paused = False
        self._dispatch_next()

    def set_max_workers(self, n: int):
        """Update concurrency limit dynamically."""
        self.max_workers = max(1, min(16, int(n)))
        if not self.is_paused and not self.is_cancelled:
            self._dispatch_next()

    def set_bitrate(self, bitrate: str):
        """Update bitrate for upcoming tasks."""
        self.bitrate = bitrate

    def add_item(self, item: VideoToMp3Item):
        """Add a new item to the queue at runtime."""
        self.items.append(item)
        self._emit_overall()
        if not self.is_paused and not self.is_cancelled:
            self._dispatch_next()

    def cancel_all(self):
        """Cancel all active and queued tasks."""
        self.is_cancelled = True
        self.is_paused = True
        for w in list(self.active_workers.values()):
            w.cancel()
        for it in self.items:
            if it.status in ("queued", "converting"):
                it.status = "cancelled"

    def cancel_item(self, job_id: int):
        """Cancel a specific task."""
        if job_id in self.active_workers:
            self.active_workers[job_id].cancel()
        for it in self.items:
            if it.job_id == job_id and it.status == "queued":
                it.status = "cancelled"

    def retry_item(self, job_id: int):
        """Reset and retry a failed or cancelled task."""
        for it in self.items:
            if it.job_id == job_id:
                if it.status == "failed":
                    self.failed_count = max(0, self.failed_count - 1)
                it.status = "queued"
                it.progress = 0
                it.speed = "--"
                it.error_msg = ""
                break
        self._emit_overall()
        if not self.is_paused and not self.is_cancelled:
            self._dispatch_next()

    def _dispatch_next(self):
        """Dispatch queued items up to max_workers concurrency."""
        if self.is_paused or self.is_cancelled:
            return

        while len(self.active_workers) < self.max_workers:
            next_item = None
            for it in self.items:
                if it.status == "queued":
                    next_item = it
                    break

            if not next_item:
                break

            next_item.status = "converting"
            next_item.start_time = time.time()
            self.item_started.emit(next_item.job_id)

            worker = VideoToMp3WorkerThread(next_item, bitrate=self.bitrate, parent=self)
            worker.progress_signal.connect(self._on_worker_progress)
            worker.completed_signal.connect(self._on_worker_completed)
            worker.failed_signal.connect(self._on_worker_failed)

            self.active_workers[next_item.job_id] = worker
            worker.start()

        # Check if all completed
        self._check_all_finished()

    def _on_worker_progress(self, job_id: int, pct: int, speed: str):
        for it in self.items:
            if it.job_id == job_id:
                it.progress = pct
                it.speed = speed
                break
        self.item_progress.emit(job_id, pct, speed)
        self._emit_overall()

    def _on_worker_completed(self, job_id: int, output_path: str, size_bytes: int):
        if job_id in self.active_workers:
            del self.active_workers[job_id]

        for it in self.items:
            if it.job_id == job_id:
                it.status = "completed"
                it.progress = 100
                it.output_size = size_bytes
                it.finish_time = time.time()
                break

        self.completed_count += 1
        self.successful_paths.append(output_path)
        self.item_completed.emit(job_id, output_path, size_bytes)
        self._emit_overall()
        self._dispatch_next()

    def _on_worker_failed(self, job_id: int, err_msg: str):
        if job_id in self.active_workers:
            del self.active_workers[job_id]

        for it in self.items:
            if it.job_id == job_id:
                it.status = "failed" if not self.is_cancelled else "cancelled"
                it.error_msg = err_msg
                it.finish_time = time.time()
                break

        self.failed_count += 1
        self.item_failed.emit(job_id, err_msg)
        self._emit_overall()
        self._dispatch_next()

    def _emit_overall(self):
        total = len(self.items)
        if total == 0:
            self.overall_progress.emit(0, 0, 0)
            return

        # Sum of per-item progress / total
        sum_pct = sum(it.progress for it in self.items)
        overall_pct = int(sum_pct / total)
        self.overall_progress.emit(self.completed_count, total, overall_pct)

    def _check_all_finished(self):
        if not self.active_workers:
            has_queued = any(it.status == "queued" for it in self.items)
            if not has_queued and len(self.items) > 0:
                self.all_finished.emit(self.completed_count, self.failed_count, self.successful_paths)


class InlineProgressWidget(QWidget):
    """Custom inline progress bar widget with percentage text and speed badge."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(16)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar, 1)

        self.lbl_info = QLabel("0% (--x)")
        self.lbl_info.setStyleSheet("font-size: 11px; font-weight: bold; min-width: 68px;")
        self.lbl_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.lbl_info)

    def update_progress(self, pct: int, speed: str):
        self.bar.setValue(pct)
        spd = speed if speed and speed != "--" else ""
        spd_tag = f" ({spd})" if spd else ""
        self.lbl_info.setText(f"{pct}%{spd_tag}")


class VideoToMp3Dialog(QDialog):
    """
    Modern Real-Time Parallel Video to MP3 Conversion Monitor Dialog.
    Features per-video live progress bars, speed metrics, status pills,
    concurrency controls, and post-conversion file actions.
    """
    def __init__(self, video_files: List[str], output_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir or (os.path.dirname(video_files[0]) if video_files else os.path.expanduser("~"))

        # Default max workers: 4 or CPU count
        cpu_count = os.cpu_count() or 4
        default_workers = min(4, max(1, cpu_count))

        self.items = [
            VideoToMp3Item(job_id=i + 1, video_path=f, output_dir=self.output_dir)
            for i, f in enumerate(video_files)
        ]

        self.manager = VideoToMp3ParallelManager(
            items=self.items,
            max_workers=default_workers,
            bitrate="192k",
            parent=self
        )

        self._row_progress_widgets: dict = {}
        self._init_ui()
        self._connect_signals()

        # Auto-start after brief UI display delay
        QTimer.singleShot(250, self.manager.start)

    def _init_ui(self):
        self.setWindowTitle("🎵 Parallel Video to MP3 Converter")
        self.resize(1080, 640)
        self.setMinimumSize(880, 520)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(10)

        # ── 1. Top Header Card ───────────────────────────────────────────────
        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        h_layout = QVBoxLayout(header_card)
        h_layout.setContentsMargins(12, 10, 12, 10)
        h_layout.setSpacing(8)

        # Row 1: Title, Bitrate, Parallel Concurrency
        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.title_lbl = QLabel(f"🎵 Parallel Video to MP3 ({len(self.items)} Videos)")
        self.title_lbl.setStyleSheet("font-size: 15px; font-weight: bold;")
        top_row.addWidget(self.title_lbl)

        top_row.addStretch()

        # Bitrate selector
        lbl_bitrate = QLabel("Quality:")
        lbl_bitrate.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_row.addWidget(lbl_bitrate)

        self.combo_bitrate = QComboBox()
        self.combo_bitrate.addItems(["128k (Compact)", "192k (Standard)", "256k (High)", "320k (Ultra)"])
        self.combo_bitrate.setCurrentIndex(1)  # 192k default
        self.combo_bitrate.currentIndexChanged.connect(self._on_bitrate_changed)
        top_row.addWidget(self.combo_bitrate)

        # Concurrency SpinBox
        lbl_concur = QLabel("⚡ Parallel Threads:")
        lbl_concur.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_row.addWidget(lbl_concur)

        self.spin_concurrency = QSpinBox()
        self.spin_concurrency.setRange(1, 16)
        self.spin_concurrency.setValue(self.manager.max_workers)
        self.spin_concurrency.setStyleSheet("font-weight: bold; font-size: 12px; min-width: 50px;")
        self.spin_concurrency.valueChanged.connect(self.manager.set_max_workers)
        top_row.addWidget(self.spin_concurrency)

        h_layout.addLayout(top_row)

        # Row 2: Output Directory + Change/Open buttons
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)

        self.lbl_dir = QLabel(f"📂 Output Folder: <b>{self.output_dir}</b>")
        self.lbl_dir.setStyleSheet("font-size: 11.5px;")
        dir_row.addWidget(self.lbl_dir, 1)

        self.btn_change_dir = QPushButton("Change Folder")
        self.btn_change_dir.setObjectName("secondaryBtn")
        self.btn_change_dir.clicked.connect(self._on_change_folder)
        dir_row.addWidget(self.btn_change_dir)

        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.setObjectName("secondaryBtn")
        self.btn_open_folder.clicked.connect(self._on_open_folder)
        dir_row.addWidget(self.btn_open_folder)

        h_layout.addLayout(dir_row)

        # Row 3: Overall Progress Bar
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFixedHeight(20)
        self.overall_bar.setAlignment(Qt.AlignCenter)
        h_layout.addWidget(self.overall_bar)

        # Row 4: Metric summary pills
        pills_row = QHBoxLayout()
        pills_row.setSpacing(6)
        self.pill_total = self._create_pill(f"Total: {len(self.items)}", "#34495E")
        self.pill_queued = self._create_pill(f"Queued: {len(self.items)}", "#7F8C8D")
        self.pill_converting = self._create_pill("⚡ Converting: 0", "#2980B9")
        self.pill_done = self._create_pill("✅ Done: 0", "#27AE60")
        self.pill_failed = self._create_pill("❌ Failed: 0", "#C0392B")

        pills_row.addWidget(self.pill_total)
        pills_row.addWidget(self.pill_queued)
        pills_row.addWidget(self.pill_converting)
        pills_row.addWidget(self.pill_done)
        pills_row.addWidget(self.pill_failed)
        pills_row.addStretch()

        h_layout.addLayout(pills_row)
        main_layout.addWidget(header_card)

        # ── 2. Table of Video Items ──────────────────────────────────────────
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "#", "Video File", "Duration", "Status", "Inline Progress", "Output Details", "Action"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        # Column widths
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 40)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 85)
        h.setSectionResizeMode(3, QHeaderView.Fixed)
        self.table.setColumnWidth(3, 115)
        h.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 230)
        h.setSectionResizeMode(5, QHeaderView.Interactive)
        self.table.setColumnWidth(5, 160)
        h.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 120)

        main_layout.addWidget(self.table, 1)

        # ── 3. Bottom Control Action Bar ─────────────────────────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.btn_add_files = QPushButton("➕ Add Videos")
        self.btn_add_files.setObjectName("primaryBtn")
        self.btn_add_files.clicked.connect(self._on_add_videos)
        action_row.addWidget(self.btn_add_files)

        self.btn_pause_resume = QPushButton("⏸ Pause")
        self.btn_pause_resume.setObjectName("secondaryBtn")
        self.btn_pause_resume.clicked.connect(self._on_pause_resume_clicked)
        action_row.addWidget(self.btn_pause_resume)

        self.btn_cancel_all = QPushButton("⏹ Cancel All")
        self.btn_cancel_all.setObjectName("dangerBtn")
        self.btn_cancel_all.clicked.connect(self._on_cancel_all_clicked)
        action_row.addWidget(self.btn_cancel_all)

        action_row.addStretch()

        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("secondaryBtn")
        self.btn_close.clicked.connect(self.close)
        action_row.addWidget(self.btn_close)

        main_layout.addLayout(action_row)

        # Populate rows
        self._populate_all_rows()

    def _create_pill(self, text: str, color_hex: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {color_hex};
                color: #FFFFFF;
                font-size: 11px;
                font-weight: bold;
                border-radius: 3px;
                padding: 3px 8px;
            }}
        """)
        return lbl

    def _populate_all_rows(self):
        self.table.setRowCount(len(self.items))
        for row, it in enumerate(self.items):
            self._setup_row(row, it)

    def _setup_row(self, row: int, it: VideoToMp3Item):
        # 0: #
        idx_item = QTableWidgetItem(str(it.job_id))
        idx_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 0, idx_item)

        # 1: Video File
        file_item = QTableWidgetItem(it.video_name)
        file_item.setToolTip(it.video_path)
        self.table.setItem(row, 1, file_item)

        # 2: Duration
        dur_item = QTableWidgetItem(it.duration_str)
        dur_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 2, dur_item)

        # 3: Status
        status_lbl = self._create_status_badge(it.status)
        self.table.setCellWidget(row, 3, status_lbl)

        # 4: Inline Progress
        prog_w = InlineProgressWidget()
        prog_w.update_progress(it.progress, it.speed)
        self.table.setCellWidget(row, 4, prog_w)
        self._row_progress_widgets[it.job_id] = prog_w

        # 5: Output Details
        detail_item = QTableWidgetItem(os.path.basename(it.output_path))
        self.table.setItem(row, 5, detail_item)

        # 6: Actions
        act_w = self._create_row_actions(it)
        self.table.setCellWidget(row, 6, act_w)

    def _create_status_badge(self, status: str) -> QLabel:
        styles = {
            "queued": ("Queued", "#7F8C8D"),
            "converting": ("⚡ Converting", "#2980B9"),
            "completed": ("✅ Done", "#27AE60"),
            "failed": ("❌ Failed", "#C0392B"),
            "cancelled": ("⏹ Cancelled", "#E67E22"),
        }
        text, color = styles.get(status, (status.capitalize(), "#7F8C8D"))
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: #FFFFFF;
                font-size: 11px;
                font-weight: bold;
                border-radius: 4px;
                padding: 2px 6px;
            }}
        """)
        return lbl

    def _create_row_actions(self, it: VideoToMp3Item) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(4)

        if it.status == "completed":
            btn_play = QPushButton("▶️ Play")
            btn_play.setObjectName("primaryBtn")
            btn_play.setStyleSheet("font-size: 10px; padding: 2px 8px; border-radius: 4px;")
            btn_play.clicked.connect(lambda _, p=it.output_path: QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
            layout.addWidget(btn_play)

            btn_folder = QPushButton("📁")
            btn_folder.setToolTip("Open folder")
            btn_folder.setObjectName("secondaryBtn")
            btn_folder.setStyleSheet("font-size: 10px; padding: 2px 6px; border-radius: 4px;")
            btn_folder.clicked.connect(lambda _, p=it.output_path: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(p))))
            layout.addWidget(btn_folder)

        elif it.status in ("failed", "cancelled"):
            btn_retry = QPushButton("🔄 Retry")
            btn_retry.setObjectName("primaryBtn")
            btn_retry.setStyleSheet("font-size: 10px; padding: 2px 8px; border-radius: 4px;")
            btn_retry.clicked.connect(lambda _, j=it.job_id: self.manager.retry_item(j))
            layout.addWidget(btn_retry)
        else:
            btn_cancel = QPushButton("✖")
            btn_cancel.setToolTip("Cancel this file")
            btn_cancel.setObjectName("dangerBtn")
            btn_cancel.setStyleSheet("font-size: 10px; padding: 2px 6px; border-radius: 4px;")
            btn_cancel.clicked.connect(lambda _, j=it.job_id: self.manager.cancel_item(j))
            layout.addWidget(btn_cancel)

        return container

    def _connect_signals(self):
        self.manager.item_started.connect(self._on_item_started)
        self.manager.item_progress.connect(self._on_item_progress)
        self.manager.item_completed.connect(self._on_item_completed)
        self.manager.item_failed.connect(self._on_item_failed)
        self.manager.overall_progress.connect(self._on_overall_progress)
        self.manager.all_finished.connect(self._on_all_finished)

    def _on_item_started(self, job_id: int):
        row = self._find_row_by_id(job_id)
        if row >= 0:
            self.table.setCellWidget(row, 3, self._create_status_badge("converting"))
        self._update_pills()

    def _on_item_progress(self, job_id: int, pct: int, speed: str):
        if job_id in self._row_progress_widgets:
            self._row_progress_widgets[job_id].update_progress(pct, speed)

    def _on_item_completed(self, job_id: int, output_path: str, size_bytes: int):
        row = self._find_row_by_id(job_id)
        if row >= 0:
            self.table.setCellWidget(row, 3, self._create_status_badge("completed"))
            # Update details with size
            sz_str = format_file_size(size_bytes)
            name = os.path.basename(output_path)
            item = QTableWidgetItem(f"{name} ({sz_str})")
            item.setToolTip(f"Saved: {output_path}\nSize: {sz_str}")
            self.table.setItem(row, 5, item)

            it = next((x for x in self.items if x.job_id == job_id), None)
            if it:
                self.table.setCellWidget(row, 6, self._create_row_actions(it))

        self._update_pills()

    def _on_item_failed(self, job_id: int, error_msg: str):
        row = self._find_row_by_id(job_id)
        if row >= 0:
            status = "cancelled" if self.manager.is_cancelled else "failed"
            self.table.setCellWidget(row, 3, self._create_status_badge(status))
            err_item = QTableWidgetItem(f"Error: {error_msg[:40]}")
            err_item.setToolTip(error_msg)
            self.table.setItem(row, 5, err_item)

            it = next((x for x in self.items if x.job_id == job_id), None)
            if it:
                self.table.setCellWidget(row, 6, self._create_row_actions(it))

        self._update_pills()

    def _on_overall_progress(self, completed: int, total: int, overall_pct: int):
        self.overall_bar.setValue(overall_pct)
        self.overall_bar.setFormat(f"{completed} / {total} files ({overall_pct}%)")
        self._update_pills()

    def _on_all_finished(self, succ_cnt: int, fail_cnt: int, paths: list):
        self.btn_pause_resume.setEnabled(False)
        self.btn_cancel_all.setEnabled(False)
        self.overall_bar.setValue(100)
        self.overall_bar.setFormat(f"Completed: {succ_cnt} succeeded, {fail_cnt} failed (100%)")

        msg = f"Parallel MP3 Conversion Finished!\n\n✅ Succeeded: {succ_cnt} files"
        if fail_cnt > 0:
            msg += f"\n❌ Failed: {fail_cnt} files"
        msg += f"\n\nOutput Directory:\n{self.output_dir}"

        QMessageBox.information(self, "Conversion Complete", msg)

    def _update_pills(self):
        total = len(self.items)
        queued = sum(1 for it in self.items if it.status == "queued")
        converting = sum(1 for it in self.items if it.status == "converting")
        done = sum(1 for it in self.items if it.status == "completed")
        failed = sum(1 for it in self.items if it.status in ("failed", "cancelled"))

        self.pill_total.setText(f"Total: {total}")
        self.pill_queued.setText(f"Queued: {queued}")
        self.pill_converting.setText(f"⚡ Converting: {converting}")
        self.pill_done.setText(f"✅ Done: {done}")
        self.pill_failed.setText(f"❌ Failed: {failed}")

    def _find_row_by_id(self, job_id: int) -> int:
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.text() == str(job_id):
                return r
        return -1

    def _on_bitrate_changed(self, idx: int):
        bitrates = ["128k", "192k", "256k", "320k"]
        if 0 <= idx < len(bitrates):
            self.manager.set_bitrate(bitrates[idx])

    def _on_change_folder(self):
        new_dir = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.output_dir)
        if new_dir:
            self.output_dir = new_dir
            self.lbl_dir.setText(f"📂 Output Folder: <b>{new_dir}</b>")
            for it in self.items:
                if it.status == "queued":
                    stem, _ = os.path.splitext(it.video_name)
                    it.output_path = os.path.join(new_dir, f"{stem}.mp3")

    def _on_open_folder(self):
        if os.path.exists(self.output_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))

    def _on_add_videos(self):
        filters = "Video Files (*.mp4 *.mkv *.avi *.mov *.flv *.webm *.wmv *.m4v *.ts);;All Files (*.*)"
        files, _ = QFileDialog.getOpenFileNames(self, "Select Additional Video(s) to Convert", "", filters)
        if not files:
            return

        for f in files:
            new_id = len(self.items) + 1
            item = VideoToMp3Item(job_id=new_id, video_path=f, output_dir=self.output_dir)
            self.items.append(item)
            new_row = self.table.rowCount()
            self.table.setRowCount(new_row + 1)
            self._setup_row(new_row, item)
            self.manager.add_item(item)

        self.title_lbl.setText(f"🎵 Parallel Video to MP3 ({len(self.items)} Videos)")
        self._update_pills()

    def _on_pause_resume_clicked(self):
        if self.manager.is_paused:
            self.manager.resume()
            self.btn_pause_resume.setText("⏸ Pause")
            self.btn_pause_resume.setObjectName("secondaryBtn")
            self.btn_pause_resume.setStyleSheet("")
            self.btn_pause_resume.style().unpolish(self.btn_pause_resume)
            self.btn_pause_resume.style().polish(self.btn_pause_resume)
        else:
            self.manager.pause()
            self.btn_pause_resume.setText("▶ Resume")
            self.btn_pause_resume.setObjectName("primaryBtn")
            self.btn_pause_resume.setStyleSheet("")
            self.btn_pause_resume.style().unpolish(self.btn_pause_resume)
            self.btn_pause_resume.style().polish(self.btn_pause_resume)

    def _on_cancel_all_clicked(self):
        reply = QMessageBox.question(
            self,
            "Cancel All Conversions",
            "Are you sure you want to cancel all conversions?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.manager.cancel_all()
            self.btn_pause_resume.setEnabled(False)
            self.btn_cancel_all.setEnabled(False)

    def closeEvent(self, event):
        """Prompt if conversions are actively running upon close."""
        has_running = any(it.status == "converting" for it in self.items)
        if has_running:
            reply = QMessageBox.question(
                self,
                "Close Dialog",
                "Conversions are currently running. Do you want to cancel active tasks and close?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.manager.cancel_all()
        event.accept()


def convert_video_to_mp3_enhanced(self):
    """
    Enhanced replacement for DubbingApp.convert_video_to_mp3.
    Launches the modern multi-worker Parallel Video to MP3 dialog with
    per-video live progress indicators.
    """
    video_filter = getattr(
        self,
        "VIDEO_FILE_DIALOG_FILTER",
        "Video Files (*.mp4 *.mkv *.avi *.mov *.flv *.webm *.wmv *.m4v *.ts);;All Files (*.*)"
    )

    video_files, _ = QFileDialog.getOpenFileNames(
        self,
        "Select Video(s) to Convert to MP3 (Multiple Selection Supported)",
        "",
        video_filter
    )

    if not video_files:
        return

    output_dir = None
    if len(video_files) > 1:
        default_dir = os.path.dirname(video_files[0])
        output_dir = QFileDialog.getExistingDirectory(
            self,
            f"Select Output Directory for {len(video_files)} MP3 files",
            default_dir
        )
        if not output_dir:
            return
    else:
        output_dir = os.path.dirname(video_files[0])

    # Instantiate and open the parallel dialog
    dlg = VideoToMp3Dialog(video_files=video_files, output_dir=output_dir, parent=self)
    self._video_to_mp3_dialog = dlg  # retain reference to avoid premature garbage collection

    # Synchronize main window's bottom status bar as well
    if hasattr(self, "progress_bar") and hasattr(self.progress_bar, "set_status"):
        self.progress_bar.set_status(f"🎵 Converting {len(video_files)} video(s) to MP3 in parallel...")
        dlg.manager.all_finished.connect(
            lambda succ, fail, _: self.progress_bar.set_status(
                f"✅ Parallel MP3 conversion finished: {succ} done, {fail} failed."
            )
        )

    dlg.exec_()


class VideoToMp3WorkerAdapter(QThread):
    """
    Backward-compatible adapter matching the legacy VideoToMp3Worker signature,
    powered internally by the parallel manager.
    """
    progress = pyqtSignal(str)
    progress_value = pyqtSignal(int)
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, video_paths, output_dir=None, parent=None):
        super().__init__(parent)
        if isinstance(video_paths, str):
            self.video_paths = [video_paths]
        else:
            self.video_paths = list(video_paths)
        self.output_dir = output_dir

    def run(self):
        items = [
            VideoToMp3Item(job_id=i + 1, video_path=p, output_dir=self.output_dir)
            for i, p in enumerate(self.video_paths)
        ]
        manager = VideoToMp3ParallelManager(items=items, max_workers=4)

        def _on_prog(completed, total, pct):
            self.progress_value.emit(pct)
            self.progress.emit(f"🎵 Converting in parallel ({completed}/{total}) - {pct}%")

        manager.overall_progress.connect(_on_prog)
        manager.start()

        # Block thread until all tasks complete
        while len(manager.active_workers) > 0 or any(it.status == "queued" for it in manager.items):
            time.sleep(0.1)

        self.progress_value.emit(100)
        self.finished.emit(manager.successful_paths)
        if manager.failed_count > 0:
            self.error.emit(f"{manager.failed_count} file(s) failed during conversion.")
