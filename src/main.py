# -*- coding: utf-8 -*-
"""
AI Dubber Ultimate entry point.
"""

from app_launcher import launch_app
import os
import sys
from runtime_paths import get_app_dir

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, 'reconfigure'):
        stream.reconfigure(errors='replace')

app_dir = get_app_dir()
try:
    if os.path.normcase(os.path.abspath(os.getcwd())) != os.path.normcase(os.path.abspath(app_dir)):
        os.chdir(app_dir)
except Exception:
    app_dir = os.getcwd()

try:
    from debug_log import setup_vscode_debug_log
    setup_vscode_debug_log(os.path.join(app_dir, 'app_debug.log'))
except Exception:
    pass


if __name__ == '__main__':
    try:
        launch_app()
    except KeyboardInterrupt:
        print('Startup cancelled.')
