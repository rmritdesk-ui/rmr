@echo off
setlocal
cd /d "%~dp0"
title Reset RMR Global Product Owner Demo
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0RESET-PRODUCT-OWNER-DEMO.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
pause
exit /b %EXITCODE%
