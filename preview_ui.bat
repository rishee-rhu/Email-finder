@echo off
REM ====================================================================
REM  Cold Email Engine - UI PREVIEW (fake data, nothing is sent)
REM  Double-click to open the app filled with demo leads and drafts, so
REM  you can work on the look without keys or Gmail.
REM  Uses demo.db. Your real leads.db is never touched.
REM  Edit ui.py (styles) or app.py (layout), save, then click
REM  "Rerun" in the browser (or press R) to see changes.
REM ====================================================================
cd /d "%~dp0"
set CEE_DB=demo.db

python demo_data.py
if errorlevel 1 py demo_data.py

start "" "http://localhost:8502"
python -m streamlit run app.py --server.port 8502 --server.address localhost --server.runOnSave true
if errorlevel 1 py -m streamlit run app.py --server.port 8502 --server.address localhost --server.runOnSave true
pause
