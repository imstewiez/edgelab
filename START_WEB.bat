@echo off
title CoreEA EdgeLab Web
cd apps\web
if not exist node_modules (
  npm install
)
npm run dev
pause
