@echo off
title Wellfound 1-Time Session Login
cd /d "%~dp0"
echo ========================================================
echo   Wellfound 1-Time Browser Login Helper
echo ========================================================
echo.
echo Launching browser window...
echo Please sign into your Wellfound account in the opened window.
echo Once logged in, your session is saved automatically!
echo.
python apply_bot.py --login-wellfound
echo.
echo Session saved! You can close this window now.
pause
