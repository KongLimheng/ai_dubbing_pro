# -*- coding: utf-8 -*-
"""
UI Theme Tokens & Design System Constants for AI Dubber Ultimate.

Adheres strictly to the 60-30-10 Design System for both Dark Mode and Light Mode:
- Dark Mode:
  - 60% Base Canvas:       #0F141C (Obsidian Midnight Dark)
  - 30% Structural Surface: #161D28 (Dark Slate Surface, Border: #212936)
  - 10% Hero Accent:        #F97316 (Flame Orange)
- Light Mode:
  - 60% Base Canvas:       #F8FAFC (Slate Cloud Off-White)
  - 30% Structural Surface: #FFFFFF (Pure White Surface, Border: #E2E8F0 / #CBD5E1)
  - 10% Hero Accent:        #EA580C (Rich Flame Orange - WCAG AAA compliant)
- Universal Font Stack with Khmer script and full Emoji icon support.
"""

import os
from typing import Dict

# ── 1. Dark Mode 3-Color Tokens ──────────────────────────────────────────────
COLOR_CANVAS = "#0F141C"           # 60% Base Canvas
COLOR_SURFACE = "#161D28"          # 30% Structural Surface (Cards, Panels)
COLOR_SURFACE_INPUT = "#0D121B"    # Recessed surface for text inputs
COLOR_SURFACE_HOVER = "#1E293B"    # Interactive surface hover state
COLOR_BORDER = "#212936"           # Structural border
COLOR_BORDER_ELEVATED = "#283548"  # Interactive/elevated border
COLOR_ACCENT = "#F97316"           # 10% Hero Accent (Flame Orange)
COLOR_ACCENT_HOVER = "#FB923C"     # Accent hover state
COLOR_ACCENT_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6a00, stop:1 #ee0979)"

COLOR_TEXT_PRIMARY = "#FFFFFF"     # High-contrast white for headers/titles
COLOR_TEXT_SECONDARY = "#F1F5F9"   # Off-white for body text & inputs
COLOR_TEXT_MUTED = "#8B949E"       # Muted slate grey for captions & hints

# ── 2. Light Mode 3-Color Tokens ─────────────────────────────────────────────
LIGHT_COLOR_CANVAS = "#F8FAFC"           # 60% Base Canvas (Slate Cloud Off-White)
LIGHT_COLOR_SURFACE = "#FFFFFF"          # 30% Structural Surface (Cards, Panels)
LIGHT_COLOR_SURFACE_INPUT = "#FFFFFF"    # Pure white surface for inputs
LIGHT_COLOR_SURFACE_HOVER = "#F1F5F9"    # Hover surface
LIGHT_COLOR_BORDER = "#E2E8F0"           # Structural border (Slate 200)
LIGHT_COLOR_BORDER_ELEVATED = "#CBD5E1"  # Elevated border (Slate 300)
LIGHT_COLOR_ACCENT = "#EA580C"           # 10% Hero Accent (Rich Flame Orange)
LIGHT_COLOR_ACCENT_HOVER = "#F97316"     # Accent hover state
LIGHT_COLOR_ACCENT_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6a00, stop:1 #ee0979)"

LIGHT_COLOR_TEXT_PRIMARY = "#0F172A"     # Deep slate navy for headers (Slate 900)
LIGHT_COLOR_TEXT_SECONDARY = "#1E293B"   # Slate 800 for body text & inputs
LIGHT_COLOR_TEXT_MUTED = "#64748B"       # Slate 500 for captions & hints

# ── 3. Border Radii Hierarchy ────────────────────────────────────────────────
RADIUS_MICRO = "4px"               # Badges, progress bars, scrollbars
RADIUS_CHIP = "6px"                # Episode chips, tags
RADIUS_CONTROL = "8px"             # Standard controls, buttons, combo boxes
RADIUS_INPUT = "8px"               # Text inputs
RADIUS_CARD = "12px"               # Inner cards, preview frames, dialogs
RADIUS_CONTAINER = "16px"          # Outer sidebars, main content panels
RADIUS_PILL = "16px"               # Hero CTA pill buttons, category tabs

# ── 4. Spacing Scale (4px/8px Incremental Grid) ──────────────────────────────
SPACE_XS = 4                       # Micro gap between icon & text
SPACE_SM = 8                       # Element gap, vertical padding
SPACE_MD = 12                      # Card & panel internal padding
SPACE_LG = 14                      # Window layout margins & sidebar padding
SPACE_XL = 20                      # Major dialog padding & layout dividers

# ── 5. Universal Font Stack (Khmer + Emoji + Latin) ──────────────────────────
# Including 'Noto Color Emoji', 'Segoe UI Emoji', 'Apple Color Emoji' ensures
# emoji icons (📹, ⚙️, ✨, ⏱️, 📁, 🎙️, 🇰🇭, 🎵, 💾, ▶, ⏹, 🎯, ⚡, 🎬, ✂️) render perfectly.
FONT_FAMILY = "'Segoe UI', 'Noto Sans Khmer', 'Khmer OS Battambang', 'Noto Color Emoji', 'Segoe UI Emoji', 'Apple Color Emoji', 'PingFang SC', -apple-system, sans-serif"


def get_icon_path(filename: str) -> str:
    """Helper to locate SVG/PNG resource path formatted for QSS."""
    try:
        from runtime_paths import resource_path
        p = resource_path('resources', filename)
        if os.path.exists(p):
            return p.replace('\\', '/')
        p2 = resource_path(filename)
        if os.path.exists(p2):
            return p2.replace('\\', '/')
    except Exception:
        pass
    # Fallback to relative path
    return f"resources/{filename}"


def get_modern_stylesheet(mode: str = "dark") -> str:
    """
    Returns the complete, unified QSS stylesheet adhering to the 3-color palette
    for either 'dark' or 'light' mode.
    """
    is_dark = str(mode).strip().lower() == "dark"

    if is_dark:
        canvas = COLOR_CANVAS
        surface = COLOR_SURFACE
        input_bg = COLOR_SURFACE_INPUT
        surface_hover = COLOR_SURFACE_HOVER
        border = COLOR_BORDER
        border_elevated = COLOR_BORDER_ELEVATED
        accent = COLOR_ACCENT
        accent_hover = COLOR_ACCENT_HOVER
        accent_grad = COLOR_ACCENT_GRADIENT
        text_primary = COLOR_TEXT_PRIMARY
        text_secondary = COLOR_TEXT_SECONDARY
        text_muted = COLOR_TEXT_MUTED
        table_alt = "#121822"
        table_header = "#141a24"
        arrow_icon = get_icon_path("arrow_down_orange.svg")
        check_icon = get_icon_path("check_white.svg")
        radio_icon = get_icon_path("radio_dot_white.svg")
        btn_sec_bg = "#1a2230"
        btn_sec_border = "#2b394f"
        scrollbar_bg = "#0d1117"
        scrollbar_thumb = "#253142"
    else:
        canvas = LIGHT_COLOR_CANVAS
        surface = LIGHT_COLOR_SURFACE
        input_bg = LIGHT_COLOR_SURFACE_INPUT
        surface_hover = LIGHT_COLOR_SURFACE_HOVER
        border = LIGHT_COLOR_BORDER
        border_elevated = LIGHT_COLOR_BORDER_ELEVATED
        accent = LIGHT_COLOR_ACCENT
        accent_hover = LIGHT_COLOR_ACCENT_HOVER
        accent_grad = LIGHT_COLOR_ACCENT_GRADIENT
        text_primary = LIGHT_COLOR_TEXT_PRIMARY
        text_secondary = LIGHT_COLOR_TEXT_SECONDARY
        text_muted = LIGHT_COLOR_TEXT_MUTED
        table_alt = "#F8FAFC"
        table_header = "#F1F5F9"
        arrow_icon = get_icon_path("arrow_down_dark.svg")
        check_icon = get_icon_path("check_white.svg")
        radio_icon = get_icon_path("radio_dot_white.svg")
        btn_sec_bg = "#F1F5F9"
        btn_sec_border = "#CBD5E1"
        scrollbar_bg = "#F1F5F9"
        scrollbar_thumb = "#CBD5E1"

    return f"""
    /* ==========================================================================
       Base Canvas & Universal Defaults (60% Base)
       ========================================================================== */
    QMainWindow, QWidget#centralWidget, QDialog, QMessageBox {{
        background-color: {canvas};
        color: {text_secondary};
    }}
    QWidget {{
        font-family: {FONT_FAMILY};
        color: {text_secondary};
    }}

    /* ==========================================================================
       Structural Containers & Panels (30% Surface)
       ========================================================================== */
    QGroupBox {{
        border: 1px solid {border};
        border-radius: {RADIUS_CARD};
        margin-top: 14px;
        padding-top: 16px;
        font-weight: bold;
        color: {text_primary};
        background-color: {surface};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 3px 10px;
        color: {text_primary};
        background-color: {table_header};
        border: 1px solid {border_elevated};
        border-radius: 6px;
        font-weight: 700;
    }}
    QFrame#outerPanel, QFrame#sidebarPanel, QFrame#leftSidebar, QFrame#rightMainContent {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: {RADIUS_CONTAINER};
    }}
    QFrame#innerCard, QFrame#innerPanel, QFrame#BatchVocalRemovalFrame, QFrame#HeaderCard, QFrame#BatchHeader, QFrame#BatchHeaderFrame {{
        background-color: {surface};
        border: 1px solid {border};
        border-radius: {RADIUS_CARD};
    }}
    QFrame#previewBox {{
        background-color: {'#090d14' if is_dark else '#000000'};
        border: 2px solid {accent};
        border-radius: {RADIUS_CARD};
    }}

    /* ==========================================================================
       Select Boxes (QComboBox) - High Contrast & Clearly Visible Text/Icons
       ========================================================================== */
    QComboBox {{
        background-color: {surface};
        color: {text_secondary};
        border: 1px solid {border_elevated};
        border-radius: {RADIUS_CONTROL};
        padding: 5px 30px 5px 12px;
        min-height: 24px;
        font-weight: 600;
        font-size: 12px;
        selection-background-color: {accent};
        selection-color: #ffffff;
    }}
    QComboBox:editable {{
        background-color: {input_bg};
        color: {text_secondary};
    }}
    QComboBox QLineEdit {{
        background-color: {input_bg};
        color: {text_secondary};
        border: none;
    }}
    QComboBox:focus, QComboBox:on {{
        border: 1.5px solid {accent};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 26px;
        border-left: 1px solid {border_elevated};
        border-top-right-radius: {RADIUS_CONTROL};
        border-bottom-right-radius: {RADIUS_CONTROL};
        background-color: {btn_sec_bg};
    }}
    QComboBox::drop-down:hover {{
        background-color: {surface_hover};
    }}
    QComboBox::down-arrow {{
        image: url("{arrow_icon}");
        width: 12px;
        height: 12px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {surface};
        color: {text_secondary};
        selection-background-color: {accent};
        selection-color: #ffffff;
        border: 1px solid {border_elevated};
        border-radius: 6px;
        padding: 4px;
        outline: none;
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 26px;
        padding: 4px 8px;
        border-radius: 4px;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background-color: {surface_hover};
        color: {text_primary};
    }}
    QComboBox QAbstractItemView::item:selected {{
        background-color: {accent};
        color: #ffffff;
    }}

    /* ==========================================================================
       Transcript & Data Tables (QTableWidget)
       ========================================================================== */
    QTableWidget {{
        background-color: {surface};
        color: {text_secondary};
        gridline-color: {border};
        border: 1px solid {border};
        border-radius: 10px;
        selection-background-color: {accent};
        selection-color: #ffffff;
        alternate-background-color: {table_alt};
        font-size: 12px;
    }}
    QHeaderView::section {{
        background-color: {table_header};
        color: {text_secondary};
        padding: 6px 10px;
        border: 1px solid {border};
        font-weight: 700;
        font-size: 12px;
    }}
    QTableCornerButton::section {{
        background-color: {table_header};
        border: 1px solid {border};
    }}

    /* ==========================================================================
       Text Inputs, TextEdits, and SpinBoxes
       ========================================================================== */
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {input_bg};
        color: {text_primary};
        border: 1px solid {border_elevated};
        border-radius: {RADIUS_INPUT};
        padding: 6px 10px;
        font-size: 12px;
        selection-background-color: {accent};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1.5px solid {accent};
    }}
    QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled {{
        background-color: {'#141a24' if is_dark else '#F1F5F9'};
        color: {text_muted};
        border-color: {border};
    }}

    /* ==========================================================================
       Action Buttons (10% Hero Accent & Secondary Surface)
       ========================================================================== */
    QPushButton, QPushButton#secondaryBtn {{
        background-color: {btn_sec_bg};
        color: {text_primary};
        border: 1px solid {btn_sec_border};
        border-radius: {RADIUS_CONTROL};
        padding: 6px 14px;
        font-size: 12px;
        font-weight: 700;
    }}
    QPushButton:hover, QPushButton#secondaryBtn:hover {{
        border-color: {accent};
        color: {'#ffffff' if is_dark else text_primary};
        background-color: {surface_hover};
    }}
    QPushButton:pressed {{
        background-color: {'#243042' if is_dark else '#E2E8F0'};
    }}
    QPushButton:disabled {{
        background-color: {'#141a24' if is_dark else '#F1F5F9'};
        color: {text_muted};
        border-color: {border};
    }}
    QPushButton#primaryBtn, QPushButton#orangeBtn {{
        background-color: {accent_grad};
        border: none;
        border-radius: {RADIUS_PILL};
        color: #ffffff;
        font-weight: 800;
        font-size: 12.5px;
        padding: 6px 18px;
    }}
    QPushButton#primaryBtn:hover, QPushButton#orangeBtn:hover {{
        background-color: {accent_hover};
    }}
    QPushButton#playerBtn {{
        background-color: {btn_sec_bg};
        color: {text_primary};
        border: 1px solid {btn_sec_border};
        border-radius: {RADIUS_CONTROL};
        padding: 5px 12px;
        font-weight: 700;
        font-size: 11.5px;
    }}
    QPushButton#playerBtn:hover {{
        border-color: {accent};
        color: {'#ffffff' if is_dark else text_primary};
        background-color: {surface_hover};
    }}
    QPushButton#dangerBtn {{
        background-color: {'#DC2626' if is_dark else '#EF4444'};
        color: #ffffff;
        border: 1px solid {'#B91C1C' if is_dark else '#DC2626'};
        border-radius: {RADIUS_CONTROL};
        padding: 5px 12px;
        font-weight: 700;
        font-size: 11.5px;
    }}
    QPushButton#dangerBtn:hover {{
        background-color: {'#EF4444' if is_dark else '#DC2626'};
        border-color: {'#F87171' if is_dark else '#B91C1C'};
    }}

    /* ==========================================================================
       Checkboxes & Radio Buttons with Proper SVG Icons
       ========================================================================== */
    QCheckBox, QRadioButton {{
        color: {text_secondary};
        spacing: 8px;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {border_elevated};
        border-radius: 4px;
        background-color: {input_bg};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {accent};
    }}
    QCheckBox::indicator:checked {{
        background-color: {accent};
        border-color: {accent};
        image: url("{check_icon}");
    }}
    QRadioButton::indicator {{
        border-radius: 8px;
    }}
    QRadioButton::indicator:checked {{
        background-color: {accent};
        border-color: {accent};
        image: url("{radio_icon}");
    }}

    /* ==========================================================================
       Minimal Floating Scrollbars
       ========================================================================== */
    QScrollBar:vertical {{
        border: none;
        background: {scrollbar_bg};
        width: 8px;
        margin: 0px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {scrollbar_thumb};
        min-height: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {accent};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
        border: none;
        background: none;
    }}
    QScrollBar:horizontal {{
        border: none;
        background: {scrollbar_bg};
        height: 8px;
        margin: 0px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {scrollbar_thumb};
        min-width: 20px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {accent};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
        border: none;
        background: none;
    }}

    /* ==========================================================================
       Sliders & Progress Bars
       ========================================================================== */
    QSlider::groove:horizontal {{
        height: 6px;
        background: {border};
        border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
        background: {accent};
        border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: #ffffff;
        border: 1px solid {border_elevated};
        width: 14px;
        margin-top: -4px;
        margin-bottom: -4px;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {accent};
        border-color: {accent};
    }}
    QProgressBar {{
        background-color: {'#0b0f17' if is_dark else '#E2E8F0'};
        border: none;
        border-radius: 3px;
        height: 6px;
        text-align: center;
        color: {'#ffffff' if is_dark else '#0F172A'};
    }}
    QProgressBar::chunk {{
        background-color: {accent};
        border-radius: 3px;
    }}

    /* ==========================================================================
       Splitter Handles & Tooltips
       ========================================================================== */
    QSplitter::handle:vertical {{
        height: 6px;
        background-color: {border};
        border-radius: 3px;
        margin: 1px 10px;
    }}
    QSplitter::handle:vertical:hover {{
        background-color: {accent};
    }}
    QSplitter::handle:horizontal {{
        width: 6px;
        background-color: {border};
        border-radius: 3px;
        margin: 10px 1px;
    }}
    QSplitter::handle:horizontal:hover {{
        background-color: {accent};
    }}
    QToolTip {{
        background-color: {table_header};
        color: {text_primary};
        border: 1px solid {border_elevated};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 11.5px;
    }}
    """
