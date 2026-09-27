param(
    [ValidateSet("record", "live", "replay")]
    [string]$Mode = "record",
    [double]$Duration = 1.0,
    [double]$CommandScale = 0.001,
    [int]$VisionStride = 1,
    [double]$Speed = 0.0,
    [double]$RenderFps = 30.0,
    [string]$ReplayPath = "",
    [switch]$RecordLive,
    [switch]$HeadlessReplay,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ExitCode = 0

try {
    Write-Host "The Fly Matrix - embodied real MaleCNS" -ForegroundColor Green
    Write-Host "Project : $ProjectRoot"
    Write-Host "Mode    : $Mode"
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Yellow
    Write-Host " REAL MALECNS - CLOSED LOOP - UNCALIBRATED" -ForegroundColor Yellow
    Write-Host " No behavioral claim; interface parameters are placeholders." -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Yellow

    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Project Python was not found. Run setup.bat first."
    }
    $env:PYTHONPATH = Join-Path $ProjectRoot "src"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"

    if ($Mode -eq "replay") {
        Write-Host "[1/2] Loading a controller-independent physical trajectory" -ForegroundColor Cyan
        $Arguments = @("-m", "the_fly_matrix.physical_trajectory", "--speed", $(if ($Speed -gt 0) { $Speed } else { 1.0 }), "--render-fps", $RenderFps)
        if ($ReplayPath) { $Arguments += $ReplayPath }
        if ($HeadlessReplay) { $Arguments += "--headless" }
        Write-Host "[2/2] Starting physical replay" -ForegroundColor Cyan
    } else {
        Write-Host "[1/3] Preparing real MaleCNS, live interfaces and FlyBody" -ForegroundColor Cyan
        Write-Host "Duration       : $(if ($Duration -eq 0) { 'until viewer closes' } else { "$Duration s" })"
        Write-Host "Vision stride  : $VisionStride neural step(s)"
        Write-Host "Command guard  : tanh(raw) * $CommandScale"
        Write-Host "Target speed   : $(if ($Speed -eq 0) { 'unthrottled' } else { "${Speed}x" })"
        $Arguments = @(
            "-m", "the_fly_matrix.embodied_runtime",
            "--duration", $Duration,
            "--command-scale", $CommandScale,
            "--vision-stride", $VisionStride,
            "--render-fps", $RenderFps,
            "--speed", $Speed
        )
        if ($Mode -eq "live") {
            $Arguments += "--live"
            if ($RecordLive) { $Arguments += "--record-live" }
            Write-Host "[2/3] Starting interactive live loop" -ForegroundColor Cyan
        } else {
            Write-Host "[2/3] Recording closed-loop trajectory headlessly" -ForegroundColor Cyan
        }
    }

    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Embodied runtime failed with exit code $LASTEXITCODE."
    }
    Write-Host "`n[OK] $Mode completed cleanly." -ForegroundColor Green
    if ($Mode -ne "replay") {
        Write-Host "[3/3] Summary: runs\closed-loop\latest.json"
    }
}
catch {
    $ExitCode = 1
    Write-Host "`n[FAIL] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Press Enter to close")
    }
}

exit $ExitCode
