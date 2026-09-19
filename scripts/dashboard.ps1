param([switch]$NoPause, [switch]$NoOpen)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Report = Join-Path $ProjectRoot "reports\generated\project-status.html"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - tableau de bord" -ForegroundColor Green
    Write-Host "Projet : $ProjectRoot"
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez d'abord setup.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Write-Host "`n[1/2] Validation du registre et calcul des indicateurs" -ForegroundColor Cyan
    & $Python -m the_fly_matrix.report
    if ($LASTEXITCODE -ne 0) { throw "La generation a echoue avec le code $LASTEXITCODE." }
    Write-Host "`n[2/2] Rapport disponible : $Report" -ForegroundColor Cyan
    if (-not $NoOpen) {
        Start-Process -FilePath $Report
        Write-Host "[OK] Tableau de bord ouvert dans le navigateur." -ForegroundColor Green
    } else {
        Write-Host "[OK] Generation terminee sans ouverture du navigateur." -ForegroundColor Green
    }
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
