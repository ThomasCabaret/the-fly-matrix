@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - FH-08 HELD-OUT PROTOCOL LOCK
echo  Evaluation-only / outcomes unseen / no member selection
echo ============================================================
echo.
echo [INFO] Verifying frozen lineage, stimulus, sham, seeds and thresholds.
echo [INFO] Scheduling frozen and recipe-matched recalibrated rewires.
echo [INFO] This command does NOT execute or inspect held-out behavior.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.first_held_out_protocol_lock
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] FH-08 lock compiled. See calibration\runner\first-held-out-protocol-lock-v0.yaml
) else (
  echo [ERROR] FH-08 lock failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
