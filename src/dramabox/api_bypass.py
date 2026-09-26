"""
Bypass Strategy — Next.js Data API
====================================
Fetches episode data via the Next.js data API route:
    /_next/data/{buildId}/video/{bookId}_{slug}/{chapterId}_Episode-{num}.json

This returns the same data as __NEXT_DATA__ but via a direct JSON API call.
It's useful when:
  - The HTML page has been modified/obfuscated
  - __NEXT_DATA__ is stripped from the HTML
  - We need fresh auth tokens (each request gets new signed URLs)

Priority: HIGH (most reliable — direct API with fresh tokens)
"""

import re
import json
import logging
import requests
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


class ApiBypass(BaseBypass):
    """Fetch auth + bookPath via Next.js data API route."""

    name = "API"

    def __init__(self, status_callback=None):
        super().__init__(status_callback)
        self._build_id = ""
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.dramabox.com/",
        })

    def attempt(self, ep_id: str, html: str) -> Optional[BypassResult]:
        try:
            build_id = self._extract_build_id(html)
            if not build_id:
                self._log_debug("No buildId found in HTML")
                return None

            page_path = self._extract_page_path(html, ep_id)
            if not page_path:
                self._log_debug("Could not determine page path for API call")
                return None

            api_url = f"https://www.dramabox.com/_next/data/{build_id}/{page_path}.json"
            self._log_debug(f"Calling API: {api_url[:120]}")

            resp = self._session.get(api_url, timeout=15)
            if resp.status_code != 200:
                self._log_debug(f"API returned {resp.status_code}")
                return None

            data = resp.json()
            page_props = data.get("pageProps", {})

            auth_params = ""
            book_path = ""
            chapter_suffix = "2"

            raw_json = json.dumps(data)
            all_m3u8 = re.findall(r'"m3u8Url"\s*:\s*"([^"]+)"', raw_json)

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
                for raw in re.findall(r'"contentUrl"\s*:\s*"([^"]+)"', raw_json):
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
                for raw in re.findall(r'"mp4"\s*:\s*"([^"]+)"', raw_json):
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

            if auth_params or book_path:
                self._log_status(
                    f"🔑 [API] Fresh tokens: auth={'YES' if auth_params else 'NO'}, bookPath={'YES' if book_path else 'NO'}"
                )
                return BypassResult(
                    auth_params=auth_params,
                    book_path=book_path,
                    source=self.name,
                    chapter_suffix=chapter_suffix,
                )
        except requests.RequestException as e:
            self._log_debug(f"Request error: {e}")
        except json.JSONDecodeError as e:
            self._log_debug(f"JSON parse error: {e}")
        except Exception as e:
            self._log_debug(f"Unexpected error: {e}")
        return None

    def get_fresh_video_url(self, ep_id: str, html: str) -> Optional[str]:
        try:
            build_id = self._extract_build_id(html)
            if not build_id:
                return None
            page_path = self._extract_page_path(html, ep_id)
            if not page_path:
                return None

            api_url = f"https://www.dramabox.com/_next/data/{build_id}/{page_path}.json"
            resp = self._session.get(api_url, timeout=15)
            if resp.status_code != 200:
                return None

            data = resp.json()
            raw_json = json.dumps(data)
            for raw in re.findall(r'"m3u8Url"\s*:\s*"([^"]+)"', raw_json):
                decoded = decode_url(raw)
                if ep_id in decoded and ("15s" not in decoded.lower()):
                    return decoded

            page_props = data.get("pageProps", {})
            chapter_list = page_props.get("chapterList", [])
            for ch in chapter_list:
                if str(ch.get("id", "")) == ep_id:
                    mp4 = ch.get("mp4", "")
                    if mp4 and ("15s" not in mp4.lower()):
                        return decode_url(mp4)
        except Exception as e:
            self._log_debug(f"get_fresh_video_url error: {e}")
        return None

    def get_chapter_list(self, html: str) -> list:
        try:
            build_id = self._extract_build_id(html)
            if not build_id:
                return []
            page_path = self._extract_page_path(html, "")
            if not page_path:
                return []

            api_url = f"https://www.dramabox.com/_next/data/{build_id}/{page_path}.json"
            resp = self._session.get(api_url, timeout=15)
            if resp.status_code != 200:
                return []

            data = resp.json()
            return data.get("pageProps", {}).get("chapterList", [])
        except Exception:
            return []

    def _extract_build_id(self, html: str) -> str:
        if self._build_id:
            return self._build_id
        m = re.search(r'"buildId"\s*:\s*"([^"]+)"', html)
        if m:
            self._build_id = m.group(1)
            return self._build_id
        m2 = re.search(r"/_next/static/([^/]+)/_", html)
        if m2:
            self._build_id = m2.group(1)
            return self._build_id
        return ""

    def _extract_page_path(self, html: str, ep_id: str) -> str:
        for pattern in [
            r'<link[^>]+rel="canonical"[^>]+href="[^"]*?/([^"]*?)"',
            r'<meta[^>]+property="og:url"[^>]+content="[^"]*?/([^"]*?)"',
        ]:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                path = m.group(1)
                if "video/" in path or "ep/" in path:
                    if path.startswith("video/") or path.startswith("ep/"):
                        return path
                    vm = re.search(r"((?:video|ep)/[^?#]+)", path)
                    if vm:
                        return vm.group(1)

        try:
            nd = re.search(r"__NEXT_DATA__[^>]*>(.*?)</script>", html, re.DOTALL)
            if nd:
                nd_data = json.loads(nd.group(1))
                page = nd_data.get("page", "")
                query = nd_data.get("query", {})
                props = nd_data.get("props", {}).get("pageProps", {})
                book_info = props.get("bookInfo", {})
                chapter_id = props.get("chapterId", "") or ep_id

                if book_info:
                    book_id = book_info.get("bookId", "")
                    slug = book_info.get("bookNameLower", "")
                    if book_id and slug and chapter_id:
                        chapter_list = props.get("chapterList", [])
                        ep_num = 1
                        for ch in chapter_list:
                            if str(ch.get("id", "")) == str(chapter_id):
                                ep_num = ch.get("index", 0) + 1
                                break
                        slug_cap = slug[0].upper() + slug[1:] if slug else slug
                        return f"video/{book_id}_{slug_cap}/{chapter_id}_Episode-{ep_num}"
        except Exception:
            pass

        m = re.search(r'href="[^"]*/((?:video|ep)/[^"]+_Episode-\d+)', html, re.IGNORECASE)
        if m:
            return m.group(1)

        return ""
