@echo off
REM Ajio Size Monitor — single check
REM Schedule this with Windows Task Scheduler to run every 15 minutes

cd /d "%~dp0"
python monitor.py --once >> monitor.log 2>&1
