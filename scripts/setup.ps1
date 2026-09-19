param(
    [ValidateSet("core", "audit", "body", "full")]
    [string]$Profile = "core",
    [switch]$NoPause,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvRoot = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$ExitCode = 0

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Test-Python312([string]$Executable) {
    if (-not (Test-Path -LiteralPath $Executable)) { return $false }
    try {
        $Version = & $Executable -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
        if ($LASTEXITCODE -ne 0) { return $false }
        Write-Host "Candidat Python: $Executable ($Version)"
        return $Version -match '^3\.12\.'
    } catch {
        return $false
    }
}

function Find-Python312 {
    $Candidates = @()
    if ($env:FLYMATRIX_PYTHON) { $Candidates += $env:FLYMATRIX_PYTHON }

    foreach ($CommandName in @("python.exe", "python3.exe")) {
        $Command = Get-Command $CommandName -ErrorAction SilentlyContinue
        if ($Command) { $Candidates += $Command.Source }
    }

    $Candidates += @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Python312\python.exe"
    )

    foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
        if (Test-Python312 $Candidate) { return $Candidate }
    }
    return $null
}

try {
    Write-Host "The Fly Matrix - environment setup" -ForegroundColor Green
    Write-Host "Project : $ProjectRoot"
    Write-Host "Profile : $Profile"
    Write-Host "Venv    : $VenvRoot"

    if ($Recreate -and (Test-Path -LiteralPath $VenvRoot)) {
        Write-Step "Recreation demandee"
        $ResolvedVenv = (Resolve-Path -LiteralPath $VenvRoot).Path
        if (-not $ResolvedVenv.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refus de supprimer un environnement hors du projet: $ResolvedVenv"
        }
        Remove-Item -LiteralPath $ResolvedVenv -Recurse -Force
        Write-Host "Ancien environnement supprime."
    }

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Step "Recherche de Python 3.12"
        $Python = Find-Python312
        if ($Python) {
            Write-Host "Python retenu: $Python" -ForegroundColor Green
            Write-Step "Creation de .venv avec le module standard venv"
            & $Python -m venv $VenvRoot
            if ($LASTEXITCODE -ne 0) { throw "python -m venv a echoue." }
        } else {
            Write-Host "Aucun Python 3.12 executable n'a ete trouve." -ForegroundColor Yellow
            $Uv = Get-Command uv.exe -ErrorAction SilentlyContinue
            if (-not $Uv) {
                $BundledUv = Join-Path $ProjectRoot "tools\uv\uv.exe"
                if (Test-Path -LiteralPath $BundledUv) { $Uv = Get-Item $BundledUv }
            }
            if (-not $Uv) {
                throw "Installez Python 3.12 ou placez uv.exe dans tools\uv. Voir README.md."
            }
            Write-Host "uv retenu: $($Uv.Source)" -ForegroundColor Green
            Write-Step "Creation de .venv; uv telechargera Python 3.12 si necessaire"
            & $Uv.Source venv --python 3.12 $VenvRoot
            if ($LASTEXITCODE -ne 0) { throw "uv venv a echoue." }
        }
    } else {
        Write-Step "Environnement existant"
        Write-Host ".venv existe deja; aucune recreation demandee." -ForegroundColor Green
    }

    if (-not (Test-Python312 $VenvPython)) {
        throw "L'interpreteur de .venv n'est pas un Python 3.12 valide."
    }

    $Extra = switch ($Profile) {
        "core"  { "dev" }
        "audit" { "dev,audit" }
        "body"  { "dev,body" }
        "full"  { "dev,audit,body,warp" }
    }

    Write-Step "Mise a niveau de pip"
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "La mise a niveau de pip a echoue." }

    Write-Step "Installation editable du profil [$Extra]"
    & $VenvPython -m pip install -e "$ProjectRoot[$Extra]"
    if ($LASTEXITCODE -ne 0) { throw "L'installation du projet a echoue." }

    Write-Step "Tests de l'echafaudage"
    & $VenvPython -m unittest discover -s (Join-Path $ProjectRoot "tests") -v
    if ($LASTEXITCODE -ne 0) { throw "Les tests de l'echafaudage ont echoue." }

    Write-Step "Resume"
    & $VenvPython --version
    & $VenvPython -m pip --version
    Write-Host "Profil installe : $Profile" -ForegroundColor Green
    Write-Host "Activation       : .venv\Scripts\Activate.ps1"
    Write-Host "Etat             : status.bat"
}
catch {
    $ExitCode = 1
    Write-Host "`nECHEC: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Aucune donnee MaleCNS n'a ete supprimee ou modifiee." -ForegroundColor Yellow
}
finally {
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
