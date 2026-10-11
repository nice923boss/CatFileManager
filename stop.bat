@echo off
cd /d "%~dp0"
echo Stopping CatFileManager...
if not exist ".app.lock" goto nolock
rem Outside a ( ) block so %PID% is expanded after set /p has read it
set /p PID=<".app.lock"
taskkill /f /pid %PID% >nul 2>&1
del ".app.lock" >nul 2>&1
echo Stopped PID %PID%.
goto fallback
:nolock
echo No lockfile found - app not running.
:fallback
taskkill /f /im pythonw_catfm.exe >nul 2>&1
timeout /t 1 >nul
