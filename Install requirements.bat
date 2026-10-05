@echo off
rem Run this once (or after moving to a new PC) to install everything the app needs.
cd /d "%~dp0"
python -m pip install -r requirements.txt
echo.
echo Done. Now double-click "Start Data Scalper.bat".
pause
