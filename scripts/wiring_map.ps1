param(
    [switch]$NoPause,
    [switch]$NoOpen,
    [int]$Port = 8766
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$UiRoot = Join-Path $ProjectRoot "ui\wiring-map"
$NodeModules = Join-Path $UiRoot "node_modules"
$OutputRoot = Join-Path $ProjectRoot "reports\generated\wiring-map"
$Manifest = Join-Path $OutputRoot "wiring-map.json"
$Url = "http://127.0.0.1:$Port/"
$ExitCode = 0
$ServerProcess = $null

function Invoke-Checked {
    param(
        [string]$Label,
        [scriptblock]$Command
    )
    Write-Host $Label -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE."
    }
}

try {
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host " The Fly Matrix - exhaustive interactive wiring map" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host "Project : $ProjectRoot"
    Write-Host "Output  : $OutputRoot"

    if (-not (Test-Path -LiteralPath $Python)) {
        throw "Project Python not found. Run setup.bat first."
    }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "Node.js was not found in PATH. Install Node.js 20 or newer."
    }
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm was not found in PATH. Reinstall Node.js with npm enabled."
    }

    Write-Host "`n[1/5] Toolchain" -ForegroundColor Cyan
    Write-Host "Python : $(& $Python --version)"
    Write-Host "Node   : $(node --version)"
    Write-Host "npm    : $(npm --version)"

    if (-not (Test-Path -LiteralPath $NodeModules)) {
        Invoke-Checked "`n[2/5] Installing locked frontend dependencies (first run only)" {
            Push-Location $UiRoot
            try { npm ci } finally { Pop-Location }
        }
    }
    else {
        Write-Host "`n[2/5] Frontend dependencies already installed." -ForegroundColor DarkGray
    }

    Invoke-Checked "`n[3/5] Compiling the local React/Cytoscape viewer" {
        Push-Location $UiRoot
        try { npm run build } finally { Pop-Location }
    }

    Invoke-Checked "`n[4/5] Exporting the real terminal graph from ledger and manifests" {
        $env:PYTHONPATH = Join-Path $ProjectRoot "src"
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
        & $Python -m the_fly_matrix.wiring_map
    }

    if (-not (Test-Path -LiteralPath $Manifest)) {
        throw "The wiring manifest was not generated: $Manifest"
    }
    $ManifestSize = (Get-Item -LiteralPath $Manifest).Length / 1MB
    Write-Host ("Manifest: {0:N1} MiB" -f $ManifestSize) -ForegroundColor DarkGray

    if ($NoOpen) {
        Write-Host "`n[5/5] Build complete; browser launch disabled." -ForegroundColor Green
    }
    else {
        Write-Host "`n[5/5] Starting local viewer at $Url" -ForegroundColor Cyan
        $ServerArguments = @{
            FilePath = $Python
            ArgumentList = @(
                "-m", "http.server", "$Port", "--bind", "127.0.0.1",
                "--directory", $OutputRoot
            )
            WorkingDirectory = $ProjectRoot
            WindowStyle = "Hidden"
            PassThru = $true
        }
        $ServerProcess = Start-Process @ServerArguments
        Start-Sleep -Milliseconds 700
        if ($ServerProcess.HasExited) {
            throw "The local HTTP server stopped immediately. Port $Port may already be in use."
        }
        Start-Process -FilePath $Url
        Write-Host "[OK] Interactive wiring map opened." -ForegroundColor Green
        Write-Host "The local server will remain available while this console is open." -ForegroundColor DarkGray
    }
}
catch {
    $ExitCode = 1
    Write-Host "`n[FAILED] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        if ($ServerProcess -and -not $ServerProcess.HasExited) {
            [void](Read-Host "Press Enter to close the viewer server")
        }
        else {
            [void](Read-Host "Press Enter to close")
        }
    }
    if ($ServerProcess -and -not $ServerProcess.HasExited) {
        Stop-Process -Id $ServerProcess.Id -ErrorAction SilentlyContinue
        $ServerProcess.WaitForExit(3000) | Out-Null
        Write-Host "Local viewer server stopped." -ForegroundColor DarkGray
    }
}

exit $ExitCode
