@echo off
setlocal
cd /d "%~dp0"
set PROFILE=%~1
if "%PROFILE%"=="" set PROFILE=empty
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL.ps1" -Profile "%PROFILE%"
set EXITCODE=%ERRORLEVEL%
echo.
if not "%EXITCODE%"=="0" (
  echo RMR Platform installation failed. Review the message above.
) else (
  echo RMR Platform installation finished. The browser setup page should be available now.
)
echo.
pause
exit /b %EXITCODE%
