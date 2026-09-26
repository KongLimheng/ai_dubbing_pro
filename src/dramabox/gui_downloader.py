# -*- coding: utf-8 -*-
"""
DramaBox & Multi-Platform Video Downloader GUI with Hongguo (红果短剧) Engine.
Unified Multi-Platform Downloader supporting Hongguo, DramaBox, ReelShort,
NetShort, ShortMax, PineDrama, GoodShort, FlickReels, FreeReels, Melolo,
TikTok, YouTube, and Facebook.
Redesigned to follow down.png UI layout with Khmer localization, modern dark theme,
platform switcher bar, live catalog explorer, 9:16 cyan preview card, episode
selector grid, and real-time download queue.
"""

import concurrent.futures
import html
import json
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from PyQt5.QtCore import (
    QObject,
    QPoint,
    QRect,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_log = logging.getLogger("dramabox.gui")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import Hongguo Client
try:
    from .hongguo import GENRES_MAP, HongguoClient
except ImportError:
    try:
        from hongguo import GENRES_MAP, HongguoClient
    except ImportError:
        HongguoClient = None
        GENRES_MAP = []

# Legacy platform bypass managers
try:
    from .dramabox import DramaBoxBypassManager
except ImportError:
    try:
        from dramabox import DramaBoxBypassManager
    except ImportError:
        DramaBoxBypassManager = None

try:
    from .reelshort import ReelShortBypassManager
except (ImportError, Exception):
    try:
        from reelshort import ReelShortBypassManager
    except (ImportError, Exception):
        ReelShortBypassManager = None

try:
    from .downloader import DramaboxDownloader
except ImportError:
    try:
        from downloader import DramaboxDownloader
    except ImportError:
        DramaboxDownloader = None

try:
    from .sekai_api import SekaiDramaAPI
except ImportError:
    try:
        from sekai_api import SekaiDramaAPI
    except ImportError:
        SekaiDramaAPI = None

APP_VERSION = "v1.3.0"
ORGANIZATION_NAME = "AI_Dubber"
APPLICATION_NAME = "VideoDownloader"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.dramaboxdb.com/",
}

SUPPORTED_PLATFORMS = [
    ("Hongguo", "🔥 Hongguo", "#ff4b2b", "Hongguo Short Dramas (49,000+ Titles)"),
    ("DramaBox", "🎬 DramaBox", "#00b4d8", "DramaBox Web & App Series"),
    ("ReelShort", "⚡ ReelShort", "#f59e0b", "ReelShort Original Short Dramas"),
    ("NetShort", "📱 NetShort", "#8b5cf6", "NetShort Mini Series"),
    ("ShortMax", "✨ ShortMax", "#3b82f6", "ShortMax Micro Dramas"),
    ("PineDrama", "🌲 PineDrama", "#10b981", "PineDrama Series"),
    ("GoodShort", "📖 GoodShort", "#6366f1", "GoodShort Dramas"),
    ("FlickReels", "🎭 FlickReels", "#a855f7", "FlickReels Series"),
    ("FreeReels", "🍿 FreeReels", "#f43f5e", "FreeReels Web Dramas"),
    ("Melolo", "📺 Melolo", "#0284c7", "Melolo Short Series"),
    ("TikTok", "🎵 TikTok", "#06b6d4", "TikTok Video Clips"),
    ("YouTube", "▶️ YouTube", "#ef4444", "YouTube Videos / Shorts"),
    ("Facebook", "👥 Facebook", "#2563eb", "Facebook Watch / Reels"),
]

FEATURED_PLATFORM_DRAMAS = {
    "DramaBox": [
        {"series_id": "41000109923", "title": "My Husband, The Peerless King", "episode_cnt": 80,
            "remarks": "Billionaire • Action", "cover": "", "platform": "DramaBox"},
        {"series_id": "41000108871", "title": "The Return of the True Heir", "episode_cnt": 95,
            "remarks": "Revenge • Drama", "cover": "", "platform": "DramaBox"},
        {"series_id": "41000105342", "title": "Alpha's Forbidden Bride", "episode_cnt": 75,
            "remarks": "Werewolf • Romance", "cover": "", "platform": "DramaBox"},
        {"series_id": "41000106214", "title": "Hidden Identity: The Secret CEO",
            "episode_cnt": 88, "remarks": "CEO • Marriage", "cover": "", "platform": "DramaBox"},
        {"series_id": "41000107750", "title": "Reborn to Dominate", "episode_cnt": 100,
            "remarks": "Rebirth • Urban", "cover": "", "platform": "DramaBox"},
        {"series_id": "41000104112", "title": "The Undercover Billionaire", "episode_cnt": 68,
            "remarks": "Suspense • Drama", "cover": "", "platform": "DramaBox"},
    ],
    "ReelShort": [
        {"series_id": "651e5927c3e5a557b494d41d", "title": "The Double Life of My Billionaire Husband",
            "episode_cnt": 70, "remarks": "Billionaire • Romance", "cover": "", "platform": "ReelShort"},
        {"series_id": "652932e67503f15bf44b4194", "title": "Never Divorce a Secret Billionaire",
            "episode_cnt": 65, "remarks": "Marriage • Drama", "cover": "", "platform": "ReelShort"},
        {"series_id": "6540c1ea319a5520845be935", "title": "Fatal Attraction to My Ex-Husband",
            "episode_cnt": 60, "remarks": "Revenge • Romance", "cover": "", "platform": "ReelShort"},
        {"series_id": "656972efba9a184ef4826b52", "title": "Love at First Bite: Alpha King",
            "episode_cnt": 72, "remarks": "Werewolf • Fantasy", "cover": "", "platform": "ReelShort"},
    ],
    "NetShort": [
        {"series_id": "2102304053906497538", "title": "Sweet Revenge of the Heiress",
            "episode_cnt": 60, "remarks": "NetShort • Revenge", "cover": "", "platform": "NetShort"},
        {"series_id": "2101928838831394817", "title": "The Billionaire's Secret Bodyguard",
            "episode_cnt": 50, "remarks": "NetShort • Action", "cover": "", "platform": "NetShort"},
    ],
    "ShortMax": [
        {"series_id": "34260", "title": "Hidup Setelah Perceraian", "episode_cnt": 141,
            "remarks": "ShortMax • Drama", "cover": "", "platform": "ShortMax"},
        {"series_id": "34290", "title": "Temptation of the Mafia Boss", "episode_cnt": 70,
            "remarks": "ShortMax • Romance", "cover": "", "platform": "ShortMax"},
    ],
    "PineDrama": [
        {"series_id": "7685069260926325780", "title": "Bunga di tebing, dendam istri",
            "episode_cnt": 50, "remarks": "PineDrama • Revenge", "cover": "", "platform": "PineDrama"},
        {"series_id": "7668868224314332181", "title": "Trapped in Love with the CEO",
            "episode_cnt": 55, "remarks": "PineDrama • Romance", "cover": "", "platform": "PineDrama"},
        {"series_id": "7652634668554294292", "title": "The Resilient Daughter-in-Law",
            "episode_cnt": 62, "remarks": "PineDrama • Family", "cover": "", "platform": "PineDrama"},
    ],
    "GoodShort": [
        {"series_id": "31001740822", "title": "Kabur dari Nikah, Malah Dapat Pembalap Sultan",
            "episode_cnt": 55, "remarks": "GoodShort • Urban", "cover": "", "platform": "GoodShort"},
    ],
    "FlickReels": [
        {"series_id": "420", "title": "Dendam Seberat 200 Kilo", "episode_cnt": 80,
            "remarks": "FlickReels • Revenge", "cover": "", "platform": "FlickReels"},
        {"series_id": "418", "title": "FlickReels Exclusive Series", "episode_cnt": 45,
            "remarks": "FlickReels • Drama", "cover": "", "platform": "FlickReels"},
    ],
    "FreeReels": [
        {"series_id": "85Cc9Ubgf5", "title": "Saat Kita Bertemu Lagi", "episode_cnt": 56,
            "remarks": "FreeReels • Romance", "cover": "", "platform": "FreeReels"},
    ],
    "Melolo": [
        {"series_id": "7681162981765286917",
            "title": "(Dub)Pria Idaman", "episode_cnt": 71, "remarks": "Melolo • Romance", "cover": "", "platform": "Melolo"},
    ],
    "TikTok": [
        {"series_id": "https://www.tiktok.com/@sample/video/1234567890", "title": "TikTok Short Drama Series",
            "episode_cnt": 1, "remarks": "TikTok • Clip", "cover": "", "platform": "TikTok"},
    ],
    "YouTube": [
        {"series_id": "https://www.youtube.com/watch?v=sample", "title": "YouTube Short Drama Full Video",
            "episode_cnt": 1, "remarks": "YouTube • HD", "cover": "", "platform": "YouTube"},
    ],
    "Facebook": [
        {"series_id": "https://www.facebook.com/watch/?v=sample", "title": "Facebook Watch Short Reel",
            "episode_cnt": 1, "remarks": "Facebook • Video", "cover": "", "platform": "Facebook"},
    ],
}


# ── URL & Parsing Helpers ───────────────────────────────────────────────────

def detect_platform_from_url(url_text: str) -> Optional[str]:
    if not url_text:
        return None
    t = str(url_text).strip().lower()
    if "hongguo" in t or "hongguoduanju" in t:
        return "Hongguo"
    if "dramabox" in t:
        return "DramaBox"
    if "reelshort" in t:
        return "ReelShort"
    if "netshort" in t:
        return "NetShort"
    if "shortmax" in t:
        return "ShortMax"
    if "pinedrama" in t:
        return "PineDrama"
    if "goodshort" in t:
        return "GoodShort"
    if "flickreels" in t:
        return "FlickReels"
    if "freereels" in t:
        return "FreeReels"
    if "melolo" in t:
        return "Melolo"
    if "tiktok.com" in t:
        return "TikTok"
    if "youtube.com" in t or "youtu.be" in t:
        return "YouTube"
    if "facebook.com" in t or "fb.watch" in t:
        return "Facebook"
    return None


def extract_id_from_input(input_text: str, platform: str = "") -> str:
    text = str(input_text).strip()
    if not text:
        return ""
    if not text.startswith("http://") and not text.startswith("https://"):
        return text.strip("/")

    try:
        parsed = urlparse(text)
        qs = parse_qs(parsed.query)
        for key in (
            "id", "v", "shortPlayId", "short_play_id", "bookId", "book_id",
            "playlet_id", "collection_id", "key", "dramaId", "episodeId"
        ):
            if key in qs and qs[key]:
                return str(qs[key][0]).strip()

        path = parsed.path.strip("/")
        patterns = [
            r"(?:watch|detail)/(?:[a-zA-Z0-9_\-]+)/([^/?#]+)",
            r"(?:movie|drama|ep|episode|show|shortplay|playlet|book|series|album/detail)/([^/?#]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, path, re.IGNORECASE)
            if match:
                return match.group(1).split("/")[0].strip()

        segments = [s for s in path.split("/") if s]
        if segments:
            return segments[-1].strip()
    except Exception:
        pass
    return text


def extract_next_data(page_html: str) -> dict:
    match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except Exception:
        return {}


def extract_series_title(page_html: str, default: str = "Drama") -> str:
    data = extract_next_data(page_html)
    props = data.get("props", {}).get("pageProps", {})
    book_info = props.get("bookInfo", {})
    for key in ("bookName", "bookTitle", "title", "seoTitle"):
        val = book_info.get(key) or props.get(key)
        if val:
            return str(val).strip()
    patterns = [
        r"<title[^>]*>(.*?)</title>",
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        r"<h1[^>]*>(.*?)</h1>",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
        if match:
            title = html.unescape(match.group(1)).strip()
            title = re.sub(
                r"\s*[-|]\s*(?:DramaBox|ReelShort|NetShort).*$", "", title, flags=re.IGNORECASE)
            if title:
                return title
    return default


def extract_poster_url(page_html: str) -> str:
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE)
        if match:
            url = html.unescape(match.group(1)).strip()
            if url.startswith("//"):
                return "https:" + url
            if url.startswith("/"):
                return "https://www.dramaboxdb.com" + url
            return url
    return ""


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "y", "yes", "true", "unlock", "unlocked"}:
            return True
        if lowered in {"0", "n", "no", "lock", "false", "locked"}:
            return False
    return default


def sanitize_filename(text: str, default: str = "file") -> str:
    if not text:
        return default
    cleaned = re.sub(r'[\\/*?:"<>|]+', "", str(text)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned[:180]:
        return default
    return cleaned[:180]


def normalize_media_url(url: str) -> str:
    if not url:
        return ""
    media_url = html.unescape(str(url)).strip()
    if media_url.startswith("//"):
        return "https:" + media_url
    if media_url.startswith("/"):
        return "https://www.dramaboxdb.com" + media_url
    return media_url


def request_headers_for_url(url: str) -> dict:
    headers = dict(REQUEST_HEADERS)
    if url and url.startswith("http"):
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    return headers


def normalize_chapter(chapter: dict, fallback_index: int) -> Optional[dict]:
    if not isinstance(chapter, dict):
        return None
    media_mp4 = normalize_media_url(chapter.get("mp4", ""))
    media_m3u8 = normalize_media_url(chapter.get("m3u8Url", ""))
    media_content = normalize_media_url(chapter.get("contentUrl", ""))
    cid = str(
        chapter.get("id")
        or chapter.get("chapterId")
        or chapter.get("chapter_id")
        or fallback_index + 1
    ).strip()
    if not cid:
        return None
    sort_index = safe_int(chapter.get("index"), fallback_index)
    raw_name = chapter.get("chapterName") or chapter.get(
        "episodeName") or chapter.get("title") or ""
    name = str(raw_name).strip() if str(
        raw_name).strip() else f"Episode {sort_index + 1}"
    unlock = coerce_bool(chapter.get("unlock"), False)
    if not unlock:
        for media_url in (media_mp4, media_m3u8, media_content):
            if media_url and "15s" not in media_url.lower():
                unlock = True
                break
    return {
        "id": cid,
        "index": sort_index,
        "sort_index": sort_index,
        "chapterName": name,
        "unlock": unlock,
        "mp4": media_mp4,
        "m3u8Url": media_m3u8,
        "contentUrl": media_content,
        "platform": chapter.get("platform", "DramaBox"),
        "episodeUrl": chapter.get("episodeUrl", ""),
        "resolvedUrl": chapter.get("resolvedUrl", ""),
    }


def normalize_chapter_list(chapters: list) -> list:
    chapter_map = {}
    if not chapters:
        return []
    for pos, chapter in enumerate(chapters):
        normalized = normalize_chapter(chapter, pos)
        if not normalized:
            continue
        cid = normalized["id"]
        existing = chapter_map.get(cid)
        if not existing:
            chapter_map[cid] = normalized
            continue
        if not existing.get("unlock") and normalized.get("unlock"):
            existing["unlock"] = True
        if normalized.get("sort_index", 1000000000) < existing.get("sort_index", 1000000000):
            existing["sort_index"] = normalized["sort_index"]
            existing["index"] = normalized["index"]
        for key in ("chapterName", "mp4", "m3u8Url", "contentUrl"):
            if not existing.get(key) and normalized.get(key):
                existing[key] = normalized[key]
    return sorted(chapter_map.values(), key=lambda item: (item.get("sort_index", 1000000000), item.get("id", "")))


def extract_chapters_from_html(page_html: str) -> list:
    data = extract_next_data(page_html)
    props = data.get("props", {}).get("pageProps", {})
    chapters = props.get("chapterList", [])
    return normalize_chapter_list(chapters)


def build_platform_chapters(episodes: list, platform: str) -> list:
    chapters = []
    if not episodes:
        return chapters
    for pos, episode in enumerate(episodes):
        if not isinstance(episode, dict):
            continue
        episode_url = str(episode.get("url", "")).strip()
        chapter_id = str(episode.get("chapter_id") or episode.get(
            "id") or episode_url or f"{platform}_{pos + 1}").strip()
        ep_num = safe_int(episode.get("num"), pos + 1)
        chapter_name = str(episode.get("title") or episode.get(
            "name") or f"{platform} {ep_num}").strip()
        resolved_url = str(episode.get("resolved_url")
                           or episode.get("resolvedUrl") or "").strip()
        chapters.append({
            "id": chapter_id,
            "index": max(ep_num - 1, 0),
            "sort_index": max(ep_num - 1, 0),
            "chapterName": chapter_name,
            "unlock": not coerce_bool(episode.get("locked"), False),
            "episodeUrl": episode_url,
            "resolvedUrl": resolved_url or episode_url,
            "platform": platform,
            "chapter_id": str(episode.get("chapter_id", "")),
            "book_id": str(episode.get("book_id", "")),
            "short_play_id": str(episode.get("short_play_id", "")),
            "playlet_id": str(episode.get("playlet_id", "")),
            "video_id": str(episode.get("video_id", "")),
            "collection_id": str(episode.get("collection_id", "")),
            "num": ep_num,
        })
    return chapters


def chapter_display_name(chapter: dict) -> str:
    name = str(chapter.get("chapterName") or "").strip()
    episode_number = safe_int(chapter.get("index"), -1) + 1
    platform = str(chapter.get("platform") or "")
    if not name:
        return f"Episode {episode_number}" if episode_number > 0 else "Episode"
    if platform and platform != "DramaBox":
        return name
    if episode_number > 0 and not re.search(r"\b(?:ep|episode)\b", name, re.IGNORECASE):
        return f"Episode {episode_number} - {name}"
    return name


def extract_direct_media_url(chapter: dict) -> str:
    if not chapter:
        return ""
    for field in ("mp4", "m3u8Url", "contentUrl"):
        media_url = normalize_media_url(chapter.get(field, ""))
        if media_url and "15s" not in media_url.lower():
            return media_url
    return ""


# ── Platform Fetchers ────────────────────────────────────────────────────────

def fetch_dramabox_series_info(input_text: str, sekai_api=None) -> dict:
    book_id = extract_id_from_input(input_text, "DramaBox")
    if not book_id:
        raise ValueError("Could not extract DramaBox Book ID from input.")

    url = input_text if (input_text.startswith(
        "http") and "dramaboxdb.com" in input_text) else f"https://www.dramaboxdb.com/movie/{book_id}"
    page_html = ""
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
        if resp.status_code == 200:
            page_html = resp.text
    except Exception as e:
        _log.debug("Direct DramaBox scrape failed: %s", e)

    title = extract_series_title(
        page_html, "DramaBox Series") if page_html else "DramaBox Series"
    cover = extract_poster_url(page_html) if page_html else ""
    chapters = extract_chapters_from_html(page_html) if page_html else []

    # If chapters not found via HTML, try SekaiDramaAPI
    if not chapters and sekai_api and hasattr(sekai_api, "get_dramabox_info"):
        try:
            api_title, api_eps, api_thumb = sekai_api.get_dramabox_info(
                book_id)
            title = api_title or title
            cover = api_thumb or cover
            chapters = build_platform_chapters(api_eps, "DramaBox")
        except Exception:
            pass

    return {
        "platform": "DramaBox",
        "series_id": book_id,
        "series_name": title,
        "series_cover": cover,
        "series_intro": f"DramaBox Series • {len(chapters)} Episodes",
        "episode_cnt": len(chapters),
        "vid_list": [],
        "chapters": chapters,
        "page_html": page_html,
    }


def fetch_reelshort_series_info(input_text: str, downloader=None) -> dict:
    book_id = extract_id_from_input(input_text, "ReelShort")
    if not book_id:
        raise ValueError("Could not extract ReelShort ID from input.")

    url = input_text if (input_text.startswith(
        "http") and "reelshort.com" in input_text) else f"https://www.reelshort.com/drama/{book_id}"
    page_html = ""
    try:
        resp = requests.get(
            url, headers=request_headers_for_url(url), timeout=15)
        if resp.status_code == 200:
            page_html = resp.text
    except Exception:
        pass

    title = extract_series_title(
        page_html, "ReelShort Series") if page_html else "ReelShort Series"
    cover = extract_poster_url(page_html) if page_html else ""
    chapters = []

    if downloader and hasattr(downloader, "get_reelshort_info"):
        try:
            info = downloader.get_reelshort_info(url)
            title = info.get("title") or title
            cover = info.get("thumbnail") or cover
            chapters = build_platform_chapters(
                info.get("episodes", []), "ReelShort")
        except Exception:
            pass

    if not chapters and ReelShortBypassManager:
        try:
            mgr = ReelShortBypassManager(status_callback=lambda *a: None)
            t, eps = mgr.get_drama_info(url)
            title = t or title
            chapters = build_platform_chapters(eps, "ReelShort")
        except Exception:
            pass

    return {
        "platform": "ReelShort",
        "series_id": book_id,
        "series_name": title,
        "series_cover": cover,
        "series_intro": f"ReelShort Series • {len(chapters)} Episodes",
        "episode_cnt": len(chapters),
        "vid_list": [],
        "chapters": chapters,
        "page_html": page_html,
    }


def fetch_sekai_series_info(platform: str, input_text: str, sekai_api) -> dict:
    if not sekai_api:
        raise RuntimeError("SekaiDrama API client is not configured.")
    clean_id = extract_id_from_input(input_text, platform)
    if not clean_id:
        raise ValueError(f"Could not extract {platform} ID from input.")

    method_name = f"get_{platform.lower()}_info"
    if not hasattr(sekai_api, method_name):
        raise RuntimeError(f"SekaiDrama API does not support {platform}")

    fn = getattr(sekai_api, method_name)
    title, episodes, thumbnail = fn(clean_id)
    chapters = build_platform_chapters(episodes, platform)

    return {
        "platform": platform,
        "series_id": clean_id,
        "series_name": title or platform,
        "series_cover": thumbnail or "",
        "series_intro": f"{platform} Series • {len(chapters)} Episodes",
        "episode_cnt": len(chapters),
        "vid_list": [],
        "chapters": chapters,
        "page_html": "",
    }


def fetch_social_series_info(platform: str, input_text: str, downloader=None) -> dict:
    clean_url = input_text.strip()
    chapters = [{
        "id": "1",
        "index": 0,
        "chapterId": "1",
        "chapterName": f"{platform} Video",
        "title": f"{platform} Video",
        "url": clean_url,
        "episodeUrl": clean_url,
        "resolvedUrl": clean_url,
        "unlock": 1,
        "platform": platform,
    }]
    return {
        "platform": platform,
        "series_id": clean_url,
        "series_name": f"{platform} Video",
        "series_cover": "",
        "series_intro": f"Direct {platform} media download via pasted URL",
        "episode_cnt": 1,
        "vid_list": [],
        "chapters": chapters,
        "page_html": "",
    }


# ── Stream Resolution Helper ────────────────────────────────────────────────

def resolve_episode_stream(
    series_detail: dict,
    ep_num: int,
    client: Optional[HongguoClient],
    downloader: Optional[DramaboxDownloader],
    sekai_api: Optional[SekaiDramaAPI],
) -> Tuple[str, str]:
    platform = series_detail.get("platform", "Hongguo")
    series_id = series_detail.get("series_id", "")

    if platform == "Hongguo":
        vid_list = series_detail.get("vid_list", [])
        vid = vid_list[ep_num - 1] if ep_num - 1 < len(vid_list) else None
        if client:
            stream_info = client.get_episode_stream_url(
                series_id, vid=vid, episode_index=ep_num)
            url = stream_info.get("main_url", "") if stream_info else ""
            return url, f"第{ep_num:03d}集"
        return "", f"第{ep_num:03d}集"

    chapters = series_detail.get("chapters", [])
    chapter = chapters[ep_num - 1] if (0 <= ep_num - 1 < len(chapters)) else {}
    chapter_id = str(chapter.get("id", ""))
    chapter_name = chapter_display_name(chapter) or f"Episode {ep_num}"

    # Try direct media URL first
    direct_url = extract_direct_media_url(chapter)
    if direct_url and "15s" not in direct_url.lower():
        return direct_url, chapter_name

    # Platform specific resolution
    if platform == "DramaBox":
        page_html = series_detail.get("page_html", "")
        if DramaBoxBypassManager:
            try:
                mgr = DramaBoxBypassManager()
                if chapter.get("unlock"):
                    res = (
                        mgr.get_free_url(page_html, chapter_id)
                        or mgr.find_matching_url(page_html, chapter_id)
                        or mgr.build_bypass_url(chapter_id, page_html)
                    )
                else:
                    res = mgr.build_bypass_url(chapter_id, page_html)
                if res:
                    return res, chapter_name
            except Exception:
                pass
        return direct_url, chapter_name

    elif platform == "ReelShort":
        res = str(chapter.get("resolvedUrl") or "").strip()
        if res and not res.startswith("ytdlp://"):
            return res, chapter_name
        ep_url = str(chapter.get("episodeUrl")
                     or chapter.get("url") or "").strip()
        if downloader and hasattr(downloader, "get_reelshort_video_url"):
            res = downloader.get_reelshort_video_url(ep_url)
        if not res and ReelShortBypassManager:
            try:
                mgr = ReelShortBypassManager()
                res = mgr.get_video_url(ep_url) or mgr.bypass(ep_url)
            except Exception:
                pass
        return res or ep_url, chapter_name

    elif platform == "NetShort":
        short_play_id = str(chapter.get("short_play_id") or series_id).strip()
        if sekai_api and short_play_id:
            try:
                res = sekai_api.get_netshort_stream(short_play_id, ep_num)
                if res:
                    return res, chapter_name
            except Exception:
                pass

    elif platform == "ShortMax":
        short_play_id = str(chapter.get("short_play_id") or series_id).strip()
        if sekai_api and short_play_id:
            try:
                res = sekai_api.get_shortmax_stream(short_play_id, ep_num)
                if res:
                    return res, chapter_name
            except Exception:
                pass

    elif platform == "PineDrama":
        collection_id = str(chapter.get("collection_id") or series_id).strip()
        if sekai_api and collection_id:
            try:
                res = sekai_api.get_pinedrama_stream(collection_id, ep_num)
                if res:
                    return res, chapter_name
            except Exception:
                pass

    elif platform == "GoodShort":
        return str(chapter.get("resolvedUrl") or chapter.get("episodeUrl") or ""), chapter_name

    elif platform == "FlickReels":
        playlet_id = str(chapter.get("playlet_id") or series_id).strip()
        if sekai_api and playlet_id:
            try:
                res = sekai_api.get_flickreels_stream(playlet_id, ep_num)
                if res:
                    return res, chapter_name
            except Exception:
                pass

    elif platform == "FreeReels":
        return str(chapter.get("resolvedUrl") or chapter.get("episodeUrl") or ""), chapter_name

    elif platform == "Melolo":
        vid = str(chapter.get("video_id") or chapter.get("id") or "").strip()
        if sekai_api and vid:
            try:
                res = sekai_api.get_melolo_stream(vid)
                if res:
                    return res, chapter_name
            except Exception:
                pass

    elif platform in ("TikTok", "YouTube", "Facebook"):
        ep_url = str(chapter.get("resolvedUrl") or chapter.get(
            "episodeUrl") or chapter.get("url") or series_id).strip()
        if ep_url and not ep_url.startswith("http") and not ep_url.startswith("ytdlp://"):
            ep_url = f"https://{ep_url}"
        return ep_url, chapter_name

    return direct_url or str(chapter.get("resolvedUrl") or ""), chapter_name


# ── Async Image Loader Pool ──────────────────────────────────────────────────

class ImageLoaderSignals(QObject):
    loaded = pyqtSignal(str, bytes)


class ImageLoadTask(QRunnable):
    def __init__(self, url: str, signals: ImageLoaderSignals):
        super().__init__()
        self.url = url
        self.signals = signals

    def run(self):
        if not self.url or not self.url.startswith("http"):
            return
        try:
            resp = requests.get(
                self.url,
                headers=request_headers_for_url(self.url),
                timeout=15,
            )
            if resp.status_code == 200:
                self.signals.loaded.emit(self.url, resp.content)
        except Exception:
            pass


# ── Background Workers ───────────────────────────────────────────────────────

class CatalogWorker(QThread):
    results_ready = pyqtSignal(int, int, list)
    error = pyqtSignal(str)

    def __init__(self, client, category: str, genre: str, q: str, sort: str, page: int, size: int = 24, parent=None):
        super().__init__(parent)
        self.client = client
        self.category = category
        self.genre = genre
        self.q = q
        self.sort = sort
        self.page = page
        self.size = size

    def run(self):
        try:
            if not self.client:
                self.results_ready.emit(1, 1, [])
                return
            if self.q:
                cur, tot, items = self.client.get_explorer(
                    page=self.page, size=self.size, sort=self.sort, q=self.q)
            elif self.category == "all" or self.genre:
                cur, tot, items = self.client.get_explorer(
                    page=self.page, size=self.size, sort=self.sort, genre=self.genre)
            else:
                items = self.client.get_leaderboard(
                    category=self.category, size=self.size)
                cur, tot = 1, 34
            self.results_ready.emit(cur, tot, items)
        except Exception as e:
            self.error.emit(str(e))


class UnifiedSeriesDetailWorker(QThread):
    detail_ready = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, platform: str, input_text: str, hongguo_client, sekai_api, downloader, parent=None):
        super().__init__(parent)
        self.platform = platform
        self.input_text = input_text.strip()
        self.hongguo_client = hongguo_client
        self.sekai_api = sekai_api
        self.downloader = downloader

    def run(self):
        try:
            # Auto-detect if input is a known URL
            detected = detect_platform_from_url(self.input_text)
            target_platform = detected if detected else self.platform

            if target_platform == "Hongguo":
                if not self.hongguo_client:
                    raise RuntimeError("Hongguo Client not initialized")
                detail = self.hongguo_client.get_series_detail(self.input_text)
                if not detail:
                    raise ValueError("Could not fetch Hongguo series detail")
                detail["platform"] = "Hongguo"
                self.detail_ready.emit(detail)

            elif target_platform == "DramaBox":
                detail = fetch_dramabox_series_info(
                    self.input_text, self.sekai_api)
                self.detail_ready.emit(detail)

            elif target_platform == "ReelShort":
                detail = fetch_reelshort_series_info(
                    self.input_text, self.downloader)
                self.detail_ready.emit(detail)

            elif target_platform in ("NetShort", "ShortMax", "PineDrama", "GoodShort", "FlickReels", "FreeReels", "Melolo"):
                detail = fetch_sekai_series_info(
                    target_platform, self.input_text, self.sekai_api)
                self.detail_ready.emit(detail)

            elif target_platform in ("TikTok", "YouTube", "Facebook"):
                detail = fetch_social_series_info(
                    target_platform, self.input_text, self.downloader)
                self.detail_ready.emit(detail)

            else:
                raise RuntimeError(f"Unsupported platform: {target_platform}")

        except Exception as e:
            _log.error("SeriesDetailWorker error: %s", e)
            self.error.emit(str(e))


class UnifiedDownloadWorker(QThread):
    # task_id, pct, speed, done_b, total_b
    progress_sig = pyqtSignal(int, int, float, int, int)
    episode_done_sig = pyqtSignal(int, str)               # task_id, path
    episode_failed_sig = pyqtSignal(int, str)             # task_id, reason
    # success_count, fail_count
    all_done_sig = pyqtSignal(int, int)
    log_sig = pyqtSignal(str)
    # active_threads, done_count, total_count
    queue_stat_sig = pyqtSignal(int, int, int)

    def __init__(
        self,
        series_detail: dict,
        selected_eps: list,
        output_dir: str,
        quality: str,
        hongguo_client: Optional[HongguoClient],
        downloader: Optional[DramaboxDownloader],
        sekai_api: Optional[SekaiDramaAPI],
        max_workers: int = 4,
    ):
        super().__init__()
        self.series_detail = series_detail
        self.selected_eps = sorted(selected_eps)
        self.output_dir = output_dir
        self.quality = quality
        self.hongguo_client = hongguo_client
        self.downloader = downloader
        self.sekai_api = sekai_api
        if max_workers is None:
            max_workers = 4
        self.max_workers = max(1, min(int(max_workers), 16))
        self.cancelled = False
        self._lock = threading.Lock()
        self.executor = None

    def cancel(self):
        self.cancelled = True
        if self.executor:
            try:
                self.executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def _download_task(self, ep_num: int, series_dir: str, platform: str) -> Tuple[bool, str]:
        if self.cancelled:
            return False, "Cancelled"

        task_id = ep_num
        self.log_sig.emit(f"🔍 កំពុងដកស្រង់ Link ភាគទី {ep_num:02d}...")

        # Stagger upstream requests slightly to avoid stampede 429
        if self.max_workers > 1:
            time.sleep(0.04 * (ep_num % self.max_workers))

        if self.cancelled:
            return False, "Cancelled"

        try:
            stream_url, ep_label = resolve_episode_stream(
                self.series_detail, ep_num, self.hongguo_client, self.downloader, self.sekai_api
            )
        except Exception as exc:
            err = f"Stream resolution error: {exc}"
            self.log_sig.emit(f"⚠️ ភាគទី {ep_num}: {err}")
            self.episode_failed_sig.emit(task_id, err)
            return False, err

        if not stream_url:
            err = "មិនអាចស្វែងរក Link វីដេអូ"
            self.log_sig.emit(f"⚠️ មិនអាចស្វែងរក Link សម្រាប់ភាគទី {ep_num}")
            self.episode_failed_sig.emit(task_id, err)
            return False, err

        # Destination filename
        if platform == "Hongguo":
            dest_file = os.path.join(series_dir, f"第{ep_num:03d}集.mp4")
        elif platform in ("TikTok", "YouTube", "Facebook"):
            dest_file = os.path.join(
                series_dir, f"{platform}_Video_{int(time.time())}_{ep_num}.mp4")
        else:
            clean_ep = sanitize_filename(ep_label, f"EP{ep_num:02d}")
            dest_file = os.path.join(
                series_dir, f"EP{ep_num:02d} - {clean_ep}.mp4")

        # Check if exists and valid
        if os.path.exists(dest_file) and os.path.getsize(dest_file) > 65536:
            self.log_sig.emit(
                f"⏩ មានឯកសាររួចហើយ: {os.path.basename(dest_file)}")
            self.progress_sig.emit(task_id, 100, 0.0, os.path.getsize(
                dest_file), os.path.getsize(dest_file))
            self.episode_done_sig.emit(task_id, dest_file)
            return True, dest_file

        # Perform download
        ok = False
        if platform == "Hongguo" and self.hongguo_client:
            def _hg_progress(pct, speed, done, total):
                self.progress_sig.emit(task_id, pct, speed, done, total)

            ok = self.hongguo_client.download_file(
                stream_url,
                dest_file,
                progress_callback=_hg_progress,
                cancel_check=lambda: self.cancelled,
            )
        elif self.downloader:
            def _gen_progress(pct):
                self.progress_sig.emit(task_id, pct, 0.0, 0, 0)

            try:
                saved = self.downloader.download_file(
                    stream_url,
                    dest_file,
                    ep_label,
                    progress_callback=_gen_progress,
                    cancel_check=lambda: self.cancelled,
                )
                ok = bool(saved and os.path.exists(saved)
                          and os.path.getsize(saved) > 1024)
            except Exception as e:
                self.log_sig.emit(f"❌ Error downloading EP{ep_num}: {e}")
                self.episode_failed_sig.emit(task_id, str(e))
                return False, str(e)
        else:
            self.log_sig.emit("❌ Downloader engine unavailable.")
            self.episode_failed_sig.emit(task_id, "Engine unavailable")
            return False, "Downloader engine unavailable"

        if ok:
            self.episode_done_sig.emit(task_id, dest_file)
            self.log_sig.emit(
                f"✅ បានទាញយកជោគជ័យ: {os.path.basename(dest_file)}")
            return True, dest_file
        else:
            reason = "ការទាញយកបរាជ័យ ឬត្រូវបានបញ្ឈប់"
            self.episode_failed_sig.emit(task_id, reason)
            self.log_sig.emit(f"❌ ការទាញយកបរាជ័យ: EP{ep_num:02d}")
            return False, reason

    def run(self):
        platform = self.series_detail.get("platform", "Hongguo")
        series_name = self.series_detail.get("series_name", "Drama")
        clean_title = sanitize_filename(series_name, f"{platform}_Series")
        series_dir = os.path.join(self.output_dir, clean_title)
        os.makedirs(series_dir, exist_ok=True)

        total_eps = len(self.selected_eps)
        actual_workers = min(
            self.max_workers, total_eps) if total_eps > 0 else 1
        self.log_sig.emit(
            f"🚀 [{platform}] ចាប់ផ្តើមទាញយក 《{series_name}》 ចំនួន {total_eps} ភាគ ស្របគ្នា ({actual_workers} Threads)..."
        )

        success_count = 0
        fail_count = 0

        # Execute parallel downloads with ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
            self.executor = executor
            futures = {
                executor.submit(self._download_task, ep_num, series_dir, platform): ep_num
                for ep_num in self.selected_eps
            }

            for future in concurrent.futures.as_completed(futures):
                ep_num = futures[future]
                try:
                    ok, _ = future.result()
                    if ok:
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as exc:
                    fail_count += 1
                    self.episode_failed_sig.emit(ep_num, str(exc))

                with self._lock:
                    done = success_count + fail_count
                    remaining = total_eps - done
                    active = min(remaining, actual_workers)
                    self.queue_stat_sig.emit(active, done, total_eps)

                if self.cancelled:
                    break

        self.all_done_sig.emit(success_count, fail_count)


# ── Social Platform Metadata Worker ─────────────────────────────────────────

class SocialMetadataWorker(QThread):
    """Background thread that fetches real metadata for social platform URLs via yt-dlp.

    Uses PortableVideoSupport.get_*_info() methods which call yt-dlp
    extract_info(download=False) to retrieve real title, thumbnail, and
    playlist entries without downloading any media.

    Falls back to fetch_social_series_info() stub when yt-dlp is unavailable
    or the fetch fails.
    """
    detail_ready = pyqtSignal(object)
    error = pyqtSignal(str)
    status_sig = pyqtSignal(str)

    def __init__(self, platform: str, url: str, downloader, parent=None):
        super().__init__(parent)
        self.platform = platform
        self.url = url.strip()
        self.downloader = downloader

    def run(self):
        try:
            self.status_sig.emit(f"🔍 កំពុងផ្ទុក {self.platform} metadata...")
            detail = self._fetch_social_detail()
            self.detail_ready.emit(detail)
        except Exception as exc:
            _log.warning("SocialMetadataWorker error: %s", exc)
            # Fallback to stub on any error
            try:
                detail = fetch_social_series_info(
                    self.platform, self.url, self.downloader)
                self.detail_ready.emit(detail)
            except Exception as inner_exc:
                self.error.emit(str(inner_exc))

    def _fetch_social_detail(self) -> dict:
        """Try yt-dlp metadata fetch; fall back to stub on failure."""
        if self.downloader and hasattr(self.downloader, "portable_video"):
            pv = self.downloader.portable_video
            if pv.available:
                try:
                    if self.platform == "YouTube":
                        info = pv.get_youtube_info(self.url)
                    elif self.platform == "Facebook":
                        info = pv.get_facebook_info(self.url)
                    elif self.platform == "TikTok":
                        info = pv.get_tiktok_info(self.url)
                    else:
                        info = None

                    if info and info.get("episodes"):
                        return self._info_to_series_detail(info)
                except Exception as exc:
                    _log.debug(
                        "yt-dlp metadata fetch failed for %s: %s", self.platform, exc)

        # Fallback: create stub detail so download still works
        return fetch_social_series_info(self.platform, self.url, self.downloader)

    def _info_to_series_detail(self, info: dict) -> dict:
        """Convert yt-dlp info dict (from PortableVideoSupport) into a series_detail dict."""
        episodes = info.get("episodes", [])
        title = str(info.get("title") or self.platform).strip()
        thumbnail = str(info.get("thumbnail") or "").strip()
        chapters = build_platform_chapters(episodes, self.platform)
        ep_count = len(chapters)

        return {
            "platform": self.platform,
            "series_id": self.url,
            "series_name": title,
            "series_cover": thumbnail,
            "series_intro": (
                f"Direct {self.platform} media download via pasted URL • "
                f"{ep_count} {'videos' if ep_count > 1 else 'video'}"
            ),
            "episode_cnt": ep_count,
            "vid_list": [],
            "chapters": chapters,
            "page_html": "",
        }


# ── Flow / Wrap Layout for Genre Chips ───────────────────────────────────────

class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self.itemList = []

    def addItem(self, item):
        self.itemList.append(item)

    def count(self):
        return len(self.itemList)

    def itemAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.itemList):
            return self.itemList.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.itemList:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _doLayout(self, rect, testOnly):
        x = rect.x()
        y = rect.y()
        lineHeight = 0
        spacing = self.spacing()

        for item in self.itemList:
            wid = item.widget()
            spaceX = spacing
            spaceY = spacing
            nextX = x + item.sizeHint().width() + spaceX
            if nextX - spaceX > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spaceY
                nextX = x + item.sizeHint().width() + spaceX
                lineHeight = 0

            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))

            x = nextX
            lineHeight = max(lineHeight, item.sizeHint().height())

        return y + lineHeight - rect.y()


# ── Drama Card Widget ────────────────────────────────────────────────────────

class DramaCardWidget(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, drama_data: dict, image_cache: dict, thread_pool: QThreadPool, signals: ImageLoaderSignals, parent=None):
        super().__init__(parent)
        self.drama_data = drama_data
        self.image_cache = image_cache
        self.thread_pool = thread_pool
        self.signals = signals
        self.cover_url = drama_data.get("cover", "")

        self.setFixedSize(136, 236)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("dramaCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 8)
        layout.setSpacing(5)

        # Poster Container
        self.poster_frame = QFrame()
        self.poster_frame.setFixedSize(124, 168)
        self.poster_frame.setObjectName("cardPosterFrame")
        poster_layout = QVBoxLayout(self.poster_frame)
        poster_layout.setContentsMargins(0, 0, 0, 0)
        poster_layout.setSpacing(0)

        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setScaledContents(True)
        self.img_label.setStyleSheet(
            "border-radius: 8px; background-color: #0b0f17;")
        poster_layout.addWidget(self.img_label)

        # Episode Badge
        ep_cnt = drama_data.get("episode_cnt", 0)
        score = drama_data.get("score", "")
        badge_text = f"{ep_cnt} ភាគ" if ep_cnt else (
            f"★ {score}" if score else "រឿងពេញ")
        self.badge = QLabel(badge_text, self.poster_frame)
        self.badge.setObjectName("cardEpBadge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.adjustSize()
        self.badge.move(124 - self.badge.width() - 5,
                        168 - self.badge.height() - 5)

        layout.addWidget(self.poster_frame)

        # Title
        title_text = drama_data.get("title", "")
        self.title_label = QLabel(title_text)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setFixedHeight(32)
        self.title_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.title_label)

        # Subtitle / Remarks
        remarks = drama_data.get("remarks") or ""
        tags = drama_data.get("tags") or []
        platform = drama_data.get("platform", "Hongguo")
        if isinstance(tags, list) and tags:
            sub_text = " • ".join(tags[:3])
        elif remarks:
            sub_text = remarks
        else:
            sub_text = f"{platform} ពេញនិយម"
        self.sub_label = QLabel(sub_text)
        self.sub_label.setObjectName("cardSubtitle")
        self.sub_label.setFixedHeight(15)
        layout.addWidget(self.sub_label)

        # Load Poster
        self._load_cover()

    def showEvent(self, event):
        super().showEvent(event)
        self.badge.adjustSize()
        pw = self.poster_frame.width()
        ph = self.poster_frame.height()
        self.badge.move(pw - self.badge.width() - 5,
                        ph - self.badge.height() - 5)

    def _load_cover(self):
        if not self.cover_url:
            self.img_label.setText("🎬")
            return
        if self.cover_url in self.image_cache:
            pix = self.image_cache[self.cover_url]
            self.img_label.setPixmap(pix)
            return

        self.img_label.setText("⌛")
        task = ImageLoadTask(self.cover_url, self.signals)
        self.thread_pool.start(task)

    def set_loaded_pixmap(self, url: str, pix: QPixmap):
        if url == self.cover_url:
            self.img_label.setPixmap(pix)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.drama_data)
        super().mousePressEvent(event)


# ── Episode Chip Button ──────────────────────────────────────────────────────

class EpisodeChip(QPushButton):
    def __init__(self, ep_num: int, parent=None):
        super().__init__(str(ep_num), parent)
        self.ep_num = ep_num
        self.setCheckable(True)
        self.setChecked(True)
        self.setFixedSize(38, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("epChip")


# ── Download Queue Item Widget ───────────────────────────────────────────────

class DownloadQueueItemWidget(QFrame):
    cancel_requested = pyqtSignal(int)

    def __init__(self, task_id: int, title: str, ep_label: str, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.title = title
        self.ep_label = ep_label
        self.setObjectName("queueItem")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        self.lbl_title = QLabel(f"<b>{title}</b> • {ep_label}")
        self.lbl_title.setStyleSheet("color: #f7efe7; font-size: 12px;")
        self.lbl_status = QLabel("រង់ចាំ...")
        self.lbl_status.setStyleSheet("color: #ff9a2e; font-size: 11px;")
        top_row.addWidget(self.lbl_title, 1)
        top_row.addWidget(self.lbl_status, 0, Qt.AlignRight)
        layout.addLayout(top_row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.bar.setObjectName("queueBar")
        layout.addWidget(self.bar)

        self.lbl_metrics = QLabel("0% • 0 MB/s • 0 MB")
        self.lbl_metrics.setStyleSheet("color: #9c8a7b; font-size: 10px;")
        layout.addWidget(self.lbl_metrics)

    def update_progress(self, pct: int, speed: float = 0.0, done_bytes: int = 0, total_bytes: int = 0):
        self.bar.setValue(pct)
        if total_bytes > 0:
            done_mb = done_bytes / (1024 * 1024)
            total_mb = total_bytes / (1024 * 1024)
            spd_str = f"{speed:.1f} MB/s • " if speed > 0 else ""
            self.lbl_metrics.setText(
                f"{pct}% • {spd_str}{done_mb:.1f} MB / {total_mb:.1f} MB")
        else:
            self.lbl_metrics.setText(f"ដំណើរការ: {pct}%")
        self.lbl_status.setText("កំពុងទាញយក...")
        self.lbl_status.setStyleSheet("color: #0fbccb; font-size: 11px;")

    def set_completed(self, path: str):
        self.bar.setValue(100)
        self.lbl_status.setText("✅ ជោគជ័យ")
        self.lbl_status.setStyleSheet(
            "color: #27ae60; font-size: 11px; font-weight: bold;")
        self.lbl_metrics.setText(f"បានរក្សាទុក: {os.path.basename(path)}")

    def set_failed(self, reason: str):
        self.lbl_status.setText("❌ បរាជ័យ")
        self.lbl_status.setStyleSheet(
            "color: #e23f5c; font-size: 11px; font-weight: bold;")
        self.lbl_metrics.setText(reason)


# ── Settings Dialog ──────────────────────────────────────────────────────────

class DownloaderSettingsDialog(QDialog):
    def __init__(self, parent=None, current_api_base="", current_proxy="", current_cf_clearance="", current_max_workers=4):
        super().__init__(parent)
        self.setWindowTitle("⚙️ API & Network Settings")
        self.setFixedSize(520, 360)
        self.setStyleSheet("""
            QDialog { background-color: #1a1410; color: #f7efe7; }
            QLabel { color: #d3c3b4; font-size: 12px; }
            QLineEdit { background-color: #241b15; border: 1px solid #413326; border-radius: 8px; padding: 8px; color: #f7efe7; font-size: 13px; }
            QLineEdit:focus { border: 1px solid #ff6a2b; }
            QPushButton { background-color: #2a1f17; color: #f7efe7; border: 1px solid #413326; border-radius: 8px; padding: 8px 16px; font-weight: bold; }
            QPushButton:hover { border-color: #ff6a2b; }
            QPushButton#saveBtn { background: linear-gradient(135deg, #27ae60, #2ecc71); border: none; color: white; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Sekai API Base URL:"))
        self.api_input = QLineEdit(
            current_api_base or "https://api.sansekai.my.id/api")
        layout.addWidget(self.api_input)

        layout.addWidget(
            QLabel("HTTP/HTTPS Proxy (e.g. http://127.0.0.1:7890):"))
        self.proxy_input = QLineEdit(current_proxy)
        layout.addWidget(self.proxy_input)

        layout.addWidget(QLabel("Cloudflare cf_clearance Cookie:"))
        cf_row = QHBoxLayout()
        self.cf_input = QLineEdit(current_cf_clearance)
        self.auto_cookie_btn = QPushButton("Auto Import")
        self.auto_cookie_btn.clicked.connect(self._auto_import_cookie)
        cf_row.addWidget(self.cf_input, 1)
        cf_row.addWidget(self.auto_cookie_btn, 0)
        layout.addLayout(cf_row)

        layout.addWidget(QLabel("Download Concurrency:"))
        self.worker_spin = QSpinBox()
        self.worker_spin.setRange(1, 10)
        self.worker_spin.setValue(current_max_workers)
        self.worker_spin.setStyleSheet(
            "background-color: #241b15; color: #f7efe7; padding: 6px; border-radius: 6px;")
        layout.addWidget(self.worker_spin)

        layout.addStretch()
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("បោះបង់ (Cancel)")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("រក្សាទុក (Save)")
        btn_save.setObjectName("saveBtn")
        btn_save.clicked.connect(self.accept)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _auto_import_cookie(self):
        try:
            from sekai_api import extract_chrome_cf_clearance
            cookie = extract_chrome_cf_clearance()
            if cookie:
                self.cf_input.setText(cookie)
                QMessageBox.information(
                    self, "Success", "Imported cf_clearance successfully!")
            else:
                QMessageBox.warning(self, "Not Found",
                                    "Could not find cf_clearance in Chrome.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to import: {e}")

    def get_values(self):
        return (
            self.api_input.text().strip(),
            self.proxy_input.text().strip(),
            self.cf_input.text().strip(),
            self.worker_spin.value(),
        )


# ── Main Video Downloader Tool (Matching down.png) ───────────────────────────

class DramaBoxTool(QMainWindow):
    def __init__(self):
        super().__init__()
        # Engines
        self.hongguo_client = HongguoClient() if HongguoClient else None
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(8)
        self.image_loader_signals = ImageLoaderSignals()
        self.image_loader_signals.loaded.connect(self._on_image_loaded)

        self.selected_platform = "Hongguo"
        self.image_cache = {}
        self.card_widgets = []
        self.current_series_detail = None
        self.selected_episodes = set()
        self.current_download_worker = None

        # Hongguo state
        self.active_category = "live"
        self.active_genre = ""
        self.active_sort = "hot"
        self.current_page = 1
        self.total_pages = 34
        self.current_search_query = ""

        # Workers
        self._catalog_worker = None
        self._detail_worker = None
        self._social_worker = None

        # Social URL debounce: wait 500ms after user stops typing before fetching metadata
        self._pending_social_url = ""
        self._social_debounce_timer = QTimer(self)
        self._social_debounce_timer.setSingleShot(True)
        self._social_debounce_timer.setInterval(500)
        # Timer is connected after initUI() to ensure self exists

        # Settings
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        saved_api = settings.value(
            "api_base", "https://api.sansekai.my.id/api", type=str)
        if not saved_api or "drama.sansekai.my.id" in saved_api:
            saved_api = "https://api.sansekai.my.id/api"
            settings.setValue("api_base", saved_api)
        self.api_base = saved_api
        self.proxy_url = settings.value("proxy_url", "", type=str)
        self.cf_clearance = settings.value("cf_clearance", "", type=str)
        self.max_workers = settings.value("max_workers", 4, type=int)
        self.output_dir = self.load_output_dir()

        # Engine instances
        self.downloader = None
        if DramaboxDownloader:
            self.downloader = DramaboxDownloader(status_callback=_log.info)
            if self.proxy_url:
                self.downloader.session.proxies = {
                    "http": self.proxy_url, "https": self.proxy_url}

        self.sekai_api = None
        if SekaiDramaAPI:
            self.sekai_api = SekaiDramaAPI(
                api_base=self.api_base,
                cf_clearance=self.cf_clearance,
                status_callback=_log.info,
            )
            if self.proxy_url:
                self.sekai_api.set_proxy(self.proxy_url)

        self.initUI()
        self.apply_styles()

        # Connect social debounce timer now that initUI() has been called
        self._social_debounce_timer.timeout.connect(self._trigger_social_fetch)

        # Load initial leaderboard / catalog
        QTimer.singleShot(100, lambda: self.load_catalog(
            category="live", page=1))

    # ── UI Initialization ────────────────────────────────────────────────────

    def initUI(self):
        self.setWindowTitle(
            f"AI Dubber Ultimate {APP_VERSION} - Video Downloader (Hongguo & Multi-Platform)")
        self.resize(1300, 840)
        self.setMinimumSize(1140, 720)

        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        root_layout = QHBoxLayout(main_widget)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(14)

        # ── LEFT PANEL (Preview, Controls & Download Queue) ──────────────────
        left_panel = QFrame()
        left_panel.setFixedWidth(390)
        left_panel.setObjectName("leftSidebar")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(12)

        # 1. Top Card: Preview, Input, Episode Selection & Download Button
        top_card = QFrame()
        top_card.setObjectName("innerPanel")
        top_card_layout = QVBoxLayout(top_card)
        top_card_layout.setContentsMargins(12, 12, 12, 12)
        top_card_layout.setSpacing(10)

        # Preview + Search input side-by-side
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        # 9:16 Video Preview Card
        self.preview_frame = QFrame()
        self.preview_frame.setFixedSize(125, 190)
        self.preview_frame.setObjectName("previewBox")
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setScaledContents(True)
        self.preview_label.setText("▶\n\nរង់ចាំការពិនិត្យ")
        self.preview_label.setStyleSheet(
            "color: #64748b; font-size: 11px; font-weight: bold;")
        preview_layout.addWidget(self.preview_label)
        top_row.addWidget(self.preview_frame, 0, Qt.AlignTop)

        # Right side of top row: Search input, total count, select all, helper text
        input_col = QVBoxLayout()
        input_col.setSpacing(8)

        link_row = QHBoxLayout()
        link_row.setSpacing(6)
        self.link_input = QLineEdit()
        self.link_input.setPlaceholderText(
            "🔍 បិទភ្ជាប់ (Paste) Link Hongguo...")
        self.link_input.setFixedHeight(38)
        self.link_input.setObjectName("linkInput")
        self.link_input.textChanged.connect(self.on_link_text_changed)
        self.link_input.returnPressed.connect(self.handle_check_link)
        link_row.addWidget(self.link_input, 1)

        self.btn_check = QPushButton("ពិនិត្យ")
        self.btn_check.setFixedHeight(38)
        self.btn_check.setFixedWidth(72)
        self.btn_check.setObjectName("orangeBtn")
        self.btn_check.setCursor(Qt.PointingHandCursor)
        self.btn_check.clicked.connect(self.handle_check_link)
        link_row.addWidget(self.btn_check)
        input_col.addLayout(link_row)

        ep_meta_row = QHBoxLayout()
        self.lbl_ep_count = QLabel("ចំនួនភាគ --")
        self.lbl_ep_count.setStyleSheet(
            "color: #ff9a2e; font-size: 12px; font-weight: bold;")
        ep_meta_row.addWidget(self.lbl_ep_count, 1)

        self.chk_select_all = QCheckBox("✔ ជ្រើសរើសទាំងអស់")
        self.chk_select_all.setChecked(True)
        self.chk_select_all.setStyleSheet(
            "color: #d3c3b4; font-size: 11px; font-weight: bold;")
        self.chk_select_all.stateChanged.connect(self.handle_toggle_select_all)
        ep_meta_row.addWidget(self.chk_select_all, 0, Qt.AlignRight)
        input_col.addLayout(ep_meta_row)

        self.lbl_helper = QLabel("សូមដាក់ Link ឬចុចលើ Card រឿងដើម្បីទាញយក")
        self.lbl_helper.setWordWrap(True)
        self.lbl_helper.setStyleSheet(
            "color: #9c8a7b; font-size: 11px; line-height: 1.4;")
        input_col.addWidget(self.lbl_helper)
        input_col.addStretch()

        top_row.addLayout(input_col, 1)
        top_card_layout.addLayout(top_row)

        # Episode selection scroll area
        self.episodes_scroll = QScrollArea()
        self.episodes_scroll.setFixedHeight(110)
        self.episodes_scroll.setWidgetResizable(True)
        self.episodes_scroll.setObjectName("episodesScroll")
        self.episodes_container = QWidget()
        self.episodes_container.setObjectName("episodesContainer")
        self.episodes_layout = FlowLayout(
            self.episodes_container, margin=4, spacing=5)
        self.episodes_scroll.setWidget(self.episodes_container)
        top_card_layout.addWidget(self.episodes_scroll)

        # Range, Quality, and Concurrency dropdowns
        options_row = QHBoxLayout()
        options_row.setSpacing(8)

        self.combo_range = QComboBox()
        self.combo_range.setFixedHeight(34)
        self.combo_range.setObjectName("darkCombo")
        self.combo_range.addItems(
            ["ទាញយក: ទាំងអស់", "ទាញយក: 1-10 ភាគ", "ទាញយក: 1-30 ភាគ", "ទាញយក: 5 ភាគដំបូង"])
        self.combo_range.currentIndexChanged.connect(self.handle_range_changed)
        options_row.addWidget(self.combo_range, 1)

        self.combo_quality = QComboBox()
        self.combo_quality.setFixedHeight(34)
        self.combo_quality.setObjectName("darkCombo")
        self.combo_quality.addItems(
            ["កម្រិត: 1080p", "កម្រិត: 720p", "កម្រិត: 480p"])
        options_row.addWidget(self.combo_quality, 1)

        self.combo_threads = QComboBox()
        self.combo_threads.setFixedHeight(34)
        self.combo_threads.setObjectName("darkCombo")
        self.combo_threads.setToolTip(
            "ចំនួនទាញយកស្របគ្នា (Concurrent Download Threads)")
        self.combo_threads.addItems([
            "⚡ 1 Thread",
            "⚡ 2 Threads",
            "⚡ 3 Threads",
            "⚡ 4 Threads",
            "⚡ 5 Threads",
            "⚡ 8 Threads",
        ])
        worker_map = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 8: 5}
        self.combo_threads.setCurrentIndex(worker_map.get(self.max_workers, 3))
        self.combo_threads.currentIndexChanged.connect(
            self.handle_threads_changed)
        options_row.addWidget(self.combo_threads, 1)
        top_card_layout.addLayout(options_row)

        # Folder button, Download Now Button, and Cancel Button
        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btn_folder = QPushButton("📁 រក្សាទុក")
        self.btn_folder.setFixedHeight(44)
        self.btn_folder.setFixedWidth(85)
        self.btn_folder.setObjectName("secondaryBtn")
        self.btn_folder.setToolTip(f"Save Path: {self.output_dir}")
        self.btn_folder.setCursor(Qt.PointingHandCursor)
        self.btn_folder.clicked.connect(self.browse_folder)
        action_row.addWidget(self.btn_folder)

        self.btn_download = QPushButton("📥 ទាញយក (Download)")
        self.btn_download.setFixedHeight(44)
        self.btn_download.setObjectName("greenBtn")
        self.btn_download.setCursor(Qt.PointingHandCursor)
        self.btn_download.clicked.connect(self.handle_download_now)
        action_row.addWidget(self.btn_download, 1)

        self.btn_cancel_dl = QPushButton("⏹ បញ្ឈប់")
        self.btn_cancel_dl.setFixedHeight(44)
        self.btn_cancel_dl.setFixedWidth(80)
        self.btn_cancel_dl.setObjectName("dangerBtn")
        self.btn_cancel_dl.setStyleSheet(
            "QPushButton#dangerBtn { background: #e23f5c; color: white; font-weight: bold; border-radius: 8px; font-size: 13px; } QPushButton#dangerBtn:hover { background: #c02d46; } QPushButton#dangerBtn:disabled { background: #2f1d22; color: #6b474e; }")
        self.btn_cancel_dl.setEnabled(False)
        self.btn_cancel_dl.setCursor(Qt.PointingHandCursor)
        self.btn_cancel_dl.clicked.connect(self.handle_cancel_download)
        action_row.addWidget(self.btn_cancel_dl)
        top_card_layout.addLayout(action_row)

        left_layout.addWidget(top_card)

        # 2. Bottom Card: Download Queue Panel
        queue_card = QFrame()
        queue_card.setObjectName("innerPanel")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(12, 12, 12, 12)
        queue_layout.setSpacing(8)

        self.lbl_queue_header = QLabel("ដំណើរការទាញយក (Download Queue)  0")
        self.lbl_queue_header.setStyleSheet(
            "color: #f7efe7; font-size: 13px; font-weight: bold;")
        queue_layout.addWidget(self.lbl_queue_header)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setObjectName("queueScroll")
        self.queue_container = QWidget()
        self.queue_container.setObjectName("queueContainer")
        self.queue_items_layout = QVBoxLayout(self.queue_container)
        self.queue_items_layout.setContentsMargins(4, 4, 4, 4)
        self.queue_items_layout.setSpacing(8)

        # Empty State
        self.empty_queue_widget = QFrame()
        self.empty_queue_widget.setObjectName("queueEmptyBox")
        empty_layout = QVBoxLayout(self.empty_queue_widget)
        empty_layout.setContentsMargins(20, 30, 20, 30)
        empty_layout.setSpacing(10)
        lbl_cloud = QLabel("☁️")
        lbl_cloud.setAlignment(Qt.AlignCenter)
        lbl_cloud.setStyleSheet("font-size: 36px; color: #475569;")
        lbl_empty_msg = QLabel(
            "មិនទាន់មានដំណើរការទាញយកនៅឡើយទេ។ សូមដាក់ Link រឿងដើម្បីទាញយក!")
        lbl_empty_msg.setAlignment(Qt.AlignCenter)
        lbl_empty_msg.setWordWrap(True)
        lbl_empty_msg.setStyleSheet("color: #64748b; font-size: 11px;")
        empty_layout.addWidget(lbl_cloud)
        empty_layout.addWidget(lbl_empty_msg)
        self.queue_items_layout.addWidget(self.empty_queue_widget)
        self.queue_items_layout.addStretch()

        self.queue_scroll.setWidget(self.queue_container)
        queue_layout.addWidget(self.queue_scroll, 1)

        left_layout.addWidget(queue_card, 1)
        root_layout.addWidget(left_panel, 0)

        # ── RIGHT PANEL (Header, Tabs, Search, Genre Filters & Catalog) ──────
        right_panel = QFrame()
        right_panel.setObjectName("rightMainContent")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(14, 12, 14, 12)
        right_layout.setSpacing(10)

        # 0. Platform Switcher Bar (Horizontal Scroll Bar)
        platform_scroll = QScrollArea()
        platform_scroll.setFixedHeight(48)
        platform_scroll.setWidgetResizable(True)
        platform_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        platform_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        platform_scroll.setObjectName("platformScroll")

        platform_container = QWidget()
        platform_container.setObjectName("platformContainer")
        platform_layout = QHBoxLayout(platform_container)
        platform_layout.setContentsMargins(2, 2, 2, 2)
        platform_layout.setSpacing(8)

        self.platform_buttons = {}
        for p_id, p_label, p_color, p_hint in SUPPORTED_PLATFORMS:
            btn = QPushButton(p_label)
            btn.setObjectName("platformBtn")
            btn.setProperty("platform", p_id)
            btn.setProperty("active", "true" if p_id ==
                            self.selected_platform else "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(p_hint)
            btn.clicked.connect(
                lambda _, pid=p_id: self.set_active_platform(pid))
            platform_layout.addWidget(btn)
            self.platform_buttons[p_id] = btn

        platform_layout.addStretch()
        platform_scroll.setWidget(platform_container)
        right_layout.addWidget(platform_scroll)

        # 1. Header Row: Breadcrumb, Main Title & Controls
        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.lbl_breadcrumb = QLabel("HONGGUO (红果短剧) • រឿងទាំងអស់")
        self.lbl_breadcrumb.setObjectName("breadcrumb")
        self.lbl_main_title = QLabel("Hongguo (红果短剧)")
        self.lbl_main_title.setObjectName("mainTitle")
        self.lbl_subtitle = QLabel(
            "រឿងទាំងអស់ • ទំព័រ 1/34 • ចុច Card ដើម្បីទាញយក")
        self.lbl_subtitle.setObjectName("subtitle")
        title_col.addWidget(self.lbl_breadcrumb)
        title_col.addWidget(self.lbl_main_title)
        title_col.addWidget(self.lbl_subtitle)
        header_row.addLayout(title_col, 1)

        # Right Controls: Refresh & Settings
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setObjectName("secondaryBtn")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self.handle_refresh)
        header_row.addWidget(self.btn_refresh, 0, Qt.AlignVCenter)

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setFixedSize(36, 36)
        self.btn_settings.setObjectName("secondaryBtn")
        self.btn_settings.setToolTip("API & Network Settings")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        header_row.addWidget(self.btn_settings, 0, Qt.AlignVCenter)

        right_layout.addLayout(header_row)

        # 2. Hongguo Specific Controls Container
        self.hongguo_controls_widget = QWidget()
        hongguo_controls_layout = QVBoxLayout(self.hongguo_controls_widget)
        hongguo_controls_layout.setContentsMargins(0, 0, 0, 0)
        hongguo_controls_layout.setSpacing(8)

        # 2a. Category Tabs (Pills)
        cat_row = QHBoxLayout()
        cat_row.setSpacing(8)
        self.cat_buttons = {}
        categories = [
            ("live", "រឿងមនុស្សពិត (Live-Action)"),
            ("comic", "រឿងគំនូរជីវចល (Comic)"),
            ("ai", "រឿង AI (AI Drama)"),
            ("all", "តារាងពេញនិយម (Rankings)"),
        ]
        for key, text in categories:
            btn = QPushButton(text)
            btn.setObjectName("catTabBtn")
            btn.setCheckable(True)
            btn.setChecked(key == "live")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda _, k=key: self.handle_category_change(k))
            cat_row.addWidget(btn)
            self.cat_buttons[key] = btn
        cat_row.addStretch()
        hongguo_controls_layout.addLayout(cat_row)

        # 2b. Search Bar
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.omni_search_input = QLineEdit()
        self.omni_search_input.setFixedHeight(40)
        self.omni_search_input.setObjectName("omniSearch")
        self.omni_search_input.setPlaceholderText(
            "🔍 ស្វែងរកគ្រប់រឿងក្នុង Hongguo តាមចំណងជើង ឬកូនសោរ (Search all Hongguo)...")
        self.omni_search_input.returnPressed.connect(
            self.handle_catalog_search)
        search_row.addWidget(self.omni_search_input, 1)

        self.btn_search = QPushButton("ស្វែងរក (Search)")
        self.btn_search.setFixedHeight(40)
        self.btn_search.setFixedWidth(130)
        self.btn_search.setObjectName("orangeBtn")
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.clicked.connect(self.handle_catalog_search)
        search_row.addWidget(self.btn_search)
        hongguo_controls_layout.addLayout(search_row)

        # 2c. Genre Filter Chips (Wrapping flow)
        self.genre_scroll = QScrollArea()
        self.genre_scroll.setFixedHeight(82)
        self.genre_scroll.setWidgetResizable(True)
        self.genre_scroll.setObjectName("genreScroll")
        self.genre_container = QWidget()
        self.genre_container.setObjectName("genreContainer")
        self.genre_layout = FlowLayout(
            self.genre_container, margin=2, spacing=6)

        self.genre_buttons = {}
        for kh_label, api_genre in GENRES_MAP:
            chip = QPushButton(kh_label)
            chip.setObjectName("genreChip")
            chip.setCheckable(True)
            chip.setChecked(api_genre == "")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _, g=api_genre,
                                 b=chip: self.handle_genre_change(g, b))
            self.genre_layout.addWidget(chip)
            self.genre_buttons[api_genre] = chip

        self.genre_scroll.setWidget(self.genre_container)
        hongguo_controls_layout.addWidget(self.genre_scroll)

        right_layout.addWidget(self.hongguo_controls_widget)

        # 3. Other Platforms Banner / Guide Widget (Hidden by default in Hongguo mode)
        self.other_platform_banner = QFrame()
        self.other_platform_banner.setObjectName("platformBanner")
        banner_layout = QHBoxLayout(self.other_platform_banner)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        banner_layout.setSpacing(12)

        self.banner_hint_lbl = QLabel()
        self.banner_hint_lbl.setStyleSheet(
            "color: #f1f5f9; font-size: 12px; line-height: 1.4;")
        banner_layout.addWidget(self.banner_hint_lbl, 1)

        self.other_platform_banner.hide()
        right_layout.addWidget(self.other_platform_banner)

        # 4. Section Header
        sec_row = QHBoxLayout()
        self.lbl_sec_title = QLabel("រឿងទាំងអស់")
        self.lbl_sec_title.setStyleSheet(
            "color: #f7efe7; font-size: 14px; font-weight: bold;")
        self.lbl_sec_count = QLabel("24 រឿង / page")
        self.lbl_sec_count.setStyleSheet("color: #9c8a7b; font-size: 12px;")
        sec_row.addWidget(self.lbl_sec_title, 1)
        sec_row.addWidget(self.lbl_sec_count, 0, Qt.AlignRight)
        right_layout.addLayout(sec_row)

        # 5. Scrollable Movies Card Grid
        self.catalog_scroll = QScrollArea()
        self.catalog_scroll.setWidgetResizable(True)
        self.catalog_scroll.setObjectName("catalogScroll")
        self.catalog_container = QWidget()
        self.catalog_container.setObjectName("catalogContainer")
        self.grid_layout = QGridLayout(self.catalog_container)
        self.grid_layout.setContentsMargins(6, 6, 6, 6)
        self.grid_layout.setSpacing(12)
        self.catalog_scroll.setWidget(self.catalog_container)
        right_layout.addWidget(self.catalog_scroll, 1)

        # 6. Pagination Bar & Footer
        self.pagination_widget = QWidget()
        pag_row = QHBoxLayout(self.pagination_widget)
        pag_row.setContentsMargins(0, 0, 0, 0)
        pag_row.setSpacing(10)

        self.btn_prev = QPushButton("◀ មុន (Prev)")
        self.btn_prev.setObjectName("secondaryBtn")
        self.btn_prev.setCursor(Qt.PointingHandCursor)
        self.btn_prev.clicked.connect(self.handle_prev_page)
        pag_row.addWidget(self.btn_prev)

        self.lbl_pagination = QLabel("ទំព័រ 1 / 34")
        self.lbl_pagination.setObjectName("paginationLabel")
        pag_row.addWidget(self.lbl_pagination)

        self.btn_next = QPushButton("បន្ទាប់ (Next) ▶")
        self.btn_next.setObjectName("secondaryBtn")
        self.btn_next.setCursor(Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self.handle_next_page)
        pag_row.addWidget(self.btn_next)

        pag_row.addStretch()

        # License / Account Badge
        self.lbl_license_badge = QLabel(
            "គណនី៖ AI Dubber Ultimate • 1080p Ultra HD")
        self.lbl_license_badge.setObjectName("licenseBadge")
        pag_row.addWidget(self.lbl_license_badge)

        right_layout.addWidget(self.pagination_widget)
        root_layout.addWidget(right_panel, 1)

    # ── Platform Switcher ────────────────────────────────────────────────────

    def set_active_platform(self, platform_id: str):
        if platform_id not in [p[0] for p in SUPPORTED_PLATFORMS]:
            return
        self.selected_platform = platform_id

        # Update button visual state
        for pid, btn in self.platform_buttons.items():
            is_active = (pid == platform_id)
            btn.setProperty("active", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

        p_info = next(
            (p for p in SUPPORTED_PLATFORMS if p[0] == platform_id), None)
        title_text = p_info[1] if p_info else platform_id
        hint_text = p_info[3] if p_info else ""

        self.lbl_breadcrumb.setText(f"{platform_id.upper()} • រឿងទាំងអស់")
        self.lbl_main_title.setText(title_text)

        # Platform-specific placeholder hints
        if platform_id == "YouTube":
            self.link_input.setPlaceholderText(
                "▶️ បិទភ្ជាប់ YouTube Link (Video / Playlist / Shorts)...")
        elif platform_id == "TikTok":
            self.link_input.setPlaceholderText(
                "🎵 បិទភ្ជាប់ TikTok Video Link...")
        elif platform_id == "Facebook":
            self.link_input.setPlaceholderText(
                "👥 បិទភ្ជាប់ Facebook Watch / Reels Link...")
        else:
            self.link_input.setPlaceholderText(
                f"🔍 បិទភ្ជាប់ (Paste) Link {platform_id} ឬ ID...")

        if platform_id == "Hongguo":
            self.hongguo_controls_widget.show()
            self.other_platform_banner.hide()
            self.pagination_widget.show()
            self.load_catalog(category=self.active_category,
                              page=self.current_page)
        else:
            self.hongguo_controls_widget.hide()
            self.other_platform_banner.show()
            self.pagination_widget.hide()
            self.banner_hint_lbl.setText(
                f"💡 <b>{hint_text}</b><br/>"
                f"បញ្ចូល Link រឿង {platform_id} ក្នុងប្រអប់ខាងឆ្វេង ឬចុចលើរឿងគំរូខាងក្រោមដើម្បីទាញយក!"
            )
            self._display_platform_explorer(platform_id)

    def on_link_text_changed(self, text: str):
        detected = detect_platform_from_url(text)
        if detected and detected != self.selected_platform:
            self.set_active_platform(detected)
        target = detected if detected else self.selected_platform
        clean = text.strip()
        if target in ("TikTok", "YouTube", "Facebook") and (clean.startswith("http://") or clean.startswith("https://")):
            # Debounce: restart timer on each keystroke — only fires 500ms after user stops typing
            self._pending_social_url = clean
            self._social_debounce_timer.start()

    def _trigger_social_fetch(self):
        """Called after the 500ms debounce delay — starts SocialMetadataWorker for the pending social URL."""
        url = self._pending_social_url
        if not url:
            return
        detected = detect_platform_from_url(url)
        target_platform = detected if detected else self.selected_platform
        if target_platform not in ("TikTok", "YouTube", "Facebook"):
            return

        # Cancel any previously running social worker
        if self._social_worker and self._social_worker.isRunning():
            self._social_worker.terminate()
            self._social_worker.wait()

        # Show loading state
        self.lbl_ep_count.setText("🔍 កំពុងផ្ទុក...")
        self.btn_check.setEnabled(False)
        self.preview_label.setText("⌛\n\nកំពុងផ្ទុក...")

        self._social_worker = SocialMetadataWorker(
            platform=target_platform,
            url=url,
            downloader=self.downloader,
            parent=self,
        )
        self._social_worker.detail_ready.connect(self._apply_series_detail)
        self._social_worker.status_sig.connect(
            lambda msg: self.lbl_ep_count.setText(msg))
        self._social_worker.error.connect(
            lambda _err, _plat=target_platform, _url=url: self._apply_series_detail(
                fetch_social_series_info(_plat, _url, self.downloader)
            )
        )
        self._social_worker.start()

    def _display_platform_explorer(self, platform_id: str):
        self._clear_grid()
        self.lbl_sec_title.setText(f"{platform_id} - រឿងពេញនិយម (Featured)")
        self.lbl_sec_count.setText("ចុច Card ដើម្បីផ្ទុក Episode")
        self.lbl_subtitle.setText(
            f"{platform_id} Dramas • ចុច Card ដើម្បីទាញយក")

        items = FEATURED_PLATFORM_DRAMAS.get(platform_id, [])
        if not items:
            lbl_empty = QLabel(
                f"មិនទាន់មានរឿងគំរូសម្រាប់ {platform_id} ទេ។ សូមបិទភ្ជាប់ Link ដើម្បីទាញយក!")
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setStyleSheet(
                "color: #7f6e62; font-size: 14px; padding: 40px;")
            self.grid_layout.addWidget(lbl_empty, 0, 0, 1, 6)
            return

        cols = 6
        for idx, drama in enumerate(items):
            card = DramaCardWidget(
                drama,
                self.image_cache,
                self.thread_pool,
                self.image_loader_signals,
                parent=self.catalog_container,
            )
            card.clicked.connect(self.on_drama_card_clicked)
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)
            self.card_widgets.append(card)

    # ── Styles ───────────────────────────────────────────────────────────────

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0f141c;
            }
            QWidget {
                color: #f1f5f9;
                font-family: 'Segoe UI', 'Noto Sans Khmer', 'Khmer OS Battambang', 'PingFang SC', sans-serif;
            }
            QFrame#leftSidebar, QFrame#rightMainContent {
                background-color: #141a24;
                border: 1px solid #212936;
                border-radius: 16px;
            }
            QFrame#innerPanel {
                background-color: #161d28;
                border: 1px solid #232d3e;
                border-radius: 12px;
            }
            QFrame#platformBanner {
                background: linear-gradient(135deg, #162032, #1c273c);
                border: 1px solid #2e3e56;
                border-radius: 12px;
            }
            QFrame#previewBox {
                background-color: #090d14;
                border: 2px solid #00b4d8;
                border-radius: 12px;
            }
            QLabel#breadcrumb {
                color: #f97316;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QLabel#mainTitle {
                color: #ffffff;
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#subtitle {
                color: #8b949e;
                font-size: 12px;
            }
            QLineEdit {
                background-color: #0d121b;
                border: 1px solid #253142;
                border-radius: 10px;
                padding: 6px 12px;
                color: #ffffff;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1.5px solid #f97316;
            }
            QPushButton {
                background-color: #1a2230;
                border: 1px solid #2b394f;
                border-radius: 10px;
                padding: 6px 14px;
                color: #e2e8f0;
                font-weight: 700;
                font-size: 12px;
            }
            QPushButton:hover {
                border-color: #f97316;
                color: #ffffff;
            }
            QPushButton#platformBtn {
                background-color: #161d28;
                border: 1px solid #283548;
                border-radius: 16px;
                padding: 6px 14px;
                font-size: 11.5px;
                font-weight: 700;
                color: #94a3b8;
            }
            QPushButton#platformBtn:hover {
                background-color: #1e293b;
                border-color: #00b4d8;
                color: #ffffff;
            }
            QPushButton#platformBtn[active="true"] {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff4b2b, stop:1 #ff416c);
                border: 1px solid #ff4b2b;
                color: #ffffff;
                font-weight: 800;
            }
            QPushButton#platformBtn[platform="DramaBox"][active="true"] {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00b4d8, stop:1 #0077b6);
                border: 1px solid #00b4d8;
            }
            QPushButton#platformBtn[platform="ReelShort"][active="true"] {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f59e0b, stop:1 #d97706);
                border: 1px solid #f59e0b;
            }
            QPushButton#platformBtn[platform="NetShort"][active="true"] {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #6d28d9);
                border: 1px solid #8b5cf6;
            }
            QPushButton#platformBtn[platform="ShortMax"][active="true"] {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:1 #1d4ed8);
                border: 1px solid #3b82f6;
            }
            QPushButton#platformBtn[platform="PineDrama"][active="true"] {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #047857);
                border: 1px solid #10b981;
            }
            QPushButton#platformBtn[platform="GoodShort"][active="true"] {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #6366f1, stop:1 #4338ca);
                border: 1px solid #6366f1;
            }
            QPushButton#orangeBtn {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff6a00, stop:1 #ee0979);
                border: none;
                border-radius: 18px;
                color: #ffffff;
                font-weight: 800;
            }
            QPushButton#orangeBtn:hover {
                background-color: #fb923c;
            }
            QPushButton#greenBtn {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #059669);
                border: none;
                border-radius: 10px;
                color: #ffffff;
                font-weight: 800;
                font-size: 13px;
            }
            QPushButton#greenBtn:hover {
                background-color: #34d399;
            }
            QPushButton#secondaryBtn {
                background-color: #18202c;
                border: 1px solid #283548;
                color: #cbd5e1;
            }
            QPushButton#catTabBtn {
                background-color: #18202c;
                border: 1px solid #283548;
                border-radius: 20px;
                padding: 8px 18px;
                font-weight: 700;
                font-size: 12px;
                color: #94a3b8;
            }
            QPushButton#catTabBtn:checked {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff4b2b, stop:1 #ff416c);
                border: 1px solid #ff4b2b;
                color: #ffffff;
            }
            QPushButton#genreChip {
                background-color: #161d28;
                border: 1px solid #243042;
                border-radius: 14px;
                padding: 4px 12px;
                font-size: 11px;
                font-weight: 600;
                color: #cbd5e1;
            }
            QPushButton#genreChip:hover {
                border-color: #f97316;
                color: #ffffff;
            }
            QPushButton#genreChip:checked {
                background-color: #e11d48;
                border: 1px solid #f43f5e;
                color: #ffffff;
            }
            QPushButton#epChip {
                background-color: #161d28;
                border: 1px solid #273549;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 700;
                color: #94a3b8;
            }
            QPushButton#epChip:checked {
                background-color: #f97316;
                border: 1px solid #ea580c;
                color: #ffffff;
            }
            QFrame#dramaCard {
                background-color: #141a24;
                border: 1px solid #212936;
                border-radius: 10px;
            }
            QFrame#dramaCard:hover {
                border: 1.5px solid #00b4d8;
                background-color: #1a2230;
            }
            QLabel#cardTitle {
                color: #ffffff;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#cardSubtitle {
                color: #8b949e;
                font-size: 10.5px;
            }
            QLabel#cardEpBadge {
                background-color: rgba(9, 13, 20, 0.85);
                color: #fbbf24;
                font-size: 10.5px;
                font-weight: 800;
                padding: 2px 6px;
                border-radius: 4px;
                border: 1px solid #f59e0b;
            }
            QFrame#queueEmptyBox {
                background-color: #0f141c;
                border: 1px dashed #242f42;
                border-radius: 10px;
            }
            QFrame#queueItem {
                background-color: #18202c;
                border: 1px solid #283548;
                border-radius: 8px;
            }
            QProgressBar#queueBar {
                background-color: #0b0f17;
                border: none;
                border-radius: 3px;
            }
            QProgressBar#queueBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #34d399);
                border-radius: 3px;
            }
            QComboBox#darkCombo {
                background-color: #161d28;
                border: 1px solid #283548;
                border-radius: 8px;
                padding: 4px 10px;
                color: #f1f5f9;
                font-weight: bold;
                font-size: 12px;
            }
            QComboBox#darkCombo QAbstractItemView {
                background-color: #141a24;
                color: #f1f5f9;
                selection-background-color: #f97316;
            }
            QLabel#paginationLabel {
                color: #94a3b8;
                font-size: 12px;
                font-weight: bold;
                padding: 0 8px;
            }
            QLabel#licenseBadge {
                background-color: #161d28;
                border: 1px solid #283548;
                border-radius: 8px;
                padding: 6px 14px;
                color: #38bdf8;
                font-size: 11px;
                font-weight: bold;
            }
            QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {
                border: none;
                background: transparent;
                background-color: transparent;
            }
            QScrollArea#episodesScroll {
                background-color: #0d121b;
                border: 1px solid #202b3c;
                border-radius: 8px;
            }
            QScrollBar:horizontal {
                border: none;
                background: #0d1117;
                height: 6px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #253142;
                min-width: 20px;
                border-radius: 3px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #38bdf8;
            }
            QScrollBar:vertical {
                border: none;
                background: #0d1117;
                width: 8px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #253142;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #38bdf8;
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                width: 0px;
                height: 0px;
            }
        """)

    # ── Catalog & Data Loading ───────────────────────────────────────────────

    def load_catalog(self, category: str = "live", genre: str = "", q: str = "", page: int = 1):
        if self.selected_platform != "Hongguo":
            self._display_platform_explorer(self.selected_platform)
            return

        self.active_category = category
        self.active_genre = genre
        self.current_search_query = q
        self.current_page = page

        # Update category buttons state
        for k, btn in self.cat_buttons.items():
            btn.setChecked(k == category)

        # Clear existing cards
        self._clear_grid()
        self.lbl_sec_title.setText("កំពុងផ្ទុក... (Loading...)")

        if self._catalog_worker and self._catalog_worker.isRunning():
            self._catalog_worker.terminate()
            self._catalog_worker.wait()

        self._catalog_worker = CatalogWorker(
            self.hongguo_client,
            category=category,
            genre=genre,
            q=q,
            sort=self.active_sort,
            page=page,
            size=24,
            parent=self,
        )
        self._catalog_worker.results_ready.connect(self._populate_grid)
        self._catalog_worker.error.connect(self._on_catalog_error)
        self._catalog_worker.start()

    def _on_catalog_error(self, err_msg: str):
        _log.error("Catalog loading error: %s", err_msg)
        self.lbl_sec_title.setText("បរាជ័យក្នុងការផ្ទុក (Failed to load)")

    def _clear_grid(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            wid = item.widget()
            if wid:
                wid.deleteLater()
        self.card_widgets.clear()

    def _populate_grid(self, cur_page: int, total_pages: int, items: list):
        self.current_page = cur_page
        self.total_pages = max(1, total_pages)
        self.lbl_pagination.setText(
            f"ទំព័រ {self.current_page} / {self.total_pages}")
        self.lbl_subtitle.setText(
            f"រឿងទាំងអស់ • ទំព័រ {self.current_page}/{self.total_pages} • ចុច Card ដើម្បីទាញយក")

        label_name = self.current_search_query or (self.active_genre or (
            "រឿងមនុស្សពិត" if self.active_category == "live" else "រឿងទាំងអស់"))
        self.lbl_sec_title.setText(f"{label_name} ({len(items)} រឿង)")

        if not items:
            lbl_empty = QLabel("មិនមានរឿងត្រូវបង្ហាញទេ។ (No dramas found.)")
            lbl_empty.setAlignment(Qt.AlignCenter)
            lbl_empty.setStyleSheet(
                "color: #7f6e62; font-size: 14px; padding: 40px;")
            self.grid_layout.addWidget(lbl_empty, 0, 0, 1, 6)
            return

        cols = 6  # 6 cards per row
        for idx, drama in enumerate(items):
            card = DramaCardWidget(
                drama,
                self.image_cache,
                self.thread_pool,
                self.image_loader_signals,
                parent=self.catalog_container,
            )
            card.clicked.connect(self.on_drama_card_clicked)
            r = idx // cols
            c = idx % cols
            self.grid_layout.addWidget(card, r, c)
            self.card_widgets.append(card)

    def _on_image_loaded(self, url: str, content: bytes):
        pix = QPixmap()
        if pix.loadFromData(content):
            self.image_cache[url] = pix
            for card in self.card_widgets:
                card.set_loaded_pixmap(url, pix)
            if self.current_series_detail and self.current_series_detail.get("series_cover") == url:
                self.preview_label.setPixmap(pix)

    # ── User Actions & Event Handlers ────────────────────────────────────────

    def handle_category_change(self, category: str):
        self.active_category = category
        self.active_genre = ""
        self.current_search_query = ""
        self.omni_search_input.clear()
        for g, b in self.genre_buttons.items():
            b.setChecked(g == "")
        self.load_catalog(category=category, page=1)

    def handle_genre_change(self, genre: str, clicked_chip: QPushButton):
        for g, b in self.genre_buttons.items():
            b.setChecked(b == clicked_chip)
        self.active_genre = genre
        self.current_search_query = ""
        self.omni_search_input.clear()
        self.load_catalog(category="all", genre=genre, page=1)

    def handle_catalog_search(self):
        query = self.omni_search_input.text().strip()
        if not query:
            return
        for b in self.genre_buttons.values():
            b.setChecked(False)
        self.load_catalog(q=query, page=1)

    def handle_refresh(self):
        if self.selected_platform == "Hongguo":
            self.load_catalog(
                category=self.active_category,
                genre=self.active_genre,
                q=self.current_search_query,
                page=self.current_page,
            )
        else:
            self._display_platform_explorer(self.selected_platform)

    def handle_prev_page(self):
        if self.selected_platform == "Hongguo" and self.current_page > 1:
            self.load_catalog(
                category=self.active_category,
                genre=self.active_genre,
                q=self.current_search_query,
                page=self.current_page - 1,
            )

    def handle_next_page(self):
        if self.selected_platform == "Hongguo" and self.current_page < self.total_pages:
            self.load_catalog(
                category=self.active_category,
                genre=self.active_genre,
                q=self.current_search_query,
                page=self.current_page + 1,
            )

    def on_drama_card_clicked(self, drama_data: dict):
        series_id = str(drama_data.get("series_id", ""))
        self.link_input.setText(series_id)
        self._load_series_into_preview(series_id)

    def handle_check_link(self):
        text = self.link_input.text().strip()
        if not text:
            return
        self._load_series_into_preview(text)

    def _load_series_into_preview(self, input_text: str):
        clean_text = input_text.strip()
        detected = detect_platform_from_url(clean_text)
        target_platform = detected if detected else self.selected_platform

        # Social platforms: use async SocialMetadataWorker for real title/thumbnail/playlist data
        if target_platform in ("TikTok", "YouTube", "Facebook"):
            # Stop debounce timer — we're triggering explicitly now
            self._social_debounce_timer.stop()
            self._pending_social_url = clean_text

            # Cancel any running workers
            if self._social_worker and self._social_worker.isRunning():
                self._social_worker.terminate()
                self._social_worker.wait()
            if self._detail_worker and self._detail_worker.isRunning():
                self._detail_worker.terminate()
                self._detail_worker.wait()

            # Show loading state
            self.lbl_ep_count.setText("🔍 កំពុងផ្ទុក...")
            self.btn_check.setEnabled(False)
            self.preview_label.setText("⌛\n\nកំពុងផ្ទុក...")

            self._social_worker = SocialMetadataWorker(
                platform=target_platform,
                url=clean_text,
                downloader=self.downloader,
                parent=self,
            )
            self._social_worker.detail_ready.connect(self._apply_series_detail)
            self._social_worker.status_sig.connect(
                lambda msg: self.lbl_ep_count.setText(msg))
            self._social_worker.error.connect(
                lambda _err, _plat=target_platform, _url=clean_text: self._apply_series_detail(
                    fetch_social_series_info(_plat, _url, self.downloader)
                )
            )
            self._social_worker.start()
            return

        self.lbl_ep_count.setText("កំពុងពិនិត្យ...")
        self.btn_check.setEnabled(False)

        if self._detail_worker and self._detail_worker.isRunning():
            self._detail_worker.terminate()
            self._detail_worker.wait()

        self._detail_worker = UnifiedSeriesDetailWorker(
            platform=self.selected_platform,
            input_text=input_text,
            hongguo_client=self.hongguo_client,
            sekai_api=self.sekai_api,
            downloader=self.downloader,
            parent=self,
        )
        self._detail_worker.detail_ready.connect(self._apply_series_detail)
        self._detail_worker.error.connect(
            lambda _: self._apply_series_detail(None))
        self._detail_worker.start()

    def _apply_series_detail(self, detail: Optional[dict]):
        self.btn_check.setEnabled(True)
        if not detail:
            self.lbl_ep_count.setText("ចំនួនភាគ --")
            self.preview_label.setText("▶\n\nរង់ចាំការពិនិត្យ")
            QMessageBox.warning(
                self, "រកមិនឃើញ", "មិនអាចទាញយកព័ត៌មានរឿងនេះបានទេ។ សូមពិនិត្យ Link ឡើងវិញ។")
            return

        self.current_series_detail = detail
        title = detail.get("series_name", "Drama Series")
        ep_cnt = detail.get("episode_cnt", 0)
        cover_url = detail.get("series_cover", "")
        platform = detail.get("platform", self.selected_platform)

        self.lbl_ep_count.setText(f"ចំនួនភាគ: {ep_cnt}")

        # Platform-specific helper text
        if platform in ("TikTok", "YouTube", "Facebook"):
            if ep_cnt == 1:
                self.lbl_helper.setText(
                    f"<b>《{title}》</b> ({platform})<br>"
                    f"ចុច <b>Download</b> ដើម្បីទាញយក!"
                )
            else:
                self.lbl_helper.setText(
                    f"<b>《{title}》</b> ({platform})<br>"
                    f"{ep_cnt} វីដេអូ • ជ្រើសរើសភាគ រួចចុច Download!"
                )
        else:
            intro_text = detail.get("series_intro", "")
            self.lbl_helper.setText(
                f"<b>《{title}》</b> ({platform})\n{intro_text[:70]}...")

        # Load cover / thumbnail
        if cover_url:
            if cover_url in self.image_cache:
                self.preview_label.setPixmap(self.image_cache[cover_url])
            else:
                task = ImageLoadTask(cover_url, self.image_loader_signals)
                self.thread_pool.start(task)
        else:
            # Show platform emoji as placeholder when no cover image
            platform_icons = {
                "YouTube": "▶️", "TikTok": "🎵", "Facebook": "👥",
                "Hongguo": "🔥", "DramaBox": "🎬", "ReelShort": "⚡",
            }
            icon = platform_icons.get(platform, "🎬")
            self.preview_label.setText(f"{icon}\n\n{platform}")

        # Populate episode chips
        self._populate_episode_chips(ep_cnt)

    def _populate_episode_chips(self, total_eps: int):
        while self.episodes_layout.count():
            item = self.episodes_layout.takeAt(0)
            wid = item.widget()
            if wid:
                wid.setParent(None)
                wid.deleteLater()

        self.selected_episodes.clear()
        for i in range(1, total_eps + 1):
            chip = EpisodeChip(i, self.episodes_container)
            chip.toggled.connect(
                lambda checked, num=i: self._on_ep_chip_toggled(num, checked))
            self.episodes_layout.addWidget(chip)
            self.selected_episodes.add(i)

        self.combo_range.setCurrentIndex(0)
        self.chk_select_all.setChecked(True)

    def _on_ep_chip_toggled(self, ep_num: int, checked: bool):
        if checked:
            self.selected_episodes.add(ep_num)
        else:
            self.selected_episodes.discard(ep_num)
        self.combo_range.blockSignals(True)
        self.combo_range.setCurrentIndex(0)
        self.combo_range.blockSignals(False)

    def handle_toggle_select_all(self, state: int):
        checked = (state == Qt.Checked)
        for i in range(self.episodes_layout.count()):
            item = self.episodes_layout.itemAt(i)
            if item and item.widget():
                item.widget().setChecked(checked)

    def handle_range_changed(self, idx: int):
        if not self.current_series_detail:
            return
        total = self.current_series_detail.get("episode_cnt", 0)

        limit = total
        if idx == 1:
            limit = min(10, total)
        elif idx == 2:
            limit = min(30, total)
        elif idx == 3:
            limit = min(5, total)

        for i in range(self.episodes_layout.count()):
            item = self.episodes_layout.itemAt(i)
            if item and item.widget():
                ep_num = getattr(item.widget(), "ep_num", i + 1)
                item.widget().setChecked(ep_num <= limit)

    def handle_threads_changed(self, idx: int):
        threads_list = [1, 2, 3, 4, 5, 8]
        if 0 <= idx < len(threads_list):
            self.max_workers = threads_list[idx]
            settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
            settings.setValue("max_workers", self.max_workers)
            _log.info("Download concurrency set to %d threads",
                      self.max_workers)

    def handle_cancel_download(self):
        if self.current_download_worker and self.current_download_worker.isRunning():
            self.current_download_worker.cancel()
            self.btn_cancel_dl.setEnabled(False)
            self.btn_download.setEnabled(True)
            self.lbl_queue_header.setText(
                "ដំណើរការទាញយកត្រូវបានបញ្ឈប់ (Cancelled)")
            QMessageBox.information(
                self, "បានបញ្ឈប់", "ការទាញយកត្រូវបានបញ្ឈប់ដោយជោគជ័យ។")

    # ── Download Execution ───────────────────────────────────────────────────

    def handle_download_now(self):
        if not self.current_series_detail:
            QMessageBox.information(
                self, "ជ្រើសរើសរឿង", "សូមជ្រើសរើសរឿង ឬបិទភ្ជាប់ Link រឿងមុនពេលទាញយក!")
            return

        if not self.selected_episodes:
            QMessageBox.warning(self, "ជ្រើសរើសភាគ",
                                "សូមជ្រើសរើសយ៉ាងហោចណាស់ 1 ភាគដើម្បីទាញយក!")
            return

        platform = self.current_series_detail.get("platform", "Hongguo")
        series_name = self.current_series_detail.get("series_name", "Drama")

        # Quality selection
        q_idx = self.combo_quality.currentIndex()
        quality = "1080p" if q_idx == 0 else ("720p" if q_idx == 1 else "480p")

        # Hide empty queue widget
        self.empty_queue_widget.hide()

        # Add Queue row items
        queue_widgets = {}
        for ep_num in sorted(self.selected_episodes):
            ep_tag = f"第{ep_num:03d}集" if platform == "Hongguo" else f"EP{ep_num:02d}"
            row = DownloadQueueItemWidget(
                ep_num, series_name, ep_tag, parent=self.queue_container)
            self.queue_items_layout.addWidget(row)
            queue_widgets[ep_num] = row

        self.lbl_queue_header.setText(
            f"ដំណើរការទាញយក (Download Queue)  {len(self.selected_episodes)}")
        self.btn_download.setEnabled(False)
        self.btn_cancel_dl.setEnabled(True)

        worker = UnifiedDownloadWorker(
            series_detail=self.current_series_detail,
            selected_eps=list(self.selected_episodes),
            output_dir=self.output_dir,
            quality=quality,
            hongguo_client=self.hongguo_client,
            downloader=self.downloader,
            sekai_api=self.sekai_api,
            max_workers=self.max_workers,
        )

        def _on_prog(tid, pct, spd, done_b, tot_b):
            if tid in queue_widgets:
                queue_widgets[tid].update_progress(pct, spd, done_b, tot_b)

        def _on_ep_done(tid, path):
            if tid in queue_widgets:
                queue_widgets[tid].set_completed(path)

        def _on_ep_failed(tid, reason):
            if tid in queue_widgets:
                queue_widgets[tid].set_failed(reason)

        def _on_stat(active, done, total):
            self.lbl_queue_header.setText(
                f"ដំណើរការទាញយក (Download Queue) • ⚡ {active} កំពុងទាញយក | {done}/{total} ភាគចប់"
            )

        def _on_all_done(succ, fail):
            self.btn_download.setEnabled(True)
            self.btn_cancel_dl.setEnabled(False)
            self.lbl_queue_header.setText(
                f"ដំណើរការទាញយក (Download Queue)  {len(self.selected_episodes)}")
            QMessageBox.information(
                self,
                "ទាញយកចប់សព្វគ្រប់",
                f"ការទាញយកបានបញ្ចប់!\n✅ ជោគជ័យ: {succ} ភាគ\n❌ បរាជ័យ: {fail} ភាគ\n\nបានរក្សាទុកក្នុង: {self.output_dir}",
            )

        worker.progress_sig.connect(_on_prog)
        worker.episode_done_sig.connect(_on_ep_done)
        worker.episode_failed_sig.connect(_on_ep_failed)
        worker.queue_stat_sig.connect(_on_stat)
        worker.all_done_sig.connect(_on_all_done)
        self.current_download_worker = worker
        worker.start()

    # ── Folder & Settings ────────────────────────────────────────────────────

    def browse_folder(self):
        new_dir = QFileDialog.getExistingDirectory(
            self, "Select Save Folder", self.output_dir)
        if new_dir:
            self.output_dir = new_dir
            self.btn_folder.setToolTip(f"Save Path: {new_dir}")
            self.save_output_dir()

    def default_output_dir(self):
        candidate = os.path.join(APP_ROOT, "downloads")
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            return os.path.expanduser("~/Downloads")

    def load_output_dir(self):
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        path = settings.value("output_dir", "", type=str)
        if path and os.path.exists(path):
            return path
        return self.default_output_dir()

    def save_output_dir(self):
        settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
        settings.setValue("output_dir", self.output_dir)

    def open_settings_dialog(self):
        dlg = DownloaderSettingsDialog(
            self,
            current_api_base=self.api_base,
            current_proxy=self.proxy_url,
            current_cf_clearance=self.cf_clearance,
            current_max_workers=self.max_workers,
        )
        if dlg.exec_() == QDialog.Accepted:
            self.api_base, self.proxy_url, self.cf_clearance, self.max_workers = dlg.get_values()
            settings = QSettings(ORGANIZATION_NAME, APPLICATION_NAME)
            settings.setValue("api_base", self.api_base)
            settings.setValue("proxy_url", self.proxy_url)
            settings.setValue("cf_clearance", self.cf_clearance)
            settings.setValue("max_workers", self.max_workers)

            if self.sekai_api:
                self.sekai_api.set_api_base(self.api_base)
                self.sekai_api.set_proxy(self.proxy_url)
                self.sekai_api.set_cf_clearance(self.cf_clearance)
            if self.downloader:
                if self.proxy_url:
                    self.downloader.session.proxies = {
                        "http": self.proxy_url, "https": self.proxy_url}
                else:
                    self.downloader.session.proxies = {}

            if hasattr(self, "combo_threads"):
                worker_map = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 8: 5}
                self.combo_threads.blockSignals(True)
                self.combo_threads.setCurrentIndex(
                    worker_map.get(self.max_workers, 3))
                self.combo_threads.blockSignals(False)

            QMessageBox.information(
                self, "Success", "Settings saved successfully!")


# ── Standalone App Entry Point ───────────────────────────────────────────────

if __name__ == "__main__":
    app = QApplication(sys.argv)
    tool = DramaBoxTool()
    tool.show()
    sys.exit(app.exec_())
