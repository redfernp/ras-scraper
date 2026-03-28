@echo off
title RAS Scraper - One-Time Setup
color 0A

echo.
echo  =============================================
echo   RAS Tips Generator - One-Time Setup
echo  =============================================
echo.
echo  This will download and set up the app.
echo  It only needs to be run once.
echo.
pause

:: ── Step 1: Check Python ──────────────────────────────────────────────────
echo.
echo  [1/4] Checking Python is installed...
py --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  !! ERROR: Python is not installed.
    echo.
    echo  Please install Python from:
    echo  https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: During installation, tick the checkbox
    echo  that says "Add Python to PATH" before clicking Install.
    echo.
    echo  Then run this file again.
    echo.
    pause
    exit /b 1
)
echo       OK

:: ── Step 2: Check Git ─────────────────────────────────────────────────────
echo.
echo  [2/4] Checking Git is installed...
git --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  !! ERROR: Git is not installed.
    echo.
    echo  Please install Git from:
    echo  https://git-scm.com/download/win
    echo.
    echo  Use all the default options during installation.
    echo  Then run this file again.
    echo.
    pause
    exit /b 1
)
echo       OK

:: ── Step 3: Clone the repository ─────────────────────────────────────────
echo.
echo  [3/4] Downloading the RAS Scraper app...
cd /d "%~dp0"
git clone https://github.com/redfernp/ras-scraper.git
if errorlevel 1 (
    echo.
    echo  !! ERROR: Could not download the app.
    echo.
    echo  Check your internet connection and try again.
    echo.
    pause
    exit /b 1
)
echo       OK

:: ── Step 4: Install dependencies ─────────────────────────────────────────
echo.
echo  [4/4] Installing required components (this may take a minute)...
cd ras-scraper
py -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo  !! ERROR: Could not install components.
    echo  Please contact your administrator.
    echo.
    pause
    exit /b 1
)
py -m playwright install chromium
if errorlevel 1 (
    echo.
    echo  !! WARNING: Browser component install had an issue.
    echo  The app may still work. Try running it and see.
    echo.
)
echo       OK

:: ── Done ──────────────────────────────────────────────────────────────────
echo.
echo  =============================================
echo   Setup complete!
echo.
echo   To use the app:
echo   1. Open the "ras-scraper" folder
echo   2. Double-click "run.bat"
echo  =============================================
echo.
pause
