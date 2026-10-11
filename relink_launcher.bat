@echo off
cd /d "%~dp0"
rem Copy pythonw.exe from the Python on PATH, renamed so Task Manager shows pythonw_catfm.exe
for /f "delims=" %%i in ('python -c "import sys, os; print(os.path.dirname(sys.executable))"') do set "PY_HOME=%%i"
if not defined PY_HOME (
    echo Python not found on PATH. Install Python 3.12 first.
    pause
    exit /b 1
)
echo Using Python at %PY_HOME%
copy /y "%PY_HOME%\pythonw.exe" "pythonw_catfm.exe"
for %%d in ("%PY_HOME%\python3*.dll") do copy /y "%%d" "%%~nxd"
echo Relinked.
pause
