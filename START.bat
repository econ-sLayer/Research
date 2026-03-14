@echo off
echo === PaperCluster ===
echo Installing dependencies...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo ERROR: pip install failed. Make sure Python is installed.
    pause
    exit /b 1
)
echo.
echo Starting PaperCluster at http://localhost:8503
echo Press Ctrl+C to stop.
echo.
python -m streamlit run app.py --server.port 8503
pause
