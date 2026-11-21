@echo off
title Internshala 1-Time Session Login
cd /d "%~dp0"
echo ========================================================
echo   Internshala 1-Time Browser Login Helper
echo ========================================================
echo.
echo Launching browser window...
echo.
python open_browser_for_login.py
echo.
echo Session saved! You can close this window now.
pause
