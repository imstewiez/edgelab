@echo off
REM Portfolio Live Trading v2 — UNIFIED MULTI-ALPHA SYSTEM
REM Strategies: MultiTF + StatArb + SessionMomentum + GapFade
REM Assets: 11 MultiTF + 3 pairs + 4 session + 5 gap-fade symbols
set PYTHONPATH=%~dp0src
python -m multitf_platform.cli.main portfolio-live-v2 %*
