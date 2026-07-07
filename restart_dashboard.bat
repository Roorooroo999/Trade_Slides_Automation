@echo off
cd /d "%~dp0"
set PYTHON=C:\Users\r0c0jug\AppData\Local\Programs\Python\Python314\python.exe
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo Killing all Python processes...
taskkill /F /IM python.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo Starting dashboard...
start "Inventory Dashboard" /MIN %PYTHON% app.py

echo Dashboard starting on http://127.0.0.1:8050
timeout /t 5 /nobreak >nul
start "" "http://127.0.0.1:8050"
