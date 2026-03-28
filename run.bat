@echo off
title RAS Tips Generator
color 0A

:: Change to the folder containing this bat file (repo root)
cd /d "%~dp0"

echo.
echo  =============================================
echo   RAS Tips Generator
echo  =============================================
echo.

:: ── Pull latest updates ───────────────────────────────────────────────────
echo  Checking for updates...
git pull --quiet
echo  App is up to date.
echo.

:: ── Check if Chrome is already running on port 9222 ──────────────────────
echo  Checking Chrome...
powershell -command "try { (Invoke-WebRequest -Uri 'http://localhost:9222/json' -TimeoutSec 2 -UseBasicParsing).StatusCode | Out-Null; exit 0 } catch { exit 1 }" 2>nul
if %errorlevel% == 0 (
    echo  Chrome is ready.
    goto :launch_app
)

:: ── Find and launch Chrome ────────────────────────────────────────────────
echo  Launching Chrome...
set "CHROME_PATH="
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)

if "%CHROME_PATH%"=="" (
    echo.
    echo  !! ERROR: Google Chrome not found.
    echo  Please install Chrome and try again.
    echo.
    pause
    exit /b 1
)

start "" "%CHROME_PATH%" --remote-debugging-port=9222 --user-data-dir="C:\ChromeDebug"
echo  Chrome launched.
echo.
echo  --------------------------------------------------
echo  If racingandsports.com.au shows a security check,
echo  complete it in Chrome before clicking Generate Tips.
echo  --------------------------------------------------
echo.
timeout /t 4 /nobreak >nul

:launch_app
:: ── Launch the Streamlit app ──────────────────────────────────────────────
echo  Opening the RAS Tips app in your browser...
echo.
echo  Keep this window open while using the app.
echo  Close it when you are done.
echo.
py -3.11 -m streamlit run app.py
pause
