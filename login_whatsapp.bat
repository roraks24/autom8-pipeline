@echo off
title WhatsApp Web 1-Time Session Login
cd /d "%~dp0"
echo ========================================================
echo   WhatsApp Web 1-Time Session Login Helper
echo ========================================================
echo.
echo Launching browser window...
echo 1. Open WhatsApp on your phone (+91 7877169982).
echo 2. Go to Settings (or 3 dots) -^> Linked Devices -^> Link a Device.
echo 3. Scan the QR code shown in the Chrome window.
echo.
echo Once scanned, the session is saved permanently to ~/.whatsapp_web_profile.
echo Daily job application reports will then send automatically!
echo.
python whatsapp_sender.py --login
echo.
pause
