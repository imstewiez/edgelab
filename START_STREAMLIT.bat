@echo off
setlocal
cd /d "%~dp0"
python -m pip install -r apps\engine\requirements.txt
python -m streamlit run apps\streamlit\streamlit_app.py
pause
