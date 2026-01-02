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
python -m venv appenv

echo.
echo Activating virtual environment...
call appenv\Scripts\activate.bat

echo.
echo Installing requirements...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
set /p INSTALL_NODES="Would you like to install node dependencies? (y/n): "
if /i "%INSTALL_NODES%"=="y" (
    echo Installing node dependencies...
    call install_nodes.bat
) else (
    echo Skipping node dependencies installation.
    echo You can install them later by running: install_nodes.bat
)

echo.
echo ========================================
echo Setup completed successfully!
echo ========================================
echo.
echo To activate the environment in the future, run:
echo   appenv\Scripts\activate.bat
echo.
echo To start the PyNode server, run:
echo   python -m pynode
echo   or after installing: pynode
echo.
pause
