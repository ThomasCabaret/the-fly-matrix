param([switch]$NoPause)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - verrou aBN1 JO-CE / JO-F" -ForegroundColor Green
    Write-Host "Contrat : NEURAL REFERENCE ONLY / NO FITTING / NO BEHAVIOR CLAIM" -ForegroundColor Yellow
    Write-Host "Le scope exclut explicitement aBN2, aDN, moteurs, corps et grooming."
    if (-not (Test-Path -LiteralPath $Python)) { throw "Python du projet introuvable." }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    & $Python -m the_fly_matrix.abn1_reference_lock
    if ($LASTEXITCODE -ne 0) { throw "L'audit du verrou aBN1 a échoué ($LASTEXITCODE)." }
    Write-Host "`n[OK] Protocole reconstruit et verrouillé avant sortie candidate." -ForegroundColor Green
}
catch {
    $ExitCode = 1
    Write-Host "`n[ECHEC] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) { Write-Host ""; [void](Read-Host "Appuyez sur Entree pour fermer") }
}
exit $ExitCode
