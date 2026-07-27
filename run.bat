@echo off
title Local ITR Calculator
cd /d "%~dp0"

echo ===================================================
echo             Starting Local ITR Calculator          
echo ===================================================
echo.

if not exist "frontend\node_modules" (
    echo [setup] Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)

echo [setup] Starting application and opening browser...
python main.py %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [error] Application exited with an error.
    pause
)
