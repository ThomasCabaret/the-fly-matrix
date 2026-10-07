@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo THE FLY MATRIX - FECO ANIMAL-HELD-OUT CALCIUM FIT
echo LOCAL OBSERVATION ONLY / NO BEHAVIOR / NO NATIVE-SPIKE CLAIM
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python environment is missing. Run setup.bat first.
  set "EXIT_CODE=1"
  goto :finish
)

echo [INFO] Verifying all three checksum-locked FeCO tables.
echo [INFO] Holding out complete animals; trials and ROIs never cross folds.
echo [INFO] Comparing seven explicit source/boundary paths without choosing a winner.
echo [INFO] Fixed paths fit scale/offset; claw paths fit five padded-GCaMP polynomial coefficients.
echo [INFO] No behavior, body trajectory, routing, or native representation is selected.
echo.

".venv\Scripts\python.exe" -m the_fly_matrix.feco_calcium_fit
set "EXIT_CODE=%ERRORLEVEL%"

:finish
echo.
if "%EXIT_CODE%"=="0" (
  echo [DONE] All source candidates and animal-held-out folds were accounted for.
  echo [NOTE] This remains a local calcium-observation comparison, not a spike-model decision.
) else if "%EXIT_CODE%"=="2" (
  echo [BLOCKED] The exact Dryad tables are absent.
  echo [NEXT] Put DRYAD_BEARER_TOKEN in .env, run prepare_local_source_data.bat, then retry.
) else (
  echo [FAILED] A hash, schema, grouping, leakage, or numerical invariant failed.
)
echo Exit code: %EXIT_CODE%
echo.
pause
exit /b %EXIT_CODE%
