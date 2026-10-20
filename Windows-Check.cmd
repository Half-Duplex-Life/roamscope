@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python windows_check.py
) else (
  py -3 windows_check.py
)
echo.
pause
