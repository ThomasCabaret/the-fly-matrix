@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo  The Fly Matrix - microscopic neural-runtime regression suite
echo  SOFTWARE VERIFICATION / NOT A BIOLOGICAL MODEL VALIDATION
echo ============================================================
echo.
echo [SCOPE 1/6] aBN1 event/rate runner: units, signs, delays, resets,
echo             fresh state, configuration wiring and CPU/GPU parity.
echo [SCOPE 2/6] Source-aligned LIF: NumPy/Torch recurrence and state rules.
echo [SCOPE 3/6] Brian2 scheduler boundaries: integration, reset,
echo             refractory eligibility and delayed delivery.
echo [SCOPE 4/6] Temporal probes: rate-bin information loss and pathologies.
echo [SCOPE 5/6] Typed/hybrid ports: four boundaries, delay and type guards.
echo [SCOPE 6/6] Basal source bridges: event probability, graded conversion,
echo             explicit shapes, invalid-unit guards and reproducibility.
echo.
echo [RUN] Executing deterministic microscopic oracles...
call .venv\Scripts\python.exe -m pytest ^
  tests\test_abn1_model_class.py ^
  tests\test_lif_source_fidelity.py ^
  tests\test_brian2_conformance.py ^
  tests\test_temporal_model_probes.py ^
  tests\test_typed_hybrid_runtime.py ^
  tests\test_basal_source_bridges.py ^
  -q
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo [SUCCESS] All microscopic neural-runtime invariants passed.
  echo           This validates implementation mechanics only.
  echo           It does NOT promote rate, LIF, constants, or biology.
) else (
  echo [FAILED] At least one microscopic invariant failed.
  echo          Do not trust or promote dependent neural runs.
  echo          Pytest exit code: %EXIT_CODE%
)
echo.
pause
exit /b %EXIT_CODE%
