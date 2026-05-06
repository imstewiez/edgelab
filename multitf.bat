@echo off
REM MultiTF Platform CLI launcher for Windows
REM Usage: multitf.bat <command> [options]

set PYTHONPATH=%~dp0src
python -m multitf_platform.cli.main %*
