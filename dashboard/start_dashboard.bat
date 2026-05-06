@echo off
echo ==========================================
echo MultiTF Trading Dashboard
echo ==========================================
cd /d "%~dp0"

REM Start Flask server in a new window so it persists
echo Starting server in new window...
start "MultiTF Dashboard Server" cmd /k "python app.py"

echo Waiting for server to start...
timeout /t 3 /nobreak >nul

echo Opening browser...
start http://localhost:5000

echo.
echo Dashboard is running at http://localhost:5000
echo Close the server window to stop.
echo.
pause
