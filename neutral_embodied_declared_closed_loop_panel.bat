@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  THE FLY MATRIX - EXHAUSTIVE CAUSAL PHYSICAL PANEL
echo  240 declared tuples / 480 reset-isolated paired episodes
echo  No fit, ranking, promotion, stability or behavior claim
echo ============================================================
echo.
echo Building one reusable MuJoCo model, then resetting it before
echo every baseline and perturbed branch. Every schedule row is kept,
echo including silent routes and descriptive physical pathologies.
echo.
".venv\Scripts\python.exe" -m the_fly_matrix.neutral_embodied_declared_closed_loop_panel
set "TFM_EXIT=%ERRORLEVEL%"
echo.
if "%TFM_EXIT%"=="0" (
  echo [DONE] Exhaustive causal physical accounting passed.
) else (
  echo [FAILED] The panel stopped with exit code %TFM_EXIT%.
  echo Inspect calibration\runner\neutral-embodied-declared-closed-loop-panel-v0.yaml.
)
echo.
pause
exit /b %TFM_EXIT%
