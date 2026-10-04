param(
    [ValidateSet("auto", "cpu", "cuda", "both")]
    [string]$Backend = "both",
    [switch]$Quick,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - gate de fidelite du modele neural" -ForegroundColor Green
    Write-Host "Projet  : $ProjectRoot"
    Write-Host "Backend : $Backend"
    Write-Host "Contrat : MODEL CLASS GATE / UNCALIBRATED / NO BEHAVIOR" -ForegroundColor Yellow
    Write-Host "Ce script ne telecharge aucune morphologie et ne calibre aucun comportement."
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez setup.bat puis setup_gpu.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $Arguments = @("-m", "the_fly_matrix.lif_gate", "--backend", $Backend)
    if ($Quick) { $Arguments += "--quick" }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Le gate LIF a echoue avec le code $LASTEXITCODE." }
    Write-Host "`n[OK] Étapes d'ingénierie terminées; le gate scientifique reste explicitement ouvert." -ForegroundColor Green
}
catch {
    $ExitCode = 1
    Write-Host "`n[ECHEC] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
