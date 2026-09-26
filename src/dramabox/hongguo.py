# -*- coding: utf-8 -*-
"""
Hongguo (红果短剧) API Client & Video Stream Resolver.
Provides:
  - Leaderboard rankings (live, comic, ai, rankings)
  - Catalog browsing with genre filters, search, and pagination
  - Series details, episodes count, and episode video ID extraction
  - Direct video/mp4 stream resolution
  - Chunked high-speed MP4 downloading with progress callbacks
"""

import json
import logging
import os
import re
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

_log = logging.getLogger("dramabox.hongguo")

EXPLORER_BASE = "https://explorer.hongguodownloader.com"
HONGGUO_WEB_BASE = "https://hongguoduanju.com"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,km;q=0.7",
}

# Mapping of Khmer UI Genre names to API search values
GENRES_MAP = [
    ("រឿងទាំងអស់ All Dramas", ""),
    ("រឿងស្នេហា Romance", "爱情"),
    ("រឿងសម័យកាល Period", "年代"),
    ("រឿងព្យាបាទ / តស៊ូកែវាសនា Comeback", "逆袭"),
    ("រឿងព្រះរាជា Legend", "大男主"),
    ("រឿងកែប្រែ Growth", "成长"),
    ("រឿងគ្រួសារ Family", "家庭"),
    ("រឿងត្រកូល Clan", "豪门"),
    ("រឿងកុមារគួរឱ្យស្រឡាញ់ Cute Kids", "萌宝"),
    ("រឿងអាថ៌កំបាំង Suspense", "悬疑"),
    ("រឿងរន្ធត់ Thriller", "惊悚"),
    ("រឿងភ័យរន្ធត់ Horror", "恐怖"),
    ("រឿងអបិយជំនឿ Supernatural", "灵异"),
    ("រឿងបុរាណ Costume", "古代"),
    ("រឿងយុទ្ធសិល្ប៍ Fantasy", "玄幻"),
    ("រឿងពិភពវេទមន្ត Wonder", "脑洞"),
    ("រឿងទីក្រុង Urban", "都市"),
    ("រឿងយុវវ័យ Youth", "青春"),
    ("រឿងកំប្លែង Comedy", "搞笑"),
    ("រឿងវិទ្យាសាស្ត Sci-Fi", "科幻"),
    ("រឿងគ្រោះមហន្តរាយ Disaster", "末日"),
    ("រឿងវាយប្រហារ និងផ្សងព្រេង Action & Adventure", "冒险"),
    ("រឿងសង្គ្រាម War", "战争"),
    ("កម្មវិធីកម្សាន្ត Variety", "综艺"),
    ("រឿងជីវិត Drama", "剧情"),
]


class HongguoClient:
    """Client for interacting with Hongguo Short Drama platform."""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    # ── Discovery & Catalog ──────────────────────────────────────────────────

    def get_leaderboard(
        self,
        category: str = "live",
        board: str = "hot",
        size: int = 24,
    ) -> List[Dict[str, Any]]:
        """
        Fetch Hongguo leaderboard items.
        Categories:
          - 'live' : Live-Action (រឿងមនុស្សពិត)
          - 'comic': Comic (រឿងគំនូរជីវចល)
          - 'ai'   : AI Drama (រឿង AI)
          - 'all'  : Rankings (តារាងពេញនិយម)
        """
        url = f"{EXPLORER_BASE}/leaderboard"
        params = {"board": board, "category": category, "size": size}
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                return items
        except Exception as exc:
            _log.warning("get_leaderboard error: %s", exc)
        return []

    def get_explorer(
        self,
        page: int = 1,
        size: int = 24,
        sort: str = "hot",
        genre: str = "",
        q: str = "",
        status: str = "",
    ) -> Tuple[int, int, List[Dict[str, Any]]]:
        """
        Fetch catalog items with filtering, searching, and pagination.
        Returns: (current_page, total_pages, items)
        """
        url = f"{EXPLORER_BASE}/explorer"
        params: Dict[str, Any] = {
            "page": page,
            "size": size,
            "sort": sort,
        }
        if genre:
            params["genre"] = genre
        if q:
            params["q"] = q
        if status:
            params["status"] = status

        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                cur_page = data.get("page", 1)
                total_pages = data.get("pages", 1)
                items = data.get("items", [])
                return cur_page, total_pages, items
        except Exception as exc:
            _log.warning("get_explorer error: %s", exc)
        return page, 1, []

    # ── Detail & Metadata Parsing ────────────────────────────────────────────

    def extract_series_id(self, input_text: str) -> Optional[str]:
        """
        Extract numeric series_id from URL, share link, or raw ID.
        Examples:
          - https://hongguoduanju.com/detail?series_id=7683196130645003288
          - https://hongguoduanju.com/player/7683196130645003288
          - https://novelquickapp.com/...
          - 7683196130645003288
          - 《东北话事人》https://...
        """
        if not input_text:
            return None
        text = input_text.strip()

        # Check for query param series_id
        m = re.search(r"series_id=(\d{15,22})", text)
        if m:
            return m.group(1)

        # Check for path like /player/12345 or /detail/12345
        m = re.search(r"/(?:player|detail|drama|video|book)/(\d{15,22})", text)
        if m:
            return m.group(1)

        # Check for standalone large number
        m = re.search(r"\b(\d{16,22})\b", text)
        if m:
            return m.group(1)

        return None

    def get_series_detail(self, series_id_or_url: str) -> Optional[Dict[str, Any]]:
        """
        Fetches full metadata and episode vid_list for a Hongguo series.
        Returns dict with:
          - series_id
          - series_name (title)
          - series_cover (poster URL)
          - episode_cnt (total count)
          - series_intro (synopsis)
          - tags (list of genre strings)
          - vid_list (list of episode video IDs)
        """
        series_id = self.extract_series_id(series_id_or_url)
        if not series_id:
            # Maybe a title was passed? Try searching for it
            clean_q = re.sub(r"[《》]", "", series_id_or_url).strip()
            if clean_q:
                _, _, items = self.get_explorer(q=clean_q, size=1)
                if items:
                    series_id = str(items[0].get("series_id"))

        if not series_id:
            return None

        url = f"{HONGGUO_WEB_BASE}/detail?series_id={series_id}"
        headers = {"Referer": f"{HONGGUO_WEB_BASE}/"}
        try:
            resp = self.session.get(url, headers=headers, timeout=self.timeout)
            if resp.status_code != 200:
                _log.warning("Detail fetch status %d for %s", resp.status_code, url)
                return None

            m = re.search(r"_ROUTER_DATA\s*=\s*(\{.*?\});", resp.text)
            if not m:
                _log.warning("No _ROUTER_DATA found on detail page")
                return None

            data = json.loads(m.group(1))
            loader = data.get("loaderData", {})
            detail_page = loader.get("detail_page", {})
            sd = detail_page.get("seriesDetail", {})
            if not sd:
                # Fallback to check other keys
                for v in loader.values():
                    if isinstance(v, dict) and "seriesDetail" in v:
                        sd = v["seriesDetail"]
                        break

            if not sd:
                return None

            vid_list = sd.get("vid_list", [])
            total_eps = sd.get("episode_cnt", len(vid_list))

            return {
                "series_id": str(sd.get("series_id", series_id)),
                "series_name": sd.get("series_name", "Hongguo Drama"),
                "series_cover": sd.get("series_cover", ""),
                "episode_cnt": int(total_eps),
                "series_intro": sd.get("series_intro", ""),
                "tags": sd.get("tags", []),
                "vid_list": [str(v) for v in vid_list],
            }
        except Exception as exc:
            _log.error("Failed to fetch series detail: %s", exc)
            return None

    # ── Video Stream Resolution ──────────────────────────────────────────────

    def get_episode_stream_url(
        self,
        series_id: str,
        vid: Optional[str] = None,
        episode_index: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolves the direct MP4 streaming URL for an episode.
        Returns dict with:
          - main_url (direct video/mp4 URL)
          - duration (seconds)
          - width, height
          - poster_url
        """
        if vid:
            player_url = f"{HONGGUO_WEB_BASE}/player/{series_id}/{vid}"
        else:
            player_url = f"{HONGGUO_WEB_BASE}/player/{series_id}"

        headers = {"Referer": f"{HONGGUO_WEB_BASE}/detail?series_id={series_id}"}
        try:
            resp = self.session.get(player_url, headers=headers, timeout=self.timeout)
            if resp.status_code != 200:
                return None

            m = re.search(r"_ROUTER_DATA\s*=\s*(\{.*?\});", resp.text)
            if not m:
                return None

            data = json.loads(m.group(1))
            loader = data.get("loaderData", {})

            # Search loaderData for video_player_info
            for val in loader.values():
                if val and isinstance(val, dict):
                    vpi = val.get("video_player_info")
                    if vpi and vpi.get("main_url"):
                        return {
                            "main_url": vpi.get("main_url"),
                            "duration": vpi.get("duration", 0),
                            "width": vpi.get("width", 720),
                            "height": vpi.get("height", 1280),
                            "poster_url": vpi.get("poster_url", ""),
                        }
        except Exception as exc:
            _log.warning("Stream resolution error for %s: %s", player_url, exc)

        return None

    # ── High-Speed File Downloader ────────────────────────────────────────────

    def download_file(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[int, float, int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        referer: str = "https://hongguoduanju.com/",
    ) -> bool:
        """
        Downloads a media file with resume support, chunking, and speed metrics.
        progress_callback: fn(pct: int, speed_mbps: float, downloaded_bytes: int, total_bytes: int)
        """
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        part_path = dest_path + ".part"

        downloaded = 0
        if os.path.exists(part_path):
            downloaded = os.path.getsize(part_path)

        headers = {"Referer": referer}
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"

        try:
            resp = self.session.get(url, headers=headers, stream=True, timeout=20)
            if resp.status_code == 416:  # Range not satisfiable -> file already complete
                if os.path.exists(part_path):
                    os.replace(part_path, dest_path)
                    return True
                downloaded = 0
                headers.pop("Range", None)
                resp = self.session.get(url, headers=headers, stream=True, timeout=20)

            if resp.status_code not in (200, 206):
                _log.error("Download HTTP error: %d for %s", resp.status_code, url)
                return False

            total_size = downloaded
            content_length = resp.headers.get("Content-Length")
            if content_length:
                total_size += int(content_length)

            mode = "ab" if downloaded > 0 else "wb"
            start_time = time.time()
            bytes_since_tick = 0
            last_tick = start_time

            with open(part_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if cancel_check and cancel_check():
                        _log.info("Download cancelled by user.")
                        return False
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    bytes_since_tick += len(chunk)

                    now = time.time()
                    if now - last_tick >= 0.5:
                        speed = (bytes_since_tick / (now - last_tick)) / (1024 * 1024)
                        pct = int((downloaded / total_size) * 100) if total_size > 0 else 0
                        if progress_callback:
                            progress_callback(pct, speed, downloaded, total_size)
                        last_tick = now
                        bytes_since_tick = 0

            # Completed
            if os.path.exists(dest_path):
                try:
                    os.remove(dest_path)
                except OSError:
                    pass
            os.replace(part_path, dest_path)

            if progress_callback:
                progress_callback(100, 0.0, downloaded, downloaded)

            return True
        except Exception as exc:
            _log.error("Download failed: %s", exc)
            return False
