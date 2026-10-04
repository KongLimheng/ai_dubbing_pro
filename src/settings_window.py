"""
settings_window.py — Enhanced Settings Window Extension for AI Dubber Ultimate.

Injects 5 additional tabs into the compiled Settings dialog at runtime via
QTimer-based tab injection. This module is loaded by the core_app.py patch
and called from _open_settings_dialog_enhanced().

New tabs:
  1. 🔑 More APIs    — OpenAI, Groq, AssemblyAI, DeepSeek, Gladia, Azure
  2. 🌍 Translation  — Engine selector + default target language
  3. 🎨 Appearance   — Dark/Light theme + burn subtitle styles
  4. 📤 Export       — Audio mix percentages + batch output directory
  5. 🔧 Advanced     — UI feature flags + VoxCPM2 install paths
"""

import os
import sys

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QCheckBox, QComboBox, QGroupBox, QScrollArea, QSpinBox,
    QPushButton, QSlider, QFileDialog, QColorDialog, QFrame,
    QTextEdit, QRadioButton, QButtonGroup, QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

# ── Shared constants ───────────────────────────────────────────────────────────

LANG_OPTIONS = [
    ("Khmer (ភាសាខ្មែរ) [km]", "km"),
    ("English [en]", "en"),
    ("Chinese Simplified (中文) [zh-CN]", "zh-CN"),
    ("Japanese (日本語) [ja]", "ja"),
    ("Korean (한국어) [ko]", "ko"),
    ("Thai (ไทย) [th]", "th"),
    ("Vietnamese (Tiếng Việt) [vi]", "vi"),
    ("French (Français) [fr]", "fr"),
    ("Spanish (Español) [es]", "es"),
    ("German (Deutsch) [de]", "de"),
    ("Portuguese (Português) [pt]", "pt"),
    ("Russian (Русский) [ru]", "ru"),
    ("Arabic (العربية) [ar]", "ar"),
    ("Indonesian (Bahasa Indonesia) [id]", "id"),
]

# ── Helper functions ───────────────────────────────────────────────────────────


def _make_lang_combo(current='km', parent=None):
    """Create a language selection QComboBox pre-selected to `current`."""
    combo = QComboBox(parent)
    combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    for label, code in LANG_OPTIONS:
        combo.addItem(label, code)
    idx = combo.findData(current)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    return combo


def _make_group_box(title):
    return QGroupBox(title)


def _make_key_edit(placeholder="Paste API key here"):
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.Password)
    edit.setPlaceholderText(placeholder)
    return edit


def _label_row(label_text, widget, label_width=145):
    """Return a QHBoxLayout with a fixed-width label and a widget."""
    h = QHBoxLayout()
    lbl = QLabel(label_text)
    lbl.setFixedWidth(label_width)
    try:
        from settings_manager import get_theme_mode
        is_dark = get_theme_mode() == "dark"
    except Exception:
        is_dark = True
    color = "#F1F5F9" if is_dark else "#0F172A"
    lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 500;")
    h.addWidget(lbl)
    h.addWidget(widget, 1)
    return h


def _scrollable(inner_widget):
    """Wrap a QWidget in a frameless QScrollArea for use as a tab page."""
    scroll = QScrollArea()
    scroll.setWidget(inner_widget)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setAutoFillBackground(False)
    scroll.setAttribute(Qt.WA_StyledBackground, True)
    if scroll.viewport():
        scroll.viewport().setAutoFillBackground(False)
        scroll.viewport().setAttribute(Qt.WA_StyledBackground, True)
    if inner_widget:
        inner_widget.setAutoFillBackground(False)
        inner_widget.setAttribute(Qt.WA_StyledBackground, True)
    return scroll


def _luma(hex_color):
    """Return perceived brightness 0-255 of a hex color string like '#RRGGBB'."""
    try:
        h = hex_color.lstrip('#')
        if len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        pass
    return 128


def _hint(text):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setObjectName("mutedLabel")
    try:
        from settings_manager import get_theme_mode
        is_dark = get_theme_mode() == "dark"
    except Exception:
        is_dark = True
    color = "#94A3B8" if is_dark else "#64748B"
    lbl.setStyleSheet(f"color: {color}; font-size: 11px; padding-bottom: 4px;")
    return lbl


# ── Tab 1: More APIs ───────────────────────────────────────────────────────────

def _build_more_apis_tab():
    """Build the '🔑 More APIs' tab. Returns (scroll_widget, load_fn, save_fn)."""
    import settings_manager

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(10)
    layout.setContentsMargins(12, 12, 12, 12)

    # ── OpenAI ──────────────────────────────────────
    txt_openai_key = _make_key_edit("sk-...")
    cmb_openai_model = QComboBox()
    for m in ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]:
        cmb_openai_model.addItem(m, m)
    chk_openai_translate = QCheckBox("Auto-translate transcription")
    cmb_openai_lang = _make_lang_combo()

    gb_openai = _make_group_box("🤖 OpenAI")
    gl = QVBoxLayout(gb_openai)
    gl.setSpacing(6)
    gl.addLayout(_label_row("🔑 API Key:", txt_openai_key))
    gl.addLayout(_label_row("🤖 Model:", cmb_openai_model))
    gl.addWidget(chk_openai_translate)
    gl.addLayout(_label_row("🌍 Target Language:", cmb_openai_lang))
    layout.addWidget(gb_openai)

    # ── Groq ────────────────────────────────────────
    txt_groq_key = _make_key_edit("gsk_...")
    chk_groq_translate = QCheckBox("Auto-translate transcription")
    cmb_groq_lang = _make_lang_combo()

    gb_groq = _make_group_box("⚡ Groq Cloud")
    gl = QVBoxLayout(gb_groq)
    gl.setSpacing(6)
    gl.addLayout(_label_row("🔑 API Key:", txt_groq_key))
    gl.addWidget(chk_groq_translate)
    gl.addLayout(_label_row("🌍 Target Language:", cmb_groq_lang))
    layout.addWidget(gb_groq)

    # ── AssemblyAI ──────────────────────────────────
    txt_aai_key = _make_key_edit("AssemblyAI key...")
    chk_aai_translate = QCheckBox("Auto-translate transcription")
    cmb_aai_lang = _make_lang_combo()

    gb_aai = _make_group_box("🎙️ AssemblyAI")
    gl = QVBoxLayout(gb_aai)
    gl.setSpacing(6)
    gl.addLayout(_label_row("🔑 API Key:", txt_aai_key))
    gl.addWidget(chk_aai_translate)
    gl.addLayout(_label_row("🌍 Target Language:", cmb_aai_lang))
    layout.addWidget(gb_aai)

    # ── DeepSeek ────────────────────────────────────
    txt_ds_key = _make_key_edit("sk-...")
    cmb_ds_model = QComboBox()
    for m in ["deepseek-chat", "deepseek-reasoner"]:
        cmb_ds_model.addItem(m, m)
    chk_ds_translate = QCheckBox("Auto-translate transcription")
    cmb_ds_lang = _make_lang_combo()

    gb_ds = _make_group_box("🧠 DeepSeek")
    gl = QVBoxLayout(gb_ds)
    gl.setSpacing(6)
    gl.addLayout(_label_row("🔑 API Key:", txt_ds_key))
    gl.addLayout(_label_row("🤖 Model:", cmb_ds_model))
    gl.addWidget(chk_ds_translate)
    gl.addLayout(_label_row("🌍 Target Language:", cmb_ds_lang))
    layout.addWidget(gb_ds)

    # ── Gladia ──────────────────────────────────────
    txt_gladia_key = _make_key_edit("Gladia primary API key...")
    txt_gladia_extra = QTextEdit()
    txt_gladia_extra.setPlaceholderText(
        "Extra keys for rotation (one per line)")
    txt_gladia_extra.setFixedHeight(60)
    chk_gladia_rotate = QCheckBox("Rotate keys when quota exhausted")
    cmb_gladia_lang = _make_lang_combo()

    gb_gladia = _make_group_box("📡 Gladia")
    gl = QVBoxLayout(gb_gladia)
    gl.setSpacing(6)
    gl.addLayout(_label_row("🔑 Primary Key:", txt_gladia_key))
    gl.addWidget(QLabel("📋 Extra Keys (one per line):"))
    gl.addWidget(txt_gladia_extra)
    gl.addWidget(chk_gladia_rotate)
    gl.addLayout(_label_row("🌍 Target Language:", cmb_gladia_lang))
    layout.addWidget(gb_gladia)

    # ── Azure TTS ───────────────────────────────────
    txt_azure_key = _make_key_edit("Azure Cognitive Services key...")
    txt_azure_region = QLineEdit()
    txt_azure_region.setPlaceholderText("e.g. eastus, southeastasia")

    gb_azure = _make_group_box("☁️ Azure TTS")
    gl = QVBoxLayout(gb_azure)
    gl.setSpacing(6)
    gl.addLayout(_label_row("🔑 API Key:", txt_azure_key))
    gl.addLayout(_label_row("🗺️ Region:", txt_azure_region))
    layout.addWidget(gb_azure)

    layout.addStretch()

    # ── Load / Save ──────────────────────────────────
    def load():
        try:
            cfg = settings_manager.get_openai_api_config()
            txt_openai_key.setText(cfg.get('api_key', ''))
            idx = cmb_openai_model.findData(cfg.get('model', 'gpt-4o-mini'))
            if idx >= 0:
                cmb_openai_model.setCurrentIndex(idx)
            chk_openai_translate.setChecked(
                bool(cfg.get('auto_translate', False)))
            idx = cmb_openai_lang.findData(cfg.get('target_language', 'km'))
            if idx >= 0:
                cmb_openai_lang.setCurrentIndex(idx)
        except Exception as e:
            print(f"[SETTINGS] Load OpenAI: {e}")

        try:
            cfg = settings_manager.get_groq_api_config()
            txt_groq_key.setText(cfg.get('api_key', ''))
            chk_groq_translate.setChecked(
                bool(cfg.get('auto_translate', False)))
            idx = cmb_groq_lang.findData(cfg.get('target_language', 'km'))
            if idx >= 0:
                cmb_groq_lang.setCurrentIndex(idx)
        except Exception as e:
            print(f"[SETTINGS] Load Groq: {e}")

        try:
            cfg = settings_manager.get_assemblyai_api_config()
            txt_aai_key.setText(cfg.get('api_key', ''))
            chk_aai_translate.setChecked(
                bool(cfg.get('auto_translate', False)))
            idx = cmb_aai_lang.findData(cfg.get('target_language', 'km'))
            if idx >= 0:
                cmb_aai_lang.setCurrentIndex(idx)
        except Exception as e:
            print(f"[SETTINGS] Load AssemblyAI: {e}")

        try:
            cfg = settings_manager.get_deepseek_api_config()
            txt_ds_key.setText(cfg.get('api_key', ''))
            idx = cmb_ds_model.findData(cfg.get('model', 'deepseek-chat'))
            if idx >= 0:
                cmb_ds_model.setCurrentIndex(idx)
            chk_ds_translate.setChecked(bool(cfg.get('auto_translate', False)))
            idx = cmb_ds_lang.findData(cfg.get('target_language', 'km'))
            if idx >= 0:
                cmb_ds_lang.setCurrentIndex(idx)
        except Exception as e:
            print(f"[SETTINGS] Load DeepSeek: {e}")

        try:
            cfg = settings_manager.get_gladia_api_config()
            txt_gladia_key.setText(cfg.get('api_key', ''))
            extra = [k for k in cfg.get(
                'api_keys', []) if k != cfg.get('api_key', '')]
            txt_gladia_extra.setPlainText('\n'.join(extra))
            chk_gladia_rotate.setChecked(bool(cfg.get('rotate_keys', True)))
            idx = cmb_gladia_lang.findData(cfg.get('target_language', 'km'))
            if idx >= 0:
                cmb_gladia_lang.setCurrentIndex(idx)
        except Exception as e:
            print(f"[SETTINGS] Load Gladia: {e}")

        try:
            cfg = settings_manager.get_azure_api_config()
            txt_azure_key.setText(cfg.get('api_key', ''))
            txt_azure_region.setText(cfg.get('region', ''))
        except Exception as e:
            print(f"[SETTINGS] Load Azure: {e}")

    def save():
        try:
            settings_manager.save_openai_api_config(
                api_key=txt_openai_key.text().strip(),
                auto_translate=chk_openai_translate.isChecked(),
                target_language=cmb_openai_lang.currentData() or 'km',
                model=cmb_openai_model.currentData() or 'gpt-4o-mini',
            )
        except Exception as e:
            print(f"[SETTINGS] Save OpenAI: {e}")

        try:
            settings_manager.save_groq_api_config(
                api_key=txt_groq_key.text().strip(),
                auto_translate=chk_groq_translate.isChecked(),
                target_language=cmb_groq_lang.currentData() or 'km',
            )
        except Exception as e:
            print(f"[SETTINGS] Save Groq: {e}")

        try:
            settings_manager.save_assemblyai_api_config(
                api_key=txt_aai_key.text().strip(),
                auto_translate=chk_aai_translate.isChecked(),
                target_language=cmb_aai_lang.currentData() or 'km',
            )
        except Exception as e:
            print(f"[SETTINGS] Save AssemblyAI: {e}")

        try:
            settings_manager.save_deepseek_api_config(
                api_key=txt_ds_key.text().strip(),
                auto_translate=chk_ds_translate.isChecked(),
                target_language=cmb_ds_lang.currentData() or 'km',
                model=cmb_ds_model.currentData() or 'deepseek-chat',
            )
        except Exception as e:
            print(f"[SETTINGS] Save DeepSeek: {e}")

        try:
            extra_keys = [
                k.strip() for k in txt_gladia_extra.toPlainText().splitlines() if k.strip()]
            settings_manager.save_gladia_api_config(
                api_key=txt_gladia_key.text().strip(),
                api_keys=extra_keys,
                rotate_keys=chk_gladia_rotate.isChecked(),
                target_language=cmb_gladia_lang.currentData() or 'km',
            )
        except Exception as e:
            print(f"[SETTINGS] Save Gladia: {e}")

        try:
            settings_manager.save_azure_api_config(
                api_key=txt_azure_key.text().strip(),
                region=txt_azure_region.text().strip(),
            )
        except Exception as e:
            print(f"[SETTINGS] Save Azure: {e}")

    return _scrollable(page), load, save


# ── Tab 2: Translation ─────────────────────────────────────────────────────────

def _build_translation_tab():
    """Build the '🌍 Translation' tab. Returns (scroll_widget, load_fn, save_fn)."""
    import settings_manager

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(12)
    layout.setContentsMargins(16, 16, 16, 16)

    # Translation Engine
    gb_engine = _make_group_box("⚙️ Translation Engine")
    gl = QVBoxLayout(gb_engine)
    gl.addWidget(_hint(
        "Select which AI or service is used to translate subtitles after transcription."))

    cmb_engine = QComboBox()
    for label, code in [
        ("🤖 Auto (Gemini if key available, else Google)", "auto"),
        ("🤖 Gemini AI — best quality, context-aware", "gemini"),
        ("🌐 Google Translate — free, fast fallback", "google"),
        ("🤖 OpenAI GPT-4.1 mini", "openai_gpt41_mini"),
    ]:
        cmb_engine.addItem(label, code)
    gl.addWidget(cmb_engine)
    layout.addWidget(gb_engine)

    # Default target language
    gb_lang = _make_group_box("🎯 Default Transcribe Target Language")
    gl = QVBoxLayout(gb_lang)
    gl.addWidget(_hint(
        "The language shown by default in the Transcribe dialog when you click 🎙️ Transcribe. "
        "The user can still change it each time."
    ))
    cmb_default_lang = _make_lang_combo('km')
    gl.addWidget(cmb_default_lang)
    layout.addWidget(gb_lang)

    layout.addStretch()

    def load():
        try:
            cfg = settings_manager.get_translation_config()
            idx = cmb_engine.findData(cfg.get('engine', 'gemini'))
            if idx >= 0:
                cmb_engine.setCurrentIndex(idx)
        except Exception as e:
            print(f"[SETTINGS] Load translation engine: {e}")

        try:
            config = settings_manager.read_config()
            lang = config.get('transcribe_target_language',
                              config.get('gemini_target_language', 'km'))
            idx = cmb_default_lang.findData(lang)
            if idx >= 0:
                cmb_default_lang.setCurrentIndex(idx)
        except Exception as e:
            print(f"[SETTINGS] Load default lang: {e}")

    def save():
        try:
            settings_manager.save_translation_config(
                cmb_engine.currentData() or 'gemini')
        except Exception as e:
            print(f"[SETTINGS] Save translation engine: {e}")

        try:
            lang = cmb_default_lang.currentData() or 'km'
            settings_manager.write_config({
                'transcribe_target_language': lang,
                'gemini_target_language': lang,
            })
        except Exception as e:
            print(f"[SETTINGS] Save default lang: {e}")

    return _scrollable(page), load, save


# ── Tab 3: Appearance & Subtitles ─────────────────────────────────────────────

def _build_appearance_tab():
    """Build the '🎨 Appearance' tab. Returns (scroll_widget, load_fn, save_fn)."""
    import settings_manager

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(12)
    layout.setContentsMargins(16, 16, 16, 16)

    # Theme
    gb_theme = _make_group_box("🎨 UI Theme")
    gl = QVBoxLayout(gb_theme)
    gl.addWidget(
        _hint("Theme change takes effect after restarting the application."))
    btn_group = QButtonGroup(gb_theme)
    rb_dark = QRadioButton("🌙 Dark (default)")
    rb_light = QRadioButton("☀️ Light")
    btn_group.addButton(rb_dark)
    btn_group.addButton(rb_light)
    rb_dark.setChecked(True)
    gl.addWidget(rb_dark)
    gl.addWidget(rb_light)
    layout.addWidget(gb_theme)

    # Burn Subtitle Style
    gb_sub = _make_group_box("📝 Burn Subtitle Style")
    gl = QVBoxLayout(gb_sub)
    gl.setSpacing(8)
    gl.addWidget(_hint(
        "Applies when you use 'Burn Subtitles into video'. Does not affect SRT export."))

    # Font family
    txt_font_family = QLineEdit()
    txt_font_family.setPlaceholderText("Leave blank for system default")
    gl.addLayout(_label_row("Font Family:", txt_font_family))

    # Font size
    spn_font_size = QSpinBox()
    spn_font_size.setRange(1, 120)
    spn_font_size.setValue(10)
    gl.addLayout(_label_row("Font Size (pt):", spn_font_size))

    # Font color
    _font_color = ['#FFFFFF']
    btn_font_color = QPushButton("  #FFFFFF")
    btn_font_color.setStyleSheet(
        "background-color: #FFFFFF; color: #000000; "
        "padding: 5px 10px; border: 1px solid #64748B; border-radius: 6px;"
    )

    def _update_color_btn(btn, color_ref, new_color):
        color_ref[0] = new_color
        text_col = "#000000" if _luma(new_color) > 128 else "#FFFFFF"
        btn.setStyleSheet(
            f"background-color: {new_color}; color: {text_col}; "
            f"padding: 5px 10px; border: 1px solid #64748B; border-radius: 6px;"
        )
        btn.setText(f"  {new_color}")

    def pick_font_color(checked=False):
        c = QColorDialog.getColor(
            QColor(_font_color[0]), page, "Choose Font Color")
        if c.isValid():
            _update_color_btn(btn_font_color, _font_color, c.name())

    btn_font_color.clicked.connect(pick_font_color)
    gl.addLayout(_label_row("Font Color:", btn_font_color))

    # Font opacity
    sld_opacity = QSlider(Qt.Orientation.Horizontal)
    sld_opacity.setRange(0, 100)
    sld_opacity.setValue(100)
    lbl_opacity_val = QLabel("100%")
    lbl_opacity_val.setFixedWidth(36)
    sld_opacity.valueChanged.connect(
        lambda v: lbl_opacity_val.setText(f"{v}%"))

    h_opacity = QHBoxLayout()
    lbl_opacity_lbl = QLabel("Font Opacity:")
    lbl_opacity_lbl.setFixedWidth(145)
    h_opacity.addWidget(lbl_opacity_lbl)
    h_opacity.addWidget(sld_opacity, 1)
    h_opacity.addWidget(lbl_opacity_val)
    gl.addLayout(h_opacity)

    # Background color
    _bg_color = ['#9B000000']
    btn_bg_color = QPushButton("  #9B000000")
    btn_bg_color.setStyleSheet(
        "background-color: #000000; color: #FFFFFF; "
        "padding: 5px 10px; border: 1px solid #64748B; border-radius: 6px;"
    )

    def pick_bg_color(checked=False):
        raw = _bg_color[0]
        # Strip alpha prefix (#AARRGGBB → #RRGGBB) for color dialog
        hex_rgb = '#' + \
            raw.lstrip('#')[-6:] if len(raw.lstrip('#')) >= 6 else '#000000'
        c = QColorDialog.getColor(
            QColor(hex_rgb), page, "Choose Background Color")
        if c.isValid():
            _update_color_btn(btn_bg_color, _bg_color, c.name())

    btn_bg_color.clicked.connect(pick_bg_color)
    gl.addLayout(_label_row("Background Color:", btn_bg_color))

    # Shadow
    chk_shadow = QCheckBox("Enable text shadow")
    gl.addWidget(chk_shadow)
    layout.addWidget(gb_sub)

    layout.addStretch()

    def load():
        try:
            mode = settings_manager.get_theme_mode()
            (rb_light if mode == 'light' else rb_dark).setChecked(True)
        except Exception as e:
            print(f"[SETTINGS] Load theme: {e}")

        try:
            cfg = settings_manager.get_burn_subtitle_config()
            txt_font_family.setText(cfg.get('font_family', ''))
            spn_font_size.setValue(cfg.get('font_size', 10))

            fc = cfg.get('font_color', '#FFFFFF')
            _update_color_btn(btn_font_color, _font_color, fc)

            sld_opacity.setValue(cfg.get('font_opacity', 100))

            bgc = cfg.get('background_color', '#9B000000')
            _bg_color[0] = bgc
            btn_bg_color.setText(f"  {bgc}")

            chk_shadow.setChecked(bool(cfg.get('shadow_enabled', False)))
        except Exception as e:
            print(f"[SETTINGS] Load burn subtitle: {e}")

    def save():
        try:
            mode = 'light' if rb_light.isChecked() else 'dark'
            settings_manager.save_theme_mode(mode)
            try:
                from theme_manager import apply_theme
                apply_theme(mode)
            except Exception:
                pass
        except Exception as e:
            print(f"[SETTINGS] Save theme: {e}")

        try:
            settings_manager.save_burn_subtitle_config(
                font_family=txt_font_family.text().strip(),
                font_size=spn_font_size.value(),
                font_color=_font_color[0],
                background_color=_bg_color[0],
                font_opacity=sld_opacity.value(),
                shadow_enabled=chk_shadow.isChecked(),
            )
        except Exception as e:
            print(f"[SETTINGS] Save burn subtitle: {e}")

    return _scrollable(page), load, save


# ── Tab 4: Export & Batch ──────────────────────────────────────────────────────

def _build_export_tab():
    """Build the '📤 Export' tab. Returns (scroll_widget, load_fn, save_fn)."""
    import settings_manager

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(12)
    layout.setContentsMargins(16, 16, 16, 16)

    # Audio Mix
    gb_mix = _make_group_box("🎵 Export Audio Mix")
    gl = QVBoxLayout(gb_mix)
    gl.setSpacing(8)
    gl.addWidget(_hint(
        "Set the loudness of each audio layer in the exported dubbed video. "
        "100% = original volume. Use >100% to boost or 0% to mute."
    ))

    def _spin_row(label_text, default_val):
        h = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setFixedWidth(230)
        spn = QSpinBox()
        spn.setRange(0, 500)
        spn.setValue(default_val)
        spn.setSuffix("  %")
        spn.setStyleSheet("padding: 4px; min-width: 80px;")
        h.addWidget(lbl)
        h.addWidget(spn)
        h.addStretch()
        return h, spn

    h_bg, spn_bg = _spin_row("🎵 Background Music Volume:", 30)
    h_ai, spn_ai = _spin_row("🎙️ AI Voice Volume:", 100)
    gl.addLayout(h_bg)
    gl.addLayout(h_ai)
    layout.addWidget(gb_mix)

    # Batch Output Directory
    gb_batch = _make_group_box("📁 Batch Output Directory")
    gl = QVBoxLayout(gb_batch)
    gl.addWidget(_hint(
        "Default output folder for Batch Dubbing. Leave blank to save next to each source video."))

    h_dir = QHBoxLayout()
    txt_batch_dir = QLineEdit()
    txt_batch_dir.setPlaceholderText("(blank = same folder as source video)")

    btn_browse = QPushButton("📂 Browse...")
    btn_browse.setObjectName("secondaryBtn")
    btn_clear = QPushButton("Clear")
    btn_clear.setObjectName("secondaryBtn")

    def browse_dir(checked=False):
        d = QFileDialog.getExistingDirectory(
            page, "Select Batch Output Directory", txt_batch_dir.text())
        if d:
            txt_batch_dir.setText(d)

    btn_browse.clicked.connect(browse_dir)
    btn_clear.clicked.connect(lambda: txt_batch_dir.clear())

    h_dir.addWidget(txt_batch_dir, 1)
    h_dir.addWidget(btn_browse)
    h_dir.addWidget(btn_clear)
    gl.addLayout(h_dir)
    layout.addWidget(gb_batch)

    # Video Quality & Facebook Compression
    gb_video = _make_group_box("📹 Video Quality & Facebook Compression")
    gv = QVBoxLayout(gb_video)
    gv.setSpacing(8)
    gv.addWidget(_hint(
        "Optimize video resolution and compress file size for Facebook and web uploads.\n"
        "Facebook recommends 720p HD (2.5 - 3.5 Mbps) which reduces 1-minute video size from ~100MB to ~20-25MB."
    ))

    h_preset = QHBoxLayout()
    lbl_preset = QLabel("📹 Video Resolution & Preset:")
    lbl_preset.setFixedWidth(230)
    cmb_video_quality = QComboBox()
    cmb_video_quality.addItem("Auto / Match Source (Recommended - Smart Size, ~15-20MB)", "auto")
    cmb_video_quality.addItem("720p HD (Facebook Standard - Downscale Only, ~20MB)", "720p")
    cmb_video_quality.addItem("1080p Full HD (Downscale Only, ~35-45MB)", "1080p")
    cmb_video_quality.addItem("Original Source Resolution (Preserve Stream)", "source")
    cmb_video_quality.setStyleSheet("padding: 4px; min-width: 280px;")
    h_preset.addWidget(lbl_preset)
    h_preset.addWidget(cmb_video_quality)
    h_preset.addStretch()
    gv.addLayout(h_preset)

    chk_faststart = QCheckBox("🚀 Optimize MP4 for Facebook & Streaming (+faststart)")
    chk_faststart.setChecked(True)
    chk_faststart.setToolTip("Places MOOV atom at the front of the MP4 container so Facebook can process and stream the video instantly.")
    gv.addWidget(chk_faststart)

    layout.addWidget(gb_video)

    layout.addStretch()

    def load():
        try:
            cfg = settings_manager.get_export_audio_mix_config()
            spn_bg.setValue(cfg.get('background_percent', 30))
            spn_ai.setValue(cfg.get('ai_voice_percent', 100))
        except Exception as e:
            print(f"[SETTINGS] Load audio mix: {e}")

        try:
            d = settings_manager.get_batch_output_dir()
            txt_batch_dir.setText(d or '')
        except Exception as e:
            print(f"[SETTINGS] Load batch output dir: {e}")

        try:
            vcfg = settings_manager.get_export_video_config()
            q = vcfg.get('video_quality', 'auto')
            idx = cmb_video_quality.findData(q)
            if idx >= 0:
                cmb_video_quality.setCurrentIndex(idx)
            chk_faststart.setChecked(vcfg.get('facebook_faststart', True))
        except Exception as e:
            print(f"[SETTINGS] Load video quality: {e}")

    def save():
        try:
            settings_manager.save_export_audio_mix_config(
                background_percent=spn_bg.value(),
                ai_voice_percent=spn_ai.value(),
            )
        except Exception as e:
            print(f"[SETTINGS] Save audio mix: {e}")

        try:
            settings_manager.save_batch_output_dir(
                txt_batch_dir.text().strip())
        except Exception as e:
            print(f"[SETTINGS] Save batch dir: {e}")

        try:
            chosen_q = cmb_video_quality.currentData() or "auto"
            settings_manager.save_export_video_config(
                video_quality=chosen_q,
                video_crf=25,
                facebook_faststart=chk_faststart.isChecked(),
                compress_enabled=(chosen_q != "source"),
                allow_upscale=False,
                audio_bitrate="96k",
            )
        except Exception as e:
            print(f"[SETTINGS] Save video quality: {e}")

    return _scrollable(page), load, save


# ── Tab 5: Advanced ────────────────────────────────────────────────────────────

def _build_advanced_tab():
    """Build the '🔧 Advanced' tab. Returns (scroll_widget, load_fn, save_fn)."""
    import settings_manager

    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSpacing(12)
    layout.setContentsMargins(16, 16, 16, 16)

    # UI Feature Flags
    gb_flags = _make_group_box("🔌 UI Feature Flags")
    gl = QVBoxLayout(gb_flags)
    gl.addWidget(_hint(
        "Enable or disable optional UI modules. Changes take effect after restarting the app."))

    chk_voxcpm2 = QCheckBox("✅ Enable VoxCPM2 voice synthesis")
    chk_rvc = QCheckBox("✅ Enable RVC voice conversion")
    chk_voice_clone = QCheckBox("✅ Enable Voice Clone")
    for chk in [chk_voxcpm2, chk_rvc, chk_voice_clone]:
        chk.setChecked(True)
        gl.addWidget(chk)
    layout.addWidget(gb_flags)

    # VoxCPM2 Install Paths
    gb_vox = _make_group_box("📂 VoxCPM2 Install Paths (Advanced)")
    gl = QVBoxLayout(gb_vox)
    gl.addWidget(_hint(
        "Optional: configure external VoxCPM2 installation paths. "
        "Leave blank to use bundled defaults."
    ))

    path_fields = {}

    def _path_row(label_text, key, is_file=False):
        h = QHBoxLayout()
        lbl = QLabel(label_text)
        lbl.setFixedWidth(130)
        txt = QLineEdit()
        btn = QPushButton("📂")
        btn.setObjectName("secondaryBtn")
        btn.setFixedSize(32, 28)
        btn.setToolTip("Browse...")

        _key = key
        _is_file = is_file
        _txt = txt

        def _browse(checked=False):

            if _is_file:
                f, _ = QFileDialog.getOpenFileName(
                    page, f"Select {label_text}")
                if f:
                    _txt.setText(f)
            else:
                d = QFileDialog.getExistingDirectory(
                    page, f"Select {label_text}", _txt.text())
                if d:
                    _txt.setText(d)

        btn.clicked.connect(_browse)
        h.addWidget(lbl)
        h.addWidget(txt, 1)
        h.addWidget(btn)
        path_fields[_key] = txt
        return h

    gl.addLayout(_path_row("Source Dir:", "source_dir"))
    gl.addLayout(_path_row("Model Path:", "model_path", is_file=True))
    gl.addLayout(_path_row("Python Path:", "python_path", is_file=True))

    gl.addWidget(_hint("Package URLs for managed downloads (optional):"))

    txt_pkg_url = QLineEdit()
    txt_pkg_url.setPlaceholderText("VoxCPM2 package URL")
    txt_runtime_url = QLineEdit()
    txt_runtime_url.setPlaceholderText("VoxCPM2 runtime package URL")
    gl.addWidget(txt_pkg_url)
    gl.addWidget(txt_runtime_url)
    layout.addWidget(gb_vox)

    layout.addStretch()

    def load():
        try:
            flags = settings_manager.get_ui_feature_flags()
            chk_voxcpm2.setChecked(bool(flags.get('enable_voxcpm2', True)))
            chk_rvc.setChecked(bool(flags.get('enable_rvc', True)))
            chk_voice_clone.setChecked(
                bool(flags.get('enable_voice_clone', True)))
        except Exception as e:
            print(f"[SETTINGS] Load feature flags: {e}")

        try:
            cfg = settings_manager.get_voxcpm_install_config()
            path_fields['source_dir'].setText(cfg.get('source_dir', ''))
            path_fields['model_path'].setText(cfg.get('model_path', ''))
            path_fields['python_path'].setText(cfg.get('python_path', ''))
            txt_pkg_url.setText(cfg.get('package_url', ''))
            txt_runtime_url.setText(cfg.get('runtime_package_url', ''))
        except Exception as e:
            print(f"[SETTINGS] Load VoxCPM2 paths: {e}")

    def save():
        try:
            settings_manager.save_ui_feature_flags(
                enable_voxcpm2=chk_voxcpm2.isChecked(),
                enable_rvc=chk_rvc.isChecked(),
                enable_voice_clone=chk_voice_clone.isChecked(),
            )
        except Exception as e:
            print(f"[SETTINGS] Save feature flags: {e}")

        try:
            settings_manager.save_voxcpm_install_config(
                source_dir=path_fields['source_dir'].text().strip(),
                model_path=path_fields['model_path'].text().strip(),
                python_path=path_fields['python_path'].text().strip(),
                package_url=txt_pkg_url.text().strip(),
                runtime_package_url=txt_runtime_url.text().strip(),
            )
        except Exception as e:
            print(f"[SETTINGS] Save VoxCPM2 paths: {e}")

    return _scrollable(page), load, save


# ── Main Injection Entry Point ─────────────────────────────────────────────────

def inject_extra_settings_tabs(dialog, tab_widget):
    """
    Append the 5 extra settings tabs to the compiled Settings QTabWidget.

    Called from _open_settings_dialog_enhanced() in core_app.py after the
    compiled dialog has been created and is visible.
    """
    try:
        # Build all 5 new tabs
        w1, load1, save1 = _build_more_apis_tab()
        w2, load2, save2 = _build_translation_tab()
        w3, load3, save3 = _build_appearance_tab()
        w4, load4, save4 = _build_export_tab()
        w5, load5, save5 = _build_advanced_tab()

        # Append to tab widget
        tab_widget.addTab(w1, "🔑 More APIs")
        tab_widget.addTab(w2, "🌍 Translation")
        tab_widget.addTab(w3, "🎨 Appearance")
        tab_widget.addTab(w4, "📤 Export")
        tab_widget.addTab(w5, "🔧 Advanced")

        # Load current values into all new tabs
        loaders = [load1, load2, load3, load4, load5]
        for loader in loaders:
            try:
                loader()
            except Exception as e:
                print(f"[SETTINGS] Tab load error: {e}")

        # Locate the Save/Accept button (green: #27AE60, padding: 8px 20px, or 'Save' / 'OK')
        # and hook our extended save onto its clicked signal.
        from PyQt5.QtWidgets import QPushButton
        save_btn = None
        for btn in dialog.findChildren(QPushButton):
            style = btn.styleSheet() or ''
            if '#27AE60' in style:
                save_btn = btn
                break

        if save_btn is None:
            for btn in dialog.findChildren(QPushButton):
                txt = (btn.text() or '').strip().lower()
                if 'save' in txt or 'ok' in txt:
                    save_btn = btn
                    break

        if save_btn is not None:
            savers = [save1, save2, save3, save4, save5]

            def _on_extended_save(checked=False):
                for saver in savers:
                    try:
                        saver()
                    except Exception as exc:
                        print(f"[SETTINGS] Extended save error: {exc}")
                print("[SETTINGS] Extended settings saved ✅")

            save_btn.clicked.connect(_on_extended_save)
            print(f"[SETTINGS] Hooked extended save → {save_btn.text()!r}")
        else:
            print(
                "[SETTINGS] ⚠ Could not locate Save button — extended settings will not auto-save.")

        # Modernize all buttons and apply complete 3-Color Design System theme
        apply_settings_dialog_theme(dialog)

        print(
            f"[SETTINGS] Injected 5 extra tabs. Total tabs: {tab_widget.count()}")

    except Exception as exc:
        import traceback
        print(f"[SETTINGS] inject_extra_settings_tabs failed: {exc}")
        traceback.print_exc()


def apply_settings_dialog_theme(dialog, mode=None):
    """
    Applies the 3-Color Design System theme (dark/light) to the settings dialog,
    including QTabWidget, tab bars, cards, labels, and scrollareas.
    """
    if mode is None:
        try:
            import settings_manager
            mode = settings_manager.get_theme_mode()
        except Exception:
            mode = "dark"
    is_dark = str(mode).strip().lower() == "dark"

    from ui_theme_tokens import (
        get_settings_dialog_stylesheet,
        COLOR_CANVAS, COLOR_SURFACE, COLOR_SURFACE_INPUT, COLOR_TEXT_PRIMARY, COLOR_TEXT_SECONDARY, COLOR_TEXT_MUTED,
        COLOR_BORDER, COLOR_BORDER_ELEVATED,
        LIGHT_COLOR_CANVAS, LIGHT_COLOR_SURFACE, LIGHT_COLOR_SURFACE_INPUT, LIGHT_COLOR_TEXT_PRIMARY,
        LIGHT_COLOR_TEXT_SECONDARY, LIGHT_COLOR_TEXT_MUTED, LIGHT_COLOR_BORDER, LIGHT_COLOR_BORDER_ELEVATED
    )
    from PyQt5.QtGui import QPalette, QColor
    from PyQt5.QtWidgets import QScrollArea, QLabel, QComboBox, QLineEdit, QTextEdit, QPlainTextEdit, QPushButton, QTabWidget

    canvas = COLOR_CANVAS if is_dark else LIGHT_COLOR_CANVAS
    surface = COLOR_SURFACE if is_dark else LIGHT_COLOR_SURFACE
    input_bg = COLOR_SURFACE_INPUT if is_dark else LIGHT_COLOR_SURFACE_INPUT
    card_bg = "#121824" if is_dark else "#F8FAFC"
    border = COLOR_BORDER if is_dark else LIGHT_COLOR_BORDER
    border_elevated = COLOR_BORDER_ELEVATED if is_dark else LIGHT_COLOR_BORDER_ELEVATED
    text_primary = COLOR_TEXT_PRIMARY if is_dark else LIGHT_COLOR_TEXT_PRIMARY
    text_secondary = COLOR_TEXT_SECONDARY if is_dark else LIGHT_COLOR_TEXT_SECONDARY
    text_muted = COLOR_TEXT_MUTED if is_dark else LIGHT_COLOR_TEXT_MUTED

    # 1. Apply dedicated settings stylesheet
    dialog.setStyleSheet(get_settings_dialog_stylesheet(mode))

    # 2. Synchronize QPalette to avoid OS gray bleed
    pal = dialog.palette()
    pal.setColor(QPalette.Window, QColor(canvas))
    pal.setColor(QPalette.WindowText, QColor(text_primary))
    pal.setColor(QPalette.Base, QColor(input_bg))
    pal.setColor(QPalette.Text, QColor(text_secondary))
    dialog.setPalette(pal)

    # 3. Clean up scroll areas
    for sa in dialog.findChildren(QScrollArea):
        sa.setAutoFillBackground(False)
        sa.setAttribute(Qt.WA_StyledBackground, True)
        if sa.viewport():
            sa.viewport().setAutoFillBackground(False)
            sa.viewport().setAttribute(Qt.WA_StyledBackground, True)
        if sa.widget():
            sa.widget().setAutoFillBackground(False)
            sa.widget().setAttribute(Qt.WA_StyledBackground, True)

    # 4. Sanitize labels and white info boxes
    for lbl in dialog.findChildren(QLabel):
        ss = lbl.styleSheet() or ""
        # Informational card boxes
        if any(w in ss for w in ["#FDFEFE", "#FBFCFC", "#F4F6F7", "white", "2px solid"]):
            lbl.setStyleSheet(f"background-color: {card_bg}; padding: 10px; border-radius: 8px; border: 1px solid {border_elevated}; color: {text_primary};")
        elif any(c in ss for c in ["#2C3E50", "#34495E", "#5D6D7E"]):
            if "16px" in ss:
                lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {text_primary}; padding: 8px;")
            elif "11px" in ss:
                lbl.setStyleSheet(f"color: {text_muted}; font-size: 11px;")
            else:
                lbl.setStyleSheet(f"font-weight: bold; color: {text_primary}; padding: 4px 0;")

    # 5. Sanitize combo boxes, line edits, text edits
    for cb in dialog.findChildren(QComboBox):
        cb.setStyleSheet("")
    for le in dialog.findChildren(QLineEdit):
        if "border: 2px solid" in (le.styleSheet() or ""):
            le.setStyleSheet("")
    for te in dialog.findChildren((QTextEdit, QPlainTextEdit)):
        te.setStyleSheet("")

    # 6. Demucs and dialog buttons
    for btn in dialog.findChildren(QPushButton):
        txt = btn.text().strip()
        txt_l = txt.lower()
        if "save" in txt_l or "ok" in txt_l:
            btn.setObjectName("primaryBtn")
            btn.setStyleSheet("")
        elif "cancel" in txt_l or "close" in txt_l or any(k in txt for k in ["Install", "Uninstall", "Refresh", "Browse", "Clear"]):
            if "uninstall" in txt_l:
                btn.setObjectName("dangerBtn")
            else:
                btn.setObjectName("secondaryBtn")
            btn.setStyleSheet("")

    # Attach apply_dialog_theme for live theme updates
    dialog.apply_dialog_theme = lambda new_mode=None: apply_settings_dialog_theme(dialog, new_mode)
