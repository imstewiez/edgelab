@echo off
setlocal
title CoreEA EdgeLab Web
cd /d "%~dp0apps\web"
if not exist node_modules (
  npm install
)
npm run dev
pause
