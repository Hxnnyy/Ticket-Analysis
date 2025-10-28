@echo off
setlocal
cd /d "%~dp0"

echo Starting Streamlit dashboard...
python -m streamlit run "dashboard.py"

endlocal
