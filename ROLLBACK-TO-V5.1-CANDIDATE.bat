@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ROLLBACK-TO-V5.1-CANDIDATE.ps1"
pause
