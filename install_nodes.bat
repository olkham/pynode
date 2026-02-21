@echo off
setlocal EnableDelayedExpansion

:: Activate virtual environment if not already activated
if defined VIRTUAL_ENV (
    echo Virtual environment already activated.
    goto :venv_ready
)
if exist "appenv" (
    echo Activating virtual environment (appenv^)...
    call appenv\Scripts\activate.bat
    goto :venv_ready
)
if exist ".venv" (
    echo Activating virtual environment (.venv^)...
    call .venv\Scripts\activate.bat
    goto :venv_ready
)
echo Warning: No virtual environment found (checked appenv and .venv^).
set /p USE_CURRENT="Would you like to install into the current environment? (y/n): "
if /i not "!USE_CURRENT!"=="y" (
    echo Aborted. Please run setup.bat first or create a virtual environment.
    exit /b 1
)
echo Proceeding with the current environment...
:venv_ready

:: Iterate through node folders
echo Installing node dependencies...
set /a NODE_COUNT=0
set /a INSTALLED_COUNT=0

for /d %%D in (pynode\nodes\*) do (
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
