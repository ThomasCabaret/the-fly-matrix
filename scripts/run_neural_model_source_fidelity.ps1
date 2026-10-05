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
    Write-Host "The Fly Matrix - correction de fidelite LIF v1" -ForegroundColor Green
    Write-Host "Projet  : $ProjectRoot"
    Write-Host "Backend : $Backend"
    Write-Host "Contrat : SOURCE-ALIGNED / UNCALIBRATED / NO BEHAVIOR" -ForegroundColor Yellow
    Write-Host "Le benchmark v0 est conserve; ce run verifie le reset-g, le gel refractaire et l'integrateur lineaire."
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez setup.bat puis setup_gpu.bat."
    }
    $SourceCheckout = Join-Path $ProjectRoot "runs\reference-source\Drosophila_brain_model"
    if (-not (Test-Path -LiteralPath $SourceCheckout)) {
        throw "Source epinglee absente: clonez https://github.com/philshiu/Drosophila_brain_model dans runs\reference-source\Drosophila_brain_model."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $Arguments = @("-m", "the_fly_matrix.lif_source_fidelity", "--backend", $Backend)
    if ($Quick) { $Arguments += "--quick" }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Le gate source-aligne a echoue avec le code $LASTEXITCODE." }
    Write-Host "`n[OK] Fidelite d'implementation v1 verifiee; le gate scientifique reste ouvert." -ForegroundColor Green
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
