@echo off
title Wellfound Auto-Submit Pipeline v2.0
cd /d "%~dp0"
echo ================================================================
echo   Wellfound Target Roles AUTO-SUBMIT Run (Pipeline v2.0)
echo   Candidate: Rohit Saini (+91 7877169982)
echo ================================================================
echo.
echo Starting auto-submit workflow for Wellfound...
python daily_workflow.py --platform wellfound --count 20 --submit
echo.
echo Applications submitted and report dispatched to WhatsApp!
pause
