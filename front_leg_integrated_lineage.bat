@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo The Fly Matrix - FH-06 integrated factorized lineage
echo ============================================================
echo.
echo Verifies every frozen parent hash, compiles the complete
echo FH-03 x FH-04 x FH-05 conditional lineage without expanding it,
echo then executes one outcome-blind physical/replay witness.
echo No member, parameter, behavior, or body trajectory is selected.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_integrated_lineage
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] FH-06 integrated lineage is frozen and replay-checked.
) else (
  echo [FAILED] FH-06 stopped with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
