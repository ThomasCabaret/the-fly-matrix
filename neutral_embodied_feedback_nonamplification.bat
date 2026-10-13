@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - LOCAL FEEDBACK NON-AMPLIFICATION
echo  65 rows x 4 new mirrored perturbations; no behavior
echo ============================================================
echo.
echo This run performs technical pass/fail selection without ranking.
echo It cannot accept whole-body stability or biological behavior.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_feedback_nonamplification
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Locked local non-amplification validation completed.
) else (
  echo [FAILED] Validation stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
