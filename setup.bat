@echo off
echo ========================================
echo PyNode Setup Script
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ and try again
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv .venv

echo.
echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo.
echo Installing requirements...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ========================================
echo Setup completed successfully!
echo ========================================
echo.
echo To activate the environment in the future, run:
echo   .venv\Scripts\activate.bat
echo.
echo To start the PyNode server, run:
echo   python main.py
echo.
pause
