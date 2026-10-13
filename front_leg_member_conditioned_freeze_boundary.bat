@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - MEMBER-CONDITIONED FREEZE BOUNDARY
echo  Exact local composites only; no behavior and no family freeze
echo ============================================================
echo.
echo This run reconstructs all accepted local members without ranking them.
echo It explicitly keeps sensory, central and motor factors coupled.
echo Basal families are accounted as NOT EXERCISED, never defaulted to zero.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.front_leg_member_conditioned_freeze_boundary
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Three member-conditioned bundles were checked and written.
  echo [NEXT] Whole-body technical preview remains separate and requires user review.
) else (
  echo [FAILED] Compilation stopped with exit code %TFM_EXIT%.
)
echo.
pause
exit /b %TFM_EXIT%
