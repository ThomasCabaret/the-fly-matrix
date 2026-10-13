@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - DIRECT-MOTOR FACTOR ISOLATION
echo  3 failed tuples x 4 one-factor ablations x 2 branches
echo  Exact-row policy over all 240 immutable schedule rows
echo ============================================================
echo.
echo This technical runner never clips, fits, ranks or promotes a row.
echo It stops before an invalid command and preserves the fixed 0.01 limit.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_command_factor_isolation
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Factor isolation and exact-row accounting passed.
) else (
  echo [FAILED] Factor isolation stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
