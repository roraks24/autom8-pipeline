@echo off
title Daily 40-Job Auto-Submit Pipeline (20 Internshala + 20 Wellfound)
cd /d "%~dp0"
echo ================================================================
echo   Daily Job AUTO-SUBMIT Run: 20 Internshala + 20 Wellfound (Total: 40)
echo   Target: Internshala, Wellfound
echo   Candidate: Rohit Saini (+91 7877169982)
echo ================================================================
echo.
echo Starting auto-submit workflow...
python daily_workflow.py --count 20 --submit
echo.
echo Applications submitted and report dispatched to WhatsApp!
pause
