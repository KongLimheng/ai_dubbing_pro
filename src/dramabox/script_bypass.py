"""
Bypass Strategy — Deep Script Tag Scanner
==========================================
Scans ALL <script> tags in the HTML for video URLs and auth tokens.

This is a generic fallback strategy that works even when:
  - JSON-LD block is removed or modified
  - __NEXT_DATA__ is stripped or encrypted
  - Video data is embedded in inline JavaScript

It searches for:
  - m3u8 URLs (HLS playlists)
  - mp4 URLs (direct video files)
  - CloudFront signed URLs (Expires, Signature, Key-Pair-Id)
  - CDN paths containing chapterId patterns

Priority: MEDIUM (generic fallback when structured data is unavailable)
"""

import re
import logging
from typing import Optional

try:
    from .base import (
        BaseBypass,
        BypassResult,
        decode_url,
        extract_auth,
        extract_book_path,
        extract_chapter_suffix,
    )
except ImportError:
    from base import (
        BaseBypass,
        BypassResult,
        decode_url,
        extract_auth,
        extract_book_path,
        extract_chapter_suffix,
    )

_log = logging.getLogger("dramabox.bypass")


class ScriptBypass(BaseBypass):
    """Deep scan all script tags for video URLs and auth tokens."""

    name = "Script"

    _URL_PATTERNS = [
        r'(?:https?:)?//[^\s"\'<>]+\.m3u8[^\s"\'<>]*',
        r'(?:https?:)?//[^\s"\'<>]+\.mp4[^\s"\'<>]*',
        r'(?:https?:)?//[^\s"\'<>]*(?:hwzthls|hwztvideo|thwzt)[^\s"\'<>]*\?[^\s"\'<>]*Expires=[^\s"\'<>]*',
        r'(?:https?:)?//[^\s"\'<>]*dramabox[^\s"\'<>]*\d{6,}_\d+[^\s"\'<>]*',
    ]

    def attempt(self, ep_id: str, html: str) -> Optional[BypassResult]:
        try:
            auth_params = ""
            book_path = ""
            chapter_suffix = "2"

            scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
            all_urls = []

            for script_text in scripts:
                if len(script_text) < 20:
                    continue
                for pattern in self._URL_PATTERNS:
                    matches = re.findall(pattern, script_text)
                    for raw_url in matches:
                        decoded = decode_url(raw_url)
                        decoded = re.sub(r"[;,\)\]\}]+$", "", decoded)
                        if decoded and len(decoded) > 30:
                            all_urls.append(decoded)

            if not all_urls:
                self._log_debug("No video URLs found in script tags")
                return None

            seen = set()
            unique_urls = []
            for u in all_urls:
                if u not in seen:
                    seen.add(u)
                    unique_urls.append(u)

            for url in unique_urls:
                if "15s" in url.lower():
                    continue
                if not auth_params:
                    auth_params = extract_auth(url)
                if not book_path:
                    book_path = extract_book_path(url)
                    if book_path:
                        chapter_suffix = extract_chapter_suffix(url)
                if auth_params and book_path:
                    break

            if not (auth_params and book_path):
                for url in unique_urls:
                    if not auth_params:
                        auth_params = extract_auth(url)
                    if not book_path:
                        book_path = extract_book_path(url)
                        if book_path:
                            chapter_suffix = extract_chapter_suffix(url)
                    if auth_params and book_path:
                        break

            if auth_params or book_path:
                self._log_status(
                    f"🔑 [Script] Deep scan: auth={'YES' if auth_params else 'NO'}, bookPath={'YES' if book_path else 'NO'} (from {len(unique_urls)} URLs)"
                )
                return BypassResult(
                    auth_params=auth_params,
                    book_path=book_path,
                    source=self.name,
                    chapter_suffix=chapter_suffix,
                )
        except Exception as e:
            self._log_debug(f"Error: {e}")
        return None

    def find_all_video_urls(self, html: str) -> list:
        all_urls = []
        seen = set()
        for pattern in self._URL_PATTERNS:
            for raw in re.findall(pattern, html):
                decoded = decode_url(raw)
                decoded = re.sub(r"[;,\)\]\}]+$", "", decoded)
                if decoded and (decoded not in seen) and len(decoded) > 30:
                    seen.add(decoded)
                    all_urls.append(decoded)
        return all_urls

    def find_ep_specific_url(self, html: str, ep_id: str) -> Optional[str]:
        if not ep_id:
            return None
        all_urls = self.find_all_video_urls(html)
        for url in all_urls:
            if ep_id in url and ("15s" not in url.lower()):
                return url
        return None
