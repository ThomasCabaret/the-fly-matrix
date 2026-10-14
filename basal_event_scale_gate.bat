@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - basal event/scale compatibility gate
echo  TECHNICAL GRID ONLY - NO PHYSIOLOGY - NO BEHAVIOR
echo ============================================================
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.basal_event_scale_gate
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] The complete preregistered grid was recorded.
) else (
  echo [FAIL] The gate stopped with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
