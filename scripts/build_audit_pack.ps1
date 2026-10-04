param(
    [switch]$NoPause,
    [string]$OutputDirectory,
    [int64]$MaxTextFileBytes = 262144,
    [int64]$CodeSampleBudgetBytes = 368640
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot "audit-packs"
} elseif (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory = Join-Path $ProjectRoot $OutputDirectory
}

$AllowedExtensions = @(
    ".bat", ".css", ".html", ".json", ".md", ".ps1", ".py",
    ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml"
)

# These trees contain the project's scientific policy, decisions, canonical
# registries and reproducible campaign descriptions. New text files added below
# them are included automatically.
$ExhaustivePrefixes = @(
    ".agents/skills/",
    "benchmarks/profiles/",
    "calibration/",
    "decisions/",
    "docs/",
    "ledger/",
    "protocols/",
    "wiring/revalidation/"
)

$RootDocuments = @(
    ".env.example",
    "AGENTS.md",
    "PROJECT_STATE.md",
    "README.md",
    "data/derived/README.md",
    "data/raw/README.md",
    "drosophila_virtual_fly_project_contract.md",
    "pyproject.toml",
    "requirements-gpu-cu126.txt",
    "requirements-lock.txt",
    "runs/README.md"
)

# Whole files, not rewritten excerpts. The budget prevents implementation code
# from crowding out policy. Update this short list only when a new subsystem is
# important enough that an external reviewer needs to inspect its implementation.
$PriorityCodeSamples = @(
    "src/the_fly_matrix/central_graph.py",
    "src/the_fly_matrix/calibration_registry.py",
    "src/the_fly_matrix/calibration_parameters.py",
    "src/the_fly_matrix/calibration_runner.py",
    "src/the_fly_matrix/wiring_revalidation.py",
    "src/the_fly_matrix/runtime.py",
    "src/the_fly_matrix/embodied_runtime.py",
    "src/the_fly_matrix/physical_trajectory.py",
    "src/the_fly_matrix/signed_dynamics.py",
    "tests/test_calibration_registry.py",
    "tests/test_wiring_revalidation.py",
    "tests/test_embodied_runtime.py",
    "scripts/build_audit_pack.ps1"
)

$AlwaysExcludedPrefixes = @(
    ".git/", ".venv/", ".cache/", "audit-packs/", "data/raw/",
    "data/derived/", "reports/generated/", "runs/", "tools/uv/",
    "ui/wiring-map/node_modules/", "ui/wiring-map/dist/"
)

$ExitCode = 0
$StageRoot = $null

function Normalize-RelativePath([string]$Path) {
    # git ls-files already returns repository-relative paths. In particular, do
    # not trim leading dots: .agents and .env.example are meaningful names.
    return $Path.Replace("\", "/")
}

function Starts-WithAny([string]$Path, [string[]]$Prefixes) {
    foreach ($Prefix in $Prefixes) {
        if ($Path.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Get-LineCount([string]$Path) {
    $Count = 0
    $Reader = [System.IO.File]::OpenText($Path)
    try {
        while ($null -ne $Reader.ReadLine()) { $Count++ }
    } finally {
        $Reader.Dispose()
    }
    return $Count
}

function Copy-AuditFile([string]$RelativePath, [string]$Category) {
    $Source = Join-Path $ProjectRoot ($RelativePath.Replace("/", "\"))
    $Destination = Join-Path $PackRoot ($RelativePath.Replace("/", "\"))
    $DestinationParent = Split-Path -Parent $Destination
    if (-not (Test-Path -LiteralPath $DestinationParent)) {
        [void](New-Item -ItemType Directory -Path $DestinationParent -Force)
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
    $Item = Get-Item -LiteralPath $Source
    $Lines = Get-LineCount $Source
    $Hash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
    $script:Included.Add([pscustomobject]@{
        path = $RelativePath
        category = $Category
        bytes = $Item.Length
        lines = $Lines
        sha256 = $Hash
    })
}

try {
    Write-Host "The Fly Matrix - pack d'audit externe" -ForegroundColor Green
    Write-Host "Projet : $ProjectRoot"
    Write-Host "Sortie : $OutputDirectory"

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "Git est requis pour inventorier les fichiers suivis et non suivis non ignores."
    }

    Push-Location $ProjectRoot
    try {
        $Tracked = @(& git ls-files)
        if ($LASTEXITCODE -ne 0) { throw "git ls-files a echoue." }
        $Untracked = @(& git ls-files --others --exclude-standard)
        if ($LASTEXITCODE -ne 0) { throw "git ls-files --others a echoue." }
        $Commit = (& git rev-parse HEAD).Trim()
        $Branch = (& git branch --show-current).Trim()
        $DirtyLines = @(& git status --porcelain)
    } finally {
        Pop-Location
    }

    $SourceKinds = @{}
    foreach ($Path in $Tracked) {
        if (-not [string]::IsNullOrWhiteSpace($Path)) {
            $SourceKinds[(Normalize-RelativePath $Path)] = "tracked"
        }
    }
    foreach ($Path in $Untracked) {
        if (-not [string]::IsNullOrWhiteSpace($Path)) {
            $Normalized = Normalize-RelativePath $Path
            if (-not $SourceKinds.ContainsKey($Normalized)) {
                $SourceKinds[$Normalized] = "untracked"
            }
        }
    }

    $Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $ArchiveName = "the-fly-matrix-audit-$Stamp.zip"
    [void](New-Item -ItemType Directory -Path $OutputDirectory -Force)
    $ArchivePath = Join-Path $OutputDirectory $ArchiveName
    $StageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("flymatrix-audit-" + [guid]::NewGuid().ToString("N"))
    $PackRoot = Join-Path $StageRoot "the-fly-matrix-audit"
    [void](New-Item -ItemType Directory -Path $PackRoot -Force)

    $Included = [System.Collections.Generic.List[object]]::new()
    $Omitted = [System.Collections.Generic.List[object]]::new()
    $Selected = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $CodeBytes = 0L

    Write-Host "`n[1/4] Selection des sources textuelles" -ForegroundColor Cyan
    $Candidates = @($SourceKinds.Keys | Sort-Object)
    foreach ($RelativePath in $Candidates) {
        $FullPath = Join-Path $ProjectRoot ($RelativePath.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $FullPath -PathType Leaf)) { continue }

        $Extension = [System.IO.Path]::GetExtension($RelativePath).ToLowerInvariant()
        $IsAllowedText = ($AllowedExtensions -contains $Extension) -or ($RelativePath -eq ".env.example")
        $Reason = $null
        $Category = $null

        if ($RootDocuments -contains $RelativePath) {
            $Category = "root-policy-and-environment"
        } elseif (Starts-WithAny $RelativePath $AlwaysExcludedPrefixes) {
            $Reason = "excluded-resource-or-generated-tree"
        } elseif (-not $IsAllowedText) {
            $Reason = "non-text-or-unsupported-extension"
        } elseif ($RelativePath -match '(^|/)(\.env|[^/]*(secret|token|credential|private-key)[^/]*)$' -and $RelativePath -ne ".env.example") {
            $Reason = "secret-risk-name"
        } elseif ((Split-Path -Parent $RelativePath) -eq "" -and $Extension -eq ".bat") {
            $Category = "launcher"
        } elseif (Starts-WithAny $RelativePath $ExhaustivePrefixes) {
            $Category = "policy-status-and-reproducibility"
        } elseif ($PriorityCodeSamples -contains $RelativePath) {
            $Category = "implementation-sample"
        } else {
            $Reason = "outside-audit-scope"
        }

        $Item = Get-Item -LiteralPath $FullPath
        if ($null -eq $Reason -and $Item.Length -gt $MaxTextFileBytes) {
            $Reason = "file-size-limit"
            $Category = $null
        }
        if ($null -eq $Reason -and $Category -eq "implementation-sample") {
            if (($CodeBytes + $Item.Length) -gt $CodeSampleBudgetBytes) {
                $Reason = "code-sample-budget"
                $Category = $null
            } else {
                $CodeBytes += $Item.Length
            }
        }

        if ($null -ne $Category) {
            Copy-AuditFile $RelativePath $Category
            [void]$Selected.Add($RelativePath)
        } else {
            $Omitted.Add([pscustomobject]@{
                path = $RelativePath
                source_state = $SourceKinds[$RelativePath]
                bytes = $Item.Length
                reason = $Reason
            })
        }
    }

    Write-Host ("      {0} fichiers copies; {1} fichiers inventories mais omis." -f $Included.Count, $Omitted.Count)

    Write-Host "`n[2/4] Ecriture du contexte et des manifestes" -ForegroundColor Cyan
    $Dirty = if ($DirtyLines.Count -gt 0) { "yes" } else { "no" }
    $Readme = @"
# The Fly Matrix — external audit pack

This is a bounded, text-only snapshot intended for review by another human or
language model. It is not a runnable checkout and deliberately excludes raw and
derived datasets, generated reports, run outputs, environments, dependencies,
large resources, secrets and most implementation code.

- Generated: $(Get-Date -Format "yyyy-MM-ddTHH:mm:ssK")
- Git branch: $Branch
- Git commit: $Commit
- Working tree dirty when captured: $Dirty
- Included files: $($Included.Count)
- Omitted inventoried files: $($Omitted.Count)
- Included source bytes before compression: $([int64](($Included | Measure-Object -Property bytes -Sum).Sum))
- Included source lines: $([int64](($Included | Measure-Object -Property lines -Sum).Sum))

Read `AGENTS.md`, `PROJECT_STATE.md`, `README.md`, `docs/`, `decisions/` and the
canonical YAML registries first. `MANIFEST.tsv` records every copied file and its
SHA-256. `OMISSIONS.tsv` records every tracked or visible non-ignored file that
was not copied and why. Implementation samples are complete source files but are
only examples; do not infer that omitted code does not exist.

The archive copies current working-tree contents, so tracked modifications and
eligible untracked files are represented even when `dirty` is `yes`.
"@
    [System.IO.File]::WriteAllText((Join-Path $PackRoot "AUDIT_PACK_README.md"), $Readme, [System.Text.UTF8Encoding]::new($false))

    $ManifestPath = Join-Path $PackRoot "MANIFEST.tsv"
    $ManifestLines = [System.Collections.Generic.List[string]]::new()
    $ManifestLines.Add("path`tcategory`tbytes`tlines`tsha256")
    foreach ($Row in ($Included | Sort-Object path)) {
        $ManifestLines.Add("$($Row.path)`t$($Row.category)`t$($Row.bytes)`t$($Row.lines)`t$($Row.sha256)")
    }
    [System.IO.File]::WriteAllLines($ManifestPath, $ManifestLines, [System.Text.UTF8Encoding]::new($false))

    $OmissionsPath = Join-Path $PackRoot "OMISSIONS.tsv"
    $OmissionLines = [System.Collections.Generic.List[string]]::new()
    $OmissionLines.Add("path`tsource_state`tbytes`treason")
    foreach ($Row in ($Omitted | Sort-Object path)) {
        $OmissionLines.Add("$($Row.path)`t$($Row.source_state)`t$($Row.bytes)`t$($Row.reason)")
    }
    [System.IO.File]::WriteAllLines($OmissionsPath, $OmissionLines, [System.Text.UTF8Encoding]::new($false))

    $StatusPath = Join-Path $PackRoot "GIT_STATUS.txt"
    $StatusText = if ($DirtyLines.Count -gt 0) { ($DirtyLines -join [Environment]::NewLine) } else { "clean" }
    [System.IO.File]::WriteAllText($StatusPath, $StatusText + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

    Write-Host "`n[3/4] Compression" -ForegroundColor Cyan
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ArchivePath) {
        [System.IO.File]::Delete($ArchivePath)
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $StageRoot,
        $ArchivePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )

    Write-Host "`n[4/4] Verification de l'archive" -ForegroundColor Cyan
    $Zip = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $EntryCount = $Zip.Entries.Count
        $ActualEntries = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        foreach ($Entry in $Zip.Entries) {
            [void]$ActualEntries.Add($Entry.FullName.Replace("\", "/"))
        }
        $ExpectedEntries = @(
            $Included.path | ForEach-Object { "the-fly-matrix-audit/$_" }
        ) + @(
            "the-fly-matrix-audit/AUDIT_PACK_README.md",
            "the-fly-matrix-audit/GIT_STATUS.txt",
            "the-fly-matrix-audit/MANIFEST.tsv",
            "the-fly-matrix-audit/OMISSIONS.tsv"
        )
        $MissingEntries = @($ExpectedEntries | Where-Object { -not $ActualEntries.Contains($_) })
        if ($MissingEntries.Count -gt 0) {
            throw "Archive incomplete; entrees absentes : $($MissingEntries -join ', ')"
        }
    } finally {
        $Zip.Dispose()
    }

    $ArchiveItem = Get-Item -LiteralPath $ArchivePath
    $SourceBytes = [int64](($Included | Measure-Object -Property bytes -Sum).Sum)
    $SourceLines = [int64](($Included | Measure-Object -Property lines -Sum).Sum)
    Write-Host "`n[OK] Pack d'audit construit." -ForegroundColor Green
    Write-Host "     Archive       : $ArchivePath"
    Write-Host "     Taille ZIP    : $([math]::Round($ArchiveItem.Length / 1KB, 1)) KiB"
    Write-Host "     Sources       : $($Included.Count) fichiers, $([math]::Round($SourceBytes / 1KB, 1)) KiB, $SourceLines lignes"
    Write-Host "     Echant. code  : $([math]::Round($CodeBytes / 1KB, 1)) KiB / $([math]::Round($CodeSampleBudgetBytes / 1KB, 1)) KiB"
    Write-Host "     Omissions     : $($Omitted.Count), detaillees dans OMISSIONS.tsv"
}
catch {
    $ExitCode = 1
    Write-Host "`n[ECHEC] $($_.Exception.Message)" -ForegroundColor Red
}
finally {
    if ($null -ne $StageRoot -and (Test-Path -LiteralPath $StageRoot)) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
    if (-not $NoPause) {
        Write-Host ""
        [void](Read-Host "Appuyez sur Entree pour fermer")
    }
}

exit $ExitCode
