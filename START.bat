@echo off
echo.
echo  ============================================
echo   LitLens — Streamlit App
echo  ============================================
echo.

cd /d "%~dp0"

echo  Installing dependencies...
pip install -r requirements.txt --quiet

echo.
echo  Starting LitLens at http://localhost:8501
echo  (The app will open automatically in your browser)
echo.
echo  Press Ctrl+C to stop.
echo.

streamlit run app.py
pause
