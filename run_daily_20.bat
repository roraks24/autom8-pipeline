@echo off
title Daily 40-Job Application Pipeline (20 Internshala + 20 Wellfound)
cd /d "%~dp0"
echo ================================================================
echo   Daily Job Application Run: 20 Internshala + 20 Wellfound (Total: 40)
echo   Target: Internshala, Wellfound
echo   Candidate: Rohit Saini (+91 7877169982)
echo ================================================================
echo.
echo Starting automated workflow...
python daily_workflow.py --count 20
echo.
echo Workflow completed. Report dispatched to WhatsApp!
pause
