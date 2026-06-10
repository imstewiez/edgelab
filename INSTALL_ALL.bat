@echo off
setlocal
title CoreEA EdgeLab Install
cd /d "%~dp0"
echo Installing engine dependencies...
cd apps\engine
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt
cd /d "%~dp0apps\web"
echo Installing web dependencies...
npm install
echo Done.
pause
