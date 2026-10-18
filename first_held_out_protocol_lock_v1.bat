@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - FH-08 V1 TIMEBASE-EXACT PROTOCOL LOCK
echo  Evaluation-only / outcomes unseen / no member selection
echo ============================================================
echo.
echo [INFO] Verifying the exact 650-step ramp on the frozen MuJoCo timebase.
echo [INFO] This command does NOT execute or inspect held-out behavior.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.first_held_out_protocol_lock ^
  --campaign calibration\campaigns\first-held-out-protocol-lock-v1.yaml ^
  --result calibration\runner\first-held-out-protocol-lock-v1.yaml ^
  --evaluation calibration\evaluations\first-held-out-protocol-lock-v1.yaml
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] FH-08 v1 lock compiled with zero held-out outcomes.
) else (
  echo [ERROR] FH-08 v1 lock failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
