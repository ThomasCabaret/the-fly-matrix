@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - EXACT DIRECT-MOTOR PATHOLOGY POLICY
echo  240 immutable rows; unseen combinations fail closed
echo ============================================================
echo.
echo This compiler preserves the failed factor experiment, rejects no broad
echo factor domain, and never clips, ranks or promotes a candidate.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_command_pathology_policy
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Exact-schedule command policy compiled and verified.
) else (
  echo [FAILED] Policy compilation stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
