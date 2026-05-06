@echo off
REM Portfolio Live Trading v3 -- FINAL UNIFIED SYSTEM (Edges Only)
REM Strategies: StatArb + SessionMomentum + GapFade
REM MultiTF momentum: DISABLED
set PYTHONPATH=%~dp0src
python -m multitf_platform.cli.main portfolio-live-v3 %*
