@echo off
setlocal EnableDelayedExpansion

:: Check if virtual environment exists
if not exist "appenv" (
    echo Error: Virtual environment not found. Please run setup.bat first.
    exit /b 1
)

:: Activate virtual environment if not already activated
if "%VIRTUAL_ENV%"=="" (
    echo Activating virtual environment...
    call appenv\Scripts\activate.bat
) else (
    echo Virtual environment already activated.
)

:: Iterate through node folders
echo Installing node dependencies...
set /a NODE_COUNT=0
set /a INSTALLED_COUNT=0

for /d %%D in (nodes\*) do (
    set "node_dir=%%D"
    set "requirements_file=%%D\requirements.txt"
    
    if exist "!requirements_file!" (
        for %%N in ("%%D") do set "node_name=%%~nxN"
        echo Installing requirements for !node_name!...
        
        pip install -r "!requirements_file!"
        
        if !errorlevel! equ 0 (
            set /a INSTALLED_COUNT+=1
            echo [OK] !node_name! dependencies installed successfully
        ) else (
            echo [ERROR] Failed to install dependencies for !node_name!
        )
        set /a NODE_COUNT+=1
    )
)

echo.
echo Installation complete!
echo Processed !NODE_COUNT! nodes with requirements.txt files
echo Successfully installed dependencies for !INSTALLED_COUNT! nodes

endlocal
