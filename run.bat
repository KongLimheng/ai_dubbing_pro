@echo off
setlocal enabledelayedexpansion

title AI Dubber Ultimate v1.2.9
cd /d "%~dp0"

echo ==================================================
echo       AI Dubber Ultimate v1.2.9 Portable         
echo ==================================================

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"

:: Check if uv is available
where uv >nul 2>nul
if %errorlevel% equ 0 (
    echo [*] Launching via uv (Python 3.11)...
    uv run --python 3.11 --with-requirements requirements.txt python src\main.py %*
    goto :eof
)

:: Check for existing virtual environment
if not exist ".venv" (
    echo [*] Setting up Python 3.11 virtual environment...
    where py >nul 2>nul
    if !errorlevel! equ 0 (
        py -3.11 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if not exist ".venv" (
        echo [!] Failed to create virtual environment. Please install Python 3.11.
        pause
        exit /b 1
    )
    echo [*] Installing dependencies from requirements.txt...
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

python src\main.py %*
if %errorlevel% neq 0 (
    pause
)
