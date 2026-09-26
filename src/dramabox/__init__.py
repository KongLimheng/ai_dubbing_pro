# -*- coding: utf-8 -*-
"""
DramaBox package initialization.
Exports DramaBoxBypassManager, DramaboxDownloader, and DramaBoxTool.
"""

from .base import BypassResult, decode_url, extract_chapter_suffix
from .api_bypass import ApiBypass
from .jsonld_bypass import JsonLdBypass
from .mp4_bypass import Mp4Bypass
from .nextdata_bypass import NextDataBypass
from .script_bypass import ScriptBypass
from .cache_bypass import CacheBypass
from .probe_bypass import ProbeBypass
from .dramabox import DramaBoxBypassManager
from .downloader import DramaboxDownloader

try:
    from .gui_downloader import DramaBoxTool
except ImportError:
    DramaBoxTool = None

__all__ = [
    'BypassResult',
    'decode_url',
    'extract_chapter_suffix',
    'ApiBypass',
    'JsonLdBypass',
    'Mp4Bypass',
    'NextDataBypass',
    'ScriptBypass',
    'CacheBypass',
    'ProbeBypass',
    'DramaBoxBypassManager',
    'DramaboxDownloader',
    'DramaBoxTool',
]
