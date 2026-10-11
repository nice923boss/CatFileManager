@echo off
cd /d "%~dp0"
echo Stopping CatFileManager...
set LOCK=.app.lock

if exist "%LOCK%" (
    set /p PID=<"%LOCK%"
    taskkill /f /pid %PID% >nul 2>&1
    del "%LOCK%" >nul 2>&1
    echo Stopped PID %PID%.
) else (
    echo No lockfile found - app not running.
)

taskkill /f /im pythonw_catfm.exe >nul 2>&1
timeout /t 1 >nul
