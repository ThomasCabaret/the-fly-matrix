@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - temporal representation probes
echo ============================================================
echo.
echo [RUN] Measuring information collisions and shared pathologies...
".\.venv\Scripts\python.exe" -m the_fly_matrix.temporal_model_probes
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Temporal probe report generated.
) else (
  echo [ERROR] Probe campaign failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
