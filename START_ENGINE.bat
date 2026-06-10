@echo off
setlocal
title CoreEA EdgeLab Engine
cd /d "%~dp0apps\engine"
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8765 --reload
pause
