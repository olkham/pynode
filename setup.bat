@echo off
setlocal enabledelayedexpansion
echo ========================================
echo PyNode Setup Script
echo ========================================
echo.

REM Check if Python path was provided as argument
if "%~1"=="" (
    REM No argument provided, ask user
    echo No Python path specified.
    echo.
    set /p PYTHON_PATH="Enter the full path to Python executable (or press Enter to use 'python' from PATH): "
    
    if "!PYTHON_PATH!"=="" (
        set PYTHON_PATH=python
        echo Using 'python' from system PATH
    ) else (
        echo Using specified Python: !PYTHON_PATH!
    )
) else (
    REM Use the provided argument
    set PYTHON_PATH=%~1
    echo Using specified Python: !PYTHON_PATH!
)

echo.
echo Verifying Python installation...
"!PYTHON_PATH!" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not found at: !PYTHON_PATH!
    echo Please check the path and try again
    pause
    exit /b 1
)

REM Display Python version
for /f "delims=" %%i in ('"!PYTHON_PATH!" --version 2^>^&1') do set PYTHON_VERSION=%%i
echo Found: !PYTHON_VERSION!

echo.
echo Creating virtual environment...
"!PYTHON_PATH!" -m venv appenv

if %errorlevel% equ 0 (
    echo Creating .gitignore in virtual environment...
    echo * > appenv\.gitignore
) else (
    echo ERROR: Failed to create virtual environment
    pause
    exit /b 1
)

echo.
echo Activating virtual environment...
call appenv\Scripts\activate.bat

python -m pip install --upgrade pip

echo.
echo Checking for CUDA and installing PyTorch with appropriate CUDA support...
REM Check for CUDA version using nvcc first, then nvidia-smi as fallback
nvcc --version >nul 2>&1
if %errorlevel% equ 0 (
    REM Extract CUDA version from nvcc output
    REM Parse: "Cuda compilation tools, release 12.8, V12.8.61"
    for /f "tokens=5 delims=, " %%i in ('nvcc --version ^| findstr "release"') do set CUDA_VERSION=%%i
    REM Remove 'V' prefix if present
    set CUDA_VERSION=!CUDA_VERSION:V=!
    REM Extract major.minor
    for /f "tokens=1,2 delims=." %%a in ("!CUDA_VERSION!") do (
        set CUDA_MAJOR=%%a
        set CUDA_MINOR=%%b
    )
    echo Detected CUDA !CUDA_MAJOR!.!CUDA_MINOR!
) else (
    REM Fallback to nvidia-smi if nvcc not found
    nvidia-smi --query-gpu=driver_version --format=csv,noheader,nounits >nul 2>&1
    if %errorlevel% equ 0 (
        REM If nvidia-smi works, assume CUDA is available but use CPU version as safe fallback
        echo CUDA drivers detected via nvidia-smi, but CUDA toolkit not found.
        echo Installing CPU-only PyTorch. For GPU support, install CUDA toolkit.
        set CUDA_SUFFIX=
    ) else (
        echo No CUDA installation detected. Installing CPU-only PyTorch.
        set CUDA_SUFFIX=
    )
)

REM Set PyTorch index URL based on CUDA version
if defined CUDA_MAJOR (
    if !CUDA_MAJOR! EQU 12 (
        if !CUDA_MINOR! EQU 6 (
            set PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu126
            echo Installing PyTorch with CUDA 12.6 support...
        ) else if !CUDA_MINOR! EQU 8 (
            set PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
            echo Installing PyTorch with CUDA 12.8 support...
        ) else if !CUDA_MINOR! EQU 9 (
            set PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu129
            echo Installing PyTorch with CUDA 12.9 support...
        ) else (
            set PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu121
            echo CUDA !CUDA_VERSION! detected. Using CUDA 12.1 PyTorch wheels as fallback...
        )
    ) else if !CUDA_MAJOR! EQU 11 (
        set PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu118
        echo Installing PyTorch with CUDA 11.8 support...
    ) else (
        set PYTORCH_INDEX_URL=
        echo Unsupported CUDA version !CUDA_VERSION!. Installing CPU-only PyTorch.
    )
) else (
    set PYTORCH_INDEX_URL=
    echo Installing CPU-only PyTorch.
)

REM Install PyTorch and torchvision with appropriate CUDA support
if defined PYTORCH_INDEX_URL (
    pip install torch torchvision --index-url %PYTORCH_INDEX_URL%
) else (
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
)

echo.
echo Installing requirements...
pip install -r requirements.txt

echo.
echo Installing PyNode in editable mode...
pip install -e .

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
echo Python used: !PYTHON_PATH!
echo.
echo To activate the environment in the future, run:
echo   appenv\Scripts\activate.bat
echo.
echo To start the PyNode server, run:
echo   python -m pynode
echo   or after installing: pynode
echo.

set /p LAUNCH_PYNODE="Would you like to launch PyNode now? (y/n): "
if /i "%LAUNCH_PYNODE%"=="y" (
    echo.
    echo Launching PyNode...
    python -m pynode
) else (
    echo You can launch PyNode later by running: python -m pynode
)
echo.
pause
