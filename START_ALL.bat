@echo off
setlocal
title CoreEA EdgeLab Launcher
cd /d "%~dp0"
start "CoreEA EdgeLab Engine" cmd /k "START_ENGINE.bat"
timeout /t 3 /nobreak >nul
start "CoreEA EdgeLab Web" cmd /k "START_WEB.bat"
echo Engine: http://127.0.0.1:8765/health
echo Web:    http://localhost:5173
pause
