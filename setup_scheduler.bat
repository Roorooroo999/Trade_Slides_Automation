@echo off
title Setup Inventory Dashboard — Scheduled Tasks
cd /d "%~dp0"
set DIR=%~dp0
set PYTHON=C:\Users\r0c0jug\AppData\Local\Programs\Python\Python314\python.exe

echo.
echo  ============================================================
echo   Inventory Dashboard — Scheduled Task Setup
echo  ============================================================
echo.
echo  This will create 2 Windows Scheduled Tasks:
echo.
echo    1. InvDash_WeeklyRefresh
echo       Runs every Wednesday at 7:00 AM
echo       Generates PDF, captures Build/Burn chart,
echo       updates PPTX, restarts dashboard
echo.
echo    2. InvDash_Startup
echo       Runs at login — keeps dashboard alive after reboot
echo.

REM ── Task 1: Weekly Refresh (Wed 7:00 AM) ────────────────────────────────────
schtasks /delete /tn "InvDash_WeeklyRefresh" /f >nul 2>&1

schtasks /create ^
  /tn "InvDash_WeeklyRefresh" ^
  /tr "cmd.exe /c cd /d \"%DIR%\" && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && \"%PYTHON%\" capture_buildburn.py >> \"%DIR%scheduler.log\" 2>&1 && \"%PYTHON%\" generate_talk_track_pdf.py >> \"%DIR%scheduler.log\" 2>&1 && \"%PYTHON%\" update_pptx.py >> \"%DIR%scheduler.log\" 2>&1 && taskkill /F /IM python.exe /T >nul 2>&1 && start \"\" /MIN \"%PYTHON%\" app.py" ^
  /sc WEEKLY ^
  /d WED ^
  /st 07:00 ^
  /ru "%USERNAME%" ^
  /f

if errorlevel 1 (
    echo  [ERROR] Failed to create WeeklyRefresh task.
    goto :end
)
echo  [OK] InvDash_WeeklyRefresh created — runs every Wednesday at 07:00

REM ── Task 2: Dashboard Startup (at login) ────────────────────────────────────
schtasks /delete /tn "InvDash_Startup" /f >nul 2>&1

schtasks /create ^
  /tn "InvDash_Startup" ^
  /tr "cmd.exe /c cd /d \"%DIR%\" && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && timeout /t 30 /nobreak >nul && start \"\" /MIN \"%PYTHON%\" app.py" ^
  /sc ONLOGON ^
  /ru "%USERNAME%" ^
  /f

if errorlevel 1 (
    echo  [WARN] Could not create Startup task.
) else (
    echo  [OK] InvDash_Startup created — starts dashboard at every login
)

REM ── Summary ──────────────────────────────────────────────────────────────────
echo.
echo  ============================================================
echo   Setup Complete!
echo.
echo   WeeklyRefresh : Every Wednesday 07:00 AM (auto)
echo   Startup       : Dashboard starts at login (auto)
echo   Dashboard URL : http://127.0.0.1:8050
echo.
echo   To view tasks:  Task Scheduler ^> Task Scheduler Library
echo   To run now:     schtasks /run /tn "InvDash_WeeklyRefresh"
echo   To remove:      schtasks /delete /tn "InvDash_WeeklyRefresh" /f
echo  ============================================================
echo.

:end
pause
