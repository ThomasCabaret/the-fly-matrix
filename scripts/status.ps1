param([switch]$NoPause)

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExitCode = 0

$ExpectedData = @(
    @{ Name = "body-annotations-male-cns-v1.0-minconf-0.5.feather"; Bytes = 14483314L },
    @{ Name = "body-neurotransmitters-male-cns-v1.0.feather"; Bytes = 43282834L },
    @{ Name = "connectome-weights-male-cns-v1.0-minconf-0.5.feather"; Bytes = 1051241946L }
)

function Write-Section([string]$Title) {
    Write-Host "`n--- $Title ---" -ForegroundColor Cyan
}

function Find-Executable([string[]]$Names, [string[]]$Fallbacks) {
    foreach ($Name in $Names) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) { return $Command.Source }
    }
    foreach ($Path in $Fallbacks) {
        if (Test-Path -LiteralPath $Path) { return $Path }
    }
    return $null
}

try {
    Write-Host "The Fly Matrix - project status" -ForegroundColor Green
    Write-Host "Project: $ProjectRoot"

    Write-Section "Outils"
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $VenvPython) {
        $Python = $VenvPython
    } else {
        $Python = Find-Executable @("python.exe", "python3.exe") @(
            "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        )
    }
    if ($Python) {
        $PythonVersion = & $Python --version 2>&1
        Write-Host "Python   : $PythonVersion [$Python]" -ForegroundColor Green
        if ($Python -eq $VenvPython) {
            $PackageSummary = & $Python -c "import importlib.metadata as m, torch; print('FlyGym=' + m.version('flygym') + '; MuJoCo=' + m.version('mujoco') + '; PyTorch=' + torch.__version__ + '; CUDA=' + str(torch.cuda.is_available()))" 2>&1
            Write-Host "Paquets  : $PackageSummary" -ForegroundColor Green
        }
    } else {
        Write-Host "Python   : introuvable" -ForegroundColor Red
        $ExitCode = 1
    }

    $Uv = Find-Executable @("uv.exe") @((Join-Path $ProjectRoot "tools\uv\uv.exe"))
    if ($Uv) { Write-Host "uv       : $(& $Uv --version 2>&1) [$Uv]" } else { Write-Host "uv       : absent (facultatif)" }

    $Dot = Find-Executable @("dot.exe") @("C:\Program Files\Graphviz\bin\dot.exe")
    if ($Dot) { Write-Host "Graphviz : $(& $Dot -V 2>&1) [$Dot]" -ForegroundColor Green } else { Write-Host "Graphviz : introuvable" -ForegroundColor Yellow }

    $Git = Find-Executable @("git.exe") @()
    if ($Git) { Write-Host "Git      : $(& $Git --version 2>&1)" -ForegroundColor Green }

    $NvidiaSmi = Find-Executable @("nvidia-smi.exe") @("C:\Windows\System32\nvidia-smi.exe")
    if ($NvidiaSmi) {
        $Gpu = & $NvidiaSmi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>&1
        Write-Host "GPU      : $Gpu" -ForegroundColor Green
    }

    Write-Section "Donnees MaleCNS minimales"
    $DataRoot = Join-Path $ProjectRoot "data\raw\malecns\v1.0"
    $ValidCount = 0
    foreach ($Spec in $ExpectedData) {
        $Path = Join-Path $DataRoot $Spec.Name
        if (Test-Path -LiteralPath $Path) {
            $Actual = (Get-Item -LiteralPath $Path).Length
            if ($Actual -eq $Spec.Bytes) {
                Write-Host "[OK]      $($Spec.Name) ($Actual octets)" -ForegroundColor Green
                $ValidCount++
            } else {
                Write-Host "[INVALIDE] $($Spec.Name): $Actual au lieu de $($Spec.Bytes)" -ForegroundColor Red
                $ExitCode = 1
            }
        } else {
            Write-Host "[ABSENT]  $($Spec.Name)" -ForegroundColor Red
            $ExitCode = 1
        }
    }
    Write-Host "Valides  : $ValidCount/$($ExpectedData.Count)"

    Write-Section "Registre"
    foreach ($Kind in @("boxes", "wires", "parameter_families", "validations")) {
        $Folder = Join-Path $ProjectRoot "ledger\$Kind"
        $Count = if (Test-Path $Folder) { @(Get-ChildItem $Folder -File -Filter "*.yaml" | Where-Object Name -ne "_template.yaml").Count } else { 0 }
        Write-Host ("{0,-20}: {1}" -f $Kind, $Count)
    }

    Write-Section "Git"
    if (Test-Path (Join-Path $ProjectRoot ".git")) {
        & git -C $ProjectRoot status --short
        if ($LASTEXITCODE -ne 0) { $ExitCode = 1 }
    } else {
        Write-Host "Depot Git absent." -ForegroundColor Red
        $ExitCode = 1
    }

    Write-Section "Conclusion"
    if ($ExitCode -eq 0) {
        Write-Host "Socle local pret pour l'audit d'interface." -ForegroundColor Green
    } else {
        Write-Host "Un ou plusieurs controles demandent une intervention." -ForegroundColor Yellow
    }
}
catch {
    $ExitCode = 1
    Write-Host "ECHEC: $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
