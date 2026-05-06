@echo off
REM Manually trigger one live paper trade iteration
set PYTHONPATH=%~dp0src
python -m multitf_platform.cli.main live %*
