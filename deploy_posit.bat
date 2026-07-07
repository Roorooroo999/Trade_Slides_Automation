@echo off
title Deploy to Posit Connect
cd /d "%~dp0"
set PYTHON=C:\Users\r0c0jug\AppData\Local\Programs\Python\Python314\python.exe

echo.
echo  ============================================================
echo   Inventory Dashboard — Deploy to Posit Connect
echo  ============================================================
echo.

REM ── Load CONNECT_SERVER and CONNECT_API_KEY from .env ────────────
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if "%%A"=="CONNECT_SERVER"  set CONNECT_SERVER=%%B
    if "%%A"=="CONNECT_API_KEY" set CONNECT_API_KEY=%%B
)

if "%CONNECT_SERVER%"=="" (
    echo  [ERROR] CONNECT_SERVER not set in .env
    echo  Edit .env and set: CONNECT_SERVER=https://your-posit-url
    pause & exit /b 1
)
if "%CONNECT_API_KEY%"=="" (
    echo  [ERROR] CONNECT_API_KEY not set in .env
    echo  Edit .env and set: CONNECT_API_KEY=your-key
    pause & exit /b 1
)

echo  Server : %CONNECT_SERVER%
echo  Key    : %CONNECT_API_KEY:~0,6%...
echo.

REM ── Register server (idempotent) ────────────────────────────────
echo  Step 1: Registering Posit server...
%PYTHON% -m rsconnect add ^
    --server "%CONNECT_SERVER%" ^
    --api-key "%CONNECT_API_KEY%" ^
    --name walmart-posit ^
    --insecure 2>nul
echo.

REM ── Deploy ──────────────────────────────────────────────────────
echo  Step 2: Deploying dashboard...
%PYTHON% -m rsconnect deploy dash ^
    --server walmart-posit ^
    --entrypoint app:server ^
    --title "Inventory Health Dashboard" ^
    --exclude "*.pptx" ^
    --exclude "*.pdf" ^
    --exclude "*.log" ^
    --exclude ".git" ^
    --exclude "__pycache__" ^
    .

if errorlevel 1 (
    echo.
    echo  [ERROR] Deploy failed. Check output above.
    pause & exit /b 1
)

echo.
echo  ============================================================
echo   Deploy complete! Dashboard live at:
echo   %CONNECT_SERVER%
echo  ============================================================
echo.
pause
