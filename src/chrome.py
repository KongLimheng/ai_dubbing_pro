# File: chrome.py - Chrome Profile Manager (Cross-platform)
import base64
import datetime
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time

try:
    import sqlite3
    SQLITE3_IMPORT_ERROR = None
except ImportError as exc:
    sqlite3 = None
    SQLITE3_IMPORT_ERROR = exc

try:
    import psutil
except ImportError:
    psutil = None

try:
    import win32gui
    import win32process
except ImportError:
    win32gui = None
    win32process = None

try:
    import win32crypt
except ImportError:
    win32crypt = None

try:
    import qtawesome as qta
except Exception:
    qta = None

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QStyle, QLineEdit, QTextEdit, QScrollArea, QPushButton,
    QInputDialog, QMessageBox, QListWidget, QListWidgetItem, QTableWidget,
    QTableWidgetItem, QHeaderView, QMenu, QTabBar, QDialog,
    QDialogButtonBox, QFormLayout, QLabel, QSizePolicy, QComboBox,
    QColorDialog, QCheckBox, QFileDialog
)
from PyQt5.QtGui import QIcon, QColor, QFont
from PyQt5.QtCore import Qt, QPoint, pyqtSignal, QSettings, QTimer

from app_links import AI_STUDIO_TRANSLATE_URL

if sys.platform == 'win32':
    CHROME_PATH = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
elif sys.platform == 'darwin':
    CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
else:
    CHROME_PATH = (
        shutil.which('google-chrome-stable')
        or shutil.which('google-chrome')
        or shutil.which('chromium-browser')
        or shutil.which('chromium')
        or '/usr/bin/google-chrome'
    )

DATA_FILE = 'data.json'
DEFAULT_STARTUP_URL = AI_STUDIO_TRANSLATE_URL
DEFAULT_WINDOW_WIDTH = 629
DEFAULT_WINDOW_HEIGHT = 781
ORGANIZATION_NAME = 'ChromeProfileManager'
APPLICATION_NAME = 'ChromeProfileManager'


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath('.')
    return os.path.join(base_path, relative_path)


def themed_icon(icon_name, color='gray'):
    """Return a qtawesome icon when available, otherwise an empty QIcon."""
    if qta:
        try:
            return qta.icon(icon_name, color=color)
        except Exception:
            pass
    return QIcon()


class CreateProfileDialog(QDialog):
    """Dialog for creating a new Chrome profile."""

    def __init__(self, group_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Create New Profile')
        self.layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        self.name_edit = QLineEdit()
        self.group_combo = QComboBox()
        self.group_combo.addItems(group_names)
        form_layout.addRow(QLabel('New Profile Name:'), self.name_edit)
        form_layout.addRow(QLabel('Add to Group:'), self.group_combo)
        self.layout.addLayout(form_layout)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)


class ProfileDetailsDialog(QDialog):
    """Dialog for editing profile notes and tags."""

    def __init__(self, notes, tags, url, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit Profile Details')
        self.layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        self.url_edit = QLineEdit(url)
        self.notes_edit = QTextEdit(notes)
        self.tags_edit = QLineEdit(', '.join(tags))
        form_layout.addRow(QLabel('Startup URL:'), self.url_edit)
        form_layout.addRow(QLabel('Notes:'), self.notes_edit)
        form_layout.addRow(QLabel('Tags (comma-separated):'), self.tags_edit)
        self.layout.addLayout(form_layout)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)


class ProfileListWidget(QListWidget):
    """Custom QListWidget with Drag-and-Drop."""
    orderChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.orderChanged.emit()


class ProfileTableWidget(QTableWidget):
    """Custom QTableWidget with Drag & Drop."""
    orderChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(6)
        self.setHorizontalHeaderLabels([
            '#',
            '🐤',
            'Name',
            'Profile Key',
            '📧 Gmail',
            '🔐 Passwords'
        ])
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.setShowGrid(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTableWidget.InternalMove)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.orderChanged.emit()


class ChromeProfileManager(QMainWindow):

    def __init__(self):
        global CHROME_PATH
        super().__init__()
        self.setWindowTitle('Chrome Manager')
        self.setGeometry(100, 100, 700, 500)
        icon_path = resource_path('icon.png')
        if not os.path.exists(icon_path):
            icon_path = resource_path('icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.chrome_profiles = {}
        self.groups = {}
        self.favorites = set()
        self.profile_metadata = {}
        self.running_profiles = set()
        self.show_gmail = True
        self.auto_restore_session = False
        self.last_session = {}
        self.group_colors = {}
        self.chrome_path = self.load_chrome_path()
        CHROME_PATH = self.chrome_path
        self.load_data()
        self._setup_ui()
        self.find_chrome_profiles()
        self.load_data()
        self.apply_default_startup_url_to_all_profiles()
        self.populate_tabs()
        self.load_settings()
        if self.auto_restore_session or self.last_session:
            QTimer.singleShot(1000, self._auto_restore_on_startup)

    def _auto_restore_on_startup(self):
        """Auto-restore session on startup (called after window is shown)."""
        if self.auto_restore_session or self.last_session:
            print(f"Auto-restoring session with {len(self.last_session)} profiles...")
            self.restore_session(auto=True)

    def has_sqlite_support(self):
        """Return whether this runtime can read Chrome's SQLite-backed password store."""
        return sqlite3 is not None

    def show_sqlite_unavailable_message(self):
        """Explain why password-related Chrome features are unavailable."""
        details = str(SQLITE3_IMPORT_ERROR) if SQLITE3_IMPORT_ERROR else 'sqlite3 support is unavailable.'
        QMessageBox.warning(
            self,
            'Password Features Unavailable',
            f"This build does not include Python's sqlite3 module, so Chrome saved-password features are disabled.\n\n"
            f"The rest of Chrome Manager can still be used normally.\n\nDetails: {details}"
        )

    def _setup_ui(self):
        menu_bar = self.menuBar()
        view_menu = menu_bar.addMenu('&View')
        session_menu = menu_bar.addMenu('💾 &Session')
        save_session_action = session_menu.addAction('💾 Save Current Session')
        save_session_action.triggered.connect(self.save_current_session)
        restore_session_action = session_menu.addAction('🔄 Restore Last Session')
        restore_session_action.triggered.connect(self.restore_session)
        clear_session_action = session_menu.addAction('🗑️ Clear Session Data')
        clear_session_action.triggered.connect(self.clear_session)
        session_menu.addSeparator()
        self.auto_restore_action = session_menu.addAction('✅ Auto-restore on Startup')
        self.auto_restore_action.setCheckable(True)
        self.auto_restore_action.setChecked(self.auto_restore_session)
        self.auto_restore_action.triggered.connect(self.toggle_auto_restore)
        theme_menu = view_menu.addMenu('🎨 Theme')
        light_action = theme_menu.addAction('☀️ Light Mode')
        light_action.triggered.connect(lambda: self.change_theme('light'))
        dark_action = theme_menu.addAction('🌙 Dark Mode')
        dark_action.triggered.connect(lambda: self.change_theme('dark'))
        blue_action = theme_menu.addAction('💙 Blue Theme')
        blue_action.triggered.connect(lambda: self.change_theme('blue'))
        theme_menu.addSeparator()
        opacity_menu = theme_menu.addMenu('🔆 Window Opacity')
        for opacity in (100, 95, 90, 85, 80):
            opacity_action = opacity_menu.addAction(f'{opacity}%')
            opacity_action.triggered.connect(lambda checked, o=opacity: self.set_opacity(o))
        help_menu = menu_bar.addMenu('&Help')
        about_action = help_menu.addAction('&About')
        about_action.triggered.connect(self.show_about_dialog)
        chrome_path_layout = QHBoxLayout()
        chrome_path_label = QLabel('Chrome.exe:')
        self.chrome_path_input = QLineEdit(self.chrome_path)
        self.chrome_path_input.setReadOnly(True)
        self.chrome_path_input.setToolTip('Path to Google Chrome executable.')
        self.btn_browse_chrome = QPushButton('Browse')
        self.btn_browse_chrome.setToolTip('Choose chrome executable')
        self.btn_browse_chrome.clicked.connect(self.browse_chrome_exe)
        chrome_path_layout.addWidget(chrome_path_label)
        chrome_path_layout.addWidget(self.chrome_path_input, 1)
        chrome_path_layout.addWidget(self.btn_browse_chrome)
        self.layout.addLayout(chrome_path_layout)
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText('Search profiles by name or key (e.g., User, Profile 1)...')
        self.search_bar.textChanged.connect(self.filter_profiles)
        self.search_bar.setClearButtonEnabled(True)
        self.layout.addWidget(self.search_bar)
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(False)
        self.tab_widget.setMovable(True)
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self.show_tab_context_menu)
        self.tab_widget.tabBar().tabMoved.connect(self.update_tab_order)
        self.tab_widget.tabBar().setElideMode(Qt.ElideNone)
        self.tab_widget.tabBar().setExpanding(False)
        self.tab_widget.tabBar().setUsesScrollButtons(True)
        self.layout.addWidget(self.tab_widget)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        self.btn_create_group = QPushButton('📁 Create Group')
        self.btn_create_group.setObjectName('secondaryBtn')
        self.btn_create_profile = QPushButton('➕ Create New Profile')
        self.btn_create_profile.setObjectName('primaryBtn')
        self.btn_refresh = QPushButton('🔄 Refresh Profiles')
        self.btn_refresh.setObjectName('secondaryBtn')
        self.btn_save = QPushButton('💾 Save Layout')
        self.btn_save.setObjectName('secondaryBtn')
        self.btn_clear_running = QPushButton('❌ Close All Chrome & Clear Status')
        self.btn_clear_running.setObjectName('dangerBtn')

        self.btn_create_profile.clicked.connect(self.create_new_profile)
        self.btn_create_group.clicked.connect(self.create_group)
        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_save.clicked.connect(self.save_data)
        self.btn_clear_running.clicked.connect(self.clear_running_status)
        self.gmail_checkbox = QCheckBox('📧 Show Gmail')
        self.gmail_checkbox.setChecked(True)
        self.gmail_checkbox.setStyleSheet('font-weight: bold;')
        self.gmail_checkbox.stateChanged.connect(self.toggle_gmail_column)
        button_layout.addWidget(self.btn_create_group)
        button_layout.addWidget(self.btn_create_profile)
        button_layout.addWidget(self.btn_refresh)
        button_layout.addWidget(self.btn_clear_running)
        button_layout.addWidget(self.gmail_checkbox)
        button_layout.addStretch()
        button_layout.addWidget(self.btn_save)
        self.layout.addLayout(button_layout)

    def get_themes(self):
        """Return theme stylesheets adhering to the unified 60-30-10 Design System."""
        try:
            from ui_theme_tokens import get_modern_stylesheet
            light_ss = get_modern_stylesheet("light")
            dark_ss = get_modern_stylesheet("dark")
        except Exception:
            light_ss = ""
            dark_ss = ""

        return {
            'dark': {
                'name': 'Dark Mode',
                'stylesheet': dark_ss,
            },
            'light': {
                'name': 'Light Mode',
                'stylesheet': light_ss,
            },
        }

    def change_theme(self, theme_name):
        """Change current application theme."""
        themes = self.get_themes()
        if theme_name in themes:
            self.current_theme = theme_name
            theme = themes[theme_name]
            self.setStyleSheet(theme['stylesheet'])
            settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
            settings.setValue('theme', theme_name)
            QMessageBox.information(self, 'Theme Changed', f"Theme changed to {theme['name']}!")

    def set_opacity(self, opacity_percent):
        """Set window opacity."""
        self.setWindowOpacity(opacity_percent / 100.0)
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        settings.setValue('opacity', opacity_percent)

    def refresh_all(self):
        """Refresh all profiles and tabs."""
        self.find_chrome_profiles()
        self.apply_default_startup_url_to_all_profiles()
        self.populate_tabs()

    def candidate_chrome_paths(self):
        """Generate candidate Chrome paths depending on platform."""
        candidates = [CHROME_PATH]
        if sys.platform == 'win32':
            candidates.extend([
                os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
                os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
                os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe')
            ])
        elif sys.platform == 'darwin':
            candidates.extend([
                '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                os.path.expanduser('~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            ])
        else:
            for name in ['google-chrome-stable', 'google-chrome', 'chromium-browser', 'chromium']:
                p = shutil.which(name)
                if p:
                    candidates.append(p)
            candidates.extend([
                '/usr/bin/google-chrome-stable',
                '/usr/bin/google-chrome',
                '/usr/bin/chromium-browser',
                '/usr/bin/chromium'
            ])
        return [c for c in candidates if c]

    def find_existing_chrome_path(self):
        """Find an existing Chrome executable path."""
        for path in self.candidate_chrome_paths():
            if os.path.exists(path):
                return os.path.abspath(path)
        return CHROME_PATH

    def load_chrome_path(self):
        """Load Chrome path from settings or auto-detect."""
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        saved_path = settings.value('chrome_path', '', type=str)
        if saved_path and os.path.exists(saved_path):
            return os.path.abspath(saved_path)
        return self.find_existing_chrome_path()

    def set_chrome_path(self, path):
        """Set and save Chrome executable path."""
        global CHROME_PATH
        normalized = os.path.abspath(str(path or '').strip())
        self.chrome_path = normalized
        CHROME_PATH = normalized
        if hasattr(self, 'chrome_path_input'):
            self.chrome_path_input.setText(normalized)
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        settings.setValue('chrome_path', normalized)

    def browse_chrome_exe(self):
        """Open file dialog to browse for Chrome executable."""
        initial_dir = os.path.dirname(self.chrome_path) if self.chrome_path else os.path.expanduser('~')
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            'Choose Chrome Executable',
            initial_dir,
            'Chrome executable (chrome.exe; google-chrome; chromium);;Executable Files (*.exe *);;All Files (*)'
        )
        if not file_path:
            return
        base = os.path.basename(file_path).lower()
        if sys.platform == 'win32' and base != 'chrome.exe':
            QMessageBox.warning(self, 'Invalid File', 'Please choose chrome.exe.')
            return
        self.set_chrome_path(file_path)
        QMessageBox.information(self, 'Chrome Path Saved', f'Chrome path saved:\n{file_path}')

    def ensure_chrome_path(self):
        """Ensure valid Chrome path exists, prompting user if not."""
        if os.path.exists(CHROME_PATH):
            return True
        reply = QMessageBox.question(
            self,
            'Chrome Not Found',
            f"Chrome was not found at:\n{CHROME_PATH}\n\nDo you want to choose chrome now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return False
        self.browse_chrome_exe()
        return os.path.exists(CHROME_PATH)

    def build_chrome_command(self, profile_key, url='', *, new_window=False, position=None, size=None):
        """Build Chrome execution command line arguments."""
        width, height = size if size else (DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        command = [CHROME_PATH, f'--profile-directory={profile_key}']
        if new_window:
            command.extend([
                '--new-window',
                '--disable-session-crashed-bubble',
                '--disable-infobars',
                '--no-default-browser-check'
            ])
        if position is not None:
            command.append(f'--window-position={position[0]},{position[1]}')
        command.append(f'--window-size={width},{height}')
        final_url = (url or '').strip()
        command.append(final_url or 'chrome://newtab')
        return command

    def apply_default_startup_url_to_all_profiles(self):
        """Force the shared startup URL onto every detected Chrome profile."""
        changed = False
        for profile_key in self.chrome_profiles:
            profile_meta = self.profile_metadata.setdefault(profile_key, {})
            if profile_meta.get('url') != DEFAULT_STARTUP_URL:
                profile_meta['url'] = DEFAULT_STARTUP_URL
                changed = True
        if changed:
            self._auto_save_layout()

    def _get_group_name_from_tab(self, tab_index):
        """Extract group name from tab text."""
        tab_text = self.tab_widget.tabText(tab_index)
        return tab_text.rsplit(' (', 1)[0] if ' (' in tab_text else tab_text

    def find_chrome_profiles(self):
        """Scan Chrome User Data directory and read profiles."""
        self.chrome_profiles.clear()
        if sys.platform == 'win32':
            user_data_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
        elif sys.platform == 'darwin':
            user_data_path = os.path.expanduser('~/Library/Application Support/Google/Chrome')
        else:
            user_data_path = os.path.expanduser('~/.config/google-chrome')
        if not os.path.exists(user_data_path):
            return
        for item in os.listdir(user_data_path):
            if item == 'Default' or item.startswith('Profile '):
                profile_path = os.path.join(user_data_path, item)
                preferences_path = os.path.join(profile_path, 'Preferences')
                icon_path = os.path.join(profile_path, 'Google Profile Picture.png')
                if not os.path.exists(icon_path):
                    icon_path = None
                if os.path.exists(preferences_path):
                    try:
                        with open(preferences_path, 'r', encoding='utf-8') as f:
                            preferences = json.load(f)
                        profile_name = preferences.get('profile', {}).get('name', item)
                        gmail_account = None
                        try:
                            account_info = preferences.get('account_info', [])
                            if account_info and len(account_info) > 0:
                                gmail_account = account_info[0].get('email', None)
                            if not gmail_account:
                                signin_info = preferences.get('signin', {})
                                gmail_account = signin_info.get('allowed_username', None)
                        except Exception:
                            pass
                        self.chrome_profiles[item] = {
                            'name': profile_name,
                            'icon_path': icon_path,
                            'gmail': gmail_account
                        }
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        self.chrome_profiles[item] = {
                            'name': item,
                            'icon_path': icon_path,
                            'gmail': None
                        }
        print(f"Found profiles: {self.chrome_profiles}")

    def get_gmail_password(self, profile_key, gmail_email):
        """Get password for Gmail in profile if available (Windows CryptUnprotectData)."""
        if not gmail_email or not self.has_sqlite_support():
            return None
        if win32crypt is None:
            return None
        temp_db = None
        try:
            if sys.platform == 'win32':
                user_data_path = os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data')
            else:
                user_data_path = os.path.expanduser('~/.config/google-chrome')
            login_data_path = os.path.join(user_data_path, profile_key, 'Login Data')
            if not os.path.exists(login_data_path):
                return None
            temp_db = login_data_path + '.tmp'
            shutil.copy2(login_data_path, temp_db)
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT origin_url, username_value, password_value FROM logins WHERE username_value = ? AND (origin_url LIKE '%google.com%' OR origin_url LIKE '%gmail.com%')",
                (gmail_email,)
            )
            result = cursor.fetchone()
            if result:
                origin_url, username, encrypted_password = result
                try:
                    decrypted_password = win32crypt.CryptUnprotectData(encrypted_password, None, None, None, 0)[1]
                    password = decrypted_password.decode('utf-8')
                    conn.close()
                    if os.path.exists(temp_db):
                        os.remove(temp_db)
                    return password
                except Exception as e:
                    print(f"Error decrypting password: {e}")
            conn.close()
            if os.path.exists(temp_db):
                os.remove(temp_db)
            return None
        except Exception as e:
            if temp_db and os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except Exception:
                    pass
            print(f"Error getting Gmail password for {profile_key}: {e}")
            return None

    def get_password_count(self, profile_key):
        """Get number of saved passwords in profile."""
        if not self.has_sqlite_support():
            return 0
        temp_db = None
        try:
            if sys.platform == 'win32':
                user_data_path = os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data')
            else:
                user_data_path = os.path.expanduser('~/.config/google-chrome')
            login_data_path = os.path.join(user_data_path, profile_key, 'Login Data')
            if not os.path.exists(login_data_path):
                return 0
            temp_db = login_data_path + '.tmp'
            shutil.copy2(login_data_path, temp_db)
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM logins WHERE username_value != ''")
            count = cursor.fetchone()[0]
            conn.close()
            if os.path.exists(temp_db):
                os.remove(temp_db)
            return count
        except Exception as e:
            if temp_db and os.path.exists(temp_db):
                try:
                    os.remove(temp_db)
                except Exception:
                    pass
            print(f"Error getting password count for {profile_key}: {e}")
            return 0

    def load_data(self):
        """Load group layout data from JSON."""
        if hasattr(self, 'groups') and self.groups:
            return
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and 'groups' in data:
                    self.groups = data['groups']
                    self.favorites = set(data.get('favorites', []))
                    self.profile_metadata = data.get('profile_metadata', {})
                    self.group_colors = data.get('group_colors', {})
                    self.last_session = data.get('last_session', {})
                    self.auto_restore_session = data.get('auto_restore_session', False)
                else:
                    self.groups = data
                    self.favorites = set()
            except (json.JSONDecodeError, Exception):
                pass
        print(f"Loaded groups: {self.groups}, Favorites: {self.favorites}, Metadata: {len(self.profile_metadata)} items")

    def save_data(self):
        """Save group layout data to JSON."""
        data_to_save = {
            'groups': self.groups,
            'favorites': list(self.favorites),
            'profile_metadata': self.profile_metadata,
            'group_colors': getattr(self, 'group_colors', {}),
            'last_session': self.last_session,
            'auto_restore_session': self.auto_restore_session
        }
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4)
            QMessageBox.information(self, 'Success', 'Layout has been saved successfully!')
            print(f"Saved data: {data_to_save}")
        except Exception as e:
            QMessageBox.warning(self, 'Error', f"Failed to save data: {e}")

    def _auto_save_layout(self):
        """Silently auto-save group layout data to JSON."""
        data_to_save = {
            'groups': self.groups,
            'favorites': list(self.favorites),
            'profile_metadata': self.profile_metadata,
            'group_colors': getattr(self, 'group_colors', {}),
            'last_session': self.last_session,
            'auto_restore_session': self.auto_restore_session
        }
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4)
        except Exception:
            pass

    def populate_tabs(self):
        """Populate tabs in tab widget."""
        self.tab_widget.clear()
        for group_name, profile_keys in list(self.groups.items()):
            self.groups[group_name] = list(profile_keys)
        profiles_in_groups = set()
        for profiles in self.groups.values():
            profiles_in_groups.update(profiles)
        self.add_group_tab('Favorites', sorted(list(self.favorites)))
        self.tab_widget.tabBar().setTabButton(0, QTabBar.RightSide, None)
        for group_name in self.groups:
            self.add_group_tab(group_name, self.groups[group_name])
        unassigned_profiles = []
        for profile_key in self.chrome_profiles:
            if profile_key not in profiles_in_groups:
                unassigned_profiles.append(profile_key)
        self.add_group_tab('Unassigned', unassigned_profiles)
        if self.search_bar.text():
            self.filter_profiles(self.search_bar.text())
        self.update_tab_order()

    def add_group_tab(self, group_name, profile_keys):
        """Create and populate a group tab table."""
        table_widget = ProfileTableWidget()
        table_widget.cellDoubleClicked.connect(lambda row, col: self.launch_profile_from_table(table_widget, row))
        table_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        table_widget.customContextMenuRequested.connect(self.show_table_context_menu)
        table_widget.orderChanged.connect(lambda: self.on_order_changed(table_widget))
        if group_name == 'Favorites':
            table_widget.setDragDropMode(QTableWidget.NoDragDrop)
        table_widget.model().rowsMoved.connect(lambda parent, start, end: self.on_profile_moved(table_widget))
        table_widget.setRowCount(len(profile_keys))
        for row, profile_key in enumerate(profile_keys):
            profile_data = self.chrome_profiles.get(profile_key)
            if not profile_data:
                continue
            display_name = profile_data['name']
            icon_path = profile_data['icon_path']
            gmail = profile_data.get('gmail') or ''
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setTextAlignment(Qt.AlignCenter)
            num_item.setData(Qt.UserRole, profile_key)
            icon_item = QTableWidgetItem()
            if profile_key in self.running_profiles:
                icon = QIcon(icon_path) if icon_path else themed_icon('fa5s.user-circle', color='green')
                icon_item.setIcon(icon)
                icon_item.setText('●')
            elif icon_path:
                icon = QIcon(icon_path)
                icon_item.setIcon(icon)
            else:
                icon = themed_icon('fa5s.user-circle', color='gray')
                icon_item.setIcon(icon)
            icon_item.setTextAlignment(Qt.AlignCenter)
            name_item = QTableWidgetItem(display_name)
            if profile_key in self.running_profiles:
                name_item.setForeground(Qt.darkGreen)
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
            key_item = QTableWidgetItem(profile_key)
            key_item.setTextAlignment(Qt.AlignCenter)
            gmail_item = QTableWidgetItem(gmail)
            if gmail:
                gmail_item.setForeground(QColor('#0066cc'))
            password_count = self.get_password_count(profile_key)
            password_item = QTableWidgetItem(str(password_count) if password_count > 0 else '')
            password_item.setTextAlignment(Qt.AlignCenter)
            if password_count > 0:
                password_item.setForeground(QColor('#d35400'))
                font = password_item.font()
                font.setBold(True)
                password_item.setFont(font)
            table_widget.setItem(row, 0, num_item)
            table_widget.setItem(row, 1, icon_item)
            table_widget.setItem(row, 2, name_item)
            table_widget.setItem(row, 3, key_item)
            table_widget.setItem(row, 4, gmail_item)
            table_widget.setItem(row, 5, password_item)
            metadata = self.profile_metadata.get(profile_key, {})
            notes = metadata.get('notes', '')
            tags = metadata.get('tags', [])
            url = metadata.get('url', '')
            tooltip_text = f'<b>{display_name}</b> ({profile_key})'
            if gmail:
                tooltip_text += f'<br><b>📧 Gmail:</b> {gmail}'
            if password_count > 0:
                tooltip_text += f'<br><b>🔐 Saved Passwords:</b> {password_count}'
            elif not self.has_sqlite_support():
                tooltip_text += '<br><b>Saved Passwords:</b> unavailable in this build'
            if url:
                tooltip_text += f'<br><br><b>Startup URL:</b> {url}'
            if notes:
                tooltip_text += f'<br><br><b>Notes:</b><br>{notes.replace(os.linesep, "<br>")}'
            if tags:
                tooltip_text += f'<br><br><b>Tags:</b> {", ".join(tags)}'
            for col in range(6):
                if table_widget.item(row, col):
                    table_widget.item(row, col).setToolTip(tooltip_text)
        if not self.show_gmail:
            table_widget.setColumnHidden(4, True)
        profile_count = len(profile_keys)
        tab_display_name = f'{group_name} ({profile_count})'
        tab_index = self.tab_widget.addTab(table_widget, tab_display_name)
        if group_name == 'Favorites':
            self.tab_widget.tabBar().setTabTextColor(tab_index, Qt.darkYellow)
            self.tab_widget.tabBar().setStyleSheet('''
                QTabBar::tab:selected {
                    background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1,
                                                stop: 0 #ffd700, stop: 1 #ffed4e);
                    color: #000;
                    font-weight: bold;
                }
            ''')
        elif group_name in self.group_colors:
            color_hex = self.group_colors[group_name]
            color = QColor(color_hex)
            self.tab_widget.tabBar().setTabTextColor(tab_index, color)
            lighter_color = color.lighter(180)
            self.tab_widget.tabBar().setStyleSheet(f'''
                QTabBar::tab:nth-child({tab_index + 1}) {{
                    background-color: {lighter_color.name()};
                }}
                QTabBar::tab:nth-child({tab_index + 1}):selected {{
                    background-color: {color.name()};
                    color: white;
                    font-weight: bold;
                }}
            ''')

    def on_order_changed(self, widget):
        """Update profile order when dragged and dropped."""
        if not widget:
            return
        tab_index = self.tab_widget.indexOf(widget)
        group_name = self._get_group_name_from_tab(tab_index)
        if group_name not in ('Unassigned', 'Favorites') and group_name in self.groups:
            if isinstance(widget, QTableWidget):
                new_profile_keys = [widget.item(i, 0).data(Qt.UserRole) for i in range(widget.rowCount()) if widget.item(i, 0)]
            elif isinstance(widget, QListWidget):
                new_profile_keys = [widget.item(i).data(Qt.UserRole) for i in range(widget.count()) if widget.item(i)]
            else:
                new_profile_keys = []
            self.groups[group_name] = new_profile_keys
            self._auto_save_layout()
            print(f"Order updated for group '{group_name}': {self.groups[group_name]}")

    def on_profile_moved(self, source_widget):
        """Handle profile movement across tabs."""
        source_tab_index = self.tab_widget.indexOf(source_widget)
        source_group_name = self._get_group_name_from_tab(source_tab_index)
        QApplication.processEvents()
        dest_widget = self.tab_widget.currentWidget()
        self.on_order_changed(dest_widget)
        if source_group_name not in ('Unassigned', 'Favorites'):
            if isinstance(source_widget, QTableWidget):
                source_keys = [source_widget.item(i, 0).data(Qt.UserRole) for i in range(source_widget.rowCount()) if source_widget.item(i, 0)]
            elif isinstance(source_widget, QListWidget):
                source_keys = [source_widget.item(i).data(Qt.UserRole) for i in range(source_widget.count()) if source_widget.item(i)]
            else:
                source_keys = []
            self.groups[source_group_name] = source_keys
        self.update_tab_order()

    def update_tab_order(self):
        """Update group order according to tab indices."""
        new_groups = {}
        for i in range(self.tab_widget.count()):
            tab_text = self.tab_widget.tabText(i)
            group_name = tab_text.rsplit(' (', 1)[0] if ' (' in tab_text else tab_text
            if group_name in self.groups:
                new_groups[group_name] = self.groups[group_name]
        self.groups = new_groups
        self._auto_save_layout()

    def create_group(self):
        """Prompt user and create a new group."""
        group_name, ok = QInputDialog.getText(self, 'Create Group', 'Enter group name:')
        if ok and group_name and group_name != 'Unassigned':
            if group_name not in self.groups:
                self.groups[group_name] = []
                self.add_group_tab(group_name, [])
                new_index = self.tab_widget.count() - 2
                self.tab_widget.tabBar().moveTab(self.tab_widget.count() - 1, new_index)
                self.tab_widget.setCurrentIndex(new_index)
                self.update_tab_order()
                self._auto_save_layout()
                return
            QMessageBox.warning(self, 'Warning', 'Group with this name already exists.')

    def show_item_context_menu(self, pos):
        """Show context menu for list item."""
        list_widget = self.sender()
        item = list_widget.itemAt(pos)
        if not item:
            return
        profile_key = item.data(Qt.UserRole)
        current_tab_name = self._get_group_name_from_tab(self.tab_widget.indexOf(list_widget))
        menu = QMenu()
        if profile_key in self.favorites:
            fav_action = menu.addAction(themed_icon('fa5s.star', color='gold'), 'Remove from Favorites')
            fav_action.triggered.connect(lambda: self.toggle_favorite(profile_key, False))
        else:
            fav_action = menu.addAction(themed_icon('fa5s.star', color='gray'), 'Add to Favorites')
            fav_action.triggered.connect(lambda: self.toggle_favorite(profile_key, True))
        menu.addSeparator()
        edit_details_action = menu.addAction(themed_icon('fa5s.pencil-alt', color='gray'), 'Edit Notes/Tags...')
        edit_details_action.triggered.connect(lambda: self.edit_profile_details(profile_key))
        set_url_action = menu.addAction(themed_icon('fa5s.link', color='gray'), 'Set Startup URL...')
        set_url_action.triggered.connect(lambda: self.set_startup_url(profile_key))
        rename_action = menu.addAction(themed_icon('fa5s.edit', color='gray'), 'Rename Profile...')
        rename_action.triggered.connect(lambda: self.rename_profile(profile_key))
        menu.addSeparator()
        move_menu = QMenu('Move to Group', self)
        move_menu.setIcon(themed_icon('fa5s.folder-open', color='gray'))
        menu.addMenu(move_menu)
        destination_groups = []
        for i in range(self.tab_widget.count()):
            group_name = self._get_group_name_from_tab(i)
            if group_name != current_tab_name and group_name != 'Favorites':
                destination_groups.append(group_name)
        for group in destination_groups:
            action = move_menu.addAction(group)
            action.triggered.connect(lambda checked, g=group, pk=profile_key, tn=current_tab_name: self.move_profile_to_group(pk, tn, g))
        menu.addSeparator()
        delete_action = menu.addAction(themed_icon('fa5s.trash', color='red'), 'Delete Profile')
        delete_action.triggered.connect(lambda: self.delete_profile_from_disk(profile_key))
        menu.exec_(list_widget.viewport().mapToGlobal(pos))

    def show_table_context_menu(self, pos):
        """Show context menu for table item."""
        table_widget = self.sender()
        row = table_widget.rowAt(pos.y())
        if row < 0:
            return
        item = table_widget.item(row, 0)
        if not item:
            return
        profile_key = item.data(Qt.UserRole)
        current_tab_name = self._get_group_name_from_tab(self.tab_widget.indexOf(table_widget))
        menu = QMenu()
        if profile_key in self.favorites:
            fav_action = menu.addAction(themed_icon('fa5s.star', color='gold'), 'Remove from Favorites')
            fav_action.triggered.connect(lambda: self.toggle_favorite(profile_key, False))
        else:
            fav_action = menu.addAction(themed_icon('fa5s.star', color='gray'), 'Add to Favorites')
            fav_action.triggered.connect(lambda: self.toggle_favorite(profile_key, True))
        menu.addSeparator()
        edit_details_action = menu.addAction(themed_icon('fa5s.pencil-alt', color='gray'), 'Edit Notes/Tags...')
        edit_details_action.triggered.connect(lambda: self.edit_profile_details(profile_key))
        set_url_action = menu.addAction(themed_icon('fa5s.link', color='gray'), 'Set Startup URL...')
        set_url_action.triggered.connect(lambda: self.set_startup_url(profile_key))
        rename_action = menu.addAction(themed_icon('fa5s.edit', color='gray'), 'Rename Profile...')
        rename_action.triggered.connect(lambda: self.rename_profile(profile_key))
        gmail = self.chrome_profiles.get(profile_key, {}).get('gmail', '')
        if gmail:
            password_action = menu.addAction(themed_icon('fa5s.key', color='#FF6B6B'), '🔐 View Gmail Password...')
            if self.has_sqlite_support():
                password_action.triggered.connect(lambda: self.show_gmail_password(profile_key, gmail))
            else:
                password_action.setEnabled(False)
        menu.addSeparator()
        move_menu = QMenu('Move to Group', self)
        move_menu.setIcon(themed_icon('fa5s.folder-open', color='gray'))
        menu.addMenu(move_menu)
        destination_groups = []
        for i in range(self.tab_widget.count()):
            group_name = self._get_group_name_from_tab(i)
            if group_name != current_tab_name and group_name != 'Favorites':
                destination_groups.append(group_name)
        for group in destination_groups:
            action = move_menu.addAction(group)
            action.triggered.connect(lambda checked, g=group, pk=profile_key, tn=current_tab_name: self.move_profile_to_group(pk, tn, g))
        menu.addSeparator()
        delete_action = menu.addAction(themed_icon('fa5s.trash', color='red'), 'Delete Profile')
        delete_action.triggered.connect(lambda: self.delete_profile_from_disk(profile_key))
        menu.exec_(table_widget.viewport().mapToGlobal(pos))

    def move_profile_to_group(self, profile_key, source_group, dest_group):
        """Move profile between groups."""
        current_tab_index = self.tab_widget.currentIndex()
        if source_group not in ('Unassigned', 'Favorites') and source_group in self.groups and profile_key in self.groups[source_group]:
            self.groups[source_group].remove(profile_key)
        if dest_group not in ('Unassigned', 'Favorites'):
            if dest_group not in self.groups:
                self.groups[dest_group] = []
            self.groups[dest_group].append(profile_key)
        print(f"Moved '{profile_key}' from '{source_group}' to '{dest_group}'")
        self.populate_tabs()
        if current_tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(current_tab_index)
        self._auto_save_layout()

    def toggle_favorite(self, profile_key, add):
        """Add or remove profile from favorites."""
        if add:
            self.favorites.add(profile_key)
            print(f"Added '{profile_key}' to favorites.")
        else:
            self.favorites.discard(profile_key)
            print(f"Removed '{profile_key}' from favorites.")
        self.populate_tabs()
        self._auto_save_layout()

    def set_startup_url(self, profile_key):
        """Prompt user and set profile startup URL."""
        metadata = self.profile_metadata.get(profile_key, {})
        current_url = metadata.get('url', DEFAULT_STARTUP_URL)
        new_url, ok = QInputDialog.getText(self, 'Set Startup URL', 'Enter the URL to open on startup:', text=current_url)
        if ok:
            if profile_key not in self.profile_metadata:
                self.profile_metadata[profile_key] = {}
            self.profile_metadata[profile_key]['url'] = new_url.strip()
            self.populate_tabs()
            self._auto_save_layout()
            print(f"Set startup URL for '{profile_key}' to '{new_url.strip()}'")

    def rename_profile(self, profile_key):
        """Rename profile by modifying Chrome's Preferences file."""
        current_name = self.chrome_profiles.get(profile_key, {}).get('name', '')
        new_name, ok = QInputDialog.getText(self, 'Rename Profile', 'Enter new profile name:', text=current_name)
        if ok and new_name and new_name.strip() and new_name.strip() != current_name:
            new_name = new_name.strip()
            reply = QMessageBox.warning(
                self,
                'Warning',
                f"To safely rename the profile '{current_name}', please close any Chrome windows using this profile first.\n\nContinue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
            if sys.platform == 'win32':
                user_data_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
            elif sys.platform == 'darwin':
                user_data_path = os.path.expanduser('~/Library/Application Support/Google/Chrome')
            else:
                user_data_path = os.path.expanduser('~/.config/google-chrome')
            preferences_path = os.path.join(user_data_path, profile_key, 'Preferences')
            if not os.path.exists(preferences_path):
                QMessageBox.critical(self, 'Error', 'Preferences file not found.')
                return
            try:
                with open(preferences_path, 'r+', encoding='utf-8') as f:
                    preferences = json.load(f)
                    preferences.setdefault('profile', {})['name'] = new_name
                    f.seek(0)
                    json.dump(preferences, f, indent=4)
                    f.truncate()
                self.chrome_profiles[profile_key]['name'] = new_name
                self.update_items_display()
                self.save_data()
                QMessageBox.information(self, 'Success', f"Profile renamed to '{new_name}'!")
            except (IOError, json.JSONDecodeError, PermissionError) as e:
                QMessageBox.critical(self, 'Error', f"Failed to rename profile.\nError: {e}\n\nPlease ensure Chrome is not using this profile and try again.")

    def edit_profile_details(self, profile_key):
        """Edit profile metadata: notes, tags, URL."""
        metadata = self.profile_metadata.get(profile_key, {})
        current_notes = metadata.get('notes', '')
        current_tags = metadata.get('tags', [])
        current_url = metadata.get('url', DEFAULT_STARTUP_URL)
        dialog = ProfileDetailsDialog(current_notes, current_tags, current_url, self)
        if dialog.exec_() == QDialog.Accepted:
            new_url = dialog.url_edit.text().strip()
            new_notes = dialog.notes_edit.toPlainText().strip()
            new_tags = [tag.strip() for tag in dialog.tags_edit.text().split(',') if tag.strip()]
            self.profile_metadata[profile_key] = {
                'url': new_url,
                'notes': new_notes,
                'tags': new_tags
            }
            self.populate_tabs()
            self._auto_save_layout()
            print(f"Updated details for '{profile_key}'")

    def show_tab_context_menu(self, pos):
        """Show context menu for group tab."""
        tab_bar = self.tab_widget.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index == -1:
            return
        group_name = self._get_group_name_from_tab(tab_index)
        if group_name in ('Unassigned', 'Favorites'):
            return
        menu = QMenu(self)
        launch_all_action = menu.addAction('Launch All Profiles in Group')
        if not self.groups.get(group_name):
            launch_all_action.setEnabled(False)
        set_group_url_action = menu.addAction('Set Startup URL for All...')
        if not self.groups.get(group_name):
            set_group_url_action.setEnabled(False)
        set_group_url_action.triggered.connect(lambda: self.set_group_startup_url(group_name))
        grid_menu = menu.addMenu('Launch Group in Grid')
        if not self.groups.get(group_name):
            grid_menu.setEnabled(False)
        else:
            smart_action = grid_menu.addAction('🧩 Smart Grid (Auto)')
            smart_action.triggered.connect(lambda: self.launch_group_in_smart_grid(group_name))
            smart_action.setToolTip('Automatically arranges windows in optimal grid layout')
            grid_menu.addSeparator()
            grid_layouts = {
                '1x2': (1, 2),
                '2x2': (2, 2),
                '2x3': (2, 3),
                '3x3': (3, 3),
                '3x4': (3, 4),
                '4x4': (4, 4)
            }
            for layout_name, dims in grid_layouts.items():
                rows, cols = dims
                if len(self.groups.get(group_name, [])) >= 1:
                    action = grid_menu.addAction(layout_name)
                    action.triggered.connect(lambda checked, r=rows, c=cols: self.launch_group_in_grid(group_name, r, c))
        menu.addSeparator()
        change_color_action = menu.addAction(themed_icon('fa5s.palette', color='gray'), 'Change Group Color...')
        change_color_action.triggered.connect(lambda: self.change_group_color(group_name, tab_index))
        if group_name in self.group_colors:
            clear_color_action = menu.addAction(themed_icon('fa5s.eraser', color='gray'), 'Clear Group Color')
            clear_color_action.triggered.connect(lambda: self.clear_group_color(group_name))
        menu.addSeparator()
        rename_action = menu.addAction('Rename Group')
        delete_action = menu.addAction('Delete Group')
        action = menu.exec_(tab_bar.mapToGlobal(pos))
        if action == launch_all_action:
            self.launch_group_profiles(group_name)
        elif action == rename_action:
            new_name, ok = QInputDialog.getText(self, 'Rename Group', 'Enter new name:', text=group_name)
            if ok and new_name and new_name not in self.groups:
                self.groups[new_name] = self.groups.pop(group_name)
                profile_count = len(self.groups[new_name])
                tab_bar.setTabText(tab_index, f'{new_name} ({profile_count})')
                self._auto_save_layout()
        elif action == delete_action:
            reply = QMessageBox.question(
                self,
                'Delete Group',
                f"Are you sure you want to delete the group '{group_name}'?\nProfiles will be moved to Unassigned.",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                del self.groups[group_name]
                self.populate_tabs()
                self.update_tab_order()

    def change_group_color(self, group_name, tab_index):
        """Open color picker to customize group tab color."""
        current_color = QColor(self.group_colors.get(group_name, '#1E90FF'))
        color = QColorDialog.getColor(current_color, self, f"Choose color for '{group_name}'")
        if color.isValid():
            self.group_colors[group_name] = color.name()
            self._auto_save_layout()
            self.populate_tabs()
            QMessageBox.information(self, 'Success', f"Color for '{group_name}' has been updated!")

    def clear_group_color(self, group_name):
        """Remove custom group tab color."""
        if group_name in self.group_colors:
            del self.group_colors[group_name]
            self._auto_save_layout()
            self.populate_tabs()
            QMessageBox.information(self, 'Success', f"Color for '{group_name}' has been cleared!")

    def set_group_startup_url(self, group_name):
        """Set startup URL for all profiles in a group."""
        profile_keys = self.groups.get(group_name, [])
        if not profile_keys:
            return
        first_profile_meta = self.profile_metadata.get(profile_keys[0], {})
        current_url = first_profile_meta.get('url', DEFAULT_STARTUP_URL)
        new_url, ok = QInputDialog.getText(self, 'Set Group Startup URL', f"Enter the URL for all profiles in '{group_name}':", text=current_url)
        if ok:
            new_url = new_url.strip()
            for profile_key in profile_keys:
                self.profile_metadata.setdefault(profile_key, {})['url'] = new_url
            self.populate_tabs()
            self._auto_save_layout()
            QMessageBox.information(self, 'Success', f"Startup URL for all profiles in '{group_name}' has been updated.")

    def launch_profile(self, item):
        """Launch Chrome with specified profile."""
        profile_key = item.data(Qt.UserRole)
        if not self.ensure_chrome_path():
            return
        metadata = self.profile_metadata.get(profile_key, {})
        url = metadata.get('url', DEFAULT_STARTUP_URL).strip()
        command = self.build_chrome_command(profile_key, url)
        print(f"Launching: {' '.join(command)}")
        subprocess.Popen(command)
        self.running_profiles.add(profile_key)
        self.update_items_display()

    def launch_profile_from_table(self, table_widget, row):
        """Launch Chrome profile from table row."""
        item = table_widget.item(row, 0)
        if item:
            profile_key = item.data(Qt.UserRole)
            if profile_key:
                dummy_item = QTableWidgetItem()
                dummy_item.setData(Qt.UserRole, profile_key)
                self.launch_profile(dummy_item)

    def show_gmail_password(self, profile_key, gmail_email):
        """Display Gmail password dialog."""
        if not self.has_sqlite_support():
            self.show_sqlite_unavailable_message()
            return
        reply = QMessageBox.warning(
            self,
            '⚠️ Security Warning',
            'Are you sure you want to view the password for this Gmail account?\n\n'
            'This feature is intended only for account management. Never share your password.\n\nContinue?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.No:
            return
        password = self.get_gmail_password(profile_key, gmail_email)
        if password:
            dialog = QDialog(self)
            dialog.setWindowTitle(f'Gmail Password - {gmail_email}')
            dialog.setModal(True)
            dialog.resize(500, 250)
            layout = QVBoxLayout(dialog)
            email_label = QLabel(f'📧 Gmail Account: <b>{gmail_email}</b>')
            email_label.setWordWrap(True)
            layout.addWidget(email_label)
            layout.addSpacing(10)
            password_container = QWidget()
            password_layout = QHBoxLayout(password_container)
            password_layout.setContentsMargins(0, 0, 0, 0)
            password_edit = QLineEdit()
            password_edit.setText(password)
            password_edit.setEchoMode(QLineEdit.Password)
            password_edit.setReadOnly(True)
            password_layout.addWidget(password_edit)
            show_hide_btn = QPushButton('👁️ Show')
            show_hide_btn.setObjectName('secondaryBtn')
            show_hide_btn.setFixedWidth(80)
            show_hide_btn.setCheckable(True)

            def toggle_password():
                if show_hide_btn.isChecked():
                    password_edit.setEchoMode(QLineEdit.Normal)
                    show_hide_btn.setText('🙈 Hide')
                else:
                    password_edit.setEchoMode(QLineEdit.Password)
                    show_hide_btn.setText('👁️ Show')

            show_hide_btn.clicked.connect(toggle_password)
            password_layout.addWidget(show_hide_btn)
            layout.addWidget(password_container)
            layout.addSpacing(10)
            copy_btn = QPushButton('📋 Copy Password')
            copy_btn.setObjectName('primaryBtn')
            copy_btn.clicked.connect(lambda: (QApplication.clipboard().setText(password), QMessageBox.information(dialog, 'Copied', 'Password copied to clipboard!')))
            layout.addWidget(copy_btn)
            layout.addSpacing(10)
            warning_label = QLabel('⚠️ <i>Never share your password. Keep it secure at all times.</i>')
            warning_label.setStyleSheet('QLabel { color: #EF4444; }')
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)
            close_btn = QPushButton('Close')
            close_btn.setObjectName('secondaryBtn')
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            dialog.exec_()
            return
        QMessageBox.warning(
            self,
            'Password Not Found',
            f"Could not find a saved password for Gmail account '{gmail_email}' in this profile.\n\n"
            "Possible reasons:\n- The password was not saved in Chrome.\n- The account uses OAuth or Google Sign-in.\n- The password is encrypted and could not be decrypted."
        )

    def delete_profile_from_disk(self, profile_key):
        """Permanently delete profile folder from disk."""
        profile_data = self.chrome_profiles.get(profile_key)
        if not profile_data:
            QMessageBox.critical(self, 'Error', f"Profile '{profile_key}' not found.")
            return
        profile_name = profile_data['name']
        warning_message = (
            f"This will permanently delete the profile '{profile_name} ({profile_key})' and all its data "
            "(bookmarks, history, passwords, etc.). This action cannot be undone.\n\n"
            f"To confirm, please type the profile key '{profile_key}' below:"
        )
        text, ok = QInputDialog.getText(self, 'Confirm Permanent Deletion', warning_message)
        if ok and text == profile_key:
            if sys.platform == 'win32':
                user_data_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
            elif sys.platform == 'darwin':
                user_data_path = os.path.expanduser('~/Library/Application Support/Google/Chrome')
            else:
                user_data_path = os.path.expanduser('~/.config/google-chrome')
            profile_dir_path = os.path.join(user_data_path, profile_key)
            if os.path.exists(profile_dir_path):
                try:
                    shutil.rmtree(profile_dir_path)
                    QMessageBox.information(self, 'Success', f"Profile '{profile_name}' has been deleted successfully.")
                    self.refresh_all()
                except OSError as e:
                    QMessageBox.critical(
                        self,
                        'Deletion Error',
                        f"Could not delete profile directory.\nError: {e}\n\nPlease make sure Chrome is not running with this profile and try again."
                    )
            else:
                QMessageBox.warning(self, 'Warning', 'Profile directory not found. It may have already been deleted.')
                self.refresh_all()

    def launch_group_profiles(self, group_name):
        """Launch all profiles in group."""
        if not self.ensure_chrome_path():
            return
        profile_keys = self.groups.get(group_name, [])
        if not profile_keys:
            QMessageBox.information(self, 'Info', f"The group '{group_name}' is empty.")
            return
        print(f"Launching all profiles in group '{group_name}': {profile_keys}")
        for profile_key in profile_keys:
            metadata = self.profile_metadata.get(profile_key, {})
            url = metadata.get('url', DEFAULT_STARTUP_URL).strip()
            command = self.build_chrome_command(profile_key, url)
            subprocess.Popen(command)
            self.running_profiles.add(profile_key)
        self.update_items_display()

    def calculate_optimal_grid(self, num_windows):
        """Calculate optimal grid layout for given number of windows."""
        if num_windows <= 1:
            return (1, 1)
        if num_windows == 2:
            return (1, 2)
        if num_windows <= 4:
            return (2, 2)
        if num_windows <= 6:
            return (2, 3)
        if num_windows <= 9:
            return (3, 3)
        if num_windows <= 12:
            return (3, 4)
        if num_windows <= 16:
            return (4, 4)
        cols = math.ceil(math.sqrt(num_windows))
        rows = math.ceil(num_windows / cols)
        return (rows, cols)

    def launch_group_in_smart_grid(self, group_name):
        """Launch group profiles in automatically calculated smart grid."""
        profile_keys = self.groups.get(group_name, [])
        if not profile_keys:
            return
        num_profiles = len(profile_keys)
        rows, cols = self.calculate_optimal_grid(num_profiles)
        QMessageBox.information(self, 'Smart Grid Layout', f"Launching {num_profiles} profiles in optimal {rows}x{cols} grid layout.")
        self.launch_group_in_grid(group_name, rows, cols)
        QApplication.processEvents()
        time.sleep(2)
        self.save_current_session(auto=True)

    def save_current_session(self, auto=False):
        """Save window arrangement of current session."""
        chrome_windows = self._get_all_chrome_windows_with_profiles()
        if not chrome_windows:
            if not auto:
                QMessageBox.information(self, 'No Windows', 'No Chrome windows found to save.')
            return
        self.last_session = {}
        for profile_key, hwnd in chrome_windows.items():
            try:
                if win32gui is not None:
                    rect = win32gui.GetWindowRect(hwnd)
                    self.last_session[profile_key] = {
                        'x': rect[0],
                        'y': rect[1],
                        'width': rect[2] - rect[0],
                        'height': rect[3] - rect[1]
                    }
            except Exception as e:
                print(f"Error getting window position for {profile_key}: {e}")
        self._auto_save_layout()
        if not auto:
            QMessageBox.information(self, 'Session Saved', f"Saved window positions for {len(self.last_session)} profiles.")
        print(f"Session saved: {len(self.last_session)} windows")

    def restore_session(self, auto=False):
        """Restore last saved window layout session."""
        if not self.ensure_chrome_path():
            return
        if not self.last_session:
            if not auto:
                QMessageBox.information(self, 'No Session', 'No session data to restore.')
            return
        for profile_key, position in self.last_session.items():
            if profile_key not in self.chrome_profiles:
                continue
            url = self.profile_metadata.get(profile_key, {}).get('url', '')
            command = self.build_chrome_command(
                profile_key,
                url,
                new_window=True,
                position=(position['x'], position['y']),
                size=(position['width'], position['height'])
            )
            print(f"Restoring {profile_key} at ({position['x']}, {position['y']})")
            subprocess.Popen(command)
            self.running_profiles.add(profile_key)
            time.sleep(0.8)
        self.update_items_display()
        if not auto:
            QMessageBox.information(self, 'Session Restored', f"Restored {len(self.last_session)} profile windows.")
        else:
            print(f"Auto-restored {len(self.last_session)} profile windows")

    def clear_session(self):
        """Clear saved session data."""
        if not self.last_session:
            QMessageBox.information(self, 'No Session', 'No session data to clear.')
            return
        reply = QMessageBox.question(self, 'Clear Session', 'Clear saved session data?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.last_session = {}
            self._auto_save_layout()
            QMessageBox.information(self, 'Session Cleared', 'Session data has been cleared.')

    def toggle_auto_restore(self):
        """Toggle auto-restore session on startup."""
        self.auto_restore_session = self.auto_restore_action.isChecked()
        self._auto_save_layout()
        status = 'enabled' if self.auto_restore_session else 'disabled'
        print(f"Auto-restore session {status}")

    def _get_all_chrome_windows_with_profiles(self):
        """Get mapping of profile_key -> hwnd for visible Chrome windows."""
        if win32gui is None or win32process is None or psutil is None:
            return {}
        chrome_windows = {}

        def enum_handler(hwnd, results):
            if win32gui.IsWindowVisible(hwnd):
                class_name = win32gui.GetClassName(hwnd)
                if class_name == 'Chrome_WidgetWin_1':
                    try:
                        _, pid = win32process.GetWindowThreadProcessId(hwnd)
                        process = psutil.Process(pid)
                        if 'chrome.exe' in process.name().lower():
                            cmdline = process.cmdline()
                            for arg in cmdline:
                                if '--profile-directory=' in arg:
                                    profile_key = arg.split('=')[1]
                                    if profile_key in self.chrome_profiles:
                                        chrome_windows[profile_key] = hwnd
                                        print(f"Found window for {profile_key}: {hwnd}")
                    except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError):
                        pass
            return True

        win32gui.EnumWindows(enum_handler, None)
        return chrome_windows

    def launch_group_in_grid(self, group_name, rows, cols):
        """Launch profiles arranged in a grid."""
        if not self.ensure_chrome_path():
            return
        profile_keys = self.groups.get(group_name, [])
        if not profile_keys:
            return
        screen_rect = QApplication.primaryScreen().availableGeometry()
        screen_height = screen_rect.height()
        screen_width = screen_rect.width()
        cell_width = screen_width // cols
        cell_height = screen_height // rows
        chrome_windows_before = self._get_all_chrome_windows() if win32gui is not None else []
        num_profiles_to_launch = min(len(profile_keys), rows * cols)
        print(f"Launching {num_profiles_to_launch} Chrome profiles...")
        for i in range(num_profiles_to_launch):
            profile_key = profile_keys[i]
            r = i // cols
            c = i % cols
            x = screen_rect.left() + c * cell_width
            y = screen_rect.top() + r * cell_height
            metadata = self.profile_metadata.get(profile_key, {})
            url = metadata.get('url', DEFAULT_STARTUP_URL).strip()
            command = self.build_chrome_command(
                profile_key,
                url,
                new_window=True,
                position=(x, y),
                size=(cell_width, cell_height)
            )
            print(f"Launching profile {i + 1}/{num_profiles_to_launch}: {profile_key}")
            subprocess.Popen(command)
            self.running_profiles.add(profile_key)
            time.sleep(0.8)

        self.update_items_display()

        if win32gui is not None:
            print(f"Waiting for {num_profiles_to_launch} Chrome windows to open...")
            max_wait_time = 30
            wait_interval = 0.5
            elapsed_time = 0
            new_windows = []
            while elapsed_time < max_wait_time:
                chrome_windows_after = self._get_all_chrome_windows()
                new_windows = [w for w in chrome_windows_after if w not in chrome_windows_before]
                print(f"Found {len(new_windows)}/{num_profiles_to_launch} windows after {elapsed_time:.1f}s")
                if len(new_windows) >= num_profiles_to_launch:
                    break
                time.sleep(wait_interval)
                elapsed_time += wait_interval

            def get_window_pos(hwnd):
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    return (rect[1], rect[0])
                except Exception:
                    return (0, 0)

            new_windows.sort(key=get_window_pos)
            print('Windows sorted by position')
            successfully_arranged = 0
            for i, hwnd in enumerate(new_windows[:rows * cols]):
                row = i // cols
                col = i % cols
                x = screen_rect.left() + col * cell_width
                y = screen_rect.top() + row * cell_height
                try:
                    print(f"Arranging window {i + 1}/{len(new_windows[:rows * cols])} (HWND: {hwnd})")
                    win32gui.ShowWindow(hwnd, 9)
                    time.sleep(0.15)
                    win32gui.MoveWindow(hwnd, x, y, cell_width, cell_height, True)
                    successfully_arranged += 1
                    print(f"  ✓ Moved to position ({x},{y}) size ({cell_width}x{cell_height})")
                except Exception as e:
                    print(f"  ✗ Error moving window {hwnd}: {e}")

            completion_msg = (
                f"Grid arrangement complete!\n\n"
                f"Successfully arranged: {successfully_arranged}/{num_profiles_to_launch} windows\n"
                f"Layout: {rows}x{cols} grid"
            )
            print(f"\n{completion_msg}")
            QMessageBox.information(self, 'Complete', completion_msg)
        else:
            QMessageBox.information(self, 'Complete', f"Launched {num_profiles_to_launch} profiles in {rows}x{cols} grid layout.")

    def _get_all_chrome_windows(self):
        """Get list of all Chrome window handles."""
        if win32gui is None or win32process is None or psutil is None:
            return []
        chrome_windows = []

        def callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    process = psutil.Process(pid)
                    if 'chrome.exe' in process.name().lower():
                        class_name = win32gui.GetClassName(hwnd)
                        if class_name == 'Chrome_WidgetWin_1':
                            rect = win32gui.GetWindowRect(hwnd)
                            width = rect[2] - rect[0]
                            height = rect[3] - rect[1]
                            if width > 100 and height > 100:
                                windows.append(hwnd)
                except Exception:
                    pass
            return True

        win32gui.EnumWindows(callback, chrome_windows)
        return chrome_windows

    def _find_main_window_for_pid(self, pid):
        """Helper function to find main window HWND for given PID."""
        if win32gui is None or win32process is None:
            return None
        hwnd_list = []

        def callback(hwnd, hwnds):
            if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd):
                _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
                if found_pid == pid and win32gui.GetWindowText(hwnd):
                    hwnds.append(hwnd)
            return True

        win32gui.EnumWindows(callback, hwnd_list)
        return hwnd_list[0] if hwnd_list else None

    def filter_profiles(self, text):
        """Filter profiles across all tabs based on search text."""
        search_term = text.lower()
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, QTableWidget):
                for row in range(widget.rowCount()):
                    name_item = widget.item(row, 2)
                    key_item = widget.item(row, 3)
                    gmail_item = widget.item(row, 4)
                    profile_key = widget.item(row, 0).data(Qt.UserRole) if widget.item(row, 0) else ''
                    metadata = self.profile_metadata.get(profile_key, {})
                    notes = metadata.get('notes', '').lower()
                    tags = ' '.join(metadata.get('tags', [])).lower()
                    name_text = name_item.text().lower() if name_item else ''
                    key_text = key_item.text().lower() if key_item else ''
                    gmail_text = gmail_item.text().lower() if gmail_item else ''
                    searchable = f"{name_text} {key_text} {gmail_text} {notes} {tags}"
                    widget.setRowHidden(row, search_term not in searchable)
            elif isinstance(widget, QListWidget):
                for j in range(widget.count()):
                    item = widget.item(j)
                    profile_key = item.data(Qt.UserRole)
                    metadata = self.profile_metadata.get(profile_key, {})
                    notes = metadata.get('notes', '').lower()
                    tags = ' '.join(metadata.get('tags', [])).lower()
                    searchable = f"{item.text().lower()} {notes} {tags}"
                    item.setHidden(search_term not in searchable)

    def load_settings(self):
        """Restore window geometry and preferences."""
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        geometry = settings.value('geometry', self.saveGeometry())
        self.restoreGeometry(geometry)
        last_tab_index = settings.value('last_tab_index', 0, type=int)
        if last_tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(last_tab_index)
        theme = settings.value('theme', 'light', type=str)
        themes = self.get_themes()
        if theme in themes:
            self.current_theme = theme
            self.setStyleSheet(themes[theme]['stylesheet'])
        opacity = settings.value('opacity', 100, type=int)
        self.setWindowOpacity(opacity / 100.0)
        self.show_gmail = settings.value('show_gmail', True, type=bool)
        self.gmail_checkbox.setChecked(self.show_gmail)

    def toggle_gmail_column(self, state):
        """Toggle display of Gmail column in profile tables."""
        self.show_gmail = (state == Qt.Checked)
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, ProfileTableWidget):
                widget.setColumnHidden(4, not self.show_gmail)
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        settings.setValue('show_gmail', self.show_gmail)

    def closeEvent(self, event):
        """Save settings and layout on close."""
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('last_tab_index', self.tab_widget.currentIndex())
        self._auto_save_layout()
        super().closeEvent(event)

    def create_new_profile(self):
        """Create new profile dialog."""
        if not self.ensure_chrome_path():
            return
        group_names = [name for name in self.groups.keys() if name != 'Favorites']
        group_names.append('Unassigned')
        dialog = CreateProfileDialog(group_names, self)
        if dialog.exec_() == QDialog.Accepted:
            new_name = dialog.name_edit.text().strip()
            selected_group = dialog.group_combo.currentText()
            if not new_name:
                QMessageBox.warning(self, 'Input Error', 'Profile name cannot be empty.')
                return
            self._execute_profile_creation(new_name, selected_group)

    def _execute_profile_creation(self, new_name, group_name):
        """Execute creation of new profile on disk."""
        try:
            if sys.platform == 'win32':
                user_data_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data')
            elif sys.platform == 'darwin':
                user_data_path = os.path.expanduser('~/Library/Application Support/Google/Chrome')
            else:
                user_data_path = os.path.expanduser('~/.config/google-chrome')
            os.makedirs(user_data_path, exist_ok=True)
            existing_nums = [0]
            for item in os.listdir(user_data_path):
                if item.startswith('Profile '):
                    try:
                        existing_nums.append(int(item.split(' ')[1]))
                    except (ValueError, IndexError):
                        pass
            next_profile_num = max(existing_nums) + 1
            new_profile_key = f'Profile {next_profile_num}'
            new_profile_path = os.path.join(user_data_path, new_profile_key)
            os.makedirs(new_profile_path, exist_ok=True)
            preferences_path = os.path.join(new_profile_path, 'Preferences')
            preferences_data = {'profile': {'name': new_name}}
            with open(preferences_path, 'w', encoding='utf-8') as f:
                json.dump(preferences_data, f, indent=4)
            if group_name != 'Unassigned':
                self.groups.setdefault(group_name, []).append(new_profile_key)
            QMessageBox.information(self, 'Success', f"Profile '{new_name}' has been created successfully.\nThe list will now be refreshed.")
            self.refresh_all()
        except Exception as e:
            QMessageBox.critical(self, 'Creation Error', f"Failed to create new profile.\nError: {e}")

    def update_items_display(self):
        """Update items display formatting to reflect running status."""
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if isinstance(widget, QTableWidget):
                for row in range(widget.rowCount()):
                    item = widget.item(row, 0)
                    if not item:
                        continue
                    profile_key = item.data(Qt.UserRole)
                    profile_data = self.chrome_profiles.get(profile_key)
                    if not profile_data:
                        continue
                    display_name = profile_data['name']
                    icon_path = profile_data['icon_path']
                    name_item = widget.item(row, 2)
                    icon_item = widget.item(row, 1)
                    if profile_key in self.running_profiles:
                        if name_item:
                            name_item.setForeground(Qt.darkGreen)
                            font = name_item.font()
                            font.setBold(True)
                            name_item.setFont(font)
                        if icon_item:
                            icon = QIcon(icon_path) if icon_path else themed_icon('fa5s.user-circle', color='green')
                            icon_item.setIcon(icon)
                            icon_item.setText('●')
                    else:
                        if name_item:
                            name_item.setForeground(Qt.black)
                            font = name_item.font()
                            font.setBold(False)
                            name_item.setFont(font)
                        if icon_item:
                            icon = QIcon(icon_path) if icon_path else themed_icon('fa5s.user-circle', color='gray')
                            icon_item.setIcon(icon)
                            icon_item.setText('')
            elif isinstance(widget, QListWidget):
                for j in range(widget.count()):
                    item = widget.item(j)
                    profile_key = item.data(Qt.UserRole)
                    profile_data = self.chrome_profiles.get(profile_key)
                    if not profile_data:
                        continue
                    display_name = profile_data['name']
                    icon_path = profile_data['icon_path']
                    index = j + 1
                    if profile_key in self.running_profiles:
                        item.setText(f"● {index}. {display_name} ({profile_key})")
                        icon = QIcon(icon_path) if icon_path else themed_icon('fa5s.user-circle', color='green')
                        item.setIcon(icon)
                        item.setForeground(Qt.darkGreen)
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    else:
                        item.setText(f"{index}. {display_name} ({profile_key})")
                        icon = QIcon(icon_path) if icon_path else themed_icon('fa5s.user-circle', color='gray')
                        item.setIcon(icon)
                        item.setForeground(Qt.black)
                        font = item.font()
                        font.setBold(False)
                        item.setFont(font)

    def clear_running_status(self):
        """Close all Chrome windows and clear running status."""
        reply = QMessageBox.question(
            self,
            'Close All Chrome Profiles',
            'This will close ALL Chrome windows and clear the running status.\n\nAre you sure?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                if sys.platform == 'win32':
                    subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'], creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    subprocess.run(['pkill', '-f', 'chrome'])
                self.running_profiles.clear()
                self.update_items_display()
                QMessageBox.information(self, 'Success', 'All Chrome windows have been closed and running status cleared.')
            except Exception as e:
                QMessageBox.warning(self, 'Error', f'Failed to close Chrome processes.\nError: {e}')

    def show_about_dialog(self):
        """Display about information dialog."""
        about_title = 'អំពីកម្មវិធីគ្រប់គ្រង Profile'
        about_text = """
        <h2>Chrome Profile Manager</h2>
        <p>កម្មវិធីសាមញ្ញសម្រាប់គ្រប់គ្រង Profile ជាច្រើនរបស់ Google Chrome។</p>
        <h3>របៀបប្រើប្រាស់៖</h3>
        <ul>
            <li><b>បង្កើតក្រុម៖</b> បង្កើត Tab ក្រុមថ្មី។</li>
            <li><b>ផ្លាស់ទី Profile៖</b> ទាញ-និង-ទម្លាក់ Profile ទៅកាន់ Tab ក្រុម ឬចុច Mouse ស្ដាំ ហើយប្រើ "Move to Group"។</li>
            <li><b>បើក Profile៖</b> ចុច Double-click លើ Profile ដើម្បីបើកវា។</li>
            <li><b>ជម្រើសផ្សេងៗ៖</b> ចុច Mouse ស្ដាំលើ Profile ឬលើ Tab របស់ក្រុម ដើម្បីទទួលបានជម្រើសផ្សេងៗទៀតដូចជា ប្តូរឈ្មោះ, កំណត់ URL, លុប, ។ល។</li>
        </ul>
        <hr>
        <p>បង្កើតដោយ៖ <b>ឡេង សៀកម៉េង</b></p>
        """
        QMessageBox.about(self, about_title, about_text)


if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    manager = ChromeProfileManager()
    manager.show()
    sys.exit(app.exec_())
