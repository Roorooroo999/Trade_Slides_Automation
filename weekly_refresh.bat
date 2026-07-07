@echo off
title Inventory Dashboard — Daily Refresh
cd /d "%~dp0"
set PYTHON=C:\Users\r0c0jug\AppData\Local\Programs\Python\Python314\python.exe
set PYTHONUTF8=1

echo.
echo  ============================================================
echo   Inventory Health Dashboard — Daily Refresh
echo  ============================================================
echo.

echo  Step 1: Regenerating Talk Track PDF from live BQ data...
echo.
%PYTHON% generate_talk_track_pdf.py
if errorlevel 1 (
    echo  [ERROR] PDF generation failed. Check BigQuery credentials.
    pause
    exit /b 1
)
echo.

echo  Step 2: Capturing Build/Burn chart from BQ data...
echo.
%PYTHON% capture_buildburn.py
if errorlevel 1 (
    echo  [WARN] Build/Burn chart capture failed — PPTX slide 2 will use existing chart.
)
echo.

echo  Step 3: Updating Trade Slides PPTX with latest numbers + insights...
echo.
%PYTHON% update_pptx.py
if errorlevel 1 (
    echo  [WARN] PPTX update failed — continuing with dashboard restart.
)
echo.

echo  Step 3: Restarting dashboard (kills existing, starts fresh)...
echo.
taskkill /F /IM python.exe /T >nul 2>&1
timeout /t 1 /nobreak >nul
start "Inventory Dashboard" /MIN %PYTHON% app.py

echo.
echo  Step 4: Waiting for dashboard to load...
timeout /t 20 /nobreak >nul

echo.
echo  ============================================================
echo   Done!
echo   Dashboard:  http://127.0.0.1:8050
echo   PDF:        see folder for talk_track_WK*.pdf
echo   Slides:     see folder for Trade Slides - Inventory WK*.pptx
echo  ============================================================
echo.
start "" "http://127.0.0.1:8050"

REM Open the latest PDF
for /f "delims=" %%f in ('dir /b /o-d "talk_track_WK*.pdf" 2^>nul') do (
    start "" "%%f"
    goto :pdf_opened
)
:pdf_opened

REM Open the latest PPTX
for /f "delims=" %%f in ('dir /b /o-d "Trade Slides - Inventory WK*.pptx" 2^>nul') do (
    start "" "%%f"
    goto :pptx_opened
)
:pptx_opened

pause
