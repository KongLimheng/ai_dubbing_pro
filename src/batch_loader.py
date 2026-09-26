# -*- coding: utf-8 -*-
"""
Enhanced Batch Loader Module for AI Dubber Ultimate.
Provides folder loading, automatic SRT discovery with episode-number-aware matching,
drag & drop support, video row addition & removal, and polished table layouts.
"""

import os
import re
import sys
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import (
    QPushButton, QFileDialog, QMessageBox, QHeaderView,
    QMenu, QAction, QTableWidgetItem
)

VALID_VIDEO_EXTENSIONS = {
    '.mp4', '.mkv', '.avi', '.mov', '.flv', '.webm', '.ts', '.wmv', '.m4v'
}

VALID_SUBTITLE_EXTENSIONS = {
    '.srt', '.vtt', '.ass'
}


def natural_sort_key(path):
    """Sort key for natural alphanumeric ordering (e.g. EP1, EP2, EP10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', os.path.basename(path or ''))]


def sort_file_paths_naturally(file_paths):
    """Sorts file paths using natural numerical ordering."""
    return sorted(list(file_paths or []), key=natural_sort_key)


def _extract_episode_number(stem):
    """
    Extracts numerical episode identifier from filename stem.
    Matches EP01, EP 01, Episode 1, E01, - 01 -, or bare number.
    """
    if not stem:
        return None
    lower = stem.lower()
    patterns = [
        r'(?:ep|episode|ch|chapter|e)\s*[-_]?\s*0*(\d+)',
        r'[-_]\s*0*(\d+)\s*[-_]',
        r'[-_]\s*0*(\d+)$',
        r'^0*(\d+)\s*[-_]',
        r'^0*(\d+)$'
    ]
    for pat in patterns:
        m = re.search(pat, lower)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
    return None


def scan_folder_for_media(folder_path, recursive=True):
    """
    Scans a folder for video and subtitle files.
    Returns (video_paths, srt_paths).
    """
    video_files = []
    srt_files = []
    if not folder_path or not os.path.isdir(folder_path):
        return video_files, srt_files

    if recursive:
        for root, _, files in os.walk(folder_path):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                full_p = os.path.abspath(os.path.join(root, f))
                if ext in VALID_VIDEO_EXTENSIONS:
                    video_files.append(full_p)
                elif ext in VALID_SUBTITLE_EXTENSIONS:
                    srt_files.append(full_p)
    else:
        for f in os.listdir(folder_path):
            ext = os.path.splitext(f)[1].lower()
            full_p = os.path.abspath(os.path.join(folder_path, f))
            if os.path.isfile(full_p):
                if ext in VALID_VIDEO_EXTENSIONS:
                    video_files.append(full_p)
                elif ext in VALID_SUBTITLE_EXTENSIONS:
                    srt_files.append(full_p)

    return video_files, srt_files


def create_enhanced_batch_mapping_dialog_class(base_dialog_class):
    """
    Factory creating EnhancedBatchSrtMappingDialog subclassing the original compiled dialog.
    """
    class EnhancedBatchSrtMappingDialog(base_dialog_class):
        def _sort_file_paths_naturally(self, file_paths):
            return sort_file_paths_naturally(file_paths)

        def __init__(self, video_files, parent=None):
            # Ensure valid video_files list
            initial_videos = list(video_files or [])
            super().__init__(initial_videos, parent)

            # Unwrap redundant QScrollArea so content fills dialog directly without nested scroll trap
            try:
                from PyQt5.QtWidgets import QScrollArea, QSizePolicy
                from PyQt5.QtCore import QSize
                sa = self.findChild(QScrollArea)
                if sa and self.layout():
                    cw = sa.takeWidget()
                    if cw:
                        self.layout().removeWidget(sa)
                        sa.setParent(None)
                        sa.deleteLater()
                        self.layout().addWidget(cw)
                        cw.setMinimumSize(QSize(0, 0))
                        cw.setSizePolicy(QSizePolicy.Expanding,
                                         QSizePolicy.Expanding)

                        cw_layout = cw.layout()
                        if cw_layout:
                            table_idx = cw_layout.indexOf(self.table)
                            for i in range(cw_layout.count()):
                                if i == table_idx:
                                    cw_layout.setStretch(i, 1)
                                else:
                                    cw_layout.setStretch(i, 0)
            except Exception as e:
                print(f"[BatchLoader] ScrollArea unwrap notice: {e}")

            # Enable Window maximize and minimize buttons
            self.setWindowFlags(
                self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowMinimizeButtonHint)

            # Enable Drag & Drop
            self.setAcceptDrops(True)
            self.table.setAcceptDrops(True)
            self.table.viewport().setAcceptDrops(True)

            # Proportional window sizing & style
            try:
                from PyQt5.QtWidgets import QApplication
                screen = QApplication.primaryScreen()
                if screen:
                    ag = screen.availableGeometry()
                    self.resize(min(1600, int(ag.width() * 0.95)),
                                min(920, int(ag.height() * 0.92)))
                else:
                    self.resize(1366, 780)
            except Exception:
                self.resize(1366, 780)

            self.setMinimumSize(960, 560)

            # Open maximized so table fits the maximum window
            self.setWindowState(self.windowState() |
                                Qt.WindowState.WindowMaximized)

            # Insert Add Videos & Add Folder buttons into tools layout
            self._inject_toolbar_controls()

            # Insert Vocal Removal & Background Music Mix controls
            self._inject_vocal_removal_controls()

            # Polish table column headers and sizing
            self._polish_table_layout()

        def _inject_vocal_removal_controls(self):
            """
            Injects Vocal Removal (Demucs) and Background Mix controls into the batch dialog.
            Allows toggling instrumental background preservation and adjusting mix levels.
            """
            try:
                content_widget = self.btn_load_srts.parentWidget()
                if not content_widget or not content_widget.layout():
                    return
                parent_layout = content_widget.layout()

                # Find bulk controls layout index
                bulk_idx = -1
                for i in range(parent_layout.count()):
                    it = parent_layout.itemAt(i)
                    if it and it.layout() and hasattr(self, 'btn_apply_all_voice') and it.layout().indexOf(self.btn_apply_all_voice) >= 0:
                        bulk_idx = i
                        break

                from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QSpinBox

                # Container frame for clear visual grouping
                vocal_frame = QFrame()
                vocal_frame.setObjectName("BatchVocalRemovalFrame")
                vocal_layout = QVBoxLayout(vocal_frame)
                vocal_layout.setContentsMargins(12, 8, 12, 8)
                vocal_layout.setSpacing(6)

                # Row 1: Vocal Removal (Demucs) & Background Mix Controls
                row1_layout = QHBoxLayout()
                row1_layout.setSpacing(14)

                # 1. Demucs Vocal Removal Checkbox
                self.chk_batch_demucs = QCheckBox("🎵 Auto Remove Vocals (Demucs) & Keep Background Music")
                self.chk_batch_demucs.setObjectName("BatchChkDemucs")
                self.chk_batch_demucs.setToolTip(
                    "Remove original vocals using Demucs AI, isolating background music and sound effects,\n"
                    "and mix them with the new AI voice at your chosen volume levels."
                )
                self.chk_batch_demucs.setStyleSheet("font-weight: bold; font-size: 13px;")

                # Read initial state from parent window or persistent settings
                init_remove_vocal = False
                init_bg_percent = 30
                init_ai_percent = 100

                parent_win = self.parent()
                if parent_win and hasattr(parent_win, "chk_demucs_export"):
                    try:
                        init_remove_vocal = bool(parent_win.chk_demucs_export.isChecked())
                    except Exception:
                        pass
                else:
                    try:
                        from settings_manager import get_batch_auto_dub_config
                        init_remove_vocal = bool(get_batch_auto_dub_config().get('remove_vocal', False))
                    except Exception:
                        pass

                if parent_win and hasattr(parent_win, "spin_bg_mix"):
                    try:
                        init_bg_percent = int(parent_win.spin_bg_mix.value())
                    except Exception:
                        pass
                if parent_win and hasattr(parent_win, "spin_ai_mix"):
                    try:
                        init_ai_percent = int(parent_win.spin_ai_mix.value())
                    except Exception:
                        pass
                if not (parent_win and hasattr(parent_win, "spin_bg_mix")):
                    try:
                        from settings_manager import get_export_audio_mix_config
                        mix_cfg = get_export_audio_mix_config()
                        init_bg_percent = mix_cfg.get('background_percent', 30)
                        init_ai_percent = mix_cfg.get('ai_voice_percent', 100)
                    except Exception:
                        pass

                self.chk_batch_demucs.setChecked(init_remove_vocal)
                row1_layout.addWidget(self.chk_batch_demucs)

                # Separator
                row1_layout.addStretch()

                # 2. Background Music Volume
                bg_lbl = QLabel("🎼 Background Music:")
                bg_lbl.setStyleSheet("font-weight: 600;")
                row1_layout.addWidget(bg_lbl)

                self.spin_batch_bg_mix = QSpinBox()
                self.spin_batch_bg_mix.setObjectName("BatchSpinBgMix")
                self.spin_batch_bg_mix.setRange(0, 500)
                self.spin_batch_bg_mix.setValue(init_bg_percent)
                self.spin_batch_bg_mix.setSuffix("%")
                self.spin_batch_bg_mix.setToolTip("Volume level for the separated background music (default: 30%)")
                self.spin_batch_bg_mix.setStyleSheet("min-width: 65px; font-weight: bold;")
                self.spin_batch_bg_mix.setEnabled(init_remove_vocal)
                row1_layout.addWidget(self.spin_batch_bg_mix)

                # 3. AI Voice Volume
                ai_lbl = QLabel("🎙️ AI Voice:")
                ai_lbl.setStyleSheet("font-weight: 600;")
                row1_layout.addWidget(ai_lbl)

                self.spin_batch_ai_mix = QSpinBox()
                self.spin_batch_ai_mix.setObjectName("BatchSpinAiMix")
                self.spin_batch_ai_mix.setRange(0, 500)
                self.spin_batch_ai_mix.setValue(init_ai_percent)
                self.spin_batch_ai_mix.setSuffix("%")
                self.spin_batch_ai_mix.setToolTip("Volume level for the generated AI dubbing voice (default: 100%)")
                self.spin_batch_ai_mix.setStyleSheet("min-width: 65px; font-weight: bold;")
                row1_layout.addWidget(self.spin_batch_ai_mix)

                # Connect checkbox toggle to enable/disable background volume
                self.chk_batch_demucs.toggled.connect(self.spin_batch_bg_mix.setEnabled)

                vocal_layout.addLayout(row1_layout)

                # Row 2: Video Speed Timing Sync (Parity with Individual Export)
                row2_layout = QHBoxLayout()
                row2_layout.setSpacing(14)

                self.chk_batch_auto_sync = QCheckBox("🎬 Auto Sync Video Speed (Recommended - Matches Single Export Quality)")
                self.chk_batch_auto_sync.setObjectName("BatchChkAutoSync")
                self.chk_batch_auto_sync.setToolTip(
                    "Analyzes speech timing and adjusts video speed so each scene fits the dialogue naturally,\n"
                    "preserving 100% crisp, natural voice quality without audio distortion."
                )
                self.chk_batch_auto_sync.setStyleSheet("font-weight: bold; font-size: 13px;")

                init_auto_sync = True
                if parent_win and hasattr(parent_win, "chk_analyze_video"):
                    try:
                        init_auto_sync = bool(parent_win.chk_analyze_video.isChecked())
                    except Exception:
                        pass
                self.chk_batch_auto_sync.setChecked(init_auto_sync)
                row2_layout.addWidget(self.chk_batch_auto_sync)

                # Keep alias for backward compatibility
                self.chk_batch_sync_tts = self.chk_batch_auto_sync

                sync_hint = QLabel("💡 Adjusts video cuts to dialogue; voice is 100% crisp, natural, and never compressed")
                sync_hint.setStyleSheet("font-size: 11px; font-style: italic; opacity: 0.8;")
                row2_layout.addWidget(sync_hint)
                row2_layout.addStretch()

                vocal_layout.addLayout(row2_layout)

                # Insert into parent layout right after bulk controls
                insert_pos = bulk_idx + 1 if bulk_idx >= 0 else 4
                parent_layout.insertWidget(insert_pos, vocal_frame)

            except Exception as e:
                print(f"[BatchLoader] Vocal removal controls injection notice: {e}")

        def _inject_toolbar_controls(self):
            """Injects '+ Add Videos' and '+ Add Folder' buttons into the top toolbar."""
            try:
                content_widget = self.btn_load_srts.parentWidget()
                if not content_widget or not content_widget.layout():
                    return
                parent_layout = content_widget.layout()

                # Tools layout is at index 2
                tools_layout = None
                for i in range(parent_layout.count()):
                    it = parent_layout.itemAt(i)
                    if it and it.layout() and it.layout().indexOf(self.btn_load_srts) >= 0:
                        tools_layout = it.layout()
                        break

                if tools_layout is None and parent_layout.count() > 2 and parent_layout.itemAt(2).layout():
                    tools_layout = parent_layout.itemAt(2).layout()

                if tools_layout:
                    self.btn_add_videos = QPushButton("➕ Add Videos")
                    self.btn_add_videos.setObjectName("primaryBtn")
                    self.btn_add_videos.setToolTip(
                        "Select more video files to append to the batch list")
                    self.btn_add_videos.clicked.connect(self.browse_add_videos)

                    self.btn_add_folder = QPushButton("📂 Add Folder")
                    self.btn_add_folder.setObjectName("secondaryBtn")
                    self.btn_add_folder.setToolTip(
                        "Select a folder to automatically scan and append videos and SRT subtitles")
                    self.btn_add_folder.clicked.connect(self.browse_add_folder)

                    tools_layout.insertWidget(0, self.btn_add_videos)
                    tools_layout.insertWidget(1, self.btn_add_folder)

                # Also adjust bulk layout spacing so Echo Apply All is not clipped
                for i in range(parent_layout.count()):
                    it = parent_layout.itemAt(i)
                    if it and it.layout() and hasattr(self, 'btn_apply_all_echo') and it.layout().indexOf(self.btn_apply_all_echo) >= 0:
                        it.layout().setSpacing(6)
                        it.layout().setContentsMargins(0, 4, 0, 4)
                        break
            except Exception as e:
                print(f"[BatchLoader] Toolbar injection notice: {e}")

        def _polish_table_layout(self):
            """Applies clean column headers, widths, and stretch behavior."""
            try:
                headers = ["Video File", "Folder", "Assigned SRT",
                           "Voice", "Pitch", "Speed", "Echo", "Actions"]
                self.table.setHorizontalHeaderLabels(headers)
                header_view = self.table.horizontalHeader()
                header_view.setStretchLastSection(False)
                header_view.setMinimumSectionSize(45)

                from PyQt5.QtWidgets import QSizePolicy
                self.table.setSizePolicy(
                    QSizePolicy.Expanding, QSizePolicy.Expanding)

                # Set clean resize modes and collision-proof column dimensions
                header_view.setSectionResizeMode(
                    0, QHeaderView.Stretch)       # Video File (dynamic)
                header_view.setSectionResizeMode(
                    1, QHeaderView.Interactive)   # Folder
                self.table.setColumnWidth(1, 115)
                header_view.setSectionResizeMode(
                    2, QHeaderView.Stretch)       # Assigned SRT (dynamic)
                header_view.setSectionResizeMode(
                    3, QHeaderView.Interactive)   # Voice
                self.table.setColumnWidth(3, 190)
                header_view.setSectionResizeMode(
                    4, QHeaderView.Interactive)   # Pitch
                self.table.setColumnWidth(4, 65)
                header_view.setSectionResizeMode(
                    5, QHeaderView.Interactive)   # Speed
                self.table.setColumnWidth(5, 65)
                header_view.setSectionResizeMode(
                    6, QHeaderView.Interactive)   # Echo
                self.table.setColumnWidth(6, 110)
                header_view.setSectionResizeMode(
                    7, QHeaderView.Interactive)   # Actions
                self.table.setColumnWidth(7, 325)

                self.table.setSelectionBehavior(self.table.SelectRows)
                self.table.setAlternatingRowColors(True)
            except Exception as e:
                print(f"[BatchLoader] Table polish notice: {e}")

        def _build_rows(self):
            """Builds rows and appends Remove button to each row's action widget."""
            try:
                for r in range(self.table.rowCount()):
                    for c in range(self.table.columnCount()):
                        w = self.table.cellWidget(r, c)
                        if w:
                            w.deleteLater()
                self.table.clearContents()
                self.table.setRowCount(0)
            except Exception:
                pass
            super()._build_rows()
            try:
                for r in range(self.table.rowCount()):
                    action_widget = self.table.cellWidget(r, 7)
                    if action_widget and action_widget.layout():
                        action_widget.setMinimumWidth(320)
                        layout = action_widget.layout()
                        layout.setSpacing(3)
                        layout.setContentsMargins(2, 2, 2, 2)

                        # Compact existing action buttons in this cell
                        for i in range(layout.count()):
                            w = layout.itemAt(i).widget()
                            if w and isinstance(w, QPushButton):
                                cur_style = w.styleSheet() or ""
                                if "padding" not in cur_style:
                                    w.setStyleSheet(
                                        cur_style + "; padding: 2px 6px; font-size: 11px;")

                        # Verify Remove button not already added
                        has_remove = False
                        for i in range(layout.count()):
                            w = layout.itemAt(i).widget()
                            if w and getattr(w, 'objectName', lambda: '')() == 'BatchRowRemoveButton':
                                has_remove = True
                                break
                        if not has_remove:
                            remove_btn = QPushButton("❌ Remove")
                            remove_btn.setObjectName("dangerBtn")
                            remove_btn.setStyleSheet(
                                "padding: 2px 6px; font-weight: bold; border-radius: 4px; font-size: 11px;"
                            )
                            remove_btn.setToolTip(
                                "Remove this video from the batch list (or select row and press Delete)")
                            remove_btn.clicked.connect(
                                lambda _, row_idx=r: self.remove_video_row(row_idx))
                            layout.addWidget(remove_btn)
                self._polish_table_layout()
            except Exception as e:
                print(f"[BatchLoader] _build_rows button notice: {e}")

        def _candidate_score(self, video_path, srt_path):
            """
            Enhanced matching score with intelligent episode number extraction.
            Exact stem = 100
            Episode number match = 95
            Normalized stem = 90
            Substring stem = 60
            """
            video_stem = os.path.splitext(
                os.path.basename(video_path or ''))[0].lower()
            srt_stem = os.path.splitext(
                os.path.basename(srt_path or ''))[0].lower()
            if not video_stem or not srt_stem:
                return -1

            if video_stem == srt_stem:
                return 100

            # Episode number matching (EP01 vs 1.srt / Episode 1.srt)
            video_ep = _extract_episode_number(video_stem)
            srt_ep = _extract_episode_number(srt_stem)
            if video_ep is not None and srt_ep is not None and video_ep == srt_ep:
                # If same folder or same root name, high confidence match
                if os.path.dirname(video_path) == os.path.dirname(srt_path):
                    return 95
                return 92

            norm_v = self._normalized_stem(video_path)
            norm_s = self._normalized_stem(srt_path)
            if norm_v and norm_s and norm_v == norm_s:
                return 90

            if video_stem in srt_stem or srt_stem in video_stem:
                return 60

            return -1

        def browse_add_videos(self):
            """File dialog to append more videos to the batch list."""
            start_dir = ""
            if self.video_files:
                start_dir = os.path.dirname(self.video_files[0])
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "Select Videos to Add",
                start_dir,
                "Video Files (*.mp4 *.mkv *.avi *.mov *.flv *.webm *.ts *.wmv *.m4v);;All Files (*)"
            )
            if files:
                self.add_video_files(files)

        def browse_add_folder(self):
            """Folder dialog to scan and append an entire folder of videos and subtitles."""
            start_dir = ""
            if self.video_files:
                start_dir = os.path.dirname(self.video_files[0])
            folder = QFileDialog.getExistingDirectory(
                self, "Select Video Folder to Add", start_dir)
            if folder:
                self.add_video_folder(folder)

        def add_video_files(self, new_paths):
            """Appends new video paths, avoiding duplicates, and re-triggers auto-match."""
            if not new_paths:
                return
            added = 0
            existing_normalized = {os.path.normcase(
                os.path.abspath(p)) for p in self.video_files}
            for p in new_paths:
                if not os.path.isfile(p):
                    continue
                ext = os.path.splitext(p)[1].lower()
                if ext not in VALID_VIDEO_EXTENSIONS:
                    continue
                norm = os.path.normcase(os.path.abspath(p))
                if norm not in existing_normalized:
                    self.video_files.append(p)
                    existing_normalized.add(norm)
                    added += 1

            if added > 0:
                self.video_files = self._sort_file_paths_naturally(
                    self.video_files)
                self._build_rows()
                self.auto_match_srt_files()
                self._set_status_message(
                    f"Added {added} new video(s). Total: {len(self.video_files)}", "#27AE60")
            else:
                self._set_status_message(
                    "No new video files were added (duplicates or unsupported).", "#E67E22")

        def add_video_folder(self, folder_path):
            """Scans folder for videos and SRT subtitles, adds both, and auto-matches."""
            videos, srts = scan_folder_for_media(folder_path, recursive=True)
            if not videos and not srts:
                QMessageBox.information(
                    self, "No Media Found", f"No supported video or subtitle files found in:\n{folder_path}")
                return

            if srts:
                for s in srts:
                    if s not in self.available_srt_files:
                        self.available_srt_files.append(s)
                self.available_srt_files = self._sort_file_paths_naturally(
                    self.available_srt_files)

            self.add_video_files(videos)
            self.auto_match_srt_files()
            self._set_status_message(
                f"Imported from folder: {len(videos)} video(s), {len(srts)} subtitle(s).",
                "#27AE60"
            )

        def remove_video_row(self, row_idx):
            """Removes the video at row_idx and refreshes the table."""
            if 0 <= row_idx < len(self.video_files):
                removed_video = self.video_files.pop(row_idx)
                self.assignments.pop(removed_video, None)
                self.timeline_assignments.pop(removed_video, None)
                self.voice_assignments.pop(removed_video, None)
                self.echo_assignments.pop(removed_video, None)
                self._build_rows()
                self._refresh_assignment_cells()
                self._set_status_message(
                    f"Removed '{os.path.basename(removed_video)}'. Remaining: {len(self.video_files)}", "#E74C3C")

        def keyPressEvent(self, event):
            """Allows deleting selected table rows using Delete or Backspace key."""
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                selected_rows = sorted(
                    set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
                if selected_rows:
                    for r in selected_rows:
                        self.remove_video_row(r)
                    return
            super().keyPressEvent(event)

        # Drag & Drop Implementation
        def dragEnterEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event):
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragMoveEvent(event)

        def dropEvent(self, event):
            if not event.mimeData().hasUrls():
                super().dropEvent(event)
                return

            event.acceptProposedAction()
            dropped_videos = []
            dropped_srts = []
            dropped_folders = []

            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if not path:
                    continue
                if os.path.isdir(path):
                    dropped_folders.append(path)
                elif os.path.isfile(path):
                    ext = os.path.splitext(path)[1].lower()
                    if ext in VALID_VIDEO_EXTENSIONS:
                        dropped_videos.append(path)
                    elif ext in VALID_SUBTITLE_EXTENSIONS:
                        dropped_srts.append(path)

            total_added_videos = len(dropped_videos)
            total_added_srts = len(dropped_srts)

            # Process dropped folders
            for folder in dropped_folders:
                v_list, s_list = scan_folder_for_media(folder, recursive=True)
                dropped_videos.extend(v_list)
                dropped_srts.extend(s_list)

            # Add subtitles to pool
            for s in dropped_srts:
                if s not in self.available_srt_files:
                    self.available_srt_files.append(s)
            if dropped_srts:
                self.available_srt_files = self._sort_file_paths_naturally(
                    self.available_srt_files)

            # Add videos to list
            if dropped_videos:
                self.add_video_files(dropped_videos)

            # Re-run auto match
            self.auto_match_srt_files()
            self._set_status_message(
                f"Drop processed: {len(dropped_videos)} video(s), {len(dropped_srts)} subtitle(s).",
                "#27AE60"
            )

        def accept(self):
            """
            Overrides dialog acceptance (Start Batch button clicked).
            Validates jobs, selects output directory and merge preference,
            and launches BatchProcessingProgressDialog for parallel execution
            with per-episode inline progress bars.
            """
            jobs = self.get_jobs()
            if not jobs:
                QMessageBox.warning(
                    self, "Batch Load", "No videos were prepared for batch processing.")
                return

            start_dir = ""
            if self.video_files:
                start_dir = os.path.dirname(self.video_files[0])

            saved_output_dir = ""
            try:
                from core_app import get_batch_output_dir
                saved_output_dir = str(get_batch_output_dir() or "").strip()
            except Exception:
                pass

            default_dir = saved_output_dir or start_dir
            output_dir = QFileDialog.getExistingDirectory(
                self, "Select Batch Output Folder", default_dir)
            if not output_dir:
                return

            try:
                from core_app import save_batch_output_dir
                save_batch_output_dir(output_dir)
            except Exception:
                pass

            merge_reply = QMessageBox.question(
                self,
                "Merge Finished Videos?",
                "After all videos finish, do you want the app to also merge them into one final MP4 file?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            merge_enabled = (merge_reply == QMessageBox.Yes)

            # Read vocal removal & background mix preferences
            remove_vocal = bool(self.chk_batch_demucs.isChecked()) if hasattr(self, "chk_batch_demucs") else False
            bg_percent = int(self.spin_batch_bg_mix.value()) if hasattr(self, "spin_batch_bg_mix") else 30
            ai_percent = int(self.spin_batch_ai_mix.value()) if hasattr(self, "spin_batch_ai_mix") else 100
            use_demucs = remove_vocal
            auto_sync = bool(self.chk_batch_auto_sync.isChecked()) if hasattr(self, "chk_batch_auto_sync") else (
                bool(self.chk_batch_sync_tts.isChecked()) if hasattr(self, "chk_batch_sync_tts") else True
            )
            sync_tts = not auto_sync

            # Save configuration for future sessions
            try:
                from settings_manager import save_export_audio_mix_config, get_batch_auto_dub_config, save_batch_auto_dub_config
                save_export_audio_mix_config(bg_percent, ai_percent)
                auto_cfg = get_batch_auto_dub_config()
                save_batch_auto_dub_config(
                    auto_cfg.get('api_keys', []),
                    auto_cfg.get('target_language', 'km'),
                    remove_vocal,
                    output_dir,
                    auto_cfg.get('voice_mode', 'km-KH-SreymomNeural'),
                    auto_cfg.get('video_list', [])
                )
            except Exception:
                pass

            # Sync back to main window if parent is DubbingApp
            parent_window = self.parent() or self
            if hasattr(parent_window, "chk_demucs_export"):
                try:
                    parent_window.chk_demucs_export.setChecked(remove_vocal)
                except Exception:
                    pass
            if hasattr(parent_window, "chk_analyze_video"):
                try:
                    parent_window.chk_analyze_video.setChecked(auto_sync)
                except Exception:
                    pass
            if hasattr(parent_window, "spin_bg_mix"):
                try:
                    parent_window.spin_bg_mix.setValue(bg_percent)
                except Exception:
                    pass
            if hasattr(parent_window, "spin_ai_mix"):
                try:
                    parent_window.spin_ai_mix.setValue(ai_percent)
                except Exception:
                    pass
            if hasattr(parent_window, "chk_sync_tts_audio"):
                try:
                    parent_window.chk_sync_tts_audio.setChecked(sync_tts)
                except Exception:
                    pass

            # Attach audio mixing & timing sync options to every job
            for j in jobs:
                j["remove_vocal"] = remove_vocal
                j["use_demucs"] = use_demucs
                j["background_percent"] = bg_percent
                j["ai_voice_percent"] = ai_percent
                j["auto_video_sync"] = auto_sync
                j["preserve_speed"] = auto_sync
                j["fit_audio"] = sync_tts

            self.hide()

            from batch_processor import BatchProcessingProgressDialog
            self._batch_processed_parallel = True

            progress_dialog = BatchProcessingProgressDialog(
                jobs=jobs,
                output_dir=output_dir,
                merge_outputs=merge_enabled,
                max_workers=2,
                remove_vocal=remove_vocal,
                use_demucs=use_demucs,
                background_percent=bg_percent,
                ai_voice_percent=ai_percent,
                fit_audio=sync_tts,
                auto_video_sync=auto_sync,
                parent=parent_window
            )
            progress_dialog.exec_()

            super().accept()

    return EnhancedBatchSrtMappingDialog
