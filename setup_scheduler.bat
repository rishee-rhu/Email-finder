@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Sets up a Windows Task Scheduler job to run cold emails daily at 9:00 AM.
REM  Run this ONCE as Administrator (right-click → Run as administrator).
REM ─────────────────────────────────────────────────────────────────────────────

SET TASK_NAME=ColdEmailEngine
SET SCRIPT_DIR=%~dp0
SET PYTHON=python

REM Remove existing task if any
schtasks /delete /tn "%TASK_NAME%" /f 2>nul

REM Create new daily task at 9:00 AM
schtasks /create ^
  /tn "%TASK_NAME%" ^
  /tr "\"%PYTHON%\" \"%SCRIPT_DIR%run_daily.py\"" ^
  /sc daily ^
  /st 09:00 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

echo.
echo ✅  Task "%TASK_NAME%" scheduled — runs daily at 09:00 AM.
echo     Logs saved to: %SCRIPT_DIR%daily_log.txt
echo.
echo To change the time: open Task Scheduler → Task Scheduler Library → ColdEmailEngine
echo To run immediately: schtasks /run /tn "%TASK_NAME%"
echo To remove:          schtasks /delete /tn "%TASK_NAME%" /f
echo.
pause
