@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0COLLECT-DIAGNOSTICS-CB1.ps1"
pause
