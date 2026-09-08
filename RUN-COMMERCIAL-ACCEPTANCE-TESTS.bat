@echo off
setlocal
cd /d "%~dp0"
python -m pytest -q tests
if errorlevel 1 (echo TESTS FAILED& pause& exit /b 1)
echo TESTS PASSED
pause
