"""Bypass Strategy — Direct MP4 URL extraction.

Extracts direct .mp4 download URLs from the __NEXT_DATA__ chapterList.
DramaBox's chapterList includes an 'mp4' field for each episode that
contains a signed CloudFront URL to the full episode video file.
"""

import json
import logging
import re
from typing import Optional

from .base import (
    BaseBypass,
    BypassResult,
    decode_url,
    extract_auth,
    extract_book_path,
    extract_chapter_suffix,
)

_log = logging.getLogger('dramabox.bypass')


class Mp4Bypass(BaseBypass):
    """Extract auth + bookPath from mp4 URLs in chapterList."""
    name = 'MP4'

    def attempt(self, ep_id, html) -> Optional[BypassResult]:
        """Try to extract bypass info from mp4 URLs in __NEXT_DATA__."""
        try:
            nd_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not nd_match:
                self._log_debug("No __NEXT_DATA__ block found")
                return None

            nd_text = nd_match.group(1)
            all_mp4 = re.findall(r'"mp4"\s*:\s*"([^"]+)"', nd_text)
            if not all_mp4:
                self._log_debug("No mp4 entries found in chapterList")
                return None

            auth_params = ''
            book_path = ''
            chapter_suffix = '2'

            for raw in all_mp4:
                decoded = decode_url(raw)
                if '15s' in decoded.lower():
                    continue
                if 'nav' in decoded.lower() and '15s' in decoded.lower():
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
                    f"🔑 [MP4] auth={'YES' if auth_params else 'NO'}, "
                    f"bookPath={'YES' if book_path else 'NO'}"
                )
                return BypassResult(
                    video_url='',
                    auth_params=auth_params,
                    book_path=book_path,
                    source=self.name,
                    chapter_suffix=chapter_suffix,
                )
        except Exception as e:
            self._log_debug(f"Error: {e}")
        return None

    def get_direct_mp4(self, ep_id, html) -> Optional[str]:
        """Return direct mp4 URL if the episode is unlocked and full video is available."""
        try:
            nd_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not nd_match:
                return None
            data = json.loads(nd_match.group(1))
            chapter_list = data.get('props', {}).get('pageProps', {}).get('chapterList', [])
            for ch in chapter_list:
                cid = str(ch.get('chapterId', ''))
                if cid == str(ep_id):
                    mp4_url = ch.get('mp4', '')
                    if mp4_url and '15s' not in mp4_url.lower() and ch.get('unlock', False):
                        return decode_url(mp4_url)
                    break
        except Exception as e:
            self._log_debug(f"get_direct_mp4 error: {e}")
        return None

    def get_free_mp4_auth(self, html):
        """Extract auth and book_path from any unlocked episode in chapterList."""
        try:
            nd_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not nd_match:
                return ('', '')
            data = json.loads(nd_match.group(1))
            chapter_list = data.get('props', {}).get('pageProps', {}).get('chapterList', [])
            for ch in chapter_list:
                if ch.get('unlock', False):
                    mp4_url = ch.get('mp4', '')
                    if mp4_url and '15s' not in mp4_url.lower():
                        decoded = decode_url(mp4_url)
                        auth = extract_auth(decoded)
                        bp = extract_book_path(decoded)
                        if auth and bp:
                            return (auth, bp)
        except Exception:
            pass
        return ('', '')
