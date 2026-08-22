@echo off
net session >nul 2>&1
if errorlevel 1 (
    powershell start -verb runas '%0' %*
    exit /b
)
cd /d "%~dp0"
python ./core/cracker_installer.py uninstall --path "%~dp0/driver/cracker.sys"
pause