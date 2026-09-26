"""Base abstractions for DramaBox bypass extractors."""

from dataclasses import dataclass
import html
import logging
import re
from urllib.parse import urlparse

_log = logging.getLogger('dramabox.bypass')


@dataclass
class BypassResult:
    video_url: str
    auth_params: str = ''
    book_path: str = ''
    source: str = ''
    chapter_suffix: str = '2'


class BaseBypass:
    name = 'Base'

    def __init__(self, status_callback=None):
        self._report = status_callback if status_callback else (lambda *args, **kwargs: None)

    def _log_status(self, message):
        self._report(message)

    def _log_debug(self, message):
        _log.debug('[%s] %s', self.name, message)


def decode_url(value):
    if not value:
        return ''
    decoded = html.unescape(str(value).strip()).strip('"\'')
    replacements = (
        (r'\\u0026', '&'),
        (r'\u0026', '&'),
        (r'\\u003d', '='),
        (r'\u003d', '='),
        (r'\\u002f', '/'),
        (r'\u002f', '/'),
        (r'\\u002F', '/'),
        (r'\u002F', '/'),
        (r'\\/', '/'),
        (r'\/', '/'),
    )
    for old, new in replacements:
        decoded = decoded.replace(old, new)
    if decoded.startswith('//'):
        decoded = 'https:' + decoded
    return decoded


def extract_auth(url):
    if not url:
        return ''
    parsed = urlparse(url)
    return parsed.query or ''


def extract_book_path(url):
    if not url:
        return ''
    path_parts = [part for part in urlparse(url).path.split('/') if part]
    if len(path_parts) < 3:
        return ''
    episode_index = -1
    for index, part in enumerate(path_parts):
        if re.search(r'\d{6,}_\d+(?:\.[^/?#]+)?$', part):
            episode_index = index
            break
    if episode_index <= 0:
        return ''
    start_index = 1 if re.fullmatch(r'[A-Za-z0-9]{2}', path_parts[0]) else 0
    book_parts = path_parts[start_index:episode_index]
    return '/'.join(book_parts)


def extract_chapter_suffix(url):
    if not url:
        return '2'
    for part in urlparse(url).path.split('/'):
        match = re.search(r'\d{6,}_(\d+)(?:\.[^/?#]+)?$', part)
        if match:
            return match.group(1)
    return '2'
