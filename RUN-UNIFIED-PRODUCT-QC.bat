@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0RUN-UNIFIED-PRODUCT-QC.ps1"
pause
exit /b %errorlevel%
