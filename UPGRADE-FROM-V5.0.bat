@echo off
setlocal
cd /d "%~dp0"
echo RMR Platform v5.1 Commercial Candidate Upgrade
echo.
set /p OLDINSTALL=Enter the full path to the existing RMR Platform v5.0 folder: 
set OLDINSTALL=%OLDINSTALL:"=%
PowerShell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0UPGRADE-FROM-V5.0.ps1" -ExistingInstall "%OLDINSTALL%"
set EXITCODE=%ERRORLEVEL%
echo.
if "%EXITCODE%"=="0" (
  echo RMR Platform v5.1 Commercial Candidate upgrade completed successfully.
) else (
  echo RMR Platform v5.1 Commercial Candidate upgrade did not complete.
  echo Review data\LAST-UPGRADE-RESULT.json and the diagnostic file named above.
  echo If rollback succeeded, your previous v5.0 installation is still running.
)
echo.
pause
exit /b %EXITCODE%
