@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - DIRECT-MOTOR LIMIT DIAGNOSTIC
echo  3 failed tuples x 2 branches x 2 deterministic repeats
echo  No clipping, fitting, selection, stability or behavior claim
echo ============================================================
echo.
echo The runner stops before every offending command is applied and
echo records the first native step, attempted value and factor coordinates.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_command_limit_diagnostic
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] The bounded command-limit diagnostic passed.
) else (
  echo [FAILED] Diagnostic stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
