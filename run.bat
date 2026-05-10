@echo off
echo Starting Portfolio Dashboard...
cd /d "%~dp0"
streamlit run main.py --server.port 8501 --server.headless false
pause
