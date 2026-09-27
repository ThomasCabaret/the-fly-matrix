param(
    [ValidateSet("auto", "cpu", "cuda", "both")]
    [string]$Backend = "auto",
    [ValidateSet("full", "causal-core")]
    [string]$Scope = "full",
    [int]$Steps = 0,
    [switch]$RebuildCache,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - real MaleCNS execution benchmark" -ForegroundColor Green
    Write-Host "Project : $ProjectRoot"
    Write-Host "Backend : $Backend"
    Write-Host "Scope   : $Scope"
    Write-Host "Label   : BENCHMARK ONLY / UNCALIBRATED" -ForegroundColor Yellow
    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Python du projet introuvable. Lancez setup.bat puis setup_gpu.bat."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $Arguments = @("-m", "the_fly_matrix.connectome_benchmark", "--backend", $Backend, "--scope", $Scope)
    if ($Steps -gt 0) { $Arguments += @("--steps", "$Steps") }
    if ($RebuildCache) { $Arguments += "--rebuild-cache" }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Le benchmark a echoue avec le code $LASTEXITCODE." }
    Write-Host "`n[OK] Benchmark et trace de replay termines." -ForegroundColor Green
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
