@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0UPGRADE-FROM-V5.1-CANDIDATE.ps1"
pause
