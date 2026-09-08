@echo off
setlocal
cd /d "%~dp0"
title Stop RMR Global v5.4.1.2C Product Owner Test
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0STOP-PRODUCT-OWNER-TEST.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
