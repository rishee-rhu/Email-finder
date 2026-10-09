@echo off
REM ====================================================================
REM  Cold Email Engine - one-click launcher
REM  Double-click this file. It opens the app in your browser at
REM     http://localhost:8501
REM  Keep this black window open while you use the app. Close it to stop.
REM ====================================================================
cd /d "%~dp0"

echo.
echo   Starting Cold Email Engine...
echo   Opening your browser at  http://localhost:8501
echo   (If the page says "can't connect", wait 5 seconds and refresh.)
echo.

REM open the browser (the server takes a few seconds to come up)
start "" "http://localhost:8501"

REM try 'python' first; if it's not on PATH, fall back to the 'py' launcher
python -m streamlit run app.py --server.port 8501
if errorlevel 1 py -m streamlit run app.py --server.port 8501

echo.
echo   The app has stopped. You can close this window.
pause
