@echo off
setlocal
cd /d "%~dp0"
title RMR Global Product Owner Diagnostics
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0COLLECT-PRODUCT-OWNER-DIAGNOSTICS.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
