@echo off
rem Double-click to start Data Scalper. It opens in your browser at http://localhost:8501
cd /d "%~dp0"
echo Starting Data Scalper... (close this window to stop the app)
python -m streamlit run app.py
pause
