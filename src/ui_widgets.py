# -*- coding: utf-8 -*-
"""
ui_widgets module wrapper.
Loads native compiled bytecode from ui_widgets.pyc with cross-platform runtime support.
"""

import os
import sys
from importlib.machinery import SourcelessFileLoader

try:
    from utils import apply_khmer_font_patch
    apply_khmer_font_patch()
except Exception:
    pass

_pyc_path = os.path.join(os.path.dirname(__file__), 'ui_widgets.pyc')
if not os.path.exists(_pyc_path):
    raise FileNotFoundError(f"Missing compiled bytecode module: {_pyc_path}")

_mod = SourcelessFileLoader(__name__, _pyc_path).load_module()
globals().update(_mod.__dict__)
sys.modules[__name__] = _mod
