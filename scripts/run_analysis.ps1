param([switch]$NoPause)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - audit local reproductible" -ForegroundColor Green
    Write-Host "Projet : $ProjectRoot"
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez d'abord setup.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Write-Host "`n[1/1] Inventaire MaleCNS + FlyBody" -ForegroundColor Cyan
    & $Python -m the_fly_matrix.inventory
    if ($LASTEXITCODE -ne 0) { throw "L'inventaire a échoué avec le code $LASTEXITCODE." }
    Write-Host "`n[OK] Audit termine." -ForegroundColor Green
}
catch {
    $ExitCode = 1
    Write-Host "`n[ECHEC] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entrée pour fermer")
    }
}

exit $ExitCode
