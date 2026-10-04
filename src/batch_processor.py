# -*- coding: utf-8 -*-
"""
Batch Parallel Processor & Real-Time Monitoring Module for AI Dubber Ultimate.
Provides multi-worker parallel execution with isolated process workspaces,
live per-episode inline progress bars, status badges, dynamic concurrency controls,
and post-batch video concatenation.
"""

import os
import re
import sys
import json
import time
import shutil
import tempfile
import subprocess
from datetime import datetime

from PyQt5.QtCore import Qt, QObject, pyqtSignal, QProcess, QUrl, QTimer
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QProgressBar,
    QHeaderView, QMessageBox, QSpinBox, QCheckBox, QFrame,
    QWidget, QPlainTextEdit, QApplication
)


class BatchJobItem:
    """Represents a single video dubbing job in the batch."""

    def __init__(self, job_id, raw_job, output_dir, default_remove_vocal=False, default_use_demucs=False,
                 default_bg_percent=30, default_ai_percent=100, default_fit_audio=True, default_auto_sync=True):
        self.job_id = job_id
        self.raw_job = raw_job
        self.video_path = raw_job.get("video_path", "")
        self.srt_path = raw_job.get("srt_path", None)
        self.voice_id = raw_job.get(
            "voice_id", "km-KH-SreymomNeural") or "km-KH-SreymomNeural"
        self.pitch = raw_job.get("pitch", "0") or "0"
        self.rate = raw_job.get("rate", "0%") or "0%"
        self.eco_enabled = bool(raw_job.get("eco_enabled", False))
        self.echo_intensity = int(raw_job.get("echo_intensity", 50))
        self.timeline_segments = raw_job.get("timeline_segments", None)

        # Audio mixing & vocal removal settings
        self.remove_vocal = bool(raw_job.get(
            "remove_vocal", default_remove_vocal))
        self.use_demucs = bool(raw_job.get(
            "use_demucs", default_use_demucs if default_use_demucs is not None else self.remove_vocal))
        self.background_percent = int(raw_job.get(
            "background_percent", default_bg_percent))
        self.ai_voice_percent = int(raw_job.get(
            "ai_voice_percent", default_ai_percent))
        self.auto_video_sync = bool(raw_job.get(
            "auto_video_sync", default_auto_sync))
        self.preserve_speed = bool(raw_job.get("preserve_speed", False))
        self.fit_audio = bool(raw_job.get(
            "fit_audio", not self.auto_video_sync if self.auto_video_sync is not None else default_fit_audio))
        self.log_file = str(raw_job.get("log_file", ""))

        try:
            from settings_manager import get_export_video_config
            v_cfg = get_export_video_config()
        except Exception:
            v_cfg = {}
        self.video_quality = str(raw_job.get("video_quality", v_cfg.get("video_quality", "auto")))
        self.video_crf = int(raw_job.get("video_crf", v_cfg.get("video_crf", 25)))
        self.compress_enabled = bool(raw_job.get("compress_enabled", v_cfg.get("compress_enabled", True)))
        self.facebook_faststart = bool(raw_job.get("facebook_faststart", v_cfg.get("facebook_faststart", True)))
        self.allow_upscale = bool(raw_job.get("allow_upscale", v_cfg.get("allow_upscale", False)))
        self.audio_bitrate = str(raw_job.get("audio_bitrate", v_cfg.get("audio_bitrate", "96k")))

        base_name = os.path.basename(self.video_path)
        stem, ext = os.path.splitext(base_name)
        self.output_path = os.path.join(output_dir, f"dubbed_{stem}.mp4")

        # State tracking
        self.status = "queued"  # queued, running, completed, failed, cancelled
        self.progress = 0
        self.status_text = "Queued"
        self.error_msg = ""
        self.start_time = None
        self.finish_time = None


class BatchParallelManager(QObject):
    """
    Manages parallel execution of video dubbing jobs via isolated subprocesses.
    Dispatches up to `max_workers` concurrent jobs, isolating working directories
    to avoid file collisions.
    """
    job_started = pyqtSignal(int, str)  # job_id, status_text
    # job_id, pct, status_text, status_type
    job_progress = pyqtSignal(int, int, str, str)
    job_completed = pyqtSignal(int, str)  # job_id, output_path
    job_failed = pyqtSignal(int, str)  # job_id, error_message
    overall_progress = pyqtSignal(int, int, int)  # completed, total, pct
    # success_count, fail_count, merged_path
    batch_finished = pyqtSignal(int, int, str)

    def __init__(self, jobs, output_dir, max_workers=2, merge_outputs=False,
                 remove_vocal=False, use_demucs=False, background_percent=30, ai_voice_percent=100,
                 default_fit_audio=True, default_auto_sync=True, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self.max_workers = max(1, min(6, int(max_workers)))
        self.merge_outputs = merge_outputs
        self.remove_vocal = bool(remove_vocal)
        self.use_demucs = bool(use_demucs or self.remove_vocal)
        self.background_percent = int(background_percent)
        self.ai_voice_percent = int(ai_voice_percent)
        self.default_auto_sync = bool(default_auto_sync)
        self.default_fit_audio = bool(default_fit_audio)

        self.jobs = [BatchJobItem(i + 1, j, output_dir,
                                  default_remove_vocal=self.remove_vocal,
                                  default_use_demucs=self.use_demucs,
                                  default_bg_percent=self.background_percent,
                                  default_ai_percent=self.ai_voice_percent,
                                  default_fit_audio=self.default_fit_audio,
                                  default_auto_sync=self.default_auto_sync)
                     for i, j in enumerate(jobs)]
        self.active_processes = {}  # job_id -> (QProcess, job_cwd, spec_file)
        self._proc_buffers = {}  # job_id -> str buffer
        self.is_paused = False
        self.is_cancelled = False
        self.completed_count = 0
        self.success_outputs = []

        # Find python executable and batch_runner path
        self.python_exe = sys.executable
        self.runner_script = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), "batch_runner.py")

    def start(self):
        """Starts batch processing."""
        self.is_paused = False
        self.is_cancelled = False
        self._dispatch_next()

    def set_max_workers(self, n):
        """Dynamically adjusts max concurrent workers."""
        self.max_workers = max(1, min(6, int(n)))
        if not self.is_paused and not self.is_cancelled:
            self._dispatch_next()

    def pause(self):
        """Pauses dispatching of new jobs."""
        self.is_paused = True

    def resume(self):
        """Resumes dispatching jobs."""
        self.is_paused = False
        self._dispatch_next()

    def cancel_all(self):
        """Cancels all active processes and marks queued jobs as cancelled."""
        self.is_cancelled = True
        for jid in list(self.active_processes.keys()):
            proc, job_cwd, spec_file = self.active_processes[jid]
            try:
                proc.terminate()
                proc.waitForFinished(1000)
                if proc.state() != QProcess.ProcessState.NotRunning:
                    proc.kill()
            except Exception:
                pass
            self._cleanup_job_cwd(job_cwd)
            self.job_progress.emit(jid, 0, "⏹️ Stopped", "stopped")

        self.active_processes.clear()

        for job in self.jobs:
            if job.status == "queued":
                job.status = "cancelled"
                job.status_text = "⏹️ Cancelled"
                self.job_progress.emit(
                    job.job_id, 0, "⏹️ Cancelled", "stopped")

        self.batch_finished.emit(len(self.success_outputs), len(
            self.jobs) - len(self.success_outputs), "")

    def _dispatch_next(self):
        """Dispatches queued jobs up to max_workers."""
        if self.is_paused or self.is_cancelled:
            return

        while len(self.active_processes) < self.max_workers:
            next_job = None
            for j in self.jobs:
                if j.status == "queued":
                    next_job = j
                    break

            if not next_job:
                break

            self._launch_job(next_job)

        # Check if all jobs are finished
        if len(self.active_processes) == 0:
            all_done = all(j.status in ("completed", "failed",
                           "cancelled") for j in self.jobs)
            if all_done and not self.is_cancelled:
                self._handle_all_completed()

    def _launch_job(self, job):
        """Launches a single job in an isolated temp directory."""
        job.status = "running"
        job.start_time = datetime.now()
        job.status_text = "⚡ Starting..."
        self.job_started.emit(job.job_id, job.status_text)
        self.job_progress.emit(job.job_id, 5, "⚡ Starting...", "running")

        # Create isolated working directory
        job_cwd = tempfile.mkdtemp(prefix=f"dub_job_{job.job_id}_")
        spec_file = os.path.join(job_cwd, "job_spec.json")

        # Setup persistent job log file
        logs_dir = os.path.join(self.output_dir, "logs")
        try:
            os.makedirs(logs_dir, exist_ok=True)
        except Exception:
            pass
        if not getattr(job, "log_file", None):
            stem = os.path.splitext(os.path.basename(job.video_path))[0]
            safe_stem = re.sub(r'[^a-zA-Z0-9_\-]', '_', stem)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            job.log_file = os.path.abspath(os.path.join(
                logs_dir, f"batch_job_{job.job_id}_{safe_stem}_{ts}.log"))

        spec_data = {
            "job_id": job.job_id,
            "video_path": job.video_path,
            "srt_path": job.srt_path,
            "timeline_segments": job.timeline_segments,
            "voice_id": job.voice_id,
            "pitch": job.pitch,
            "rate": job.rate,
            "eco_enabled": job.eco_enabled,
            "echo_intensity": job.echo_intensity,
            "output_path": job.output_path,
            "remove_vocal": job.remove_vocal,
            "use_demucs": job.use_demucs,
            "background_percent": job.background_percent,
            "ai_voice_percent": job.ai_voice_percent,
            "auto_video_sync": getattr(job, "auto_video_sync", True),
            "preserve_speed": job.preserve_speed,
            "fit_audio": job.fit_audio,
            "log_file": job.log_file,
            "video_quality": getattr(job, "video_quality", "auto"),
            "video_crf": getattr(job, "video_crf", 25),
            "compress_enabled": getattr(job, "compress_enabled", True),
            "facebook_faststart": getattr(job, "facebook_faststart", True),
            "allow_upscale": getattr(job, "allow_upscale", False),
            "audio_bitrate": getattr(job, "audio_bitrate", "96k"),
        }

        with open(spec_file, "w", encoding="utf-8") as f:
            json.dump(spec_data, f, indent=2)

        # Setup QProcess
        proc = QProcess(self)
        proc.setWorkingDirectory(job_cwd)
        proc.setProgram(self.python_exe)
        proc.setArguments([self.runner_script, "--job-file", spec_file])

        self.active_processes[job.job_id] = (proc, job_cwd, spec_file)
        self._proc_buffers[job.job_id] = ""

        # Connect signals with explicit lambda capture
        jid = job.job_id
        proc.readyReadStandardOutput.connect(
            lambda j=jid: self._on_proc_stdout(j))
        proc.readyReadStandardError.connect(
            lambda j=jid: self._on_proc_stderr(j))
        proc.finished.connect(lambda code, status,
                              j=jid: self._on_proc_finished(j, code, status))

        proc.start()

    def _on_proc_stdout(self, job_id):
        if job_id not in self.active_processes:
            return
        proc, _, _ = self.active_processes[job_id]
        raw_data = proc.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._proc_buffers[job_id] = (
            self._proc_buffers.get(job_id, "") + raw_data)

        lines = self._proc_buffers[job_id].split("\n")
        # keep incomplete line in buffer
        self._proc_buffers[job_id] = lines[-1]

        for line in lines[:-1]:
            line = line.strip()
            if not line:
                continue

            if line.startswith("PROGRESS:"):
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    try:
                        pct = int(parts[1])
                        msg = parts[2]
                        self._update_job_progress(job_id, pct, msg)
                    except ValueError:
                        pass
            elif line.startswith("STATUS:"):
                status_msg = line[len("STATUS:"):].strip()
                self._update_job_status(job_id, status_msg)
            elif line.startswith("DONE:"):
                out_path = line[len("DONE:"):].strip()
                self._update_job_done(job_id, out_path)
            elif line.startswith("ERROR:"):
                err_msg = line[len("ERROR:"):].strip()
                self._update_job_error(job_id, err_msg)

    def _on_proc_stderr(self, job_id):
        if job_id not in self.active_processes:
            return
        proc, _, _ = self.active_processes[job_id]
        err_data = proc.readAllStandardError().data().decode("utf-8", errors="replace")
        if err_data.strip():
            print(
                f"[Worker Job {job_id} STDERR] {err_data.strip()}", file=sys.stderr)

    def _update_job_progress(self, job_id, pct, msg):
        for j in self.jobs:
            if j.job_id == job_id:
                j.progress = pct
                j.status_text = msg
                status_type = "running"
                if "Initializing" in msg:
                    status_type = "initializing"
                elif "Transcribing" in msg:
                    status_type = "transcribing"
                elif "Dubbing" in msg or "Creating" in msg or "Synthesizing" in msg:
                    status_type = "voice_gen"
                elif "Removing vocals" in msg or "Demucs" in msg or "Mixing background" in msg:
                    status_type = "vocal_removal"
                elif "Merging" in msg or "Finalizing" in msg or "Exporting" in msg:
                    status_type = "muxing"
                self.job_progress.emit(job_id, pct, msg, status_type)
                break

    def _update_job_status(self, job_id, msg):
        for j in self.jobs:
            if j.job_id == job_id:
                j.status_text = msg
                status_type = "running"
                if "Removing vocals" in msg or "Demucs" in msg or "Mixing background" in msg:
                    status_type = "vocal_removal"
                self.job_progress.emit(job_id, j.progress, msg, status_type)
                break

    def _update_job_done(self, job_id, out_path):
        for j in self.jobs:
            if j.job_id == job_id:
                j.status = "completed"
                j.progress = 100
                j.status_text = "Completed"
                j.finish_time = datetime.now()
                if out_path not in self.success_outputs:
                    self.success_outputs.append(out_path)
                self.job_completed.emit(job_id, out_path)
                self.job_progress.emit(job_id, 100, "Completed", "done")
                break

    def _update_job_error(self, job_id, err_msg):
        for j in self.jobs:
            if j.job_id == job_id:
                j.status = "failed"
                j.error_msg = err_msg
                j.status_text = f"Error: {err_msg[:40]}"
                j.finish_time = datetime.now()
                self.job_failed.emit(job_id, err_msg)
                self.job_progress.emit(job_id, 0, j.status_text, "error")
                break

    def _on_proc_finished(self, job_id, exit_code, exit_status):
        if job_id not in self.active_processes:
            return
        proc, job_cwd, spec_file = self.active_processes.pop(job_id)
        self._cleanup_job_cwd(job_cwd)

        # Check job status
        for j in self.jobs:
            if j.job_id == job_id:
                if j.status == "running":
                    if exit_code == 0 and os.path.exists(j.output_path) and os.path.getsize(j.output_path) > 0:
                        self._update_job_done(job_id, j.output_path)
                    else:
                        err = j.error_msg or f"Process failed with exit code {exit_code}"
                        self._update_job_error(job_id, err)
                break

        # Emit overall progress
        completed_count = sum(1 for j in self.jobs if j.status in (
            "completed", "failed", "cancelled"))
        total = len(self.jobs)
        overall_pct = int((completed_count / total)
                          * 100) if total > 0 else 100
        self.overall_progress.emit(completed_count, total, overall_pct)

        # Dispatch next available job
        self._dispatch_next()

    def _cleanup_job_cwd(self, job_cwd):
        try:
            if os.path.isdir(job_cwd):
                shutil.rmtree(job_cwd, ignore_errors=True)
        except Exception:
            pass

    def _handle_all_completed(self):
        """Called when all jobs have finished processing."""
        success_count = len(self.success_outputs)
        fail_count = len(self.jobs) - success_count
        merged_path = ""

        if self.merge_outputs and success_count >= 2:
            try:
                merged_path = self._merge_videos(self.success_outputs)
            except Exception as e:
                print(
                    f"[WARN] Failed to merge batch outputs: {e}", file=sys.stderr)

        self.batch_finished.emit(success_count, fail_count, merged_path)

    def _merge_videos(self, video_paths):
        """Concatenates finished videos into a single MP4 using FFmpeg."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        merged_path = os.path.join(
            self.output_dir, f"batch_merged_{timestamp}.mp4")
        concat_txt = os.path.join(
            self.output_dir, f"_concat_list_{timestamp}.txt")

        try:
            with open(concat_txt, "w", encoding="utf-8") as f:
                for vp in video_paths:
                    if os.path.exists(vp):
                        f.write(f"file '{vp}'\n")

            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_txt, "-c", "copy", merged_path
            ]
            subprocess.run(
                cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return merged_path if os.path.exists(merged_path) else ""
        finally:
            if os.path.exists(concat_txt):
                try:
                    os.remove(concat_txt)
                except Exception:
                    pass


class BatchProcessingProgressDialog(QDialog):
    """
    Real-Time Batch Processing Monitor with per-episode inline progress bars,
    status badges, dynamic concurrency control, and video actions.
    """

    def __init__(self, jobs, output_dir, merge_outputs=False, max_workers=2,
                 remove_vocal=False, use_demucs=False, background_percent=30, ai_voice_percent=100,
                 fit_audio=True, auto_video_sync=True, parent=None):
        super().__init__(parent)
        self.jobs_data = jobs
        self.output_dir = output_dir
        self.merge_outputs = merge_outputs
        self.max_workers = max_workers
        self.remove_vocal = bool(remove_vocal)
        self.use_demucs = bool(use_demucs or self.remove_vocal)
        self.background_percent = int(background_percent)
        self.ai_voice_percent = int(ai_voice_percent)
        self.auto_video_sync = bool(auto_video_sync)
        self.fit_audio = bool(fit_audio)

        self.setWindowTitle("🎬 Batch Video Dubbing Monitor")
        self.resize(1120, 700)
        self.setMinimumSize(940, 580)

        # Create manager
        self.manager = BatchParallelManager(
            jobs=jobs,
            output_dir=output_dir,
            max_workers=max_workers,
            merge_outputs=merge_outputs,
            remove_vocal=self.remove_vocal,
            use_demucs=self.use_demucs,
            background_percent=self.background_percent,
            ai_voice_percent=self.ai_voice_percent,
            default_fit_audio=self.fit_audio,
            default_auto_sync=self.auto_video_sync,
            parent=self
        )

        # Setup UI
        self._init_ui()
        self._connect_signals()

        # Start processing
        self.manager.start()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(12)

        # 1. Header Card
        header_frame = QFrame()
        header_frame.setObjectName("BatchHeaderFrame")
        h_layout = QVBoxLayout(header_frame)
        h_layout.setContentsMargins(12, 10, 12, 10)
        h_layout.setSpacing(8)

        # Title & Directory row
        top_row = QHBoxLayout()
        title_lbl = QLabel(
            f"🎬 Batch Video Processing ({len(self.jobs_data)} Episodes)")
        title_lbl.setStyleSheet("font-size: 15px; font-weight: bold;")
        top_row.addWidget(title_lbl)

        top_row.addStretch()

        # Concurrency Spinbox
        concur_lbl = QLabel("⚡ Parallel Threads:")
        concur_lbl.setStyleSheet("font-weight: bold; font-size: 12px;")
        top_row.addWidget(concur_lbl)

        self.spin_concurrency = QSpinBox()
        self.spin_concurrency.setRange(1, 6)
        self.spin_concurrency.setValue(self.max_workers)
        self.spin_concurrency.setToolTip(
            "Number of videos processed simultaneously (1 to 6 concurrent workers)")
        self.spin_concurrency.setStyleSheet("min-width: 50px; font-weight: bold; font-size: 12px;")
        self.spin_concurrency.valueChanged.connect(
            self._on_concurrency_changed)
        top_row.addWidget(self.spin_concurrency)

        h_layout.addLayout(top_row)

        # Directory label
        dir_lbl = QLabel(f"Output Folder: {self.output_dir}")
        dir_lbl.setStyleSheet("font-size: 11.5px; opacity: 0.85;")
        h_layout.addWidget(dir_lbl)

        # Overall progress bar
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFixedHeight(22)
        self.overall_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h_layout.addWidget(self.overall_bar)

        # Summary pills row
        summary_row = QHBoxLayout()
        self.lbl_summary_total = self._create_badge(
            f"Total: {len(self.jobs_data)}", "#34495E")
        self.lbl_summary_queued = self._create_badge(
            f"Queued: {len(self.jobs_data)}", "#7F8C8D")
        self.lbl_summary_running = self._create_badge("Running: 0", "#2980B9")
        self.lbl_summary_completed = self._create_badge(
            "Completed: 0", "#27AE60")
        self.lbl_summary_failed = self._create_badge("Failed: 0", "#C0392B")

        summary_row.addWidget(self.lbl_summary_total)
        summary_row.addWidget(self.lbl_summary_queued)
        summary_row.addWidget(self.lbl_summary_running)
        summary_row.addWidget(self.lbl_summary_completed)
        summary_row.addWidget(self.lbl_summary_failed)

        # Vocal removal & mixing indicator
        if self.remove_vocal:
            self.lbl_summary_vocal = self._create_badge(
                f"🎵 Vocal Removal: ON (BG: {self.background_percent}% | Voice: {self.ai_voice_percent}%)",
                "#16A085"
            )
        else:
            self.lbl_summary_vocal = self._create_badge(
                "🎵 Vocal Removal: OFF", "#7F8C8D")
        summary_row.addWidget(self.lbl_summary_vocal)

        # Speech timing sync indicator
        if self.auto_video_sync:
            self.lbl_summary_sync = self._create_badge(
                "🎬 Auto Video Speed Sync: ON (Single Export Parity)", "#D35400")
        elif self.fit_audio:
            self.lbl_summary_sync = self._create_badge(
                "⚡ Speech Retiming: ON", "#27AE60")
        else:
            self.lbl_summary_sync = self._create_badge(
                "⚡ Speech Sync: OFF", "#7F8C8D")
        summary_row.addWidget(self.lbl_summary_sync)

        summary_row.addStretch()

        h_layout.addLayout(summary_row)
        main_layout.addWidget(header_frame)

        # 2. Episode Progress Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "#", "Video File", "Subtitle", "Voice & Config", "Status", "Inline Progress", "Action"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)

        # Header sizing
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.setColumnWidth(0, 45)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(2, 160)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 170)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        self.table.setColumnWidth(4, 135)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.table.setColumnWidth(6, 155)

        self._populate_table()
        main_layout.addWidget(self.table)

        # 3. Bottom Controls
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 4, 0, 0)
        bottom_layout.setSpacing(10)

        # Pause / Resume
        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setObjectName("secondaryBtn")
        self.btn_pause.clicked.connect(self._toggle_pause)
        bottom_layout.addWidget(self.btn_pause)

        # Stop
        self.btn_stop = QPushButton("■ Stop Batch")
        self.btn_stop.setObjectName("dangerBtn")
        self.btn_stop.clicked.connect(self._stop_batch)
        bottom_layout.addWidget(self.btn_stop)

        # Open folder
        self.btn_open_folder = QPushButton("Open Output Folder")
        self.btn_open_folder.setObjectName("secondaryBtn")
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        bottom_layout.addWidget(self.btn_open_folder)

        # Merge checkbox
        self.chk_merge = QCheckBox("Merge finished videos into one final MP4")
        self.chk_merge.setChecked(self.merge_outputs)
        self.chk_merge.setStyleSheet("font-weight: bold;")
        self.chk_merge.toggled.connect(self._on_merge_toggled)
        bottom_layout.addWidget(self.chk_merge)

        bottom_layout.addStretch()

        # Close button
        self.btn_close = QPushButton("✓ Close")
        self.btn_close.setEnabled(False)
        self.btn_close.setObjectName("primaryBtn")
        self.btn_close.clicked.connect(self.accept)
        bottom_layout.addWidget(self.btn_close)

        main_layout.addLayout(bottom_layout)

    def _create_badge(self, text, color):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: #FFFFFF;
                font-weight: bold;
                font-size: 11px;
                padding: 4px 10px;
                border-radius: 4px;
            }}
        """)
        return lbl

    def _populate_table(self):
        self.table.setRowCount(len(self.manager.jobs))
        for row, job in enumerate(self.manager.jobs):
            # 0. Index
            idx_item = QTableWidgetItem(str(job.job_id))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, idx_item)

            # 1. Video File
            v_name = os.path.basename(job.video_path)
            v_item = QTableWidgetItem(v_name)
            v_item.setToolTip(job.video_path)
            self.table.setItem(row, 1, v_item)

            # 2. Subtitle
            s_name = os.path.basename(
                job.srt_path) if job.srt_path else "🎙️ Auto-Transcribe"
            s_item = QTableWidgetItem(s_name)
            if job.srt_path:
                s_item.setToolTip(job.srt_path)
            self.table.setItem(row, 2, s_item)

            # 3. Voice & Config
            v_short = job.voice_id.split("-")[-1].replace("Neural", "")
            echo_txt = f"{job.echo_intensity}%" if job.eco_enabled else "Off"
            cfg_txt = f"{v_short} | {job.rate} | Pitch:{job.pitch} | Echo:{echo_txt}"
            c_item = QTableWidgetItem(cfg_txt)
            self.table.setItem(row, 3, c_item)

            # 4. Status Badge
            badge = QLabel(job.status_text)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                "background-color: #7F8C8D; color: white; font-weight: bold; border-radius: 4px; padding: 3px 6px; font-size: 11px;")
            self.table.setCellWidget(row, 4, badge)

            # 5. Inline Progress Bar
            p_container = QWidget()
            p_layout = QHBoxLayout(p_container)
            p_layout.setContentsMargins(4, 2, 4, 2)
            p_layout.setSpacing(6)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(job.progress)
            bar.setFixedHeight(16)
            bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            p_layout.addWidget(bar)
            self.table.setCellWidget(row, 5, p_container)

            # 6. Action Buttons (Open Video & View Log)
            act_widget = QWidget()
            act_layout = QHBoxLayout(act_widget)
            act_layout.setContentsMargins(2, 2, 2, 2)
            act_layout.setSpacing(4)

            btn_open = QPushButton("🎬 Open")
            btn_open.setObjectName("primaryBtn")
            btn_open.setEnabled(False)
            btn_open.setToolTip("Open finished dubbed video")
            btn_open.setStyleSheet("padding: 2px 8px; font-weight: bold; font-size: 10px; border-radius: 4px;")
            btn_open.clicked.connect(
                lambda _, p=job.output_path: self._open_video_file(p))
            act_layout.addWidget(btn_open)

            btn_log = QPushButton("📋 Log")
            btn_log.setObjectName("secondaryBtn")
            btn_log.setToolTip("View real-time execution log for this job")
            btn_log.setStyleSheet("padding: 2px 8px; font-weight: bold; font-size: 10px; border-radius: 4px;")
            btn_log.clicked.connect(
                lambda _, j=job: self._open_job_log(j))
            act_layout.addWidget(btn_log)

            self.table.setCellWidget(row, 6, act_widget)
            self.table.setRowHeight(row, 36)

    def _connect_signals(self):
        self.manager.job_progress.connect(self._on_job_progress)
        self.manager.job_completed.connect(self._on_job_completed)
        self.manager.job_failed.connect(self._on_job_failed)
        self.manager.overall_progress.connect(self._on_overall_progress)
        self.manager.batch_finished.connect(self._on_batch_finished)

    def _on_job_progress(self, job_id, pct, status_text, status_type):
        row = job_id - 1
        if 0 <= row < self.table.rowCount():
            # Update status badge
            badge = self.table.cellWidget(row, 4)
            if badge:
                short_text = "Running"
                color = "#2980B9"  # blue
                if status_type == "initializing":
                    short_text = "Initializing"
                    color = "#16A085"  # teal
                elif status_type == "transcribing":
                    short_text = "Transcribing"
                    color = "#2980B9"  # blue
                elif status_type == "voice_gen":
                    short_text = "Dubbing"
                    color = "#E67E22"  # orange
                elif status_type == "vocal_removal":
                    short_text = "Vocal Removal"
                    color = "#D35400"  # rust orange
                elif status_type == "muxing":
                    short_text = "Muxing"
                    color = "#8E44AD"  # purple
                elif status_type == "done":
                    short_text = "Completed"
                    color = "#27AE60"  # green
                elif status_type in ("error", "failed"):
                    short_text = "Failed"
                    color = "#C0392B"  # red
                elif status_type == "stopped":
                    short_text = "Stopped"
                    color = "#95A5A6"  # gray

                badge.setText(short_text)
                badge.setToolTip(status_text)
                badge.setStyleSheet(
                    f"background-color: {color}; color: white; font-weight: bold; border-radius: 4px; padding: 3px 6px; font-size: 11px;")

            # Update inline progress bar
            p_container = self.table.cellWidget(row, 5)
            if p_container and p_container.layout() and p_container.layout().count() > 0:
                bar = p_container.layout().itemAt(0).widget()
                if bar:
                    bar.setValue(pct)
                    bar.setToolTip(status_text)
                    if status_text and pct < 100:
                        bar.setFormat(f"{pct}% ({status_text})")
                    else:
                        bar.setFormat(f"{pct}%")

        self._update_summary_counts()

    def _on_job_completed(self, job_id, output_path):
        row = job_id - 1
        if 0 <= row < self.table.rowCount():
            act_widget = self.table.cellWidget(row, 6)
            if act_widget:
                btn_open = act_widget.findChild(QPushButton, "btn_open")
                if btn_open:
                    btn_open.setEnabled(True)
        self._update_summary_counts()

    def _open_job_log(self, job):
        dlg = BatchJobLogDialog(
            job.log_file, os.path.basename(job.video_path), parent=self)
        dlg.exec_()

    def _on_job_failed(self, job_id, error_msg):
        self._update_summary_counts()

    def _on_overall_progress(self, completed, total, pct):
        self.overall_bar.setValue(pct)
        self.overall_bar.setFormat(f"{pct}% ({completed}/{total} Completed)")
        self._update_summary_counts()

    def _on_batch_finished(self, success_count, fail_count, merged_path):
        self.overall_bar.setValue(100)
        self.btn_close.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)

        msg = f"Batch processing finished!\n\n✅ Successfully dubbed: {success_count} video(s)\n"
        if fail_count > 0:
            msg += f"❌ Failed: {fail_count} video(s)\n"

        if merged_path and os.path.exists(merged_path):
            msg += f"\n🔗 Merged MP4 created:\n{merged_path}"

        if not getattr(self, '_suppress_msgbox', False):
            QMessageBox.information(self, "Batch Complete", msg)

    def _update_summary_counts(self):
        queued = sum(1 for j in self.manager.jobs if j.status == "queued")
        running = sum(1 for j in self.manager.jobs if j.status == "running")
        completed = sum(
            1 for j in self.manager.jobs if j.status == "completed")
        failed = sum(1 for j in self.manager.jobs if j.status in (
            "failed", "cancelled"))

        self.lbl_summary_queued.setText(f"Queued: {queued}")
        self.lbl_summary_running.setText(f"Running: {running}")
        self.lbl_summary_completed.setText(f"Completed: {completed}")
        self.lbl_summary_failed.setText(f"Failed: {failed}")

    def _on_concurrency_changed(self, val):
        self.manager.set_max_workers(val)

    def _toggle_pause(self):
        if self.manager.is_paused:
            self.manager.resume()
            self.btn_pause.setText("⏸ Pause")
            self.btn_pause.setObjectName("secondaryBtn")
            self.btn_pause.setStyleSheet("")
            self.btn_pause.style().unpolish(self.btn_pause)
            self.btn_pause.style().polish(self.btn_pause)
        else:
            self.manager.pause()
            self.btn_pause.setText("▶ Resume")
            self.btn_pause.setObjectName("primaryBtn")
            self.btn_pause.setStyleSheet("")
            self.btn_pause.style().unpolish(self.btn_pause)
            self.btn_pause.style().polish(self.btn_pause)

    def _stop_batch(self):
        reply = QMessageBox.question(
            self,
            "Stop Batch Processing?",
            "Are you sure you want to stop the remaining batch jobs?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.manager.cancel_all()
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.btn_close.setEnabled(True)

    def _open_output_folder(self):
        if os.path.exists(self.output_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))

    def _open_video_file(self, video_path):
        if os.path.exists(video_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(video_path))

    def _on_merge_toggled(self, checked):
        self.manager.merge_outputs = checked

    def closeEvent(self, event):
        active_count = len(self.manager.active_processes)
        if active_count > 0:
            reply = QMessageBox.question(
                self,
                "Close Batch Monitor?",
                f"There are still {active_count} video(s) processing in parallel.\nDo you want to stop processing and exit?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.manager.cancel_all()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


class BatchJobLogDialog(QDialog):
    """
    Dedicated log viewer dialog for inspecting real-time background dubbing progress,
    Demucs vocal separation, speech analysis, and FFmpeg muxing logs.
    """

    def __init__(self, log_file_path, video_name, parent=None):
        super().__init__(parent)
        self.log_file_path = log_file_path
        self.video_name = video_name
        self.last_pos = 0

        self.setWindowTitle(f"📋 Execution Log - {video_name}")
        self.resize(880, 560)
        self.setMinimumSize(650, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header info
        top_bar = QHBoxLayout()
        title_lbl = QLabel(f"<b>Job Log:</b> {video_name}")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        top_bar.addWidget(title_lbl)

        top_bar.addStretch()

        self.btn_copy = QPushButton("📋 Copy All")
        self.btn_copy.setObjectName("secondaryBtn")
        self.btn_copy.setStyleSheet("font-size: 11px;")
        self.btn_copy.clicked.connect(self._copy_log)
        top_bar.addWidget(self.btn_copy)

        self.btn_open_file = QPushButton("📂 Open File")
        self.btn_open_file.setObjectName("secondaryBtn")
        self.btn_open_file.setStyleSheet("font-size: 11px;")
        self.btn_open_file.clicked.connect(self._open_file_in_editor)
        top_bar.addWidget(self.btn_open_file)

        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setObjectName("secondaryBtn")
        self.btn_refresh.setStyleSheet("font-size: 11px;")
        self.btn_refresh.clicked.connect(self._manual_refresh)
        top_bar.addWidget(self.btn_refresh)

        layout.addLayout(top_bar)

        # Log content view
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        mono_font = QFont("DejaVu Sans Mono", 10)
        if not mono_font.exactMatch():
            mono_font = QFont("Courier New", 10)
        mono_font.setStyleHint(QFont.Monospace)
        self.text_edit.setFont(mono_font)
        layout.addWidget(self.text_edit)

        # Bottom bar with path
        bottom_bar = QHBoxLayout()
        path_lbl = QLabel(f"Path: {log_file_path}")
        path_lbl.setStyleSheet("font-size: 11px; opacity: 0.85;")
        bottom_bar.addWidget(path_lbl)
        bottom_bar.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setObjectName("primaryBtn")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        layout.addLayout(bottom_bar)

        # Initial load
        self._load_log()

        # Timer to auto-tail log if file exists
        self.timer = QTimer(self)
        self.timer.setInterval(1200)
        self.timer.timeout.connect(self._tail_log)
        self.timer.start()

    def _load_log(self):
        if not self.log_file_path or not os.path.exists(self.log_file_path):
            self.text_edit.setPlainText(
                "[LOG] Log file not yet generated or waiting for process to initialize...")
            return
        try:
            with open(self.log_file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                self.text_edit.setPlainText(content)
                self.last_pos = f.tell()
            self._scroll_to_bottom()
        except Exception as e:
            self.text_edit.setPlainText(f"[ERROR] Failed to read log: {e}")

    def _tail_log(self):
        if not self.log_file_path or not os.path.exists(self.log_file_path):
            return
        try:
            file_size = os.path.getsize(self.log_file_path)
            if file_size < self.last_pos:
                # File was truncated or rotated, reload
                self._load_log()
                return
            if file_size > self.last_pos:
                with open(self.log_file_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(self.last_pos)
                    new_text = f.read()
                    self.last_pos = f.tell()
                if new_text:
                    cursor = self.text_edit.textCursor()
                    cursor.movePosition(cursor.End)
                    cursor.insertText(new_text)
                    self._scroll_to_bottom()
        except Exception:
            pass

    def _manual_refresh(self):
        self._load_log()

    def _scroll_to_bottom(self):
        sb = self.text_edit.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _copy_log(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self.text_edit.toPlainText())
            self.btn_copy.setText("✓ Copied!")
            QTimer.singleShot(
                1500, lambda: self.btn_copy.setText("📋 Copy All"))

    def _open_file_in_editor(self):
        if self.log_file_path and os.path.exists(self.log_file_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.log_file_path))
