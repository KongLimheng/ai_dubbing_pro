"""Bypass Strategy — Cache (reuse auth from previous episodes).

When earlier episodes have been successfully bypassed, their auth_params
and book_path are cached. This strategy reuses that cached data for
subsequent episodes in the same drama.
"""

from typing import Optional

from .base import BaseBypass, BypassResult


class CacheBypass(BaseBypass):
    name = 'Cache'

    def __init__(self, status_callback=None):
        super().__init__(status_callback)
        self._cached_auth = ''
        self._cached_book_path = ''

    def attempt(self) -> Optional[BypassResult]:
        if self._cached_auth and self._cached_book_path:
            self._log_status("🔄 [Cache] Using cached auth/bookPath from previous episode")
            return BypassResult(
                video_url='',
                auth_params=self._cached_auth,
                book_path=self._cached_book_path,
                source=self.name,
            )
        if self._cached_auth or self._cached_book_path:
            self._log_debug(
                f"Partial cache: auth={'YES' if self._cached_auth else 'NO'}, "
                f"bookPath={'YES' if self._cached_book_path else 'NO'}"
            )
            return BypassResult(
                video_url='',
                auth_params=self._cached_auth,
                book_path=self._cached_book_path,
                source=self.name,
            )
        self._log_debug("No cached data available")
        return None

    def update(self, auth_params: str = '', book_path: str = ''):
        if auth_params:
            self._cached_auth = auth_params
        if book_path:
            self._cached_book_path = book_path

    def clear(self):
        self._cached_auth = ''
        self._cached_book_path = ''

    def has_auth(self) -> bool:
        return bool(self._cached_auth)

    def has_book_path(self) -> bool:
        return bool(self._cached_book_path)
