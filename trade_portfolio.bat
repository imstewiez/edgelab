@echo off
REM Portfolio Live Trading: XAUUSD + EURUSD + NAS100
set PYTHONPATH=%~dp0src
python -m multitf_platform.cli.main portfolio-live %*
