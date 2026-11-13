@echo off
setlocal
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PY%" (
  rem NOTE: echo text inside an if block must not contain parentheses
  echo Installing Python 3.12 for this user - first run only...
  "%~dp0python-3.12.10-amd64.exe" /quiet InstallAllUsers=0 PrependPath=0 Include_tcltk=1 Include_pip=0 Include_launcher=0 Include_test=0 Include_doc=0 Shortcuts=0
)
if not exist "%PY%" (
  echo ERROR: Python installation failed.
  pause
  exit /b 1
)
echo Starting MockHIS test window - keep it open...
rem pythonw opens no console window
start "MockHIS" "%PYW%" "%~dp0mock_his.py"
timeout /t 3 /nobreak >nul
echo Running readback probe...
"%PY%" "%~dp0probe_readback_check.py" "%~dp0agent-desktop.exe"
echo.
echo Probe finished. Copy the output above.
pause
