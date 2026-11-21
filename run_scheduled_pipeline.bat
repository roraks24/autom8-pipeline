@echo off
cd /d "e:\Coding\application automat8"
"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe" daily_workflow.py --submit >> "e:\Coding\application automat8\application_logs\scheduled_run.log" 2>&1
