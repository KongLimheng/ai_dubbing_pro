"""
Bypass Strategy — __NEXT_DATA__ (Next.js SSR data)
====================================================
Extracts auth_params and book_path from the __NEXT_DATA__ JSON
embedded by Next.js server-side rendering.

The __NEXT_DATA__ block contains `m3u8Url` entries for ALL episodes
visible on the page. We scan these URLs to extract:
  - Auth query parameters (CDN signing tokens)
  - BookPath (CDN directory structure)

For locked episodes, the m3u8Url of FREE episodes on the same page
still carries valid auth tokens that work for the locked episode's
individual TS segments.

Priority: MEDIUM (good fallback when JSON-LD has no bookPath)
"""

import re
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


class NextDataBypass(BaseBypass):
    """Extract auth + bookPath from __NEXT_DATA__ m3u8Url entries."""

    name = "__NEXT_DATA__"

    def attempt(self, ep_id: str, html: str) -> Optional[BypassResult]:
        try:
            nd_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not nd_match:
                self._log_debug("No __NEXT_DATA__ block found")
                return None
            nd_text = nd_match.group(1)
            all_m3u8 = re.findall(r'"m3u8Url"\s*:\s*"([^"]+)"', nd_text)
            if not all_m3u8:
                self._log_debug("No m3u8Url entries found")
                return None

            auth_params = ""
            book_path = ""
            chapter_suffix = "2"

            for raw in all_m3u8:
                decoded = decode_url(raw)
                if "15s" in decoded.lower():
                    continue
                if not auth_params:
                    auth_params = extract_auth(decoded)
                if not book_path:
                    book_path = extract_book_path(decoded)
                    if book_path:
                        chapter_suffix = extract_chapter_suffix(decoded)
                if auth_params and book_path:
                    break

            if not (auth_params and book_path):
                for raw in all_m3u8:
                    decoded = decode_url(raw)
                    if not auth_params:
                        auth_params = extract_auth(decoded)
                    if not book_path:
                        book_path = extract_book_path(decoded)
                        if book_path:
                            chapter_suffix = extract_chapter_suffix(decoded)
                    if auth_params and book_path:
                        break

            if auth_params or book_path:
                self._log_status(
                    f"🔑 [NEXT_DATA] auth={'YES' if auth_params else 'NO'}, bookPath={'YES' if book_path else 'NO'}"
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

    def harvest_m3u8_cache(self, html: str) -> dict:
        cache = {}
        try:
            nd_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if nd_match:
                nd_text = nd_match.group(1)
                all_m3u8 = re.findall(r'"m3u8Url"\s*:\s*"([^"]+)"', nd_text)
                for raw in all_m3u8:
                    decoded = decode_url(raw)
                    cid_m = re.search(r"/(\d{6,})_2/", decoded)
                    if cid_m and decoded and ("15s" not in decoded.lower()):
                        cache[cid_m.group(1)] = decoded
        except Exception:
            pass
        return cache

    def find_matching_url(self, html: str, ep_id: str) -> Optional[str]:
        try:
            nd_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not nd_match or not ep_id:
                return None
            nd_text = nd_match.group(1)
            for raw in re.findall(r'"m3u8Url"\s*:\s*"([^"]+)"', nd_text):
                decoded = decode_url(raw)
                if ep_id in decoded:
                    return decoded
            for raw in re.findall(r'"contentUrl"\s*:\s*"([^"]+)"', nd_text):
                decoded = decode_url(raw)
                if ep_id in decoded and ("15s" not in decoded.lower()):
                    return decoded
        except Exception:
            pass
        return None
