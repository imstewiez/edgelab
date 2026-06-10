@echo off
title CoreEA EdgeLab Install
echo Installing engine dependencies...
cd apps\engine
if not exist .venv (
  py -m venv .venv
)
call .venv\Scripts\activate
pip install -r requirements.txt
cd ..\..\apps\web
echo Installing web dependencies...
npm install
echo Done.
pause
