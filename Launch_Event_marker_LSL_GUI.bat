@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%USERPROFILE%\AppData\Local\miniconda3\envs\lsl_env\python.exe"
set "SCRIPT_PATH=%~dp0Event_marker_LSL_GUI.py"

if not exist "%PYTHON_EXE%" (
    echo Could not find lsl_env Python at:
    echo %PYTHON_EXE%
    pause
    exit /b 1
)

if not exist "%SCRIPT_PATH%" (
    echo Could not find script:
    echo %SCRIPT_PATH%
    pause
    exit /b 1
)

"%PYTHON_EXE%" "%SCRIPT_PATH%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Event_marker_LSL_GUI.py exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
