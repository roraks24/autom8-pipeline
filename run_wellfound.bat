@echo off
title Wellfound Application Pipeline v2.0
cd /d "%~dp0"
echo ================================================================
echo   Wellfound Target Roles Application Run (Pipeline v2.0)
echo   Candidate: Rohit Saini (+91 7877169982)
echo ================================================================
echo.
echo Starting automated workflow for Wellfound...
python daily_workflow.py --platform wellfound --count 20
echo.
echo Workflow completed. Report dispatched to WhatsApp!
pause
