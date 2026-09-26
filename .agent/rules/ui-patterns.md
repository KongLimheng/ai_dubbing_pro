# UI Pattern & Design System Rules

> **MANDATORY RULE FOR ALL UI CODE AND AGENTS**
> Every GUI window, dialog, widget, or layout created or modified in this repository MUST strictly follow the design system rules documented below. This ensures a consistent, high-end, modern dark and light aesthetic with full icon and select box visibility.

---

## 1. The 3-Color Strict Palette (60-30-10 Rule)

To prevent visual clutter and maintain professional visual cohesion, the application UI is strictly governed by **3 core color roles** in both Dark and Light modes:

```
+--------------------------------------------------------------------------+
|  60% Base Canvas             |  30% Structural Surface   | 10% Accent   |
|  DARK:  #0F141C (Obsidian)   |  DARK:  #161D28 (Slate)   | #F97316      |
|  LIGHT: #F8FAFC (Cloud White)|  LIGHT: #FFFFFF (White)   | #EA580C      |
+--------------------------------------------------------------------------+
```

### Dark Mode 3 Core Colors
| Role | Percentage | Hex Code | Visual Identity | Usage & Rules |
|------|------------|----------|-----------------|---------------|
| **1. Base Canvas** | **60%** | `#0F141C` | **Obsidian Midnight Dark** | Main window backdrop, viewport wells, unselected track zones, dialog backdrops. Gives deep contrast without harsh pure black (`#000000`). |
| **2. Structural Surface** | **30%** | `#161D28` | **Sleek Charcoal Slate** | Cards, sidebars, group panels, input backgrounds (`#0D121B`), table rows, dialog bodies. Paired with subtle structural borders (`#212936` resting, `#283548` elevated). |
| **3. Hero Accent** | **10%** | `#F97316` | **Vibrant Flame Orange** | Primary Call-To-Action (CTA) buttons, active toggle chips, focused input borders (`QLineEdit:focus`), progress accents, key badges. |

### Light Mode 3 Core Colors
| Role | Percentage | Hex Code | Visual Identity | Usage & Rules |
|------|------------|----------|-----------------|---------------|
| **1. Base Canvas** | **60%** | `#F8FAFC` | **Slate Cloud Off-White** | Window background, viewports, unselected wells. Eliminates blinding white glare while keeping the workspace clean and modern. |
| **2. Structural Surface** | **30%** | `#FFFFFF` | **Elevated Crisp White** | Floating cards, group boxes, sidebars, transcript table rows, inputs. Paired with subtle `1px solid #E2E8F0` resting borders and `#CBD5E1` elevated borders. |
| **3. Hero Accent** | **10%** | `#EA580C` | **Rich Flame Orange** | Primary Hero CTAs (`#primaryBtn`), active tabs, focus rings (`1.5px solid #EA580C`), progress bars, and table row selection. Calibrated for WCAG AAA contrast on light backgrounds. |

### Text Contrast System
- **Dark Mode**: Primary text `#FFFFFF` / `#F1F5F9`, Secondary/Muted text `#94A3B8` / `#8B949E`.
- **Light Mode**: Primary text `#0F172A` (Slate 900), Secondary text `#1E293B` (Slate 800), Muted text `#64748B` (Slate 500).

---

## 2. Select Box (`QComboBox`) Visibility Rules

1. **Never Hardcode Inline White Backgrounds**:
   - Never write `background-color: white` or `#BDC3C7` on `QComboBox` widgets. Doing so creates invisible white text on white backgrounds in dark mode.
   - Always let `QComboBox` inherit from the global design system stylesheet or clear legacy styles with `combo.setStyleSheet("")`.
2. **Explicit Text & Selection Colors**:
   - Dark Mode: `background-color: #161d28; color: #f1f5f9; border: 1px solid #283548;`
   - Light Mode: `background-color: #ffffff; color: #1e293b; border: 1px solid #cbd5e1;`
   - Dropdown item selection must always be `selection-background-color: #f97316; selection-color: #ffffff;`.
3. **Dropdown Button & Arrow Icon**:
   - Always define `QComboBox::drop-down` with a distinct background (`#1a2230` in dark, `#f1f5f9` in light).
   - Always define `QComboBox::down-arrow` pointing to clean vector SVG assets (`arrow_down_orange.svg` in dark, `arrow_down_dark.svg` in light).

---

## 3. Icon & Emoji Display Rules

1. **Universal Font Stack with Emoji Fonts**:
   Every QSS `font-family` rule and PyQt font declaration MUST include emoji fonts:
   ```css
   font-family: 'Segoe UI', 'Noto Sans Khmer', 'Khmer OS Battambang', 'Noto Color Emoji', 'Segoe UI Emoji', 'Apple Color Emoji', 'PingFang SC', -apple-system, sans-serif;
   ```
   *Rationale:* Without `'Noto Color Emoji'`, `'Segoe UI Emoji'`, or `'Apple Color Emoji'`, Qt overrides the system font and emoji icons on buttons (`📹`, `⚙️`, `✨`, `⏱️`, `📁`, `🎙️`, `🇰🇭`, `🎵`, `💾`, `▶`, `⏹`, `🎯`, `⚡`, `🎬`, `✂️`) render as broken rectangular boxes or blanks on Linux and Windows.
2. **Checkboxes & Radio Buttons**:
   - `QCheckBox::indicator:checked` MUST display `image: url(".../check_white.svg");` on accent background instead of `image: none;`.
   - `QRadioButton::indicator:checked` MUST display `image: url(".../radio_dot_white.svg");` on accent background instead of `image: none;`.

---

## 4. Border Rules & Radius Hierarchy

### Border Widths & Interaction States
- **Standard Structural Border**: `1px solid #212936` (Dark) / `1px solid #E2E8F0` (Light).
- **Interactive / Elevated Border**: `1px solid #283548` (Dark) / `1px solid #CBD5E1` (Light).
- **Hover Border**: `1px solid #F97316` (Dark) / `1px solid #EA580C` (Light).
- **Active / Focused Border**: `1.5px solid #F97316` (Dark) / `1.5px solid #EA580C` (Light).
- **Primary Hero Button**: `border: none` (solid or gradient accent fill).

### Border Radius Hierarchy
| Tier | Radius Range | Target Components |
|------|--------------|-------------------|
| **Micro** | `4px - 6px` | Badges, progress bar tracks & chunks, scrollbar handles, episode chips. |
| **Controls** | `8px - 10px` | `QLineEdit`, `QTextEdit`, `QPushButton` (standard), `QComboBox`, queue list items. |
| **Cards & Panels** | `12px` | Inner cards, video preview containers (`QFrame#previewBox`), dialog bodies, group panels. |
| **Major Containers** | `16px - 20px` | Outer sidebar frames (`#leftSidebar`), main content frames (`#rightMainContent`), pill category buttons. |

---

## 5. Spacing Grid (4px / 8px Incremental Scale)

All margins, paddings, and layout spacings MUST be multiples of **4px**, using **8px** as the primary base rhythm:
- `4px` (`SPACE_XS`): Micro gaps between icon and text; chip padding.
- `8px` (`SPACE_SM`): Standard button vertical padding; input padding; row item spacing.
- `10px - 12px` (`SPACE_MD`): Panel internal content spacing; card padding; inner panel margins.
- `14px - 16px` (`SPACE_LG`): Main window layout margins (`setContentsMargins(14, 14, 14, 14)`); outer sidebar padding.
- `20px - 24px` (`SPACE_XL`): Major section dividers; dialog window padding.

---

## 6. Typography Hierarchy & Khmer Compatibility

- **Khmer Script Support**: Always ensure `apply_khmer_font_patch()` (from `src/utils.py`) is called on startup.
- **Type Scale**:
  - Hero / Window Title: `20px - 22px` (Weight `800`)
  - Section Title: `14px` (Weight `700`)
  - Card / Video Title: `12px - 13px` (Weight `700`)
  - Body / Inputs: `12px - 13px` (Weight `500` / `600`)
  - Subtitles / Meta: `10.5px - 11px` (Weight `400` / `600`, `line-height: 1.4`)
