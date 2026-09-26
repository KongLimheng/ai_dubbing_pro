"""Bypass Strategy — JSON-LD (application/ld+json).

Extracts auth_params and book_path from the JSON-LD VideoObject
schema embedded in the episode page.
"""

import json
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


class JsonLdBypass(BaseBypass):
    """Extract auth + bookPath from JSON-LD contentUrl."""
    name = 'JSON-LD'

    def attempt(self, ep_id, html) -> Optional[BypassResult]:
        try:
            ld_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not ld_match:
                self._log_debug("No JSON-LD block found")
                return None
            schema = json.loads(ld_match.group(1))
        except json.JSONDecodeError as e:
            self._log_debug(f"JSON parse error: {e}")
            return None
        except Exception as e:
            self._log_debug(f"Unexpected error: {e}")
            return None

        content_url = decode_url(schema.get('contentUrl', ''))
        if not content_url:
            self._log_debug("contentUrl is empty")
            return None

        auth_params = extract_auth(content_url)
        book_path = extract_book_path(content_url)
        chapter_suffix = extract_chapter_suffix(content_url) if book_path else '2'

        if auth_params and book_path:
            self._log_status("🔑 [JSON-LD] Auth + bookPath extracted successfully")
            return BypassResult(
                video_url='',
                auth_params=auth_params,
                book_path=book_path,
                source=self.name,
                chapter_suffix=chapter_suffix,
            )
        if auth_params or book_path:
            self._log_debug(f"Partial: auth={'YES' if auth_params else 'NO'}, bookPath={'YES' if book_path else 'NO'}")
            return BypassResult(
                video_url='',
                auth_params=auth_params,
                book_path=book_path,
                source=self.name,
                chapter_suffix=chapter_suffix,
            )
        return None

    def detect_locked(self, html):
        """Check if this episode is locked (15-second preview)."""
        try:
            ld_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not ld_match:
                return False
            schema = json.loads(ld_match.group(1))
            duration = schema.get('duration', '')
            content_url = schema.get('contentUrl', '')
            if duration and duration.upper() == 'PT15S':
                return True
            if content_url and '15s' in content_url.lower():
                return True
        except Exception:
            pass
        return False

    def get_free_url(self, html, ep_id):
        """Return free video URL if this is not a 15-second preview."""
        try:
            ld_match = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not ld_match:
                return None
            schema = json.loads(ld_match.group(1))
            content_url = schema.get('contentUrl', '')
            duration = schema.get('duration', '')

            is_preview = False
            if duration and duration.upper() == 'PT15S':
                is_preview = True
            if content_url and '15s' in content_url.lower():
                is_preview = True

            if is_preview:
                return None

            if content_url and ('.m3u8' in content_url or '.mp4' in content_url):
                return decode_url(content_url)
        except Exception:
            pass
        return None
