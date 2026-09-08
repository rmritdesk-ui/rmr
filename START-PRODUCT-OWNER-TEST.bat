@echo off
setlocal
cd /d "%~dp0"
title RMR Global v5.4.1.2C Packaging Correction Product Owner Test
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0START-PRODUCT-OWNER-TEST.ps1"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" echo RMR Global Product Owner startup did not complete successfully.
if "%EXITCODE%"=="0" echo RMR Global Product Owner environment is ready.
echo.
pause
exit /b %EXITCODE%
