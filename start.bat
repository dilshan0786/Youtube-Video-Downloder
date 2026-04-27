@echo off
title YouTube Video Downloader - Server
color 0A

echo ============================================================
echo    YouTube Video Downloader - Starting Server...
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python from https://python.org/downloads
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo [1/3] Installing required packages...
python -m pip install -r requirements.txt -q --upgrade

if errorlevel 1 (
    echo [ERROR] Failed to install packages. Check your internet connection.
    pause
    exit /b 1
)

echo [2/3] Packages installed successfully!
echo.
:: Start the Flask server in a new window so this one stays for logs
echo [3/3] Starting YouTube Downloader Server...
echo.
echo ============================================================
echo   Server running at: http://localhost:5000
echo   Opening browser...
echo   Press Ctrl+C to stop the server.
echo ============================================================
echo.

:: Open the browser
timeout /t 3 /nobreak >nul
start "" "http://localhost:5000"

:: Run the server
python app.py

pause
