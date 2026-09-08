@echo off
setlocal
cd /d "%~dp0"
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0COLLECT-DIAGNOSTICS.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" echo Diagnostic collection failed with exit code %EXITCODE%.
pause
exit /b %EXITCODE%
