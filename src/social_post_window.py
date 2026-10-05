# -*- coding: utf-8 -*-
"""
social_post_window.py - Social Post Manager & Multi-Platform Video Publisher.
Supports publishing dubbed videos directly to Facebook Page, YouTube, and TikTok.
Adheres strictly to the 60-30-10 Design System and real-time Dark/Light theme toggling.
"""

import os
import sys
import re
import json
import time
import subprocess
from typing import Optional, Dict, Any, List

from PyQt5.QtCore import Qt, QUrl, QTimer, pyqtSignal, QThread, QDateTime, QDate, QTime
from PyQt5.QtGui import QDesktopServices, QColor, QFont, QIcon
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QPlainTextEdit, QProgressBar, QCheckBox,
    QComboBox, QTabWidget, QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QInputDialog, QFrame, QScrollArea, QSplitter,
    QApplication, QDialog, QRadioButton, QButtonGroup, QDateTimeEdit, QSpinBox,
    QListWidget, QListWidgetItem
)

from runtime_paths import resource_path, resolve_binary_path
from utils import get_ffmpeg_path
import settings_manager
import theme_manager
from ui_theme_tokens import (
    COLOR_CANVAS, COLOR_SURFACE, COLOR_SURFACE_INPUT, COLOR_SURFACE_HOVER,
    COLOR_BORDER, COLOR_BORDER_ELEVATED, COLOR_ACCENT, COLOR_ACCENT_HOVER,
    COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_TEXT_MUTED,
    LIGHT_COLOR_CANVAS, LIGHT_COLOR_SURFACE, LIGHT_COLOR_SURFACE_INPUT,
    LIGHT_COLOR_SURFACE_HOVER, LIGHT_COLOR_BORDER, LIGHT_COLOR_BORDER_ELEVATED,
    LIGHT_COLOR_ACCENT, LIGHT_COLOR_ACCENT_HOVER, LIGHT_COLOR_TEXT_PRIMARY,
    LIGHT_COLOR_TEXT_SECONDARY, LIGHT_COLOR_TEXT_MUTED,
    FONT_FAMILY
)
from social_post_config import (
    get_facebook_config, save_facebook_config,
    get_youtube_config, save_youtube_config,
    get_tiktok_config, save_tiktok_config,
    get_social_defaults, save_social_defaults,
    get_upload_history, add_upload_history_entry, clear_upload_history,
    get_last_selected_folder, save_last_selected_folder
)
from social_post_uploader import (
    FacebookUploader, YouTubeUploader, TikTokUploader, SocialUploadWorker,
    FacebookPlaylistsWorker, FacebookGroupsWorker,
    parse_facebook_group_identifier, build_bulk_video_title, build_bulk_video_description
)
from facebook_browser_poster import (
    FacebookBrowserPoster, list_chrome_profiles, is_playwright_ready, install_playwright,
    DEFAULT_ASSET_ID
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv",
                    ".avi", ".webm", ".flv", ".wmv", ".m4v"}


def natural_sort_key(s: str) -> list:
    """Sort strings containing numbers naturally (e.g. ep1, ep2, ep10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


def scan_folder_videos(folder_path: str) -> List[str]:
    """Scan folder for video files and return list of absolute paths naturally sorted."""
    if not folder_path or not os.path.isdir(folder_path):
        return []
    videos = []
    try:
        for entry in os.listdir(folder_path):
            full_p = os.path.join(folder_path, entry)
            if os.path.isfile(full_p):
                ext = os.path.splitext(entry)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    videos.append(full_p)
    except Exception:
        pass
    videos.sort(key=natural_sort_key)
    return videos


def parse_folder_config(folder_path: str) -> Dict[str, Any]:
    """
    Search for config.txt in folder_path (case-insensitive) and extract title, description, playlist, asset_id.
    Supports:
      1. Key-value format:
         title: My Video Title
         playlist: My Playlist Name
         asset_id: 364039971101203
         description: My Video Description...
      2. Simple format:
         First non-empty line = Title
         Subsequent lines = Description
    Returns:
      {"found": bool, "title": str, "description": str, "playlist": str, "asset_id": str, "file_path": str}
    """
    result = {"found": False, "title": "", "description": "",
              "playlist": "", "asset_id": "", "file_path": ""}
    if not folder_path or not os.path.isdir(folder_path):
        return result

    config_file = None
    try:
        for fname in os.listdir(folder_path):
            if fname.lower() == "config.txt":
                config_file = os.path.join(folder_path, fname)
                break
    except Exception:
        return result

    if not config_file or not os.path.isfile(config_file):
        return result

    result["found"] = True
    result["file_path"] = config_file

    content = ""
    for enc in ["utf-8-sig", "utf-8", "cp1252", "latin-1"]:
        try:
            with open(config_file, "r", encoding=enc) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if not content.strip():
        return result

    lines = content.splitlines()
    title = ""
    playlist = ""
    asset_id = ""
    desc_lines = []
    is_key_value = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("title:") or lower.startswith("title="):
            is_key_value = True
            break
        if lower.startswith("playlist:") or lower.startswith("playlist="):
            is_key_value = True
            break
        if lower.startswith("asset_id:") or lower.startswith("asset_id=") or lower.startswith("page_id:") or lower.startswith("page_id="):
            is_key_value = True
            break
        if lower.startswith("description:") or lower.startswith("description=") or lower.startswith("desc:"):
            is_key_value = True
            break

    if is_key_value:
        in_desc = False
        for line in lines:
            stripped = line.strip()
            lower = stripped.lower()
            if lower.startswith("title:") or lower.startswith("title="):
                in_desc = False
                sep = ":" if lower.startswith("title:") else "="
                title = stripped.split(sep, 1)[1].strip()
            elif lower.startswith("playlist:") or lower.startswith("playlist="):
                in_desc = False
                sep = ":" if lower.startswith("playlist:") else "="
                playlist = stripped.split(sep, 1)[1].strip()
            elif lower.startswith("asset_id:") or lower.startswith("asset_id=") or lower.startswith("page_id:") or lower.startswith("page_id="):
                in_desc = False
                sep = ":" if (lower.startswith("asset_id:")
                              or lower.startswith("page_id:")) else "="
                asset_id = stripped.split(sep, 1)[1].strip()
            elif lower.startswith("description:") or lower.startswith("description="):
                in_desc = True
                sep = ":" if lower.startswith("description:") else "="
                desc_lines.append(stripped.split(sep, 1)[1].strip())
            elif lower.startswith("desc:") or lower.startswith("desc="):
                in_desc = True
                sep = ":" if lower.startswith("desc:") else "="
                desc_lines.append(stripped.split(sep, 1)[1].strip())
            elif in_desc:
                desc_lines.append(line)
        description = "\n".join(desc_lines).strip()
    else:
        non_empty = [l for l in lines if l.strip()]
        if non_empty:
            title = non_empty[0].strip()
            first_idx = lines.index(non_empty[0])
            description = "\n".join(lines[first_idx + 1:]).strip()
        else:
            description = ""

    result["title"] = title
    result["description"] = description
    result["playlist"] = playlist
    result["asset_id"] = asset_id
    return result


class BatchMetadataDialog(QDialog):
    """
    Modal dialog prompted when config.txt is not found in the selected folder.
    Asks user for Title, optional Playlist, and Description to apply at once to all videos in the folder.
    """

    def __init__(self, folder_path: str, video_count: int, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.video_count = video_count
        self.applied_title = ""
        self.applied_playlist = ""
        self.applied_description = ""
        self.save_to_file = True

        self.setWindowTitle("📝 Set Title & Description for Folder Videos")
        self.resize(540, 440)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_text = (
            f"<b>No <code>config.txt</code> found in the selected folder.</b><br>"
            f"<span style='color: #8B949E; font-size: 11px;'>"
            f"Enter Title and Description below. It will be applied at once to all <b>{self.video_count}</b> video(s) in this folder:"
            f"</span>"
        )
        self.header_lbl = QLabel(header_text)
        self.header_lbl.setWordWrap(True)
        layout.addWidget(self.header_lbl)

        layout.addWidget(
            QLabel("Title / Caption (supports {filename}, {index}):"))
        self.txt_title = QLineEdit()
        self.txt_title.setPlaceholderText(
            "e.g. My Drama Episode {index} (or plain title)...")
        folder_name = os.path.basename(os.path.abspath(self.folder_path))
        self.txt_title.setText(folder_name)
        layout.addWidget(self.txt_title)

        layout.addWidget(QLabel("Target Facebook Playlist (optional):"))
        self.txt_playlist = QLineEdit()
        self.txt_playlist.setPlaceholderText(
            "e.g. Drama Series Season 1 (matching Facebook playlist name)")
        layout.addWidget(self.txt_playlist)

        layout.addWidget(QLabel("Description / Post Body:"))
        self.txt_desc = QTextEdit()
        self.txt_desc.setPlaceholderText(
            "Detailed description, credits, or hashtags to apply to all videos...")
        self.txt_desc.setText(
            f"Dubbed with AI Dubber Ultimate\n#dubbing #viral #{folder_name.replace(' ', '')}")
        self.txt_desc.setMaximumHeight(100)
        layout.addWidget(self.txt_desc)

        self.chk_save = QCheckBox(
            "💾 Save as config.txt in this folder for future use")
        self.chk_save.setChecked(True)
        layout.addWidget(self.chk_save)

        layout.addSpacing(6)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton(
            f"✅ Apply to All {self.video_count} Video(s)")
        self.btn_apply.setObjectName("primaryBtn")
        self.btn_apply.setStyleSheet("font-weight: bold; padding: 6px 14px;")
        self.btn_apply.clicked.connect(self._on_apply)
        btn_box.addWidget(self.btn_apply)

        layout.addLayout(btn_box)

    def _on_apply(self):
        title = self.txt_title.text().strip()
        playlist = self.txt_playlist.text().strip()
        desc = self.txt_desc.toPlainText().strip()
        if not title:
            QMessageBox.warning(self, "Missing Title",
                                "Please enter a title for the videos.")
            return

        self.applied_title = title
        self.applied_playlist = playlist
        self.applied_description = desc
        self.save_to_file = self.chk_save.isChecked()

        if self.save_to_file:
            cfg_path = os.path.join(self.folder_path, "config.txt")
            try:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    f.write(f"Title: {title}\n")
                    if playlist:
                        f.write(f"Playlist: {playlist}\n")
                    f.write(f"Description:\n{desc}\n")
            except Exception as e:
                print(f"[WARN] Failed to write config.txt: {e}")

        self.accept()


def format_file_size(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def probe_video_meta(file_path: str) -> Dict[str, Any]:
    """Extract video duration, resolution, and format via ffprobe."""
    meta = {"duration": 0.0, "width": 0,
            "height": 0, "size": 0, "is_shorts": False}
    if not os.path.exists(file_path):
        return meta

    meta["size"] = os.path.getsize(file_path)
    ffprobe_bin = resolve_binary_path("ffprobe")
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration:format=duration",
        "-of", "json",
        file_path,
    ]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, timeout=8, **kwargs)
        if res.returncode == 0 and res.stdout.strip():
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            if streams:
                v = streams[0]
                meta["width"] = int(v.get("width", 0))
                meta["height"] = int(v.get("height", 0))
                dur = float(v.get("duration") or data.get(
                    "format", {}).get("duration") or 0.0)
                meta["duration"] = dur
                if meta["height"] > meta["width"] or (meta["duration"] > 0 and meta["duration"] <= 60 and meta["height"] >= meta["width"]):
                    meta["is_shorts"] = True
    except Exception:
        pass
    return meta


class PermanentTokenExchangeDialog(QDialog):
    """
    Modal dialog to exchange a temporary Facebook user token into a 
    PERMANENT Page Access Token (which never expires).
    """

    def __init__(self, parent=None, initial_app_id: str = "", initial_app_secret: str = ""):
        super().__init__(parent)
        self.setWindowTitle(
            "⚡ 1-Click Facebook Permanent Page Token Generator")
        self.resize(680, 520)
        self.setModal(True)

        self.selected_page_id = ""
        self.selected_page_name = ""
        self.selected_page_token = ""
        self.selected_app_id = initial_app_id
        self.selected_app_secret = initial_app_secret
        self.fetched_pages = []

        self._init_ui(initial_app_id, initial_app_secret)

    def _init_ui(self, app_id: str, app_secret: str):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            "<b>Generate Never-Expiring Page Access Tokens</b><br>"
            "<span style='color: #8B949E; font-size: 11px;'>"
            "Standard tokens expire in 1-2 hours. This tool exchanges your temporary User Token with your Meta App credentials "
            "to produce <b>Permanent Page Access Tokens that never expire</b>."
            "</span>"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        gb_creds = QGroupBox("Meta App & User Credentials")
        cred_layout = QVBoxLayout(gb_creds)
        cred_layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("App ID:"))
        self.txt_app_id = QLineEdit()
        self.txt_app_id.setPlaceholderText("e.g. 123456789012345")
        self.txt_app_id.setText(app_id)
        row1.addWidget(self.txt_app_id, 1)

        row1.addWidget(QLabel("App Secret:"))
        self.txt_app_secret = QLineEdit()
        self.txt_app_secret.setEchoMode(QLineEdit.Password)
        self.txt_app_secret.setPlaceholderText(
            "From Meta App Settings > Basic")
        self.txt_app_secret.setText(app_secret)
        row1.addWidget(self.txt_app_secret, 1)

        btn_sec_toggle = QPushButton("👁")
        btn_sec_toggle.setFixedWidth(28)
        btn_sec_toggle.clicked.connect(
            lambda: self._toggle_echo(self.txt_app_secret))
        row1.addWidget(btn_sec_toggle)
        cred_layout.addLayout(row1)

        row2 = QVBoxLayout()
        row2.addWidget(QLabel("User Access Token (from Graph API Explorer):"))
        self.txt_user_token = QPlainTextEdit()
        self.txt_user_token.setPlaceholderText(
            "Paste your User Token here (EAAG... with pages_manage_posts, pages_read_engagement permissions)")
        self.txt_user_token.setMaximumHeight(65)
        row2.addWidget(self.txt_user_token)
        cred_layout.addLayout(row2)

        row_exchange_btn = QHBoxLayout()
        self.btn_exchange = QPushButton(
            "⚡ Exchange & Fetch Permanent Page Tokens")
        self.btn_exchange.setObjectName("primaryBtn")
        self.btn_exchange.setFixedHeight(34)
        self.btn_exchange.setStyleSheet("font-weight: bold;")
        self.btn_exchange.clicked.connect(self._run_exchange)
        row_exchange_btn.addWidget(self.btn_exchange)

        self.lbl_exchange_status = QLabel("Ready")
        self.lbl_exchange_status.setStyleSheet(
            "font-size: 11px; color: #8B949E;")
        row_exchange_btn.addWidget(self.lbl_exchange_status)
        row_exchange_btn.addStretch()
        cred_layout.addLayout(row_exchange_btn)

        layout.addWidget(gb_creds)

        # Pages Table
        layout.addWidget(
            QLabel("<b>Managed Facebook Pages with Permanent Tokens:</b>"))
        self.tbl_pages = QTableWidget()
        self.tbl_pages.setColumnCount(4)
        self.tbl_pages.setHorizontalHeaderLabels(
            ["Page Name", "Page ID", "Category", "Token Lifespan"])
        self.tbl_pages.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_pages.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.tbl_pages.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self.tbl_pages.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeToContents)
        self.tbl_pages.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_pages.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.tbl_pages, 1)

        # Bottom Buttons
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)
        btn_bar.addWidget(self.btn_cancel)

        self.btn_apply = QPushButton("✅ Select Page & Apply Permanent Token")
        self.btn_apply.setObjectName("primaryBtn")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_selection)
        btn_bar.addWidget(self.btn_apply)

        layout.addLayout(btn_bar)

    def _toggle_echo(self, edit: QLineEdit):
        if edit.echoMode() == QLineEdit.Password:
            edit.setEchoMode(QLineEdit.Normal)
        else:
            edit.setEchoMode(QLineEdit.Password)

    def _run_exchange(self):
        app_id = self.txt_app_id.text().strip()
        app_secret = self.txt_app_secret.text().strip()
        user_tok = self.txt_user_token.toPlainText().strip()

        if not app_id or not app_secret or not user_tok:
            QMessageBox.warning(
                self, "Missing Fields", "Please enter App ID, App Secret, and User Access Token.")
            return

        self.lbl_exchange_status.setText(
            "⏳ Exchanging token with Meta Graph API...")
        self.btn_exchange.setEnabled(False)
        QApplication.processEvents()

        try:
            res = FacebookUploader.exchange_for_permanent_page_tokens(
                app_id, app_secret, user_tok)
            self.fetched_pages = res.get("pages", [])
            self.selected_app_id = app_id
            self.selected_app_secret = app_secret

            self.tbl_pages.setRowCount(0)
            for r, page in enumerate(self.fetched_pages):
                self.tbl_pages.insertRow(r)
                name_item = QTableWidgetItem(page.get("name", "Unknown"))
                name_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tbl_pages.setItem(r, 0, name_item)

                id_item = QTableWidgetItem(page.get("id", ""))
                id_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tbl_pages.setItem(r, 1, id_item)

                cat_item = QTableWidgetItem(page.get("category", ""))
                cat_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tbl_pages.setItem(r, 2, cat_item)

                status_item = QTableWidgetItem(
                    page.get("status_label", "🟢 Permanent"))
                status_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                status_item.setForeground(QColor("#39D353"))
                self.tbl_pages.setItem(r, 3, status_item)

            if self.fetched_pages:
                self.tbl_pages.selectRow(0)
                self.btn_apply.setEnabled(True)
                self.lbl_exchange_status.setText(
                    f"✅ Found {len(self.fetched_pages)} Page(s) with Permanent Tokens!")
                self.lbl_exchange_status.setStyleSheet(
                    "font-size: 11px; color: #39D353; font-weight: bold;")
            else:
                self.lbl_exchange_status.setText(
                    "⚠️ Token exchanged, but no managed Pages were found.")
                self.lbl_exchange_status.setStyleSheet(
                    "font-size: 11px; color: #E3B341;")
                QMessageBox.information(
                    self, "No Pages Found",
                    "The user token is valid and was upgraded to long-lived, but does not manage any Facebook Pages."
                )
        except Exception as e:
            self.lbl_exchange_status.setText("🔴 Exchange failed")
            self.lbl_exchange_status.setStyleSheet(
                "font-size: 11px; color: #F85149;")
            QMessageBox.critical(self, "Exchange Error",
                                 f"Failed to exchange token:\n{e}")
        finally:
            self.btn_exchange.setEnabled(True)

    def _apply_selection(self):
        row = self.tbl_pages.currentRow()
        if row < 0 or row >= len(self.fetched_pages):
            QMessageBox.warning(self, "No Selection",
                                "Please select a Page from the table first.")
            return

        sel = self.fetched_pages[row]
        self.selected_page_id = sel.get("id", "")
        self.selected_page_name = sel.get("name", "")
        self.selected_page_token = sel.get("access_token", "")
        self.accept()


class FacebookGuideDialog(QDialog):
    """
    Comprehensive Guide Dialog for Facebook Video Posting Solutions.
    Provides documentation for:
      1. Permanent Page Token (1-Click Exchange)
      2. Meta Business Suite System User (Never-Expire Enterprise)
      3. Browser Automation Poster (Playwright/Chrome profile - No Dev App)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 Facebook Video Posting Solutions & Token Guide")
        self.resize(760, 560)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        tabs = QTabWidget()

        # Tab 1: 1-Click Permanent Token
        tab1 = QWidget()
        l1 = QVBoxLayout(tab1)
        t1_edit = QTextEdit()
        t1_edit.setReadOnly(True)
        t1_edit.setHtml("""
        <h3>⚡ Solution 1: 1-Click Permanent Page Token (Meta Graph API)</h3>
        <p><b>Why tokens expire:</b> Standard User tokens generated in Graph API Explorer expire in 1–2 hours. If you query <code>/me/accounts</code> with a short-lived token, the Page Token also dies in 2 hours.</p>
        <p><b>The Solution:</b> When exchanged with your <b>App ID</b> and <b>App Secret</b>, Meta upgrades the token to a 60-day token, and <code>/me/accounts</code> automatically returns <b>Permanent Page Access Tokens that NEVER EXPIRE</b> (expires_at = 0)!</p>
        <hr>
        <h4>How to set up:</h4>
        <ol>
            <li>Go to <a href="https://developers.facebook.com/apps">developers.facebook.com/apps</a> and open or create your App.</li>
            <li>In the left sidebar, navigate to <b>App Settings &rarr; Basic</b>. Copy your <b>App ID</b> and <b>App Secret</b>.</li>
            <li>In the top menu, go to <b>Tools &rarr; Graph API Explorer</b>.</li>
            <li>In the <b>Permissions</b> dropdown, add:
                <ul>
                    <li><code>pages_show_list</code></li>
                    <li><code>pages_read_engagement</code></li>
                    <li><code>pages_manage_posts</code></li>
                    <li><code>publish_video</code></li>
                </ul>
            </li>
            <li>Click <b>Generate Access Token</b> and accept the Facebook prompts.</li>
            <li>In AI Dubber, click <b>⚡ 1-Click Generate Permanent Token</b>, paste your App ID, Secret, and User Token.</li>
            <li>Click <b>Exchange</b> &rarr; select your Page &rarr; click <b>Apply</b>. You're done! Your Page Token will never expire!</li>
        </ol>
        """)
        l1.addWidget(t1_edit)
        tabs.addTab(tab1, "⚡ Permanent Page Token")

        # Tab 2: Meta Business System User
        tab2 = QWidget()
        l2 = QVBoxLayout(tab2)
        t2_edit = QTextEdit()
        t2_edit.setReadOnly(True)
        t2_edit.setHtml("""
        <h3>🏢 Solution 2: Meta Business System User Token (Official Enterprise)</h3>
        <p>This is the official Meta method used by marketing agencies and automated bots. The token belongs to a <i>System User</i> rather than a personal profile, so it <b>never expires</b> and won't break if you change your personal Facebook password.</p>
        <hr>
        <h4>Step-by-Step Instructions:</h4>
        <ol>
            <li>Open <a href="https://business.facebook.com/settings/system-users">Meta Business Settings &rarr; System Users</a>.</li>
            <li>Click <b>Add</b> to create a new System User.
                <ul>
                    <li>Name: <code>AIDubberUploader</code></li>
                    <li>System User Role: <b>Admin</b></li>
                </ul>
            </li>
            <li>Under <b>Assigned Assets</b>, click <b>Add Assets</b> &rarr; choose <b>Pages</b>.
                <ul>
                    <li>Select your Facebook Page and enable <b>Full Control (Manage Page / Create Content)</b>.</li>
                </ul>
            </li>
            <li>Click <b>Generate New Token</b>:
                <ul>
                    <li>Select your Meta App.</li>
                    <li>Set <b>Token Expiration</b> to: <b>Never</b>.</li>
                    <li>Check permissions: <code>pages_manage_posts</code>, <code>pages_read_engagement</code>, <code>pages_show_list</code>, <code>publish_video</code>.</li>
                </ul>
            </li>
            <li>Copy the generated token and paste it directly into <b>Page Access Token</b> in AI Dubber.</li>
            <li>Save settings. This token will <b>NEVER EXPIRE</b>!</li>
        </ol>
        """)
        l2.addWidget(t2_edit)
        tabs.addTab(tab2, "🏢 System User (Never-Expire)")

        # Tab 3: Browser Automation Mode
        tab3 = QWidget()
        l3 = QVBoxLayout(tab3)
        t3_edit = QTextEdit()
        t3_edit.setReadOnly(True)
        t3_edit.setHtml("""
        <h3>🌐 Solution 3: Browser Automation (Zero-Token / Cookie Session)</h3>
        <p>If you don't have a Meta Developer account or don't want to deal with App Review / APIs, you can post videos directly using our browser automation engine.</p>
        <hr>
        <h4>Features:</h4>
        <ul>
            <li>Uploads directly via <b>Meta Business Suite Composer</b> (<code>business.facebook.com/latest/composer</code>).</li>
            <li>Uses your logged-in Google Chrome Profile or saved session cookies.</li>
            <li>Zero tokens, zero Meta Developer apps required!</li>
        </ul>
        <h4>Command-Line Usage:</h4>
        <pre style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 4px;">
python src/facebook_browser_poster.py \\
    --video "output/my_video.mp4" \\
    --title "My Video Title" \\
    --description "Video Description #viral #dubbing" \\
    --profile-dir "/path/to/chrome/user/data"
        </pre>
        <p>Run <code>python src/facebook_browser_poster.py --help</code> in your terminal for all options.</p>
        """)
        l3.addWidget(t3_edit)
        tabs.addTab(tab3, "🌐 Browser Automation (No Token)")

        layout.addWidget(tabs, 1)

        btn_close = QPushButton("Close")
        btn_close.setObjectName("primaryBtn")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)


class AddFacebookGroupDialog(QDialog):
    """
    Modal dialog allowing users to enter Facebook Group IDs or URLs manually.
    Supports single ID, Facebook group URL, or comma-separated list of IDs/URLs.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("➕ Add Facebook Group (ID or URL)")
        self.resize(480, 240)
        self.setModal(True)

        self.added_groups = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        info = QLabel(
            "<b>Paste Facebook Group Link or Numeric ID:</b><br>"
            "<span style='color: #8B949E; font-size: 11px;'>"
            "Supports: <code>https://www.facebook.com/groups/123456789012345</code>, "
            "or direct ID <code>123456789012345</code>, or multiple comma-separated IDs/links."
            "</span>"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(QLabel("Group ID or URL:"))
        self.txt_input = QLineEdit()
        self.txt_input.setPlaceholderText(
            "e.g. https://www.facebook.com/groups/123456789012345 or 1234567890")
        layout.addWidget(self.txt_input)

        layout.addWidget(QLabel("Custom Group Name (Optional):"))
        self.txt_name = QLineEdit()
        self.txt_name.setPlaceholderText("e.g. My Drama Community (optional)")
        layout.addWidget(self.txt_name)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_add = QPushButton("➕ Add Group")
        self.btn_add.setObjectName("primaryBtn")
        self.btn_add.setStyleSheet("font-weight: bold; padding: 6px 16px;")
        self.btn_add.clicked.connect(self._on_add)

        btn_box.addWidget(self.btn_cancel)
        btn_box.addWidget(self.btn_add)
        layout.addLayout(btn_box)

    def _on_add(self):
        raw_text = self.txt_input.text().strip()
        custom_name = self.txt_name.text().strip()
        if not raw_text:
            QMessageBox.warning(self, "Input Required",
                                "Please enter a Group ID or Facebook Group URL.")
            return

        parsed_ids = parse_facebook_group_identifier(raw_text)
        if not parsed_ids:
            QMessageBox.warning(
                self, "Invalid Group", "Could not extract a valid Group ID from the input.")
            return

        self.added_groups = []
        for i, gid in enumerate(parsed_ids):
            name = custom_name if (custom_name and len(
                parsed_ids) == 1) else f"Group {gid}"
            self.added_groups.append({
                "id": gid,
                "name": name,
                "privacy": "CUSTOM",
                "administrator": True,
                "description": "Manually added group",
                "custom": True,
            })

        self.accept()


class FacebookGroupSelectorDialog(QDialog):
    """
    Modal dialog to search, filter, and select one or multiple Facebook Groups
    to share published video post links with.
    """

    def __init__(
        self,
        parent=None,
        groups: Optional[List[Dict[str, Any]]] = None,
        selected_ids: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("👥 Select Facebook Groups to Share With")
        self.resize(600, 540)
        self.setModal(True)

        self.all_groups = list(groups or [])
        self.selected_ids = set(str(gid).strip() for gid in (
            selected_ids or []) if str(gid).strip() and not str(gid).startswith("(None"))
        self.active_filter = "all"

        self._init_ui()
        self._populate_list()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_lbl = QLabel(
            "<b>Select one or more Facebook Groups to share your video post link with.</b><br>"
            "<span style='color: #8B949E; font-size: 11px;'>"
            "When the video finishes uploading, AI Dubber will automatically distribute the post link to each selected group."
            "</span>"
        )
        header_lbl.setWordWrap(True)
        layout.addWidget(header_lbl)

        # Search Bar + Manual Add Group Button
        search_row = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("🔍 Search groups by name or ID...")
        self.txt_search.textChanged.connect(self._filter_list)
        search_row.addWidget(self.txt_search, 1)

        self.btn_add_group = QPushButton("➕ Add Group (ID or URL)")
        self.btn_add_group.setFixedHeight(30)
        self.btn_add_group.setStyleSheet(
            "font-weight: bold; background: #238636; color: white;")
        self.btn_add_group.setToolTip(
            "Paste a Group ID or Facebook Group link (e.g. facebook.com/groups/123456789)")
        self.btn_add_group.clicked.connect(self._on_add_group_clicked)
        search_row.addWidget(self.btn_add_group)

        self.btn_remove_custom = QPushButton("🗑️")
        self.btn_remove_custom.setFixedWidth(30)
        self.btn_remove_custom.setFixedHeight(30)
        self.btn_remove_custom.setToolTip("Remove selected custom group")
        self.btn_remove_custom.clicked.connect(self._on_remove_custom_clicked)
        search_row.addWidget(self.btn_remove_custom)

        layout.addLayout(search_row)

        tip_lbl = QLabel(
            "<span style='color: #8B949E; font-size: 11px;'>"
            "💡 <b>Tip:</b> If groups don't load automatically due to Meta API restrictions, "
            "use <b>➕ Add Group</b> to paste any Group ID or Link directly!"
            "</span>"
        )
        tip_lbl.setWordWrap(True)
        layout.addWidget(tip_lbl)

        # Filter Chips & Quick Select Actions
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self.btn_filter_all = QPushButton("All Groups")
        self.btn_filter_all.setFixedHeight(26)
        self.btn_filter_all.clicked.connect(lambda: self._set_filter("all"))

        self.btn_filter_admin = QPushButton("⭐ Admin Only")
        self.btn_filter_admin.setFixedHeight(26)
        self.btn_filter_admin.clicked.connect(
            lambda: self._set_filter("admin"))

        self.btn_filter_public = QPushButton("🌐 Public Only")
        self.btn_filter_public.setFixedHeight(26)
        self.btn_filter_public.clicked.connect(
            lambda: self._set_filter("public"))

        action_row.addWidget(self.btn_filter_all)
        action_row.addWidget(self.btn_filter_admin)
        action_row.addWidget(self.btn_filter_public)
        action_row.addStretch()

        btn_select_all = QPushButton("Select All")
        btn_select_all.setFixedHeight(26)
        btn_select_all.clicked.connect(self._select_all_visible)

        btn_clear = QPushButton("Clear")
        btn_clear.setFixedHeight(26)
        btn_clear.clicked.connect(self._clear_all_selection)

        action_row.addWidget(btn_select_all)
        action_row.addWidget(btn_clear)
        layout.addLayout(action_row)

        # Group List
        self.list_groups = QListWidget()
        self.list_groups.setStyleSheet(
            "QListWidget { background: #0D121B; border: 1px solid #212936; border-radius: 8px; padding: 4px; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #161D28; border-radius: 4px; color: #F1F5F9; }"
            "QListWidget::item:hover { background: #161D28; }"
            "QListWidget::item:selected { background: #1E2738; color: #FFFFFF; }"
        )
        self.list_groups.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list_groups, 1)

        # Status & Counter
        status_row = QHBoxLayout()
        self.lbl_counter = QLabel("Selected: 0 of 0 groups")
        self.lbl_counter.setStyleSheet(
            "font-size: 11px; color: #58A6FF; font-weight: bold;")
        status_row.addWidget(self.lbl_counter, 1)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("secondaryBtn")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("✅ Apply Selection")
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.setStyleSheet("font-weight: bold; padding: 6px 16px;")
        self.btn_save.clicked.connect(self.accept)

        status_row.addWidget(self.btn_cancel)
        status_row.addWidget(self.btn_save)
        layout.addLayout(status_row)

    def _on_add_group_clicked(self):
        dlg = AddFacebookGroupDialog(self)
        if dlg.exec_() == QDialog.Accepted and dlg.added_groups:
            fb = get_facebook_config()
            existing_custom = list(fb.get("custom_groups", []))
            for new_g in dlg.added_groups:
                gid = str(new_g["id"])
                if not any(str(g.get("id")) == gid for g in self.all_groups):
                    self.all_groups.append(new_g)
                self.selected_ids.add(gid)
                if not any(str(cg.get("id")) == gid for cg in existing_custom):
                    existing_custom.append(new_g)

            save_facebook_config({"custom_groups": existing_custom})
            self._populate_list()

    def _on_remove_custom_clicked(self):
        cur_item = self.list_groups.currentItem()
        if not cur_item:
            QMessageBox.information(
                self, "Remove Group", "Please select a custom group from the list to remove.")
            return
        gid = cur_item.data(Qt.UserRole)
        grp = next((g for g in self.all_groups if str(g.get("id")) == gid), None)
        if not grp or not grp.get("custom", False):
            QMessageBox.warning(
                self, "Cannot Remove", "Only manually added custom groups can be removed.")
            return
        reply = QMessageBox.question(
            self, "Confirm Removal", f"Remove custom group '{grp.get('name')}' (ID: {gid})?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.all_groups = [
                g for g in self.all_groups if str(g.get("id")) != gid]
            self.selected_ids.discard(gid)
            fb = get_facebook_config()
            existing_custom = [cg for cg in fb.get(
                "custom_groups", []) if str(cg.get("id")) != gid]
            save_facebook_config({"custom_groups": existing_custom})
            self._populate_list()

    def _set_filter(self, filter_mode: str):
        self.active_filter = filter_mode
        self._filter_list()

    def _populate_list(self):
        self.list_groups.blockSignals(True)
        self.list_groups.clear()

        query = self.txt_search.text().strip().lower()

        for grp in self.all_groups:
            gid = str(grp.get("id", "")).strip()
            name = grp.get("name", f"Group {gid}")
            privacy = str(grp.get("privacy", "")).upper()
            is_admin = bool(grp.get("administrator", False))
            is_custom = bool(grp.get("custom", False))

            if self.active_filter == "admin" and not is_admin:
                continue
            if self.active_filter == "public" and privacy != "OPEN" and "PUBLIC" not in privacy:
                continue

            if query and query not in name.lower() and query not in gid.lower():
                continue

            badge_admin = " [⭐ Admin]" if is_admin else ""
            badge_priv = " [🌐 Public]" if (privacy == "OPEN" or "PUBLIC" in privacy) else (
                " [🔒 Private]" if privacy in ("CLOSED", "SECRET") else "")
            badge_custom = " [✏️ Custom]" if is_custom else ""
            display_text = f"{name}{badge_admin}{badge_priv}{badge_custom}  (ID: {gid})"

            item = QListWidgetItem(display_text)
            item.setData(Qt.ItemDataRole.UserRole, gid)
            item.setData(Qt.ItemDataRole.UserRole + 1, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable |
                          Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if gid in self.selected_ids:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)

            self.list_groups.addItem(item)

        self.list_groups.blockSignals(False)
        self._update_counter()

    def _filter_list(self):
        self._populate_list()

    def _on_item_changed(self, item: QListWidgetItem):
        gid = item.data(Qt.ItemDataRole.UserRole)
        if not gid:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self.selected_ids.add(gid)
        else:
            self.selected_ids.discard(gid)
        self._update_counter()

    def _select_all_visible(self):
        self.list_groups.blockSignals(True)
        for i in range(self.list_groups.count()):
            item = self.list_groups.item(i)
            gid = item.data(Qt.ItemDataRole.UserRole)
            if gid:
                item.setCheckState(Qt.CheckState.Checked)
                self.selected_ids.add(gid)
        self.list_groups.blockSignals(False)
        self._update_counter()

    def _clear_all_selection(self):
        self.list_groups.blockSignals(True)
        self.selected_ids.clear()
        for i in range(self.list_groups.count()):
            item = self.list_groups.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)
        self.list_groups.blockSignals(False)
        self._update_counter()

    def _update_counter(self):
        sel_cnt = len(self.selected_ids)
        total_cnt = len(self.all_groups)
        self.lbl_counter.setText(
            f"Selected: {sel_cnt} of {total_cnt} available group(s)")

    def get_selected_groups(self) -> List[Dict[str, str]]:
        res = []
        for gid in self.selected_ids:
            name = next((g.get("name", f"Group {gid}") for g in self.all_groups if str(
                g.get("id")) == gid), f"Group {gid}")
            res.append({"id": gid, "name": name})
        return res


class FacebookLoginWorker(QThread):
    """
    Background worker that runs interactive browser session for Facebook login
    without blocking or freezing the main Qt UI thread.
    """
    status_updated = pyqtSignal(str)
    login_finished = pyqtSignal(dict)
    login_failed = pyqtSignal(str)

    def __init__(self, profile_name: str = "Default", target_url: str = "", parent=None):
        super().__init__(parent)
        self.profile_name = profile_name
        self.target_url = target_url or FacebookBrowserPoster.MBS_COMPOSER_URL

    def run(self):
        try:
            poster = FacebookBrowserPoster(profile_name=self.profile_name)
            self.status_updated.emit("Launching browser for Facebook login...")
            res = poster.launch_profile_for_login(
                target_url=self.target_url,
                on_status_callback=lambda msg: self.status_updated.emit(msg),
            )
            self.login_finished.emit(res if isinstance(res, dict) else {})
        except Exception as e:
            self.login_failed.emit(str(e))


class SocialPostWindow(QMainWindow):
    """
    Main Window for Social Post Manager.
    Allows publishing dubbed media directly to Facebook Page, YouTube, and TikTok.
    """

    def __init__(self, parent=None, initial_video: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle(
            "📢 Social Post Manager — Facebook Page, YouTube, TikTok")
        self.resize(1000, 780)
        self.setMinimumSize(850, 650)

        # Set window icon
        for icon_name in ("icon.png", "icon.ico"):
            icon_p = resource_path(icon_name)
            if os.path.exists(icon_p):
                self.setWindowIcon(QIcon(icon_p))
                break

        self.initial_video = initial_video
        self.upload_worker: Optional[SocialUploadWorker] = None
        self._published_links: Dict[str, str] = {}
        self.folder_queue: List[str] = []
        self.is_folder_mode: bool = False
        self.selected_folder: str = ""
        self._pl_worker: Optional[FacebookPlaylistsWorker] = None
        self._grp_worker: Optional[FacebookGroupsWorker] = None
        self._all_available_groups: List[Dict[str, Any]] = []
        self._selected_group_ids: List[str] = []
        self._selected_group_names: List[str] = []

        self._init_ui()
        self._load_saved_data()

        if self.initial_video and os.path.exists(self.initial_video):
            self.set_selected_video(self.initial_video)

        # Apply current theme
        self.apply_dialog_theme()

    def _init_ui(self):
        """Construct the UI with tabbed interface."""
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(12)

        # ── Header Banner ────────────────────────────────────────────────────
        header_layout = QHBoxLayout()
        header_title_col = QVBoxLayout()
        header_title_col.setSpacing(2)

        self.title_lbl = QLabel("📢 Social Video Publisher")
        self.title_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.subtitle_lbl = QLabel(
            "Publish & distribute dubbed videos directly to Facebook Page, YouTube, and TikTok")
        self.subtitle_lbl.setStyleSheet("font-size: 12px; color: #8B949E;")

        header_title_col.addWidget(self.title_lbl)
        header_title_col.addWidget(self.subtitle_lbl)
        header_layout.addLayout(header_title_col)
        header_layout.addStretch()

        # Connection Status Pills
        self.badge_fb = QLabel("📘 FB: Ready")
        self.badge_yt = QLabel("▶️ YT: Ready")
        self.badge_tt = QLabel("🎵 TT: Ready")
        for b in (self.badge_fb, self.badge_yt, self.badge_tt):
            b.setStyleSheet(
                "background: rgba(255,255,255,0.08); border-radius: 6px; padding: 4px 8px; font-size: 11px;")
            header_layout.addWidget(b)

        main_layout.addLayout(header_layout)

        # ── Tabbed View ──────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.tabs.setObjectName("socialTabs")

        self.tab_publish = QWidget()
        self.tab_accounts = QWidget()
        self.tab_history = QWidget()

        self._build_publish_tab()
        self._build_accounts_tab()
        self._build_history_tab()

        self.tabs.addTab(self.tab_publish, "🚀 Publish Video")
        self.tabs.addTab(self.tab_accounts, "🔑 Accounts & API Setup")
        self.tabs.addTab(self.tab_history, "📜 Publishing History")

        main_layout.addWidget(self.tabs, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1: PUBLISH VIDEO
    # ─────────────────────────────────────────────────────────────────────────

    def _build_publish_tab(self):
        layout = QVBoxLayout(self.tab_publish)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 1. Video Selection Group
        gb_video = QGroupBox("🎬 1. Select Video or Folder to Publish")
        gb_video_layout = QVBoxLayout(gb_video)
        gb_video_layout.setSpacing(8)

        v_picker_row = QHBoxLayout()
        self.video_path_input = QLineEdit()
        self.video_path_input.setPlaceholderText(
            "Select a video file (.mp4, .mov...) or folder to auto-post...")
        self.video_path_input.textChanged.connect(self._on_video_path_changed)

        btn_browse = QPushButton("📁 Browse Video...")
        btn_browse.setObjectName("secondaryBtn")
        btn_browse.clicked.connect(self._browse_video)

        self.btn_browse_folder = QPushButton("📂 Browse Folder...")
        self.btn_browse_folder.setObjectName("secondaryBtn")
        self.btn_browse_folder.setToolTip(
            "Select a folder to auto post all existing videos and read config.txt")
        self.btn_browse_folder.clicked.connect(self._browse_folder)

        self.btn_use_current = QPushButton("🎯 Use Active Video")
        self.btn_use_current.setObjectName("secondaryBtn")
        self.btn_use_current.setToolTip(
            "Auto-detect video loaded or exported in AI Dubber")
        self.btn_use_current.clicked.connect(self._use_active_project_video)

        v_picker_row.addWidget(self.video_path_input, 1)
        v_picker_row.addWidget(btn_browse)
        v_picker_row.addWidget(self.btn_browse_folder)
        v_picker_row.addWidget(self.btn_use_current)
        gb_video_layout.addLayout(v_picker_row)

        # Video Metadata Badges and Queue Status
        meta_row = QHBoxLayout()
        self.video_meta_lbl = QLabel("ℹ️ No video or folder selected.")
        self.video_meta_lbl.setStyleSheet("font-size: 11px; color: #8B949E;")
        meta_row.addWidget(self.video_meta_lbl, 1)

        self.folder_queue_badge = QLabel("")
        self.folder_queue_badge.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #58A6FF;")
        meta_row.addWidget(self.folder_queue_badge)
        gb_video_layout.addLayout(meta_row)

        self.folder_queue_lbl = QLabel("")
        self.folder_queue_lbl.setStyleSheet(
            "font-size: 10px; color: #8B949E; padding: 2px 4px; background: rgba(255,255,255,0.04); border-radius: 4px;")
        self.folder_queue_lbl.setWordWrap(True)
        self.folder_queue_lbl.setVisible(False)
        gb_video_layout.addWidget(self.folder_queue_lbl)

        layout.addWidget(gb_video)

        # 2. Splitter: Left = Metadata & Platforms, Right = Progress & Console
        split = QSplitter(Qt.Orientation.Horizontal)

        # Left Panel (Metadata & Target Platforms)
        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        # Metadata Card
        gb_meta = QGroupBox("📝 2. Post Title, Description & Tags")
        gb_meta_layout = QVBoxLayout(gb_meta)
        gb_meta_layout.setSpacing(6)

        title_header = QHBoxLayout()
        title_header.addWidget(QLabel("Title / Caption:"))
        self.title_counter_lbl = QLabel("0 / 100")
        self.title_counter_lbl.setStyleSheet(
            "font-size: 10px; color: #8B949E;")
        title_header.addStretch()
        title_header.addWidget(self.title_counter_lbl)
        gb_meta_layout.addLayout(title_header)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText(
            "Catchy video title or short caption...")
        self.title_input.textChanged.connect(self._update_title_counter)
        gb_meta_layout.addWidget(self.title_input)

        gb_meta_layout.addWidget(QLabel("Description / Post Body:"))
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText(
            "Detailed description, credits, translation notes, and full hashtags...")
        self.desc_input.setMaximumHeight(85)
        gb_meta_layout.addWidget(self.desc_input)

        # Quick Hashtag Chips
        tag_row = QHBoxLayout()
        tag_row.setSpacing(4)
        tag_row.addWidget(QLabel("Quick Tags:"))
        chips = ["#dubbing", "#shorts", "#reels",
                 "#tiktok", "#viral", "#movie", "#khmer", "#ai"]
        for chip in chips:
            btn_chip = QPushButton(chip)
            btn_chip.setStyleSheet(
                "font-size: 10px; padding: 2px 6px; border-radius: 4px; border: 1px solid #30363D;")
            btn_chip.clicked.connect(lambda _, c=chip: self._append_hashtag(c))
            tag_row.addWidget(btn_chip)
        tag_row.addStretch()
        gb_meta_layout.addLayout(tag_row)

        left_layout.addWidget(gb_meta)

        # Target Platforms & Options Card
        gb_plat = QGroupBox("🌐 3. Target Platforms & Options")
        gb_plat_layout = QVBoxLayout(gb_plat)
        gb_plat_layout.setSpacing(8)

        # Platform Checkboxes
        p_row = QHBoxLayout()
        self.chk_fb = QCheckBox("📘 Facebook Page")
        self.chk_yt = QCheckBox("▶️ YouTube")
        self.chk_tt = QCheckBox("🎵 TikTok")

        self.chk_fb.setChecked(True)
        self.chk_yt.setChecked(True)
        self.chk_tt.setChecked(True)

        p_row.addWidget(self.chk_fb)
        p_row.addWidget(self.chk_yt)
        p_row.addWidget(self.chk_tt)
        p_row.addStretch()
        gb_plat_layout.addLayout(p_row)

        # ── 3.1 Compact Platforms Row: YouTube & TikTok side-by-side ──
        row_yt_tt = QHBoxLayout()
        row_yt_tt.setSpacing(12)

        # YouTube Options
        self.yt_options_container = QWidget()
        yt_box = QVBoxLayout(self.yt_options_container)
        yt_box.setContentsMargins(0, 0, 0, 0)
        yt_box.setSpacing(4)
        lbl_yt_title = QLabel("▶️ YouTube Options:")
        lbl_yt_title.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #8B949E;")
        yt_box.addWidget(lbl_yt_title)
        yt_box.addWidget(QLabel("YouTube Privacy:"))
        self.cmb_yt_privacy = QComboBox()
        self.cmb_yt_privacy.addItems(["public", "unlisted", "private"])
        yt_box.addWidget(self.cmb_yt_privacy)

        self.chk_yt_kids = QCheckBox("Made for Kids")
        yt_box.addWidget(self.chk_yt_kids)
        row_yt_tt.addWidget(self.yt_options_container, 1)

        # TikTok Options
        self.tt_options_container = QWidget()
        tt_box = QVBoxLayout(self.tt_options_container)
        tt_box.setContentsMargins(0, 0, 0, 0)
        tt_box.setSpacing(4)
        lbl_tt_title = QLabel("🎵 TikTok Options:")
        lbl_tt_title.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #8B949E;")
        tt_box.addWidget(lbl_tt_title)
        tt_box.addWidget(QLabel("TikTok Privacy:"))
        self.cmb_tt_privacy = QComboBox()
        self.cmb_tt_privacy.addItems(
            ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"])
        tt_box.addWidget(self.cmb_tt_privacy)

        self.chk_tt_comments = QCheckBox("Allow Comments")
        self.chk_tt_comments.setChecked(True)
        tt_box.addWidget(self.chk_tt_comments)
        row_yt_tt.addWidget(self.tt_options_container, 1)

        gb_plat_layout.addLayout(row_yt_tt)

        # Connect toggles to enable/disable option cards
        self.chk_yt.toggled.connect(self.yt_options_container.setEnabled)
        self.chk_tt.toggled.connect(self.tt_options_container.setEnabled)

        # ── 3.2 Facebook Options (Full Width for Maximum Clarity & Comfort) ──
        self.fb_options_container = QWidget()
        fb_box = QVBoxLayout(self.fb_options_container)
        fb_box.setContentsMargins(0, 4, 0, 0)
        fb_box.setSpacing(6)
        self.chk_fb.toggled.connect(self.fb_options_container.setEnabled)

        mode_header = QHBoxLayout()
        self.lbl_fb_mode_active = QLabel("Mode: 🚀 Graph API (Native Meta Scheduling Active)")
        self.lbl_fb_mode_active.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #58A6FF;")
        btn_fb_mode_switch = QPushButton("⚙️ Setup")
        btn_fb_mode_switch.setFixedHeight(24)
        btn_fb_mode_switch.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        btn_fb_mode_switch.setToolTip(
            "Switch posting mode or configure credentials in Accounts tab")
        btn_fb_mode_switch.clicked.connect(
            lambda: self.tabs.setCurrentIndex(1))
        mode_header.addWidget(self.lbl_fb_mode_active, 1)
        mode_header.addWidget(btn_fb_mode_switch)
        fb_box.addLayout(mode_header)

        fb_box.addWidget(QLabel("Facebook Publishing Status:"))
        self.cmb_fb_publish = QComboBox()
        self.cmb_fb_publish.addItems([
            "🚀 Publish Immediately",
            "🕒 Schedule Public",
            "📝 Save as Draft",
        ])
        self.cmb_fb_publish.currentIndexChanged.connect(
            self._on_fb_publish_status_changed)
        fb_box.addWidget(self.cmb_fb_publish)

        # ── Schedule Panel (Collapsible, shown when Schedule Public selected) ──
        self.fb_schedule_container = QWidget()
        self.fb_schedule_container.setObjectName("fb_schedule_container")
        sched_layout = QVBoxLayout(self.fb_schedule_container)
        sched_layout.setContentsMargins(10, 10, 10, 10)
        sched_layout.setSpacing(8)

        sched_lbl_row = QHBoxLayout()
        sched_lbl_row.addWidget(QLabel("📅 Scheduled Date & Time:"))
        self.lbl_sched_min_note = QLabel("(Min 10m in future)")
        self.lbl_sched_min_note.setStyleSheet(
            "font-size: 11px; color: #8B949E;")
        sched_lbl_row.addWidget(self.lbl_sched_min_note,
                                0, Qt.AlignmentFlag.AlignRight)
        sched_layout.addLayout(sched_lbl_row)

        self.dt_fb_schedule = QDateTimeEdit(
            QDateTime.currentDateTime().addSecs(3600))
        self.dt_fb_schedule.setCalendarPopup(True)
        self.dt_fb_schedule.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.dt_fb_schedule.setMinimumDateTime(
            QDateTime.currentDateTime().addSecs(660))
        self.dt_fb_schedule.setFixedHeight(30)
        self.dt_fb_schedule.dateTimeChanged.connect(
            self._on_schedule_datetime_changed)
        sched_layout.addWidget(self.dt_fb_schedule)

        lbl_presets = QLabel("⚡ Quick Schedule Presets:")
        lbl_presets.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #8B949E; margin-top: 2px;")
        sched_layout.addWidget(lbl_presets)

        # Preset Row 1: Relative offsets with comfortable sizing and pointer cursors
        preset_row1 = QHBoxLayout()
        preset_row1.setSpacing(6)
        presets_r1 = [
            ("+30m", 1800, "Schedule 30 minutes from current time"),
            ("+1h", 3600, "Schedule 1 hour from current time"),
            ("+2h", 7200, "Schedule 2 hours from current time"),
            ("+3h", 10800, "Schedule 3 hours from current time"),
            ("+6h", 21600, "Schedule 6 hours from current time"),
            ("+1d", 86400, "Schedule 24 hours from current time"),
        ]
        for label, secs, tip in presets_r1:
            btn_p = QPushButton(label)
            btn_p.setObjectName("schedulePresetBtn")
            btn_p.setProperty("class", "schedulePresetBtn")
            btn_p.setMinimumHeight(28)
            btn_p.setCursor(Qt.PointingHandCursor)
            btn_p.setToolTip(tip)
            btn_p.clicked.connect(
                lambda checked, s=secs: self._apply_schedule_offset(s))
            preset_row1.addWidget(btn_p)
        sched_layout.addLayout(preset_row1)

        # Preset Row 2: Optimal Peak Target Times & Quick Reset
        preset_row2 = QHBoxLayout()
        preset_row2.setSpacing(6)
        presets_r2 = [
            ("🌅 Tomorrow 9AM", lambda: self._apply_schedule_tomorrow_9am(), "Schedule for 9:00 AM tomorrow"),
            ("🌆 Tomorrow 6PM", lambda: self._apply_schedule_tomorrow_6pm(), "Schedule for 6:00 PM tomorrow"),
            ("🌙 Tomorrow 8PM", lambda: self._apply_schedule_tomorrow_8pm(), "Schedule for 8:00 PM tomorrow"),
            ("🔄 Reset (+1h)", lambda: self._apply_schedule_reset_1h(), "Reset schedule time to +1 hour"),
        ]
        for label, handler, tip in presets_r2:
            btn_p2 = QPushButton(label)
            btn_p2.setObjectName("schedulePresetBtn")
            btn_p2.setProperty("class", "schedulePresetBtn")
            btn_p2.setMinimumHeight(28)
            btn_p2.setCursor(Qt.PointingHandCursor)
            btn_p2.setToolTip(tip)
            btn_p2.clicked.connect(lambda checked, h=handler: h())
            preset_row2.addWidget(btn_p2)
        sched_layout.addLayout(preset_row2)

        # Real-time Relative Schedule Preview Badge
        self.lbl_schedule_preview = QLabel("")
        self.lbl_schedule_preview.setWordWrap(True)
        self.lbl_schedule_preview.setStyleSheet(
            "font-size: 11px; font-weight: 500; color: #58A6FF; padding: 5px 8px; background: rgba(88, 166, 255, 0.08); border-radius: 6px; border: 1px solid rgba(88, 166, 255, 0.2);"
        )
        sched_layout.addWidget(self.lbl_schedule_preview)
        self._update_schedule_preview_label()

        batch_interval_row = QHBoxLayout()
        lbl_interval = QLabel("⏱️ Batch Video Interval:")
        lbl_interval.setStyleSheet("font-size: 11px;")
        lbl_interval.setToolTip(
            "Time interval between consecutive videos when publishing multiple files in batch")
        self.spin_fb_schedule_interval = QSpinBox()
        self.spin_fb_schedule_interval.setRange(5, 1440)
        self.spin_fb_schedule_interval.setValue(60)
        self.spin_fb_schedule_interval.setSuffix(" mins")
        self.spin_fb_schedule_interval.setFixedWidth(85)
        batch_interval_row.addWidget(lbl_interval, 1)
        batch_interval_row.addWidget(self.spin_fb_schedule_interval)
        sched_layout.addLayout(batch_interval_row)

        self.fb_schedule_container.setVisible(False)
        fb_box.addWidget(self.fb_schedule_container)

        fb_chk_row = QHBoxLayout()
        self.chk_fb_notify = QCheckBox("Notify")
        self.chk_fb_notify.setChecked(True)
        self.chk_fb_disable_caption = QCheckBox("🚫 Disable Caption")
        self.chk_fb_disable_caption.setToolTip(
            "Post video to Facebook without caption text or subtitle files")
        fb_chk_row.addWidget(self.chk_fb_notify)
        fb_chk_row.addWidget(self.chk_fb_disable_caption)
        fb_box.addLayout(fb_chk_row)

        # Closed Caption (.srt / .vtt) auto-upload and locale row
        fb_cc_row = QHBoxLayout()
        self.chk_fb_closed_caption = QCheckBox(
            "💬 Auto-Upload Subtitles (.srt/.vtt)")
        self.chk_fb_closed_caption.setChecked(True)
        self.chk_fb_closed_caption.setToolTip(
            "Automatically detects matching .srt or .vtt subtitle file for each video and uploads it to Facebook Video Captions via Graph API."
        )
        fb_cc_row.addWidget(self.chk_fb_closed_caption, 1)

        fb_cc_lbl = QLabel("Locale:")
        fb_cc_lbl.setStyleSheet("font-size: 11px; color: #8B949E;")
        fb_cc_row.addWidget(fb_cc_lbl)

        self.cmb_fb_caption_locale = QComboBox()
        self.cmb_fb_caption_locale.setEditable(True)
        self.cmb_fb_caption_locale.setFixedWidth(120)
        self.cmb_fb_caption_locale.setToolTip(
            "Caption language locale required by Meta (e.g. en_US, km_KH, zh_CN, vi_VN)")
        common_locales = [
            ("en_US", "en_US (English US)"),
            ("km_KH", "km_KH (Khmer)"),
            ("zh_CN", "zh_CN (Chinese Simplified)"),
            ("vi_VN", "vi_VN (Vietnamese)"),
            ("th_TH", "th_TH (Thai)"),
            ("id_ID", "id_ID (Indonesian)"),
            ("es_LA", "es_LA (Spanish LatAm)"),
            ("fr_FR", "fr_FR (French)"),
            ("ja_JP", "ja_JP (Japanese)"),
            ("ko_KR", "ko_KR (Korean)"),
        ]
        for code, label in common_locales:
            self.cmb_fb_caption_locale.addItem(label, code)
        fb_cc_row.addWidget(self.cmb_fb_caption_locale)
        fb_box.addLayout(fb_cc_row)

        fb_pl_lbl = QLabel("Add to Playlist:")
        fb_pl_lbl.setStyleSheet("font-size: 11px;")
        fb_box.addWidget(fb_pl_lbl)
        pl_row = QHBoxLayout()
        self.cmb_fb_playlist = QComboBox()
        self.cmb_fb_playlist.setEditable(True)
        self.cmb_fb_playlist.addItem("(None - Do not add)", "")
        self.btn_refresh_fb_playlists = QPushButton("🔄")
        self.btn_refresh_fb_playlists.setFixedWidth(28)
        self.btn_refresh_fb_playlists.setToolTip(
            "Fetch playlists from Facebook Page via Graph API")
        self.btn_refresh_fb_playlists.clicked.connect(
            self._fetch_facebook_playlists)
        pl_row.addWidget(self.cmb_fb_playlist, 1)
        pl_row.addWidget(self.btn_refresh_fb_playlists)
        fb_box.addLayout(pl_row)

        fb_grp_lbl = QLabel("Share with Group(s):")
        fb_grp_lbl.setStyleSheet("font-size: 11px;")
        fb_box.addWidget(fb_grp_lbl)
        grp_row = QHBoxLayout()
        self.cmb_fb_group = QComboBox()
        self.cmb_fb_group.setEditable(True)
        self.cmb_fb_group.addItem("(None - Do not share)", "")
        self.cmb_fb_group.currentIndexChanged.connect(
            self._on_fb_group_combo_changed)

        self.btn_select_fb_groups = QPushButton("👥 Select...")
        self.btn_select_fb_groups.setToolTip(
            "Open full group selector dialog to pick 1 or multiple groups")
        self.btn_select_fb_groups.clicked.connect(
            self._open_facebook_group_selector)

        self.btn_refresh_fb_groups = QPushButton("🔄")
        self.btn_refresh_fb_groups.setFixedWidth(28)
        self.btn_refresh_fb_groups.setToolTip(
            "Fetch all available groups from Facebook Graph API")
        self.btn_refresh_fb_groups.clicked.connect(self._fetch_facebook_groups)
        grp_row.addWidget(self.cmb_fb_group, 1)
        grp_row.addWidget(self.btn_select_fb_groups)
        grp_row.addWidget(self.btn_refresh_fb_groups)
        fb_box.addLayout(grp_row)

        gb_plat_layout.addWidget(self.fb_options_container)
        left_layout.addWidget(gb_plat)

        # Wrap left_container in a smooth, frame-less QScrollArea
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_container)
        split.addWidget(left_scroll)

        # Right Panel (Upload Progress & Console Logs)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        gb_progress = QGroupBox("📊 4. Live Progress & Status")
        gb_progress_layout = QVBoxLayout(gb_progress)
        gb_progress_layout.setSpacing(6)

        # Facebook Bar
        self.lbl_fb_bar = QLabel("📘 Facebook Page: Ready")
        self.lbl_fb_bar.setStyleSheet("font-size: 11px;")
        self.bar_fb = QProgressBar()
        self.bar_fb.setRange(0, 100)
        self.bar_fb.setValue(0)
        gb_progress_layout.addWidget(self.lbl_fb_bar)
        gb_progress_layout.addWidget(self.bar_fb)

        # YouTube Bar
        self.lbl_yt_bar = QLabel("▶️ YouTube: Ready")
        self.lbl_yt_bar.setStyleSheet("font-size: 11px;")
        self.bar_yt = QProgressBar()
        self.bar_yt.setRange(0, 100)
        self.bar_yt.setValue(0)
        gb_progress_layout.addWidget(self.lbl_yt_bar)
        gb_progress_layout.addWidget(self.bar_yt)

        # TikTok Bar
        self.lbl_tt_bar = QLabel("🎵 TikTok: Ready")
        self.lbl_tt_bar.setStyleSheet("font-size: 11px;")
        self.bar_tt = QProgressBar()
        self.bar_tt.setRange(0, 100)
        self.bar_tt.setValue(0)
        gb_progress_layout.addWidget(self.lbl_tt_bar)
        gb_progress_layout.addWidget(self.bar_tt)

        # Live Console Log
        gb_progress_layout.addWidget(QLabel("Live Upload Console:"))
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setMaximumHeight(140)
        self.log_console.setStyleSheet(
            "font-family: monospace; font-size: 10px; background: #0D121B; color: #58A6FF;")
        gb_progress_layout.addWidget(self.log_console)

        # Success Links Area
        self.links_layout = QHBoxLayout()
        self.links_layout.setSpacing(6)
        gb_progress_layout.addLayout(self.links_layout)

        right_layout.addWidget(gb_progress)
        split.addWidget(right_container)
        split.setSizes([500, 480])

        layout.addWidget(split, 1)

        # 5. Bottom Action Buttons Bar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(10)

        self.btn_publish = QPushButton("🚀 Publish to Selected Platforms")
        self.btn_publish.setObjectName("primaryBtn")
        self.btn_publish.setFixedHeight(38)
        self.btn_publish.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.btn_publish.clicked.connect(self._start_publishing)

        self.btn_cancel = QPushButton("⏹ Cancel Upload")
        self.btn_cancel.setObjectName("dangerBtn")
        self.btn_cancel.setFixedHeight(38)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_publishing)

        btn_go_accounts = QPushButton("⚙️ Accounts Setup...")
        btn_go_accounts.setObjectName("secondaryBtn")
        btn_go_accounts.setFixedHeight(38)
        btn_go_accounts.clicked.connect(lambda: self.tabs.setCurrentIndex(1))

        action_bar.addWidget(self.btn_publish, 2)
        action_bar.addWidget(self.btn_cancel, 1)
        action_bar.addWidget(btn_go_accounts, 1)

        layout.addLayout(action_bar)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2: ACCOUNTS & CREDENTIALS SETUP
    # ─────────────────────────────────────────────────────────────────────────

    def _build_accounts_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # ── 1. Facebook Page Setup Card ──────────────────────────────────────
        gb_fb = QGroupBox("📘 Facebook Page Configuration")
        gb_fb_layout = QVBoxLayout(gb_fb)
        gb_fb_layout.setSpacing(10)

        # Mode Selector
        row_fb_mode = QHBoxLayout()
        lbl_m = QLabel("Posting Method:")
        lbl_m.setStyleSheet("font-weight: bold; font-size: 11px;")
        row_fb_mode.addWidget(lbl_m)

        self.rb_fb_mode_api = QRadioButton(
            "🚀 Meta Graph API (Permanent Token)")
        self.rb_fb_mode_browser = QRadioButton(
            "🌐 Browser Automation (Chrome Profile - Zero Token)")
        self.rb_fb_mode_api.setChecked(True)

        self.bg_fb_mode = QButtonGroup(self)
        self.bg_fb_mode.addButton(self.rb_fb_mode_api)
        self.bg_fb_mode.addButton(self.rb_fb_mode_browser)
        self.rb_fb_mode_api.toggled.connect(self._on_fb_mode_changed)

        row_fb_mode.addWidget(self.rb_fb_mode_api)
        row_fb_mode.addWidget(self.rb_fb_mode_browser)
        row_fb_mode.addStretch()
        gb_fb_layout.addLayout(row_fb_mode)

        # ── PANEL 1: Meta Graph API Mode ──────────────────────────────────
        self.panel_fb_api = QWidget()
        panel_api_layout = QVBoxLayout(self.panel_fb_api)
        panel_api_layout.setContentsMargins(0, 4, 0, 0)
        panel_api_layout.setSpacing(8)

        fb_hint = QLabel(
            "Enter your Facebook Page credentials, or use the 1-Click Permanent Generator below so tokens never expire.")
        fb_hint.setStyleSheet("font-size: 11px; color: #8B949E;")
        panel_api_layout.addWidget(fb_hint)

        row_fb_app = QHBoxLayout()
        row_fb_app.addWidget(QLabel("App ID:"))
        self.input_fb_app_id = QLineEdit()
        self.input_fb_app_id.setPlaceholderText(
            "Meta App ID (from developers.facebook.com)")
        row_fb_app.addWidget(self.input_fb_app_id, 1)

        row_fb_app.addWidget(QLabel("App Secret:"))
        self.input_fb_app_secret = QLineEdit()
        self.input_fb_app_secret.setEchoMode(QLineEdit.Password)
        self.input_fb_app_secret.setPlaceholderText("Meta App Secret")
        row_fb_app.addWidget(self.input_fb_app_secret, 1)

        btn_sec_toggle = QPushButton("👁")
        btn_sec_toggle.setFixedWidth(30)
        btn_sec_toggle.clicked.connect(
            lambda: self._toggle_echo_mode(self.input_fb_app_secret))
        row_fb_app.addWidget(btn_sec_toggle)
        panel_api_layout.addLayout(row_fb_app)

        row_fb1 = QHBoxLayout()
        row_fb1.addWidget(QLabel("Page ID:"))
        self.input_fb_page_id = QLineEdit()
        self.input_fb_page_id.setPlaceholderText("e.g. 100083928172635")
        row_fb1.addWidget(self.input_fb_page_id, 1)

        row_fb1.addWidget(QLabel("Page Name:"))
        self.input_fb_page_name = QLineEdit()
        self.input_fb_page_name.setPlaceholderText("Auto-populated on test")
        self.input_fb_page_name.setReadOnly(True)
        row_fb1.addWidget(self.input_fb_page_name, 1)
        panel_api_layout.addLayout(row_fb1)

        row_fb2 = QHBoxLayout()
        row_fb2.addWidget(QLabel("Page Access Token:"))
        self.input_fb_page_token = QLineEdit()
        self.input_fb_page_token.setEchoMode(QLineEdit.Password)
        self.input_fb_page_token.setPlaceholderText(
            "EAAG... (Page Access Token with pages_manage_posts permission)")
        row_fb2.addWidget(self.input_fb_page_token, 1)

        btn_fb_toggle = QPushButton("👁")
        btn_fb_toggle.setFixedWidth(30)
        btn_fb_toggle.clicked.connect(
            lambda: self._toggle_echo_mode(self.input_fb_page_token))
        row_fb2.addWidget(btn_fb_toggle)
        panel_api_layout.addLayout(row_fb2)

        # Token Health & Lifespan Row
        row_fb_health = QHBoxLayout()
        lbl_h_title = QLabel("Token Health:")
        lbl_h_title.setStyleSheet("font-weight: bold; font-size: 11px;")
        row_fb_health.addWidget(lbl_h_title)

        self.lbl_fb_token_health = QLabel(
            "⚪ Not checked (click Test or Generate Permanent)")
        self.lbl_fb_token_health.setStyleSheet(
            "font-size: 11px; color: #8B949E;")
        row_fb_health.addWidget(self.lbl_fb_token_health, 1)
        panel_api_layout.addLayout(row_fb_health)

        # Facebook Actions Row
        row_fb_btns = QHBoxLayout()
        self.btn_fb_test = QPushButton("🔍 Test Connection & Lifespan")
        self.btn_fb_test.setObjectName("secondaryBtn")
        self.btn_fb_test.clicked.connect(self._test_facebook_connection)

        self.btn_fb_gen_permanent = QPushButton(
            "⚡ 1-Click Generate Permanent Token")
        self.btn_fb_gen_permanent.setObjectName("primaryBtn")
        self.btn_fb_gen_permanent.setToolTip(
            "Exchanges user token for a permanent Page Token that NEVER expires")
        self.btn_fb_gen_permanent.clicked.connect(
            self._open_permanent_token_dialog)

        self.btn_fb_fetch_pages = QPushButton("📋 Fetch Pages")
        self.btn_fb_fetch_pages.setObjectName("secondaryBtn")
        self.btn_fb_fetch_pages.clicked.connect(
            self._fetch_user_facebook_pages)

        self.btn_fb_guide = QPushButton("📖 Solutions Guide")
        self.btn_fb_guide.setObjectName("secondaryBtn")
        self.btn_fb_guide.clicked.connect(self._open_facebook_guide_dialog)

        self.lbl_fb_status = QLabel("⚪ Not checked")
        self.lbl_fb_status.setStyleSheet("font-size: 11px;")

        row_fb_btns.addWidget(self.btn_fb_test)
        row_fb_btns.addWidget(self.btn_fb_gen_permanent)
        row_fb_btns.addWidget(self.btn_fb_fetch_pages)
        row_fb_btns.addWidget(self.btn_fb_guide)
        row_fb_btns.addWidget(self.lbl_fb_status)
        row_fb_btns.addStretch()
        panel_api_layout.addLayout(row_fb_btns)

        gb_fb_layout.addWidget(self.panel_fb_api)

        # ── PANEL 2: Browser Automation Mode ──────────────────────────────
        self.panel_fb_browser = QWidget()
        panel_browser_layout = QVBoxLayout(self.panel_fb_browser)
        panel_browser_layout.setContentsMargins(0, 4, 0, 0)
        panel_browser_layout.setSpacing(8)

        browser_hint = QLabel(
            "Upload videos using your logged-in Google Chrome profile via Meta Business Suite.<br>"
            "<span style='color:#39D353;'><b>Zero Developer App, Zero App Review, and Zero API Token required!</b></span>"
        )
        browser_hint.setStyleSheet("font-size: 11px; color: #8B949E;")
        panel_browser_layout.addWidget(browser_hint)

        row_br_asset = QHBoxLayout()
        row_br_asset.addWidget(QLabel("Target Page / Asset ID:"))
        self.input_fb_browser_asset_id = QLineEdit()
        self.input_fb_browser_asset_id.setPlaceholderText(
            f"e.g. {DEFAULT_ASSET_ID}")
        self.input_fb_browser_asset_id.setToolTip(
            "Facebook Page ID or Meta Business Suite Asset ID where bulk videos and reels will be uploaded")
        self.input_fb_browser_asset_id.textChanged.connect(
            lambda: self._save_accounts_data(show_msg=False))
        row_br_asset.addWidget(self.input_fb_browser_asset_id, 1)
        panel_browser_layout.addLayout(row_br_asset)

        row_br_prof = QHBoxLayout()
        row_br_prof.addWidget(QLabel("Chrome Profile:"))
        self.cmb_fb_browser_profile = QComboBox()
        self.cmb_fb_browser_profile.setToolTip(
            "Select the Chrome profile that is logged into your Facebook account")
        row_br_prof.addWidget(self.cmb_fb_browser_profile, 1)

        self.btn_refresh_chrome_profiles = QPushButton("🔄 Refresh Profiles")
        self.btn_refresh_chrome_profiles.setObjectName("secondaryBtn")
        self.btn_refresh_chrome_profiles.clicked.connect(
            self._refresh_chrome_profiles_ui)
        row_br_prof.addWidget(self.btn_refresh_chrome_profiles)
        panel_browser_layout.addLayout(row_br_prof)

        row_br_actions = QHBoxLayout()
        self.btn_fb_launch_chrome = QPushButton(
            "🔑 Open Chrome to Log In / Check Session")
        self.btn_fb_launch_chrome.setObjectName("primaryBtn")
        self.btn_fb_launch_chrome.setToolTip(
            "Opens Meta Business Suite Composer in Chrome with this profile so you can log in")
        self.btn_fb_launch_chrome.clicked.connect(
            self._launch_chrome_for_facebook)
        row_br_actions.addWidget(self.btn_fb_launch_chrome)

        self.chk_fb_browser_headless = QCheckBox("Run Headless (Background)")
        self.chk_fb_browser_headless.setToolTip(
            "When checked, uploads run silently in the background without opening a browser window")
        self.chk_fb_browser_headless.toggled.connect(
            lambda: self._save_accounts_data(show_msg=False))
        row_br_actions.addWidget(self.chk_fb_browser_headless)
        row_br_actions.addStretch()
        panel_browser_layout.addLayout(row_br_actions)

        row_br_engine = QHBoxLayout()
        self.lbl_fb_engine_status = QLabel("Automation Engine: Checking...")
        self.lbl_fb_engine_status.setStyleSheet(
            "font-size: 11px; color: #8B949E;")
        row_br_engine.addWidget(self.lbl_fb_engine_status)

        self.btn_fb_install_engine = QPushButton("📦 1-Click Install Engine")
        self.btn_fb_install_engine.setObjectName("secondaryBtn")
        self.btn_fb_install_engine.clicked.connect(
            self._install_playwright_engine)
        row_br_engine.addWidget(self.btn_fb_install_engine)

        self.btn_fb_browser_guide = QPushButton("📖 Browser Guide")
        self.btn_fb_browser_guide.setObjectName("secondaryBtn")
        self.btn_fb_browser_guide.clicked.connect(
            self._open_facebook_guide_dialog)
        row_br_engine.addWidget(self.btn_fb_browser_guide)

        self.lbl_fb_browser_status = QLabel("⚪ Ready")
        self.lbl_fb_browser_status.setStyleSheet("font-size: 11px;")
        row_br_engine.addWidget(self.lbl_fb_browser_status)
        row_br_engine.addStretch()
        panel_browser_layout.addLayout(row_br_engine)

        gb_fb_layout.addWidget(self.panel_fb_browser)

        layout.addWidget(gb_fb)

        # ── 2. YouTube Channel Setup Card ────────────────────────────────────
        gb_yt = QGroupBox(
            "▶️ YouTube Channel Configuration (Google OAuth 2.0)")
        gb_yt_layout = QVBoxLayout(gb_yt)
        gb_yt_layout.setSpacing(8)

        yt_hint = QLabel(
            "Enter your Google Cloud OAuth 2.0 Client credentials, then click 'Sign in with Google' to authorize.")
        yt_hint.setStyleSheet("font-size: 11px; color: #8B949E;")
        gb_yt_layout.addWidget(yt_hint)

        row_yt1 = QHBoxLayout()
        row_yt1.addWidget(QLabel("Client ID:"))
        self.input_yt_client_id = QLineEdit()
        self.input_yt_client_id.setPlaceholderText(
            "...apps.googleusercontent.com")
        row_yt1.addWidget(self.input_yt_client_id, 1)

        row_yt1.addWidget(QLabel("Client Secret:"))
        self.input_yt_client_secret = QLineEdit()
        self.input_yt_client_secret.setEchoMode(QLineEdit.Password)
        row_yt1.addWidget(self.input_yt_client_secret, 1)

        btn_yt_toggle = QPushButton("👁")
        btn_yt_toggle.setFixedWidth(30)
        btn_yt_toggle.clicked.connect(
            lambda: self._toggle_echo_mode(self.input_yt_client_secret))
        row_yt1.addWidget(btn_yt_toggle)
        gb_yt_layout.addLayout(row_yt1)

        row_yt2 = QHBoxLayout()
        row_yt2.addWidget(QLabel("Channel Title:"))
        self.input_yt_channel_title = QLineEdit()
        self.input_yt_channel_title.setPlaceholderText(
            "Auto-populated after authorization")
        self.input_yt_channel_title.setReadOnly(True)
        row_yt2.addWidget(self.input_yt_channel_title, 1)

        row_yt2.addWidget(QLabel("Refresh Token:"))
        self.input_yt_refresh_token = QLineEdit()
        self.input_yt_refresh_token.setEchoMode(QLineEdit.Password)
        self.input_yt_refresh_token.setPlaceholderText("Stored securely")
        row_yt2.addWidget(self.input_yt_refresh_token, 1)
        gb_yt_layout.addLayout(row_yt2)

        # YouTube Actions Row
        row_yt_btns = QHBoxLayout()
        self.btn_yt_login = QPushButton("🔑 Sign in with Google (OAuth2)")
        self.btn_yt_login.setObjectName("primaryBtn")
        self.btn_yt_login.clicked.connect(self._start_youtube_oauth)

        self.btn_yt_test = QPushButton("🔍 Test YouTube Connection")
        self.btn_yt_test.setObjectName("secondaryBtn")
        self.btn_yt_test.clicked.connect(self._test_youtube_connection)

        self.lbl_yt_status = QLabel("⚪ Not checked")
        self.lbl_yt_status.setStyleSheet("font-size: 11px;")

        row_yt_btns.addWidget(self.btn_yt_login)
        row_yt_btns.addWidget(self.btn_yt_test)
        row_yt_btns.addWidget(self.lbl_yt_status)
        row_yt_btns.addStretch()
        gb_yt_layout.addLayout(row_yt_btns)

        layout.addWidget(gb_yt)

        # ── 3. TikTok Setup Card ─────────────────────────────────────────────
        gb_tt = QGroupBox("🎵 TikTok Configuration (Content Posting API v2)")
        gb_tt_layout = QVBoxLayout(gb_tt)
        gb_tt_layout.setSpacing(8)

        tt_hint = QLabel(
            "Enter your TikTok Developer Access Token (with video.publish or video.upload permissions).")
        tt_hint.setStyleSheet("font-size: 11px; color: #8B949E;")
        gb_tt_layout.addWidget(tt_hint)

        row_tt1 = QHBoxLayout()
        row_tt1.addWidget(QLabel("Access Token:"))
        self.input_tt_access_token = QLineEdit()
        self.input_tt_access_token.setEchoMode(QLineEdit.Password)
        self.input_tt_access_token.setPlaceholderText(
            "act.example_tiktok_access_token...")
        row_tt1.addWidget(self.input_tt_access_token, 1)

        btn_tt_toggle = QPushButton("👁")
        btn_tt_toggle.setFixedWidth(30)
        btn_tt_toggle.clicked.connect(
            lambda: self._toggle_echo_mode(self.input_tt_access_token))
        row_tt1.addWidget(btn_tt_toggle)
        gb_tt_layout.addLayout(row_tt1)

        row_tt2 = QHBoxLayout()
        row_tt2.addWidget(QLabel("Creator Nickname:"))
        self.input_tt_creator = QLineEdit()
        self.input_tt_creator.setPlaceholderText("Auto-populated on test")
        self.input_tt_creator.setReadOnly(True)
        row_tt2.addWidget(self.input_tt_creator, 1)

        self.btn_tt_test = QPushButton("🔍 Test TikTok Connection")
        self.btn_tt_test.setObjectName("secondaryBtn")
        self.btn_tt_test.clicked.connect(self._test_tiktok_connection)
        row_tt2.addWidget(self.btn_tt_test)

        self.lbl_tt_status = QLabel("⚪ Not checked")
        self.lbl_tt_status.setStyleSheet("font-size: 11px;")
        row_tt2.addWidget(self.lbl_tt_status)
        row_tt2.addStretch()
        gb_tt_layout.addLayout(row_tt2)

        layout.addWidget(gb_tt)

        # Save Button
        btn_save_accounts = QPushButton("💾 Save All Accounts & Settings")
        btn_save_accounts.setObjectName("primaryBtn")
        btn_save_accounts.setFixedHeight(36)
        btn_save_accounts.clicked.connect(self._save_accounts_data)
        layout.addWidget(btn_save_accounts)

        layout.addStretch()
        scroll.setWidget(container)

        tab_layout = QVBoxLayout(self.tab_accounts)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3: PUBLISHING HISTORY
    # ─────────────────────────────────────────────────────────────────────────

    def _build_history_tab(self):
        layout = QVBoxLayout(self.tab_history)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Header bar
        hist_header = QHBoxLayout()
        hist_header.addWidget(QLabel("Past Video Publishing Records:"))
        hist_header.addStretch()

        btn_refresh_hist = QPushButton("🔄 Refresh")
        btn_refresh_hist.setObjectName("secondaryBtn")
        btn_refresh_hist.clicked.connect(self._populate_history_table)
        hist_header.addWidget(btn_refresh_hist)

        btn_clear_hist = QPushButton("🗑 Clear History")
        btn_clear_hist.setObjectName("dangerBtn")
        btn_clear_hist.clicked.connect(self._clear_history)
        hist_header.addWidget(btn_clear_hist)

        layout.addLayout(hist_header)

        # History Table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(5)
        self.history_table.setHorizontalHeaderLabels(
            ["Date / Time", "Video Name", "Title", "Platforms & Results", "Actions"])
        self.history_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeToContents)
        self.history_table.setAlternatingRowColors(True)
        layout.addWidget(self.history_table, 1)

    # ─────────────────────────────────────────────────────────────────────────
    # LOGIC & EVENTS
    # ─────────────────────────────────────────────────────────────────────────

    def _toggle_echo_mode(self, line_edit: QLineEdit):
        if line_edit.echoMode() == QLineEdit.Password:
            line_edit.setEchoMode(QLineEdit.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.Password)

    def _append_hashtag(self, tag: str):
        cur = self.desc_input.toPlainText()
        if tag not in cur:
            sep = " " if cur and not cur.endswith(
                " ") and not cur.endswith("\n") else ""
            self.desc_input.setPlainText(cur + sep + tag)

    def _update_title_counter(self, text: str):
        cnt = len(text)
        self.title_counter_lbl.setText(f"{cnt} / 100")
        if cnt > 100:
            self.title_counter_lbl.setStyleSheet(
                "font-size: 10px; color: #F85149; font-weight: bold;")
        else:
            self.title_counter_lbl.setStyleSheet(
                "font-size: 10px; color: #8B949E;")

    def _browse_video(self):
        filters = "Video Files (*.mp4 *.mov *.mkv *.avi *.webm *.flv *.wmv);;All Files (*.*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Video to Post", "", filters)
        if file_path:
            self.set_selected_video(file_path)

    def _browse_folder(self):
        last_dir = get_last_selected_folder() or ""
        folder = QFileDialog.getExistingDirectory(
            self, "Select Folder with Videos to Auto-Post", last_dir)
        if folder:
            save_last_selected_folder(folder)
            self.set_selected_folder(folder)

    def _use_active_project_video(self):
        parent = self.parent()
        candidate = None
        if parent:
            candidate = getattr(parent, "_last_exported_video", None) or getattr(
                parent, "video_path", None)
        if candidate and os.path.exists(candidate):
            self.set_selected_video(candidate)
        else:
            QMessageBox.information(
                self,
                "No Active Video",
                "No video is currently loaded or exported in the main dubber window.\nPlease browse a video file or folder manually."
            )

    def set_selected_video(self, video_path: str):
        self.is_folder_mode = False
        self.folder_queue = [video_path]
        self.selected_folder = ""
        self.folder_queue_badge.setText("")
        self.folder_queue_lbl.setVisible(False)
        self.video_path_input.setText(video_path)
        self._update_publish_button_text()

        meta = probe_video_meta(video_path)
        sz_str = format_file_size(meta["size"])
        dur_str = f"{int(meta['duration'] // 60):02d}:{int(meta['duration'] % 60):02d}"
        res_str = f"{meta['width']}x{meta['height']}" if meta["width"] else "Unknown Res"
        shorts_flag = "📱 Vertical / Shorts detected" if meta["is_shorts"] else "🖥 Standard Widescreen"

        self.video_meta_lbl.setText(
            f"📊 Size: <b>{sz_str}</b> | Duration: <b>{dur_str}</b> | Resolution: <b>{res_str}</b> | <b>{shorts_flag}</b>"
        )

        # Pre-fill title if empty
        if not self.title_input.text().strip():
            stem = os.path.splitext(os.path.basename(video_path))[0]
            self.title_input.setText(stem)

        # Auto-recommend #Shorts or #Reels if vertical video
        if meta["is_shorts"]:
            cur_desc = self.desc_input.toPlainText()
            if "#shorts" not in cur_desc.lower():
                self._append_hashtag("#shorts")
            if "#reels" not in cur_desc.lower():
                self._append_hashtag("#reels")

        self._auto_fetch_fb_options()

    def set_selected_folder(self, folder_path: str):
        if not folder_path or not os.path.isdir(folder_path):
            return

        videos = scan_folder_videos(folder_path)
        if not videos:
            QMessageBox.warning(
                self,
                "No Videos Found",
                f"No video files (.mp4, .mov, .mkv, .webm, etc.) found in:\n{folder_path}"
            )
            return

        self.selected_folder = folder_path
        self.folder_queue = videos
        self.is_folder_mode = True
        self.video_path_input.setText(folder_path)

        total_size = sum(os.path.getsize(v)
                         for v in videos if os.path.exists(v))
        sz_str = format_file_size(total_size)
        v_count = len(videos)

        self.video_meta_lbl.setText(
            f"📂 Folder: <b>{os.path.basename(folder_path)}</b> | Videos: <b>{v_count}</b> | Total Size: <b>{sz_str}</b>"
        )
        self.folder_queue_badge.setText(f"Batch Queue: {v_count} Video(s)")

        # Show queue preview
        preview_names = [os.path.basename(v) for v in videos[:4]]
        preview_str = ", ".join(preview_names)
        if v_count > 4:
            preview_str += f", and {v_count - 4} more..."

        self._update_publish_button_text()

        # Check for config.txt in the folder
        cfg_info = parse_folder_config(folder_path)
        if cfg_info["found"] and (cfg_info["title"] or cfg_info["description"] or cfg_info.get("playlist")):
            if cfg_info["title"]:
                self.title_input.setText(cfg_info["title"])
            if cfg_info["description"]:
                self.desc_input.setPlainText(cfg_info["description"])
            if cfg_info.get("playlist"):
                self.cmb_fb_playlist.setEditText(cfg_info["playlist"])
            self.video_meta_lbl.setText(
                self.video_meta_lbl.text() +
                " | <span style='color:#39D353;'>✅ config.txt loaded (Auto-Combines Episode)</span>"
            )
        else:
            # Prompt user to input Title and Description once for all videos
            dlg = BatchMetadataDialog(folder_path, v_count, parent=self)
            self._apply_dialog_theme_to_widget(dlg)
            if dlg.exec_() == QDialog.Accepted:
                if dlg.applied_title:
                    self.title_input.setText(dlg.applied_title)
                if dlg.applied_description:
                    self.desc_input.setPlainText(dlg.applied_description)
                if dlg.applied_playlist:
                    self.cmb_fb_playlist.setEditText(dlg.applied_playlist)
                self.video_meta_lbl.setText(
                    self.video_meta_lbl.text() +
                    " | <span style='color:#58A6FF;'>📝 Applied metadata to all</span>"
                )

        # Update queue preview with episode title format preview
        base_t = self.title_input.text().strip() or (cfg_info.get("title", "").strip())
        sample_title = build_bulk_video_title(
            base_t, videos[0], 1) if videos else ""
        title_preview = f"<br><span style='color:#58A6FF; font-size:11px;'><b>Episode Title Format:</b> <code>{sample_title}</code></span>" if sample_title else ""
        self.folder_queue_lbl.setText(
            f"<b>Queued Videos:</b> {preview_str}{title_preview}")
        self.folder_queue_lbl.setVisible(True)

        self._auto_fetch_fb_options()

    def _update_publish_button_text(self):
        if not hasattr(self, "btn_publish") or not self.btn_publish:
            return
        if self.upload_worker and self.upload_worker.isRunning():
            return

        status_idx = self.cmb_fb_publish.currentIndex(
        ) if hasattr(self, "cmb_fb_publish") else 0
        if self.is_folder_mode and len(self.folder_queue) > 1:
            cnt = len(self.folder_queue)
            if status_idx == 1:
                self.btn_publish.setText(
                    f"🕒 Schedule {cnt} Videos Publicly on Facebook / Socials")
            elif status_idx == 2:
                self.btn_publish.setText(
                    f"📝 Save {cnt} Videos as Draft on Facebook / Socials")
            else:
                self.btn_publish.setText(
                    f"🚀 Auto Post {cnt} Videos Immediately to Facebook / Socials")
        else:
            if status_idx == 1:
                self.btn_publish.setText("🕒 Schedule Public Post")
            elif status_idx == 2:
                self.btn_publish.setText("📝 Save as Draft")
            else:
                self.btn_publish.setText("🚀 Publish Immediately")

    def _update_schedule_preview_label(self):
        """Update live human-readable schedule preview badge and alert if under 10m."""
        if not hasattr(self, "dt_fb_schedule") or not hasattr(self, "lbl_schedule_preview"):
            return
        selected_dt = self.dt_fb_schedule.dateTime()
        now_dt = QDateTime.currentDateTime()
        secs_diff = now_dt.secsTo(selected_dt)

        if secs_diff < 600:
            self.lbl_schedule_preview.setText(
                "⚠️ Selected time is under 10 minutes in the future (Graph API minimum is 10m)!")
            self.lbl_schedule_preview.setStyleSheet(
                "font-size: 11px; font-weight: bold; color: #F85149; padding: 5px 8px; background: rgba(248, 81, 73, 0.12); border-radius: 6px; border: 1px solid rgba(248, 81, 73, 0.3);")
            return

        mins_total = secs_diff // 60
        days = mins_total // 1440
        hours = (mins_total % 1440) // 60
        mins = mins_total % 60
        rel_parts = []
        if days > 0:
            rel_parts.append(f"{days}d")
        if hours > 0:
            rel_parts.append(f"{hours}h")
        rel_parts.append(f"{mins}m")
        rel_str = " ".join(rel_parts)

        dt_str = selected_dt.toString("ddd, MMM d, yyyy 'at' hh:mm AP")
        self.lbl_schedule_preview.setText(
            f"🕒 Will publish: {dt_str} (in {rel_str})")
        self.lbl_schedule_preview.setStyleSheet(
            "font-size: 11px; font-weight: 500; color: #58A6FF; padding: 5px 8px; background: rgba(88, 166, 255, 0.08); border-radius: 6px; border: 1px solid rgba(88, 166, 255, 0.2);")

    def _on_schedule_datetime_changed(self, dt: QDateTime):
        self._update_schedule_preview_label()

    def _on_fb_publish_status_changed(self, index: int):
        is_schedule = (index == 1)
        self.fb_schedule_container.setVisible(is_schedule)
        if is_schedule:
            min_dt = QDateTime.currentDateTime().addSecs(660)
            self.dt_fb_schedule.setMinimumDateTime(min_dt)
            if self.dt_fb_schedule.dateTime() < min_dt:
                self.dt_fb_schedule.setDateTime(
                    QDateTime.currentDateTime().addSecs(3600))
            self._update_schedule_preview_label()
        self._update_publish_button_text()

    def _apply_schedule_offset(self, seconds: int):
        min_dt = QDateTime.currentDateTime().addSecs(660)
        self.dt_fb_schedule.setMinimumDateTime(min_dt)
        new_dt = QDateTime.currentDateTime().addSecs(seconds)
        if new_dt < min_dt:
            new_dt = min_dt
        self.dt_fb_schedule.setDateTime(new_dt)
        self._update_schedule_preview_label()

    def _apply_schedule_target_time(self, days_ahead: int, hour: int, minute: int = 0):
        target_date = QDate.currentDate().addDays(days_ahead)
        target_dt = QDateTime(target_date, QTime(hour, minute))
        min_dt = QDateTime.currentDateTime().addSecs(660)
        self.dt_fb_schedule.setMinimumDateTime(min_dt)
        if target_dt < min_dt:
            target_dt = QDateTime(target_date.addDays(1), QTime(hour, minute))
        self.dt_fb_schedule.setDateTime(target_dt)
        self._update_schedule_preview_label()

    def _apply_schedule_tomorrow_9am(self):
        self._apply_schedule_target_time(1, 9, 0)

    def _apply_schedule_tomorrow_6pm(self):
        self._apply_schedule_target_time(1, 18, 0)

    def _apply_schedule_tomorrow_8pm(self):
        self._apply_schedule_target_time(1, 20, 0)

    def _apply_schedule_reset_1h(self):
        self._apply_schedule_offset(3600)

    def _apply_dialog_theme_to_widget(self, widget: QWidget):
        """Apply main stylesheet to a sub-dialog."""
        if widget and self.styleSheet():
            widget.setStyleSheet(self.styleSheet())

    def _fetch_facebook_playlists(self):
        """Query Facebook Page video playlists asynchronously via Graph API."""
        fb = get_facebook_config()
        page_id = (self.input_fb_page_id.text().strip() if hasattr(self, "input_fb_page_id")
                   and self.input_fb_page_id.text().strip() else fb.get("page_id", "").strip())
        page_token = (self.input_fb_page_token.text().strip() if hasattr(self, "input_fb_page_token")
                      and self.input_fb_page_token.text().strip() else fb.get("page_token", "").strip())

        if not page_id or not page_token:
            QMessageBox.information(
                self,
                "Facebook Credentials Missing",
                "Please configure and save your Facebook Page ID and Page Access Token in the 'Accounts & API Setup' tab first."
            )
            return

        self.btn_refresh_fb_playlists.setEnabled(False)
        self.btn_refresh_fb_playlists.setText("⏳")
        self._on_log_message(
            "INFO", "Fetching playlists from Facebook Graph API...")

        user_tok = (self.input_fb_user_token.text().strip() if hasattr(self, "input_fb_user_token")
                    and self.input_fb_user_token.text().strip() else fb.get("user_token", "").strip())
        self._pl_worker = FacebookPlaylistsWorker(
            page_id, page_token, user_token=user_tok, parent=self)
        self._pl_worker.success_sig.connect(self._on_playlists_fetched)
        self._pl_worker.error_sig.connect(self._on_playlists_error)
        self._pl_worker.start()

    def _on_playlists_fetched(self, playlists: list):
        self.btn_refresh_fb_playlists.setEnabled(True)
        self.btn_refresh_fb_playlists.setText("🔄")

        cur_data = self.cmb_fb_playlist.currentData() or self.cmb_fb_playlist.currentText()
        self.cmb_fb_playlist.clear()
        self.cmb_fb_playlist.addItem("(None - Do not add)", "")
        matched_idx = 0
        for i, pl in enumerate(playlists, 1):
            badge = " [✏️ Custom]" if pl.get("custom") else ""
            display = f"📁 {pl['title']}{badge} ({pl['id']})"
            self.cmb_fb_playlist.addItem(display, pl["id"])
            if pl["id"] == cur_data or pl["title"] in cur_data or pl["id"] in cur_data:
                matched_idx = i

        self.cmb_fb_playlist.setCurrentIndex(matched_idx)
        if len(playlists) > 0:
            self._on_log_message(
                "SUCCESS", f"Loaded {len(playlists)} Facebook playlist(s).")
        else:
            self._on_log_message(
                "INFO", "Connected to Facebook Page, but 0 playlists found. (Create playlists in Meta Business Suite > Content > Playlists).")
        save_facebook_config({"cached_playlists": playlists[:50]})

    def _on_playlists_error(self, err: str):
        self.btn_refresh_fb_playlists.setEnabled(True)
        self.btn_refresh_fb_playlists.setText("🔄")
        self._on_log_message("WARN", f"Could not load playlists: {err}")
        QMessageBox.information(
            self,
            "Facebook Playlists Notice",
            f"Could not retrieve video playlists from Facebook Page:\n{err}\n\n"
            "Tips:\n"
            "1. Make sure you are using a Page Access Token with 'pages_read_engagement' permission.\n"
            "2. If no playlists exist yet, create one under Meta Business Suite > Content > Playlists.\n"
            "3. You can also type or paste your Playlist ID directly into the playlist box."
        )

    def _fetch_facebook_groups(self):
        """Query Facebook groups accessible with user/page token asynchronously."""
        fb = get_facebook_config()
        page_id = (self.input_fb_page_id.text().strip() if hasattr(self, "input_fb_page_id")
                   and self.input_fb_page_id.text().strip() else fb.get("page_id", "").strip())
        page_tok = (self.input_fb_page_token.text().strip() if hasattr(self, "input_fb_page_token")
                    and self.input_fb_page_token.text().strip() else fb.get("page_token", "").strip())
        user_tok = (self.input_fb_user_token.text().strip() if hasattr(self, "input_fb_user_token")
                    and self.input_fb_user_token.text().strip() else fb.get("user_token", "").strip())

        token = page_tok or user_tok
        if not token:
            QMessageBox.information(
                self,
                "Facebook Token Missing",
                "Please configure your Page Access Token or User Token in the 'Accounts & API Setup' tab first."
            )
            return

        self.btn_refresh_fb_groups.setEnabled(False)
        self.btn_refresh_fb_groups.setText("⏳")
        self._on_log_message(
            "INFO", "Fetching all available Facebook groups via Graph API...")

        self._grp_worker = FacebookGroupsWorker(
            token, page_id=page_id, user_token=user_tok, parent=self)
        self._grp_worker.success_sig.connect(self._on_groups_fetched)
        self._grp_worker.error_sig.connect(self._on_groups_error)
        self._grp_worker.start()

    def _on_groups_fetched(self, groups: list):
        self.btn_refresh_fb_groups.setEnabled(True)
        self.btn_refresh_fb_groups.setText("🔄")
        self._all_available_groups = groups

        cur_data = self.cmb_fb_group.currentData() or self.cmb_fb_group.currentText()
        self.cmb_fb_group.clear()
        self.cmb_fb_group.addItem("(None - Do not share)", "")
        matched_idx = 0
        for i, grp in enumerate(groups, 1):
            badge = " [⭐ Admin]" if grp.get("administrator") else ""
            if grp.get("custom"):
                badge += " [✏️ Custom]"
            display = f"{grp['name']}{badge} ({grp['id']})"
            self.cmb_fb_group.addItem(display, grp["id"])
            if grp["id"] == cur_data or grp["id"] in self._selected_group_ids:
                matched_idx = i

        if len(self._selected_group_ids) > 1:
            self.cmb_fb_group.setEditText(
                f"👥 {len(self._selected_group_ids)} Groups Selected")
        else:
            self.cmb_fb_group.setCurrentIndex(matched_idx)

        self._on_log_message(
            "SUCCESS", f"Loaded {len(groups)} Facebook group(s).")
        save_facebook_config({"cached_groups": groups[:100]})

    def _on_groups_error(self, err: str):
        self.btn_refresh_fb_groups.setEnabled(True)
        self.btn_refresh_fb_groups.setText("🔄")
        self._on_log_message("WARN", f"Could not load groups: {err}")
        if "user_managed_groups" in err.lower() or "permission" in err.lower():
            QMessageBox.information(
                self,
                "Facebook Groups Notice",
                "Meta Graph API requires the 'user_managed_groups' permission to list groups automatically.\n\n"
                "You can still easily share videos to any group by clicking '👥 Select...' -> '➕ Add Group (ID or URL)' and pasting the group link or ID!"
            )
        else:
            QMessageBox.warning(
                self,
                "Fetch Groups Notice",
                f"Could not query Facebook groups via API:\n{err}\n\nYou can manually add Group IDs or URLs via '👥 Select...' -> '➕ Add Group (ID or URL)'."
            )

    def _open_facebook_group_selector(self):
        """Open modal dialog to filter, select, and manage multiple Facebook Groups."""
        fb = get_facebook_config()
        cached = fb.get("cached_groups", [])
        custom = fb.get("custom_groups", [])
        merged_groups = list(
            self._all_available_groups) if self._all_available_groups else []

        for grp in cached + custom:
            gid = str(grp.get("id"))
            if not any(str(g.get("id")) == gid for g in merged_groups):
                merged_groups.append(grp)

        self._all_available_groups = merged_groups

        # Trigger background fetch if credentials exist and no groups yet
        page_tok = (self.input_fb_page_token.text().strip() if hasattr(self, "input_fb_page_token")
                    and self.input_fb_page_token.text().strip() else fb.get("page_token", "").strip())
        user_tok = (self.input_fb_user_token.text().strip() if hasattr(self, "input_fb_user_token")
                    and self.input_fb_user_token.text().strip() else fb.get("user_token", "").strip())
        if not self._all_available_groups and (page_tok or user_tok):
            self._fetch_facebook_groups()

        dlg = FacebookGroupSelectorDialog(
            parent=self,
            groups=self._all_available_groups,
            selected_ids=self._selected_group_ids,
        )
        self._apply_dialog_theme_to_widget(dlg)
        if dlg.exec_() == QDialog.Accepted:
            selected_items = dlg.get_selected_groups()
            self._selected_group_ids = [g["id"] for g in selected_items]
            self._selected_group_names = [g["name"] for g in selected_items]

            if not self._selected_group_ids:
                self.cmb_fb_group.setCurrentIndex(0)
            elif len(self._selected_group_ids) == 1:
                gid = self._selected_group_ids[0]
                idx = self.cmb_fb_group.findData(gid)
                if idx >= 0:
                    self.cmb_fb_group.setCurrentIndex(idx)
                else:
                    gname = self._selected_group_names[0] if self._selected_group_names else gid
                    self.cmb_fb_group.setEditText(f"{gname} ({gid})")
            else:
                self.cmb_fb_group.setEditText(
                    f"👥 {len(self._selected_group_ids)} Groups Selected")

            self._save_accounts_data(show_msg=False)

    def _on_fb_group_combo_changed(self, index: int):
        if index == 0:
            if len(self._selected_group_ids) <= 1:
                self._selected_group_ids = []
                self._selected_group_names = []
        else:
            gid = self.cmb_fb_group.currentData()
            txt = self.cmb_fb_group.currentText()
            if gid and not str(gid).startswith("👥") and not str(gid).startswith("(None"):
                self._selected_group_ids = [str(gid)]
                self._selected_group_names = [txt]

    def _auto_fetch_fb_options(self):
        """Silently populate Facebook playlists and groups if configured."""
        fb = get_facebook_config()
        # Restore cached playlists first
        cached_pls = fb.get("cached_playlists", [])
        if cached_pls and self.cmb_fb_playlist.count() <= 1:
            for pl in cached_pls:
                self.cmb_fb_playlist.addItem(
                    f"📁 {pl['title']} ({pl['id']})", pl["id"])
        elif fb.get("page_id") and fb.get("page_token") and self.cmb_fb_playlist.count() <= 1:
            try:
                self._fetch_facebook_playlists()
            except Exception:
                pass

        # Restore cached groups
        cached_grps = fb.get("cached_groups", [])
        if cached_grps:
            self._all_available_groups = cached_grps
            if self.cmb_fb_group.count() <= 1:
                for grp in cached_grps:
                    badge = " [⭐ Admin]" if grp.get("administrator") else ""
                    self.cmb_fb_group.addItem(
                        f"{grp['name']}{badge} ({grp['id']})", grp["id"])
        elif (fb.get("user_token") or fb.get("page_token")) and self.cmb_fb_group.count() <= 1:
            try:
                self._fetch_facebook_groups()
            except Exception:
                pass

    def _on_video_path_changed(self, path: str):
        path = path.strip()
        if os.path.isdir(path):
            self.set_selected_folder(path)
        elif os.path.isfile(path):
            self.set_selected_video(path)

    def _load_saved_data(self):
        """Populate input fields from saved config."""
        fb = get_facebook_config()
        self.input_fb_app_id.setText(fb.get("app_id", ""))
        self.input_fb_app_secret.setText(fb.get("app_secret", ""))
        self.input_fb_page_id.setText(fb.get("page_id", ""))
        self.input_fb_page_name.setText(fb.get("page_name", ""))
        self.input_fb_page_token.setText(fb.get("page_token", ""))
        self.chk_fb_disable_caption.setChecked(
            bool(fb.get("disable_caption", False)))
        if hasattr(self, "chk_fb_closed_caption"):
            self.chk_fb_closed_caption.setChecked(
                bool(fb.get("closed_caption_enabled", True)))
        if hasattr(self, "cmb_fb_caption_locale"):
            saved_loc = fb.get("closed_caption_locale", "en_US")
            loc_idx = self.cmb_fb_caption_locale.findData(saved_loc)
            if loc_idx >= 0:
                self.cmb_fb_caption_locale.setCurrentIndex(loc_idx)
            else:
                self.cmb_fb_caption_locale.setEditText(saved_loc)
        if fb.get("token_status"):
            self.lbl_fb_token_health.setText(fb.get("token_status"))
            if "Permanent" in fb.get("token_status"):
                self.lbl_fb_token_health.setStyleSheet(
                    "font-size: 11px; color: #39D353; font-weight: bold;")

        # Browser Automation options
        self._refresh_chrome_profiles_ui()
        saved_prof = fb.get("browser_profile", "Default")
        idx = self.cmb_fb_browser_profile.findData(saved_prof)
        if idx >= 0:
            self.cmb_fb_browser_profile.setCurrentIndex(idx)
        self.chk_fb_browser_headless.setChecked(
            bool(fb.get("browser_headless", False)))

        # Target Page / Asset ID for Browser Automation
        saved_asset = fb.get("browser_asset_id") or fb.get(
            "page_id") or DEFAULT_ASSET_ID
        if saved_asset == "12345":
            saved_asset = DEFAULT_ASSET_ID
        self.input_fb_browser_asset_id.setText(saved_asset)

        self._check_playwright_engine()

        # Mode Selection
        post_method = fb.get("post_method", "graph_api")
        if post_method == "browser":
            self.rb_fb_mode_browser.setChecked(True)
        else:
            self.rb_fb_mode_api.setChecked(True)
        self._on_fb_mode_changed()

        # Facebook Status & Schedule
        pub_status = fb.get("publish_status", "publish_now")
        if pub_status == "schedule":
            self.cmb_fb_publish.setCurrentIndex(1)
        elif pub_status == "draft":
            self.cmb_fb_publish.setCurrentIndex(2)
        else:
            self.cmb_fb_publish.setCurrentIndex(0)
        self.fb_schedule_container.setVisible(pub_status == "schedule")

        sched_time_str = fb.get("schedule_time", "")
        if sched_time_str:
            saved_dt = QDateTime.fromString(sched_time_str, "yyyy-MM-dd HH:mm")
            if saved_dt.isValid() and saved_dt > QDateTime.currentDateTime().addSecs(660):
                self.dt_fb_schedule.setDateTime(saved_dt)
            else:
                self.dt_fb_schedule.setDateTime(
                    QDateTime.currentDateTime().addSecs(3600))
        else:
            self.dt_fb_schedule.setDateTime(
                QDateTime.currentDateTime().addSecs(3600))
        self._update_schedule_preview_label()

        interval_val = fb.get("schedule_interval_minutes", 60)
        try:
            self.spin_fb_schedule_interval.setValue(int(interval_val))
        except Exception:
            self.spin_fb_schedule_interval.setValue(60)

        # Pre-select playlist and group if saved
        saved_pl = fb.get("playlist_id", "")
        if saved_pl and self.cmb_fb_playlist.findData(saved_pl) >= 0:
            self.cmb_fb_playlist.setCurrentIndex(
                self.cmb_fb_playlist.findData(saved_pl))
        elif saved_pl:
            self.cmb_fb_playlist.setEditText(saved_pl)

        # Selected groups
        self._selected_group_ids = list(fb.get("selected_group_ids", []))
        self._selected_group_names = list(fb.get("selected_group_names", []))
        saved_grp = fb.get("group_id", "")
        if len(self._selected_group_ids) > 1:
            self.cmb_fb_group.setEditText(
                f"👥 {len(self._selected_group_ids)} Groups Selected")
        elif len(self._selected_group_ids) == 1:
            idx = self.cmb_fb_group.findData(self._selected_group_ids[0])
            if idx >= 0:
                self.cmb_fb_group.setCurrentIndex(idx)
            else:
                gname = self._selected_group_names[0] if self._selected_group_names else self._selected_group_ids[0]
                self.cmb_fb_group.setEditText(
                    f"{gname} ({self._selected_group_ids[0]})")
        elif saved_grp:
            if self.cmb_fb_group.findData(saved_grp) >= 0:
                self.cmb_fb_group.setCurrentIndex(
                    self.cmb_fb_group.findData(saved_grp))
            else:
                self.cmb_fb_group.setEditText(saved_grp)

        self._update_publish_button_text()

        yt = get_youtube_config()
        self.input_yt_client_id.setText(yt.get("client_id", ""))
        self.input_yt_client_secret.setText(yt.get("client_secret", ""))
        self.input_yt_refresh_token.setText(yt.get("refresh_token", ""))
        self.input_yt_channel_title.setText(yt.get("channel_title", ""))

        tt = get_tiktok_config()
        self.input_tt_access_token.setText(tt.get("access_token", ""))
        self.input_tt_creator.setText(tt.get("creator_name", ""))

        defaults = get_social_defaults()
        self.chk_fb.setChecked(defaults.get("post_facebook", True))
        self.chk_yt.setChecked(defaults.get("post_youtube", True))
        self.chk_tt.setChecked(defaults.get("post_tiktok", True))

        self._update_badges()
        self._populate_history_table()

    def _save_accounts_data(self, show_msg: bool = True):
        """Save account fields into .app_config.json."""
        raw_asset_id = (
            self.input_fb_browser_asset_id.text().strip()
            if hasattr(self, "input_fb_browser_asset_id") else ""
        )
        if not raw_asset_id or raw_asset_id == "12345":
            raw_asset_id = DEFAULT_ASSET_ID

        status_idx = self.cmb_fb_publish.currentIndex(
        ) if hasattr(self, "cmb_fb_publish") else 0
        if status_idx == 1:
            pub_status = "schedule"
        elif status_idx == 2:
            pub_status = "draft"
        else:
            pub_status = "publish_now"

        fb_data = {
            "post_method": "browser" if self.rb_fb_mode_browser.isChecked() else "graph_api",
            "browser_profile": self.cmb_fb_browser_profile.currentData() or self.cmb_fb_browser_profile.currentText() or "Default",
            "browser_headless": self.chk_fb_browser_headless.isChecked(),
            "browser_asset_id": raw_asset_id,
            "app_id": self.input_fb_app_id.text().strip(),
            "app_secret": self.input_fb_app_secret.text().strip(),
            "page_id": raw_asset_id if self.rb_fb_mode_browser.isChecked() else (self.input_fb_page_id.text().strip() or raw_asset_id),
            "page_name": self.input_fb_page_name.text().strip(),
            "page_token": self.input_fb_page_token.text().strip(),
            "token_status": self.lbl_fb_token_health.text().strip(),
            "publish_status": pub_status,
            "published": (status_idx == 0),
            "schedule_time": self.dt_fb_schedule.dateTime().toString("yyyy-MM-dd HH:mm") if hasattr(self, "dt_fb_schedule") else "",
            "schedule_interval_minutes": self.spin_fb_schedule_interval.value() if hasattr(self, "spin_fb_schedule_interval") else 60,
            "selected_group_ids": list(self._selected_group_ids),
            "selected_group_names": list(self._selected_group_names),
            "disable_caption": self.chk_fb_disable_caption.isChecked(),
            "closed_caption_enabled": self.chk_fb_closed_caption.isChecked() if hasattr(self, "chk_fb_closed_caption") else True,
            "closed_caption_locale": (self.cmb_fb_caption_locale.currentData() or self.cmb_fb_caption_locale.currentText().strip()) if hasattr(self, "cmb_fb_caption_locale") else "en_US",
        }
        if hasattr(self, "_all_available_groups") and self._all_available_groups:
            fb_data["cached_groups"] = self._all_available_groups[:100]

        pl_data = self.cmb_fb_playlist.currentData(
        ) or self.cmb_fb_playlist.currentText().strip()
        if pl_data and not str(pl_data).startswith("(None"):
            fb_data["playlist_id"] = pl_data
            fb_data["playlist_title"] = self.cmb_fb_playlist.currentText().strip()
        grp_data = self.cmb_fb_group.currentData(
        ) or self.cmb_fb_group.currentText().strip()
        if grp_data and not str(grp_data).startswith("(None") and not str(grp_data).startswith("👥"):
            fb_data["group_id"] = grp_data
            fb_data["group_name"] = self.cmb_fb_group.currentText().strip()
        elif len(self._selected_group_ids) == 1:
            fb_data["group_id"] = self._selected_group_ids[0]
            fb_data["group_name"] = self._selected_group_names[0] if self._selected_group_names else self._selected_group_ids[0]

        save_facebook_config(fb_data)

        save_youtube_config({
            "client_id": self.input_yt_client_id.text().strip(),
            "client_secret": self.input_yt_client_secret.text().strip(),
            "refresh_token": self.input_yt_refresh_token.text().strip(),
            "channel_title": self.input_yt_channel_title.text().strip(),
        })

        save_tiktok_config({
            "access_token": self.input_tt_access_token.text().strip(),
            "creator_name": self.input_tt_creator.text().strip(),
        })

        self._update_publish_mode_display()
        self._update_badges()
        if show_msg:
            QMessageBox.information(
                self, "Saved", "All account credentials have been saved securely.")

    def _update_badges(self):
        fb = get_facebook_config()
        yt = get_youtube_config()
        tt = get_tiktok_config()

        if fb.get("post_method") == "browser":
            prof = fb.get("browser_profile") or "Default"
            short_p = prof.split(" — ")[0]
            self.badge_fb.setText(f"🌐 FB: {short_p[:12]}")
            self.badge_fb.setStyleSheet(
                "background: rgba(46, 160, 67, 0.25); color: #39D353; border-radius: 6px; padding: 4px 8px; font-size: 11px;")
        elif fb.get("page_id") and fb.get("page_token"):
            name = fb.get("page_name") or fb.get("page_id")
            self.badge_fb.setText(f"📘 FB: {name[:12]}")
            self.badge_fb.setStyleSheet(
                "background: rgba(24, 119, 242, 0.25); color: #58A6FF; border-radius: 6px; padding: 4px 8px; font-size: 11px;")
        else:
            self.badge_fb.setText("📘 FB: Setup Needed")
            self.badge_fb.setStyleSheet(
                "background: rgba(255,255,255,0.08); color: #8B949E; border-radius: 6px; padding: 4px 8px; font-size: 11px;")

        if yt.get("refresh_token") or yt.get("access_token"):
            name = yt.get("channel_title") or "Authorized"
            self.badge_yt.setText(f"▶️ YT: {name[:12]}")
            self.badge_yt.setStyleSheet(
                "background: rgba(255, 0, 0, 0.25); color: #F85149; border-radius: 6px; padding: 4px 8px; font-size: 11px;")
        else:
            self.badge_yt.setText("▶️ YT: Setup Needed")
            self.badge_yt.setStyleSheet(
                "background: rgba(255,255,255,0.08); color: #8B949E; border-radius: 6px; padding: 4px 8px; font-size: 11px;")

        if tt.get("access_token"):
            name = tt.get("creator_name") or "Connected"
            self.badge_tt.setText(f"🎵 TT: {name[:12]}")
            self.badge_tt.setStyleSheet(
                "background: rgba(37, 244, 238, 0.25); color: #39D353; border-radius: 6px; padding: 4px 8px; font-size: 11px;")
        else:
            self.badge_tt.setText("🎵 TT: Setup Needed")
            self.badge_tt.setStyleSheet(
                "background: rgba(255,255,255,0.08); color: #8B949E; border-radius: 6px; padding: 4px 8px; font-size: 11px;")

    def _on_fb_mode_changed(self):
        is_api = self.rb_fb_mode_api.isChecked()
        self.panel_fb_api.setVisible(is_api)
        self.panel_fb_browser.setVisible(not is_api)
        self._update_publish_mode_display()

    def _update_publish_mode_display(self):
        if not hasattr(self, "lbl_fb_mode_active"):
            return
        if self.rb_fb_mode_browser.isChecked():
            prof = self.cmb_fb_browser_profile.currentText() or "Default"
            short_prof = prof.split(" — ")[0]
            self.lbl_fb_mode_active.setText(f"Mode: 🌐 Browser ({short_prof})")
            self.lbl_fb_mode_active.setStyleSheet(
                "font-size: 11px; font-weight: bold; color: #39D353;")
        else:
            page_name = self.input_fb_page_name.text().strip() or "Graph API"
            self.lbl_fb_mode_active.setText(
                f"Mode: 🚀 Graph API ({page_name[:15]})")
            self.lbl_fb_mode_active.setStyleSheet(
                "font-size: 11px; font-weight: bold; color: #58A6FF;")

    def _refresh_chrome_profiles_ui(self):
        """Populate the Chrome profile combo box with discovered local profiles."""
        cur_selected = self.cmb_fb_browser_profile.currentData()
        self.cmb_fb_browser_profile.clear()
        profiles = list_chrome_profiles()
        for p in profiles:
            self.cmb_fb_browser_profile.addItem(p["name"], p["key"])

        target = cur_selected or get_facebook_config().get("browser_profile", "Default")
        idx = self.cmb_fb_browser_profile.findData(target)
        if idx >= 0:
            self.cmb_fb_browser_profile.setCurrentIndex(idx)
        try:
            self.cmb_fb_browser_profile.currentIndexChanged.disconnect(
                self._on_facebook_profile_changed)
        except Exception:
            pass
        self.cmb_fb_browser_profile.currentIndexChanged.connect(
            self._on_facebook_profile_changed)
        self._check_facebook_session_status()

    def _on_facebook_profile_changed(self):
        self._check_facebook_session_status()
        try:
            self._save_accounts_data(show_msg=False)
        except Exception:
            pass

    def _check_facebook_session_status(self):
        """Check if the selected Chrome profile has an active Facebook session saved."""
        prof_key = self.cmb_fb_browser_profile.currentData() or "Default"
        poster = FacebookBrowserPoster(profile_name=prof_key)
        info = poster.check_session_status()
        if info.get("logged_in"):
            uid = info.get("user_id") or "Active"
            self.lbl_fb_browser_status.setText(
                f"🟢 Session: Logged In (UID: {uid})")
            self.lbl_fb_browser_status.setStyleSheet(
                "font-size: 11px; color: #39D353; font-weight: bold;")
        elif info.get("cookies_count", 0) > 0:
            self.lbl_fb_browser_status.setText(
                f"🟡 Saved Session ({info['cookies_count']} cookies)")
            self.lbl_fb_browser_status.setStyleSheet(
                "font-size: 11px; color: #E3B341;")
        else:
            self.lbl_fb_browser_status.setText(
                "⚪ No Session (Click 'Open Chrome to Log In')")
            self.lbl_fb_browser_status.setStyleSheet(
                "font-size: 11px; color: #8B949E;")

    def _launch_chrome_for_facebook(self):
        """Launch dedicated Chrome session for Facebook login using Playwright."""
        prof_key = self.cmb_fb_browser_profile.currentData() or "Default"
        self.btn_fb_launch_chrome.setEnabled(False)
        self.btn_fb_launch_chrome.setText("⏳ Browser Open (Logging In...)")
        self.lbl_fb_browser_status.setText(
            "🌐 Browser window opening for login...")
        self.lbl_fb_browser_status.setStyleSheet(
            "font-size: 11px; color: #58A6FF;")

        self.login_worker = FacebookLoginWorker(
            profile_name=prof_key, parent=self)
        self.login_worker.status_updated.connect(
            lambda msg: self.lbl_fb_browser_status.setText(f"⏳ {msg[:40]}..."))
        self.login_worker.login_finished.connect(
            self._on_facebook_login_finished)
        self.login_worker.login_failed.connect(self._on_facebook_login_failed)
        self.login_worker.start()

    def _on_facebook_login_finished(self, res: dict):
        self.btn_fb_launch_chrome.setEnabled(True)
        self.btn_fb_launch_chrome.setText(
            "🔑 Open Chrome to Log In / Check Session")
        self._check_facebook_session_status()
        prof_name = self.cmb_fb_browser_profile.currentText()
        if res.get("logged_in"):
            QMessageBox.information(
                self,
                "Facebook Session Verified",
                f"✅ Facebook session successfully saved and verified for profile:\n<b>{prof_name}</b>\n\n"
                f"UID: {res.get('user_id')}\n\n"
                f"You can now publish single videos and bulk reels without having to log in again!"
            )
        else:
            QMessageBox.information(
                self,
                "Browser Session Closed",
                f"Browser session closed for profile:\n<b>{prof_name}</b>\n\n"
                f"Status: {res.get('status_text', 'Closed')}\n"
                f"If you need to log in or refresh your session, you can click this button again anytime."
            )

    def _on_facebook_login_failed(self, err_msg: str):
        self.btn_fb_launch_chrome.setEnabled(True)
        self.btn_fb_launch_chrome.setText(
            "🔑 Open Chrome to Log In / Check Session")
        self.lbl_fb_browser_status.setText("🔴 Failed to launch Chrome session")
        self.lbl_fb_browser_status.setStyleSheet(
            "font-size: 11px; color: #F85149;")
        QMessageBox.critical(self, "Login Session Error",
                             f"Could not launch browser login session:\n{err_msg}")

    def _check_playwright_engine(self):
        if is_playwright_ready():
            self.lbl_fb_engine_status.setText("Automation Engine: 🟢 Ready")
            self.lbl_fb_engine_status.setStyleSheet(
                "font-size: 11px; color: #39D353; font-weight: bold;")
            self.btn_fb_install_engine.setText("🔄 Check Engine")
        else:
            self.lbl_fb_engine_status.setText(
                "Automation Engine: ⚠️ Not Installed")
            self.lbl_fb_engine_status.setStyleSheet(
                "font-size: 11px; color: #E3B341; font-weight: bold;")
            self.btn_fb_install_engine.setText("📦 1-Click Install Engine")

    def _install_playwright_engine(self):
        self.lbl_fb_engine_status.setText(
            "Automation Engine: ⏳ Installing Playwright & Chromium...")
        self.lbl_fb_engine_status.setStyleSheet(
            "font-size: 11px; color: #58A6FF;")
        self.btn_fb_install_engine.setEnabled(False)
        QApplication.processEvents()

        def cb(msg):
            self._on_log_message("INFO", msg)
            QApplication.processEvents()

        ok = install_playwright(callback=cb)
        self.btn_fb_install_engine.setEnabled(True)
        if ok and is_playwright_ready():
            self._check_playwright_engine()
            QMessageBox.information(
                self, "Installation Succeeded", "Playwright automation engine is now ready to use!")
        else:
            self.lbl_fb_engine_status.setText(
                "Automation Engine: 🔴 Installation Failed (Check Log)")
            self.lbl_fb_engine_status.setStyleSheet(
                "font-size: 11px; color: #F85149;")
            QMessageBox.warning(
                self, "Installation Failed",
                "Could not install Playwright automatically. You can run:\n  pip install playwright\n  playwright install chromium\nin your terminal."
            )

    # ── Test Connections ─────────────────────────────────────────────────────

    def _open_permanent_token_dialog(self):
        cur_app_id = self.input_fb_app_id.text().strip()
        cur_app_sec = self.input_fb_app_secret.text().strip()
        dlg = PermanentTokenExchangeDialog(
            self, initial_app_id=cur_app_id, initial_app_secret=cur_app_sec)
        self._apply_dialog_theme_to_widget(dlg)
        if dlg.exec_() == QDialog.Accepted and dlg.selected_page_id and dlg.selected_page_token:
            self.input_fb_app_id.setText(dlg.selected_app_id)
            self.input_fb_app_secret.setText(dlg.selected_app_secret)
            self.input_fb_page_id.setText(dlg.selected_page_id)
            self.input_fb_page_name.setText(dlg.selected_page_name)
            self.input_fb_page_token.setText(dlg.selected_page_token)
            self.lbl_fb_token_health.setText(
                "🟢 Permanent Token (Never expires)")
            self.lbl_fb_token_health.setStyleSheet(
                "font-size: 11px; color: #39D353; font-weight: bold;")
            self.lbl_fb_status.setText(f"🟢 Linked: {dlg.selected_page_name}")
            self.lbl_fb_status.setStyleSheet(
                "color: #39D353; font-size: 11px;")
            self._save_accounts_data(show_msg=False)
            try:
                self._fetch_facebook_playlists()
                self._fetch_facebook_groups()
            except Exception:
                pass
            QMessageBox.information(
                self, "Permanent Token Applied",
                f"Successfully saved Permanent Page Token for:\n<b>{dlg.selected_page_name}</b>\n\nThis token will NEVER expire!"
            )

    def _open_facebook_guide_dialog(self):
        dlg = FacebookGuideDialog(self)
        self._apply_dialog_theme_to_widget(dlg)
        dlg.exec_()

    def _test_facebook_connection(self):
        page_id = self.input_fb_page_id.text().strip()
        token = self.input_fb_page_token.text().strip()
        app_id = self.input_fb_app_id.text().strip()
        app_secret = self.input_fb_app_secret.text().strip()

        if not page_id or not token:
            QMessageBox.warning(
                self, "Missing Info", "Please enter both Facebook Page ID and Page Access Token.")
            return

        self.lbl_fb_status.setText("⏳ Testing connection...")
        self.lbl_fb_token_health.setText("⏳ Inspecting token...")
        QApplication.processEvents()

        try:
            info = FacebookUploader.test_connection(page_id, token)
            page_name = info.get("name", "Unknown Page")
            self.input_fb_page_name.setText(page_name)
            self.lbl_fb_status.setText(
                f"🟢 Connected: <b>{page_name}</b> ({info.get('fans', 0)} fans)")
            self.lbl_fb_status.setStyleSheet(
                "color: #39D353; font-size: 11px;")

            # Inspect token lifespan and scopes
            try:
                insp = FacebookUploader.inspect_token(
                    token, app_id, app_secret)
                lbl = insp.get("status_label", "Checked")
                if insp.get("is_permanent"):
                    color = "#39D353"
                elif insp.get("remaining_seconds", 0) > 86400:
                    color = "#E3B341"
                else:
                    color = "#F85149"
                missing = insp.get("missing_scopes", [])
                if missing:
                    lbl += f" (⚠️ Missing scopes: {', '.join(missing)})"
                self.lbl_fb_token_health.setText(lbl)
                self.lbl_fb_token_health.setStyleSheet(
                    f"font-size: 11px; color: {color}; font-weight: bold;")
            except Exception as ie:
                self.lbl_fb_token_health.setText(
                    f"Connected (lifespan check skipped: {ie})")
                self.lbl_fb_token_health.setStyleSheet(
                    "font-size: 11px; color: #8B949E;")

            self._save_accounts_data(show_msg=False)
            try:
                self._fetch_facebook_playlists()
                self._fetch_facebook_groups()
            except Exception:
                pass
        except Exception as e:
            self.lbl_fb_status.setText(f"🔴 Error: {str(e)[:45]}")
            self.lbl_fb_status.setStyleSheet(
                "color: #F85149; font-size: 11px;")
            self.lbl_fb_token_health.setText("🔴 Connection failed")
            self.lbl_fb_token_health.setStyleSheet(
                "font-size: 11px; color: #F85149;")
            QMessageBox.critical(
                self, "Facebook Connection Failed", f"Could not connect to Facebook Page:\n{e}")

    def _fetch_user_facebook_pages(self):
        token = self.input_fb_page_token.text().strip()
        if not token:
            QMessageBox.warning(
                self, "Missing Token", "Please paste your User Access Token in the Token field first.")
            return

        try:
            pages = FacebookUploader.fetch_user_pages(token)
            if not pages:
                QMessageBox.information(
                    self, "No Pages Found", "No managed Facebook Pages found for this user token.")
                return

            items = [f"{p['name']} (ID: {p['id']})" for p in pages]
            choice, ok = QInputDialog.getItem(
                self, "Select Managed Page", "Choose a Page to link:", items, 0, False)
            if ok and choice:
                idx = items.index(choice)
                sel_page = pages[idx]
                self.input_fb_page_id.setText(sel_page["id"])
                self.input_fb_page_name.setText(sel_page["name"])
                if sel_page.get("access_token"):
                    self.input_fb_page_token.setText(sel_page["access_token"])
                self.lbl_fb_status.setText(f"🟢 Linked: {sel_page['name']}")
                self._save_accounts_data(show_msg=False)
                try:
                    self._fetch_facebook_playlists()
                    self._fetch_facebook_groups()
                except Exception:
                    pass
        except Exception as e:
            QMessageBox.critical(self, "Failed to Fetch Pages", str(e))

    def _start_youtube_oauth(self):
        client_id = self.input_yt_client_id.text().strip()
        client_secret = self.input_yt_client_secret.text().strip()
        if not client_id or not client_secret:
            QMessageBox.warning(self, "Missing Credentials",
                                "Please enter both Google Client ID and Client Secret first.")
            return

        self.lbl_yt_status.setText("⏳ Opening browser for Google login...")
        QApplication.processEvents()

        try:
            tokens = YouTubeUploader.start_oauth_flow(client_id, client_secret)
            self.input_yt_refresh_token.setText(
                tokens.get("refresh_token", ""))
            self.input_yt_channel_title.setText(
                tokens.get("channel_title", ""))
            self.lbl_yt_status.setText(
                f"🟢 Authorized: <b>{tokens.get('channel_title', 'Channel')}</b>")
            self.lbl_yt_status.setStyleSheet(
                "color: #39D353; font-size: 11px;")
            self._save_accounts_data(show_msg=False)
            QMessageBox.information(
                self, "YouTube Connected", f"Successfully authorized channel:\n{tokens.get('channel_title')}")
        except Exception as e:
            self.lbl_yt_status.setText("🔴 OAuth Cancelled / Failed")
            self.lbl_yt_status.setStyleSheet(
                "color: #F85149; font-size: 11px;")
            QMessageBox.critical(self, "Google Authorization Failed", str(e))

    def _test_youtube_connection(self):
        yt_cfg = get_youtube_config()
        client_id = self.input_yt_client_id.text().strip() or yt_cfg.get("client_id")
        client_secret = self.input_yt_client_secret.text(
        ).strip() or yt_cfg.get("client_secret")
        refresh_token = self.input_yt_refresh_token.text(
        ).strip() or yt_cfg.get("refresh_token")

        if not refresh_token:
            QMessageBox.warning(self, "Not Authorized",
                                "Please sign in with Google (OAuth2) first.")
            return

        self.lbl_yt_status.setText("⏳ Verifying YouTube connection...")
        QApplication.processEvents()

        try:
            access_token = YouTubeUploader.refresh_access_token(
                client_id, client_secret, refresh_token)
            info = YouTubeUploader.test_connection(access_token)
            ch_title = info.get("title", "YouTube Channel")
            self.input_yt_channel_title.setText(ch_title)
            self.lbl_yt_status.setText(
                f"🟢 Connected: <b>{ch_title}</b> ({info.get('subscribers', '0')} subs)")
            self.lbl_yt_status.setStyleSheet(
                "color: #39D353; font-size: 11px;")
            self._save_accounts_data(show_msg=False)
        except Exception as e:
            self.lbl_yt_status.setText(f"🔴 Error: {str(e)[:45]}")
            self.lbl_yt_status.setStyleSheet(
                "color: #F85149; font-size: 11px;")
            QMessageBox.critical(self, "YouTube Test Failed", str(e))

    def _test_tiktok_connection(self):
        token = self.input_tt_access_token.text().strip()
        if not token:
            QMessageBox.warning(self, "Missing Token",
                                "Please enter your TikTok Access Token.")
            return

        self.lbl_tt_status.setText("⏳ Testing TikTok connection...")
        QApplication.processEvents()

        try:
            info = TikTokUploader.test_connection(token)
            nickname = info.get("creator_nickname", "TikTok Creator")
            self.input_tt_creator.setText(nickname)
            self.lbl_tt_status.setText(f"🟢 Connected: <b>{nickname}</b>")
            self.lbl_tt_status.setStyleSheet(
                "color: #39D353; font-size: 11px;")
            self._save_accounts_data(show_msg=False)
        except Exception as e:
            self.lbl_tt_status.setText(f"🔴 Error: {str(e)[:45]}")
            self.lbl_tt_status.setStyleSheet(
                "color: #F85149; font-size: 11px;")
            QMessageBox.critical(self, "TikTok Test Failed", str(e))

    # ── Upload Execution ─────────────────────────────────────────────────────

    def _start_publishing(self):
        if self.is_folder_mode and self.folder_queue:
            video_queue = [v for v in self.folder_queue if os.path.exists(v)]
        else:
            raw_path = self.video_path_input.text().strip()
            if os.path.isdir(raw_path):
                video_queue = scan_folder_videos(raw_path)
            elif os.path.isfile(raw_path):
                video_queue = [raw_path]
            else:
                video_queue = []

        if not video_queue:
            QMessageBox.warning(
                self, "Missing Video", "Please select a valid video file or folder with videos first.")
            return

        platforms = []
        if self.chk_fb.isChecked():
            platforms.append("facebook")
        if self.chk_yt.isChecked():
            platforms.append("youtube")
        if self.chk_tt.isChecked():
            platforms.append("tiktok")

        if not platforms:
            QMessageBox.warning(
                self, "No Platform", "Please select at least one platform to publish to.")
            return

        # Prepare metadata
        title = self.title_input.text().strip()
        desc = self.desc_input.toPlainText().strip()
        words = (title + " " + desc).split()
        tags = [w.lstrip("#") for w in words if w.startswith("#")]

        # Facebook specific parameters
        pl_data = self.cmb_fb_playlist.currentData(
        ) or self.cmb_fb_playlist.currentText().strip()
        if str(pl_data).startswith("(None"):
            pl_data = ""
        grp_data = self.cmb_fb_group.currentData(
        ) or self.cmb_fb_group.currentText().strip()
        if str(grp_data).startswith("(None"):
            grp_data = ""

        fb_status_idx = self.cmb_fb_publish.currentIndex(
        ) if hasattr(self, "cmb_fb_publish") else 0
        if fb_status_idx == 1:
            fb_publish_status = "schedule"
            fb_published = False
            qdt = self.dt_fb_schedule.dateTime()
            min_qdt = QDateTime.currentDateTime().addSecs(660)
            if qdt < min_qdt:
                qdt = min_qdt
                self.dt_fb_schedule.setDateTime(qdt)
            fb_schedule_ts = int(qdt.toSecsSinceEpoch())
        elif fb_status_idx == 2:
            fb_publish_status = "draft"
            fb_published = False
            fb_schedule_ts = None
        else:
            fb_publish_status = "publish_now"
            fb_published = True
            fb_schedule_ts = None

        target_group_ids = list(self._selected_group_ids)
        typed_grp = self.cmb_fb_group.currentText().strip()
        if typed_grp and not typed_grp.startswith("👥") and not typed_grp.startswith("(None"):
            for gid in parse_facebook_group_identifier(typed_grp):
                if gid not in target_group_ids:
                    target_group_ids.append(gid)
        elif grp_data and grp_data not in target_group_ids and not str(grp_data).startswith("👥") and not str(grp_data).startswith("(None"):
            target_group_ids.append(grp_data)

        caption_loc = self.cmb_fb_caption_locale.currentData() or self.cmb_fb_caption_locale.currentText(
        ).strip() if hasattr(self, "cmb_fb_caption_locale") else "en_US"

        metadata = {
            "title": title,
            "description": desc,
            "tags": tags,
            "yt_privacy": self.cmb_yt_privacy.currentText(),
            "yt_category": "22",
            "yt_made_for_kids": self.chk_yt_kids.isChecked(),
            "tt_privacy": self.cmb_tt_privacy.currentText(),
            "tt_allow_comment": self.chk_tt_comments.isChecked(),
            "tt_allow_duet": True,
            "tt_allow_stitch": True,
            "fb_published": fb_published,
            "fb_publish_status": fb_publish_status,
            "fb_schedule_timestamp": fb_schedule_ts,
            "fb_schedule_interval_minutes": self.spin_fb_schedule_interval.value() if hasattr(self, "spin_fb_schedule_interval") else 60,
            "fb_disable_caption": self.chk_fb_disable_caption.isChecked(),
            "fb_closed_caption": self.chk_fb_closed_caption.isChecked() if hasattr(self, "chk_fb_closed_caption") else True,
            "fb_caption_locale": caption_loc,
            "fb_playlist_id": pl_data,
            "fb_group_id": grp_data,
            "fb_group_ids": target_group_ids,
            "asset_id": (
                self.input_fb_browser_asset_id.text().strip()
                if hasattr(self, "input_fb_browser_asset_id") and self.input_fb_browser_asset_id.text().strip() and self.input_fb_browser_asset_id.text().strip() != "12345"
                else DEFAULT_ASSET_ID
            ),
        }

        # Pre-flight Facebook Browser Session Validation
        if self.chk_fb.isChecked() and self.rb_fb_mode_browser.isChecked():
            self._save_accounts_data(show_msg=False)
            current_prof = self.cmb_fb_browser_profile.currentData() or "Default"
            cur_poster = FacebookBrowserPoster(profile_name=current_prof)
            cur_status = cur_poster.check_session_status()

            if not cur_status.get("logged_in"):
                profiles = list_chrome_profiles()
                auth_profile = None
                for p in profiles:
                    pk = p["key"]
                    if pk != current_prof:
                        p_check = FacebookBrowserPoster(
                            profile_name=pk).check_session_status()
                        if p_check.get("logged_in"):
                            auth_profile = {
                                "key": pk, "name": p["name"], "uid": p_check.get("user_id")}
                            break

                if auth_profile:
                    msg_box = QMessageBox(self)
                    msg_box.setIcon(QMessageBox.Question)
                    msg_box.setWindowTitle("Facebook Session Validation")
                    msg_box.setText(
                        f"Selected Chrome Profile '<b>{current_prof}</b>' is not logged into Facebook.\n\n"
                        f"However, profile '<b>{auth_profile['name']}</b>' has an active verified session (UID: {auth_profile['uid']}).\n\n"
                        f"Would you like to switch to '<b>{auth_profile['key']}</b>' and publish now?"
                    )
                    btn_switch = msg_box.addButton(
                        f"Switch to '{auth_profile['key']}' & Publish", QMessageBox.AcceptRole)
                    btn_login = msg_box.addButton(
                        "Open Chrome to Log In", QMessageBox.ActionRole)
                    btn_cancel = msg_box.addButton(
                        "Cancel", QMessageBox.RejectRole)
                    msg_box.setDefaultButton(btn_switch)
                    self._apply_dialog_theme_to_widget(msg_box)
                    msg_box.exec_()

                    clicked = msg_box.clickedButton()
                    if clicked == btn_switch:
                        idx = self.cmb_fb_browser_profile.findData(
                            auth_profile["key"])
                        if idx >= 0:
                            self.cmb_fb_browser_profile.setCurrentIndex(idx)
                        self._save_accounts_data(show_msg=False)
                    elif clicked == btn_login:
                        self._launch_chrome_for_facebook()
                        return
                    else:
                        return
                else:
                    ans = QMessageBox.question(
                        self,
                        "Facebook Login Required",
                        f"Chrome Profile '<b>{current_prof}</b>' is not logged into Facebook.\n\n"
                        f"Browser automation requires an active Facebook session.\n\n"
                        f"Would you like to open Chrome now to log in?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.Yes,
                    )
                    if ans == QMessageBox.Yes:
                        self._launch_chrome_for_facebook()
                    return

        # Gather credentials
        credentials = {
            "facebook": get_facebook_config(),
            "youtube": get_youtube_config(),
            "tiktok": get_tiktok_config(),
        }

        # Reset Progress Bars & Logs
        self.bar_fb.setValue(0)
        self.bar_yt.setValue(0)
        self.bar_tt.setValue(0)
        self.lbl_fb_bar.setText("📘 Facebook Page: Waiting...")
        self.lbl_yt_bar.setText("▶️ YouTube: Waiting...")
        self.lbl_tt_bar.setText("🎵 TikTok: Waiting...")
        self.log_console.clear()
        self._clear_links_layout()
        self._published_links.clear()

        # Update Buttons state
        self.btn_publish.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        # Launch Worker with batch video queue
        self.upload_worker = SocialUploadWorker(
            video_paths=video_queue,
            platforms=platforms,
            metadata=metadata,
            credentials=credentials,
            parent=self,
        )
        self.upload_worker.platform_started.connect(self._on_platform_started)
        self.upload_worker.platform_progress.connect(
            self._on_platform_progress)
        self.upload_worker.platform_completed.connect(
            self._on_platform_completed)
        self.upload_worker.log_message.connect(self._on_log_message)
        self.upload_worker.video_queue_started.connect(
            self._on_video_queue_started)
        self.upload_worker.video_queue_completed.connect(
            self._on_video_queue_completed)
        self.upload_worker.all_completed.connect(self._on_all_completed)
        self.upload_worker.start()

    def _cancel_publishing(self):
        if self.upload_worker and self.upload_worker.isRunning():
            self.upload_worker.cancel()
            self.btn_cancel.setEnabled(False)

    def _on_video_queue_started(self, idx: int, total: int, fname: str):
        if total > 1:
            self.folder_queue_badge.setText(
                f"Batch Progress: [{idx}/{total}] {fname}")
            self.lbl_fb_bar.setText(
                f"📘 Facebook Page: [{idx}/{total}] Preparing {fname}...")
            self.lbl_yt_bar.setText(
                f"▶️ YouTube: [{idx}/{total}] Preparing...")
            self.lbl_tt_bar.setText(f"🎵 TikTok: [{idx}/{total}] Preparing...")

    def _on_video_queue_completed(self, idx: int, total: int, fname: str, summary: dict):
        if total > 1:
            self.folder_queue_badge.setText(
                f"Completed [{idx}/{total}]: {fname}")

    def _on_platform_started(self, platform: str):
        if platform == "facebook":
            self.lbl_fb_bar.setText("📘 Facebook Page: Uploading...")
            self.bar_fb.setValue(5)
        elif platform == "youtube":
            self.lbl_yt_bar.setText("▶️ YouTube: Uploading...")
            self.bar_yt.setValue(5)
        elif platform == "tiktok":
            self.lbl_tt_bar.setText("🎵 TikTok: Uploading...")
            self.bar_tt.setValue(5)

    def _on_platform_progress(self, platform: str, pct: int, status_text: str):
        if platform == "facebook":
            self.bar_fb.setValue(pct)
            self.lbl_fb_bar.setText(f"📘 Facebook: {status_text}")
        elif platform == "youtube":
            self.bar_yt.setValue(pct)
            self.lbl_yt_bar.setText(f"▶️ YouTube: {status_text}")
        elif platform == "tiktok":
            self.bar_tt.setValue(pct)
            self.lbl_tt_bar.setText(f"🎵 TikTok: {status_text}")

    def _on_platform_completed(self, platform: str, success: bool, message: str, video_url: str):
        bar_map = {"facebook": (self.bar_fb, self.lbl_fb_bar), "youtube": (
            self.bar_yt, self.lbl_yt_bar), "tiktok": (self.bar_tt, self.lbl_tt_bar)}
        bar, lbl = bar_map.get(platform, (None, None))
        if bar and lbl:
            if success:
                bar.setValue(100)
                lbl.setText(f"✅ {platform.capitalize()}: {message}")
                if video_url:
                    self._published_links[platform] = video_url
                    link_lbl = f"🔗 Open {platform.capitalize()} Video"
                    if "scheduled" in str(message).lower():
                        link_lbl = f"📅 View Scheduled {platform.capitalize()} Video"
                    btn_link = QPushButton(link_lbl)
                    btn_link.setObjectName("primaryBtn")
                    btn_link.setStyleSheet(
                        "font-size: 11px; padding: 4px 8px; border-radius: 4px;")
                    btn_link.clicked.connect(
                        lambda _, u=video_url: QDesktopServices.openUrl(QUrl(u)))
                    self.links_layout.addWidget(btn_link)
            else:
                lbl.setText(f"❌ {platform.capitalize()}: {message[:40]}")

    def _on_log_message(self, level: str, text: str):
        ts = time.strftime("%H:%M:%S")
        self.log_console.appendPlainText(f"[{ts}] [{level}] {text}")

    def _on_all_completed(self, summary: dict):
        self.btn_publish.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._update_publish_button_text()

        succ = summary.get("success_count", 0)
        fail = summary.get("fail_count", 0)
        total_vids = summary.get("total_videos", 1)

        # Record history for each video in the batch
        v_results = summary.get("video_results", [])
        if v_results:
            for vr in v_results:
                v_res = vr.get("results", {})
                entry = {
                    "video_name": vr.get("video_name", ""),
                    "video_path": vr.get("video_path", ""),
                    "title": vr.get("title", self.title_input.text().strip()),
                    "platforms": v_res,
                    "links": {p: r.get("url", "") for p, r in v_res.items() if r.get("url")},
                    "success_count": vr.get("success_count", 0),
                    "fail_count": vr.get("fail_count", 0),
                }
                add_upload_history_entry(entry)
        else:
            entry = {
                "video_name": os.path.basename(self.video_path_input.text().strip()),
                "video_path": self.video_path_input.text().strip(),
                "title": self.title_input.text().strip(),
                "platforms": summary.get("results", {}),
                "links": self._published_links,
                "success_count": succ,
                "fail_count": fail,
            }
            add_upload_history_entry(entry)

        self._populate_history_table()

        if total_vids > 1:
            msg = f"Batch Auto-Post Finished!\n\nTotal Videos: {total_vids}\n✅ Successfully Uploaded: {succ}\n❌ Failed / Skipped: {fail}"
        else:
            msg = f"Publishing Finished!\n\n✅ Succeeded: {succ}\n❌ Failed: {fail}"

        if succ > 0:
            QMessageBox.information(self, "Publish Complete", msg)
        else:
            QMessageBox.warning(self, "Publish Notice", msg)

    def _clear_links_layout(self):
        while self.links_layout.count():
            item = self.links_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── History Table ────────────────────────────────────────────────────────

    def _populate_history_table(self):
        history = get_upload_history()
        self.history_table.setRowCount(len(history))
        for row, item in enumerate(history):
            self.history_table.setItem(
                row, 0, QTableWidgetItem(item.get("datetime", "")))
            self.history_table.setItem(
                row, 1, QTableWidgetItem(item.get("video_name", "")))
            self.history_table.setItem(
                row, 2, QTableWidgetItem(item.get("title", "")))

            # Platforms text
            results = item.get("platforms", {})
            parts = []
            for p, res in results.items():
                ok = res.get("success", False)
                symbol = "✅" if ok else "❌"
                parts.append(f"{symbol} {p.capitalize()}")
            self.history_table.setItem(
                row, 3, QTableWidgetItem(", ".join(parts)))

            # Action button for links
            links = item.get("links", {})
            if links:
                first_url = next(iter(links.values()))
                btn_open = QPushButton("🔗 View")
                btn_open.setStyleSheet("font-size: 10px; padding: 2px 6px;")
                btn_open.clicked.connect(
                    lambda _, u=first_url: QDesktopServices.openUrl(QUrl(u)))
                self.history_table.setCellWidget(row, 4, btn_open)
            else:
                self.history_table.setItem(row, 4, QTableWidgetItem("-"))

    def _clear_history(self):
        reply = QMessageBox.question(
            self, "Clear History", "Are you sure you want to clear all past upload records?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            clear_upload_history()
            self._populate_history_table()

    # ── Theme Support (60-30-10 Design System) ────────────────────────────────

    def apply_dialog_theme(self, mode: Optional[str] = None):
        """Apply comprehensive 60-30-10 theme tokens."""
        if mode is None:
            mode = settings_manager.get_theme_mode()

        is_dark = str(mode).strip().lower() == "dark"

        canvas_bg = COLOR_CANVAS if is_dark else LIGHT_COLOR_CANVAS
        surface_bg = COLOR_SURFACE if is_dark else LIGHT_COLOR_SURFACE
        input_bg = COLOR_SURFACE_INPUT if is_dark else LIGHT_COLOR_SURFACE_INPUT
        border_col = COLOR_BORDER if is_dark else LIGHT_COLOR_BORDER
        accent_col = COLOR_ACCENT if is_dark else LIGHT_COLOR_ACCENT
        accent_hover = COLOR_ACCENT_HOVER if is_dark else LIGHT_COLOR_ACCENT_HOVER
        text_primary = COLOR_TEXT_PRIMARY if is_dark else LIGHT_COLOR_TEXT_PRIMARY
        text_secondary = COLOR_TEXT_SECONDARY if is_dark else LIGHT_COLOR_TEXT_SECONDARY
        text_muted = COLOR_TEXT_MUTED if is_dark else LIGHT_COLOR_TEXT_MUTED

        stylesheet = f"""
            QMainWindow, QDialog {{
                background-color: {canvas_bg};
                color: {text_primary};
                font-family: {FONT_FAMILY};
            }}
            QWidget {{
                color: {text_primary};
                font-family: {FONT_FAMILY};
            }}
            QGroupBox {{
                background-color: {surface_bg};
                border: 1px solid {border_col};
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 14px;
                font-weight: bold;
                color: {text_primary};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                color: {accent_col};
            }}
            QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QDateTimeEdit, QDateEdit, QTimeEdit, QSpinBox, QDoubleSpinBox {{
                background-color: {input_bg};
                color: {text_secondary};
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 4px 8px;
            }}
            QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {accent_col};
            }}
            QDateTimeEdit QLineEdit, QSpinBox QLineEdit {{
                background: transparent;
                color: {text_secondary};
                border: none;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QDateTimeEdit::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 26px;
                border-left: 1px solid {border_col};
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background-color: {surface_bg};
            }}
            QDateTimeEdit::drop-down:hover {{
                background-color: {accent_col};
            }}
            QSpinBox::up-button, QSpinBox::down-button, QDateTimeEdit::up-button, QDateTimeEdit::down-button {{
                subcontrol-origin: border;
                width: 18px;
                background-color: {surface_bg};
                border-left: 1px solid {border_col};
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover, QDateTimeEdit::up-button:hover, QDateTimeEdit::down-button:hover {{
                background-color: {accent_hover};
            }}
            QPushButton#primaryBtn {{
                background-color: {accent_col};
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-weight: bold;
            }}
            QPushButton#primaryBtn:hover {{
                background-color: {accent_hover};
            }}
            QPushButton#secondaryBtn {{
                background-color: {surface_bg};
                color: {text_primary};
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton#secondaryBtn:hover {{
                border-color: {accent_col};
                color: {accent_col};
            }}
            QPushButton#dangerBtn {{
                background-color: rgba(248, 81, 73, 0.2);
                color: #F85149;
                border: 1px solid rgba(248, 81, 73, 0.5);
                border-radius: 6px;
                padding: 6px 12px;
            }}
            QPushButton#dangerBtn:hover {{
                background-color: #F85149;
                color: #FFFFFF;
            }}
            QWidget#fb_schedule_container {{
                background-color: {surface_bg};
                border: 1px solid {border_col};
                border-radius: 8px;
                margin-top: 4px;
            }}
            QPushButton.schedulePresetBtn, QPushButton#schedulePresetBtn {{
                background-color: {input_bg};
                color: {text_primary};
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
                font-weight: 500;
            }}
            QPushButton.schedulePresetBtn:hover, QPushButton#schedulePresetBtn:hover {{
                background-color: {accent_col};
                color: #FFFFFF;
                border-color: {accent_col};
            }}
            QPushButton.schedulePresetBtn:pressed, QPushButton#schedulePresetBtn:pressed {{
                background-color: {accent_hover};
                color: #FFFFFF;
            }}
            QProgressBar {{
                background-color: {input_bg};
                border: 1px solid {border_col};
                border-radius: 4px;
                height: 14px;
                text-align: center;
                font-size: 10px;
                color: {text_primary};
            }}
            QProgressBar::chunk {{
                background-color: {accent_col};
                border-radius: 3px;
            }}
            QTabWidget::pane {{
                border: 1px solid {border_col};
                background-color: {canvas_bg};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background-color: {surface_bg};
                color: {text_muted};
                border: 1px solid {border_col};
                border-bottom: none;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: {canvas_bg};
                color: {accent_col};
                border-bottom: 2px solid {accent_col};
                font-weight: bold;
            }}
            QTableWidget {{
                background-color: {surface_bg};
                border: 1px solid {border_col};
                border-radius: 6px;
                gridline-color: {border_col};
            }}
            QHeaderView::section {{
                background-color: {surface_bg};
                color: {text_primary};
                border: 1px solid {border_col};
                padding: 4px;
                font-weight: bold;
            }}
            QCheckBox {{
                spacing: 6px;
                color: {text_primary};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 3px;
                border: 1px solid {border_col};
                background: {input_bg};
            }}
            QCheckBox::indicator:checked {{
                background: {accent_col};
                border-color: {accent_col};
            }}
        """
        self.setStyleSheet(stylesheet)
        self._update_badges()

        # Apply comprehensive dark/light theme to popup calendar widget
        if hasattr(self, "dt_fb_schedule") and self.dt_fb_schedule:
            cal = self.dt_fb_schedule.calendarWidget()
            if cal:
                cal.setStyleSheet(f"""
                    QCalendarWidget {{
                        background-color: {canvas_bg};
                        color: {text_primary};
                        border: 1px solid {border_col};
                        border-radius: 8px;
                    }}
                    QCalendarWidget QWidget#qt_calendar_navigationbar {{
                        background-color: {surface_bg};
                        border-bottom: 1px solid {border_col};
                    }}
                    QCalendarWidget QTableView#qt_calendar_calendarview {{
                        background-color: {canvas_bg};
                        color: {text_primary};
                        selection-background-color: {accent_col};
                        selection-color: #FFFFFF;
                        alternate-background-color: {surface_bg};
                    }}
                    QCalendarWidget QToolButton {{
                        color: {text_primary};
                        background-color: transparent;
                        border-radius: 4px;
                        padding: 4px;
                        font-weight: bold;
                    }}
                    QCalendarWidget QToolButton:hover {{
                        background-color: {surface_bg};
                    }}
                    QCalendarWidget QMenu {{
                        background-color: {surface_bg};
                        color: {text_primary};
                        border: 1px solid {border_col};
                    }}
                    QCalendarWidget QSpinBox {{
                        background-color: {input_bg};
                        color: {text_primary};
                        border: 1px solid {border_col};
                    }}
                """)
