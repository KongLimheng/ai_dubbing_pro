# -*- coding: utf-8 -*-
"""
ReelShort Bypass and Media Extraction Manager.
Extracts full series episode lists and unencrypted HLS stream URLs directly from reelshort.com.
"""

import html
import json
import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

_log = logging.getLogger("reelshort.bypass")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.reelshort.com/",
}


class ReelShortBypassManager:
    """Manager for extracting full episodes and direct stream URLs from ReelShort."""

    def __init__(self, session: Optional[requests.Session] = None, status_callback=None):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._report = status_callback if status_callback else (lambda *args, **kwargs: None)

    def _log_status(self, message: str):
        self._report(message)

    def fetch_page(self, url: str, timeout: int = 15) -> str:
        headers = dict(DEFAULT_HEADERS)
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            headers["Referer"] = f"{parsed.scheme}://{parsed.netloc}/"
        response = self.session.get(url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.text

    def extract_next_data(self, page_html: str) -> dict:
        match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            page_html or "",
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return {}
        raw = match.group(1).strip()
        for candidate in (raw, html.unescape(raw)):
            try:
                payload = json.loads(candidate)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
        return {}

    def extract_series_slug(self, url: str, page_html: str = "") -> str:
        parsed = urlparse(url or "")
        path_parts = [p for p in parsed.path.split("/") if p]

        for i, part in enumerate(path_parts):
            if part.lower() in ("full-episodes", "episodes", "movie", "drama") and i + 1 < len(path_parts):
                candidate = path_parts[i + 1]
                slug_match = re.search(
                    r"(?:episode-\d+-|trailer-)?(.+?-[0-9a-f]{24})(?:-[a-z0-9]+)?$",
                    candidate,
                    re.IGNORECASE,
                )
                if slug_match:
                    return slug_match.group(1).strip("/")
                return candidate.strip("/")

        for segment in reversed(path_parts):
            slug_match = re.search(
                r"(?:episode-\d+-|trailer-)?(.+?-[0-9a-f]{24})(?:-[a-z0-9]+)?$",
                segment,
                re.IGNORECASE,
            )
            if slug_match:
                return slug_match.group(1).strip("/")

        if page_html:
            m = re.search(
                r'href=["\']/full-episodes/([^"\'/?#]+)',
                page_html,
                re.IGNORECASE,
            )
            if m:
                return m.group(1).strip("/")

        return ""

    def build_full_episodes_url(self, url: str, page_html: str = "") -> str:
        slug = self.extract_series_slug(url, page_html)
        if not slug:
            return url
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.reelshort.com"
        return f"{origin}/full-episodes/{slug}"

    def build_episode_url(self, origin: str, series_slug: str, serial_number: int, chapter_id: str) -> str:
        clean_origin = origin.rstrip("/") if origin else "https://www.reelshort.com"
        return f"{clean_origin}/episodes/episode-{serial_number}-{series_slug}-{chapter_id}"

    def get_drama_info(self, url: str) -> Tuple[str, List[dict]]:
        """
        Extract all episodes of a series across all pages.
        Returns (series_title, episodes_list).
        """
        full_episodes_url = self.build_full_episodes_url(url)
        self._log_status(f"Fetching ReelShort series metadata: {full_episodes_url}")

        first_page_html = self.fetch_page(full_episodes_url)
        next_data = self.extract_next_data(first_page_html)
        props = next_data.get("props", {}).get("pageProps", {})
        data = props.get("data", {}) if isinstance(props, dict) else {}

        series_title = (
            str(data.get("book_title") or "").strip()
            or self._extract_title(first_page_html)
            or "ReelShort Series"
        )
        series_slug = self.extract_series_slug(full_episodes_url, first_page_html)
        parsed = urlparse(full_episodes_url)
        origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else "https://www.reelshort.com"

        total_pages = int(data.get("totalPage") or props.get("totalPage") or 1)
        chapter_count = int(data.get("chapter_count") or data.get("total") or 0)
        page_size = int(data.get("page_size") or 12)
        if total_pages <= 1 and chapter_count and page_size:
            total_pages = max(1, (chapter_count + page_size - 1) // page_size)

        self._log_status(f"Found series '{series_title}' with ~{chapter_count or total_pages * 12} episodes across {total_pages} pages.")

        episodes: List[dict] = []
        seen_ids = set()

        def parse_chapters(chapter_list: list):
            for ch in chapter_list:
                if not isinstance(ch, dict):
                    continue
                cid = str(ch.get("chapter_id") or "").strip()
                if not cid or cid in seen_ids:
                    continue
                seen_ids.add(cid)
                s_num = int(ch.get("serial_number") or len(episodes) + 1)
                ep_url = self.build_episode_url(origin, series_slug, s_num, cid)
                ep_title = f"Episode {s_num} - {series_title}"
                episodes.append({
                    "id": cid,
                    "chapter_id": cid,
                    "num": s_num,
                    "title": ep_title,
                    "name": ep_title,
                    "url": ep_url,
                    "episode_url": ep_url,
                    "locked": False,
                    "thumbnail": str(ch.get("video_pic") or "").strip(),
                    "duration": ch.get("duration"),
                    "platform": "ReelShort",
                })

        parse_chapters(data.get("chapter_list", []))

        # Paginate through remaining pages
        for page_num in range(2, total_pages + 1):
            page_url = f"{full_episodes_url}/{page_num}"
            try:
                page_html = self.fetch_page(page_url)
                p_next_data = self.extract_next_data(page_html)
                p_data = p_next_data.get("props", {}).get("pageProps", {}).get("data", {})
                # Check for wrap-around
                cur_page = int(p_data.get("currentPage") or page_num)
                if cur_page != page_num:
                    break
                p_chapters = p_data.get("chapter_list", [])
                if not p_chapters:
                    break
                prev_len = len(episodes)
                parse_chapters(p_chapters)
                if len(episodes) == prev_len:
                    break
            except Exception as exc:
                self._log_status(f"Warning: page {page_num} fetch failed: {exc}")
                break

        episodes.sort(key=lambda x: int(x.get("num") or 0))
        self._log_status(f"Extracted {len(episodes)} total episodes for '{series_title}'.")
        return series_title, episodes

    def get_video_url(self, episode_url: str) -> Optional[str]:
        """
        Extract direct unencrypted .m3u8 stream URL for an episode.
        """
        if not episode_url:
            return None
        try:
            html_text = self.fetch_page(episode_url)
            next_data = self.extract_next_data(html_text)
            props = next_data.get("props", {}).get("pageProps", {})
            data = props.get("data", {}) if isinstance(props, dict) else {}

            video_url = data.get("video_url")
            if video_url and str(video_url).startswith("http"):
                return str(video_url).strip()

            # Fallback scan for m3u8 in props
            raw_props = json.dumps(props)
            m3u8_matches = re.findall(r'https?://[^\s"\'\\]+\.m3u8[^\s"\'\\]*', raw_props)
            for m in m3u8_matches:
                decoded = html.unescape(m.replace("\\u0026", "&").replace("\\/", "/"))
                return decoded

            # Fallback scan in raw html
            html_matches = re.findall(r'https?://[^\s"\'\\]+\.m3u8[^\s"\'\\]*', html_text)
            for m in html_matches:
                decoded = html.unescape(m.replace("\\u0026", "&").replace("\\/", "/"))
                return decoded

        except Exception as exc:
            self._log_status(f"Error extracting video URL for {episode_url}: {exc}")

        return None

    def bypass(self, episode_url: str) -> Optional[str]:
        """Alias for get_video_url."""
        return self.get_video_url(episode_url)

    def _extract_title(self, html_text: str) -> str:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text or "", re.IGNORECASE | re.DOTALL)
        if not m:
            return ""
        title = html.unescape(m.group(1)).strip()
        return re.sub(r"\s*[\-|]\s*ReelShort.*$", "", title, flags=re.IGNORECASE).strip()
