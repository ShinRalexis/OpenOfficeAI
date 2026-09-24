# OpenOfficeAI installer for Windows (Apache OpenOffice 4.x or LibreOffice).
#
#   install.ps1              install or update the extension
#   install.ps1 -Uninstall   remove it
#   install.ps1 -CloseOffice close a running office first (only if no document window is open)
#
# Before installing, the old manual setup (Scripts\python\ollama_ai.py and the
# custom toolbar that called it) is backed up and removed, so the buttons are
# not duplicated.
param(
    [switch]$Uninstall,
    [switch]$CloseOffice,
    [string]$Oxt = ""
)

$ErrorActionPreference = "Stop"
$ExtensionId = "org.openofficeai.extension"
$Italian = (Get-Culture).TwoLetterISOLanguageName -eq "it"

function Say([string]$it, [string]$en) {
    if ($Italian) { Write-Host $it } else { Write-Host $en }
}

function Fail([string]$it, [string]$en) {
    if ($Italian) { Write-Host "ERRORE: $it" -ForegroundColor Red } else { Write-Host "ERROR: $en" -ForegroundColor Red }
    exit 1
}

# ---------------------------------------------------------------- office ----

$offices = @(
    @{ Name = "Apache OpenOffice"; Dir = "${env:ProgramFiles(x86)}\OpenOffice 4\program"; Profile = "$env:APPDATA\OpenOffice\4\user" },
    @{ Name = "Apache OpenOffice"; Dir = "$env:ProgramFiles\OpenOffice 4\program"; Profile = "$env:APPDATA\OpenOffice\4\user" },
    @{ Name = "LibreOffice"; Dir = "$env:ProgramFiles\LibreOffice\program"; Profile = "$env:APPDATA\LibreOffice\4\user" },
    @{ Name = "LibreOffice"; Dir = "${env:ProgramFiles(x86)}\LibreOffice\program"; Profile = "$env:APPDATA\LibreOffice\4\user" }
)
$office = $offices | Where-Object { Test-Path (Join-Path $_.Dir "unopkg.com") } | Select-Object -First 1
if (-not $office) {
    Fail "OpenOffice o LibreOffice non trovato." "OpenOffice or LibreOffice not found."
}
$unopkg = Join-Path $office.Dir "unopkg.com"
Say "Trovato: $($office.Name) ($($office.Dir))" "Found: $($office.Name) ($($office.Dir))"

# unopkg must not run while the office is open.
$running = @(Get-Process soffice, soffice.bin -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    $windows = @($running | Where-Object { $_.MainWindowTitle -ne "" })
    if ($CloseOffice -and $windows.Count -eq 0) {
        Say "Chiudo l'avvio rapido di $($office.Name)..." "Closing the $($office.Name) quickstarter..."
        $running | Stop-Process -Force
        Start-Sleep -Seconds 2
    } elseif ($windows.Count -gt 0) {
        Fail "$($office.Name) ha documenti aperti ($($windows[0].MainWindowTitle)). Salvali, chiudi il programma e riprova." `
             "$($office.Name) has open documents ($($windows[0].MainWindowTitle)). Save them, close the program and try again."
    } else {
        Fail "$($office.Name) è in esecuzione (anche solo l'avvio rapido nell'area di notifica). Chiudilo o usa -CloseOffice." `
             "$($office.Name) is running (maybe just the quickstarter in the tray). Close it or use -CloseOffice."
    }
}

# -------------------------------------------------------------- uninstall ----

if ($Uninstall) {
    & $unopkg remove $ExtensionId 2>&1 | Out-Host
    Say "OpenOfficeAI rimosso." "OpenOfficeAI removed."
    exit 0
}

# ---------------------------------------------------------------- package ----

if (-not $Oxt) {
    $candidates = @(Get-ChildItem -Path $PSScriptRoot, (Join-Path $PSScriptRoot "..\dist") -Filter "OpenOfficeAI-*.oxt" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    if ($candidates.Count -eq 0) {
        Fail "File OpenOfficeAI-*.oxt non trovato accanto all'installer." "OpenOfficeAI-*.oxt not found next to the installer."
    }
    $Oxt = $candidates[0].FullName
}
Say "Pacchetto: $Oxt" "Package: $Oxt"

# ------------------------------------------------------ old manual setup ----

$profileDir = $office.Profile
$backup = Join-Path $profileDir ("backup_openofficeai_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
$moved = 0

function Backup-And-Remove([string]$path) {
    if (-not (Test-Path $script:backup)) { New-Item -ItemType Directory -Path $script:backup | Out-Null }
    Copy-Item $path -Destination $script:backup
    Remove-Item $path -Force
    $script:moved++
    Say "  rimosso (copia in backup): $path" "  removed (backed up): $path"
}

if (Test-Path $profileDir) {
    $oldScript = Join-Path $profileDir "Scripts\python\ollama_ai.py"
    if (Test-Path $oldScript) { Backup-And-Remove $oldScript }

    $writerCfg = Join-Path $profileDir "config\soffice.cfg\modules\swriter"
    Get-ChildItem (Join-Path $writerCfg "toolbar") -Filter "custom_toolbar_*.xml" -ErrorAction SilentlyContinue |
        Where-Object { (Get-Content $_.FullName -Raw) -match "ollama_ai\.py" } |
        ForEach-Object { Backup-And-Remove $_.FullName }

    # Icons assigned by hand: drop only the entries for the old macro.
    $imageList = Join-Path $writerCfg "images\sc_imagelist.xml"
    if ((Test-Path $imageList) -and ((Get-Content $imageList -Raw) -match "ollama_ai\.py")) {
        if (-not (Test-Path $backup)) { New-Item -ItemType Directory -Path $backup | Out-Null }
        Copy-Item $imageList -Destination $backup
        $lines = Get-Content $imageList -Encoding UTF8 | Where-Object { $_ -notmatch "ollama_ai\.py" }
        if (-not ($lines -match "image:entry")) {
            Remove-Item $imageList -Force
        } else {
            [System.IO.File]::WriteAllLines($imageList, [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
        }
        $moved++
        Say "  icone della vecchia macro tolte da: $imageList" "  old macro icons removed from: $imageList"
    }
}
if ($moved -gt 0) {
    Say "Vecchia installazione manuale rimossa. Backup in: $backup" "Old manual setup removed. Backup in: $backup"
}

# ---------------------------------------------------------------- install ----

Say "Installo l'estensione..." "Installing the extension..."
& $unopkg remove $ExtensionId 2>&1 | Out-Null
& $unopkg add -s $Oxt 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) {
    Fail "unopkg ha restituito l'errore $LASTEXITCODE." "unopkg failed with exit code $LASTEXITCODE."
}
# AOO's unopkg writes straight to the console, so "unopkg list" cannot be
# parsed; check the package cache of the profile instead.
$cached = Get-ChildItem (Join-Path $profileDir "uno_packages\cache\uno_packages") -Directory -ErrorAction SilentlyContinue |
    Get-ChildItem -Filter "OpenOfficeAI-*.oxt" -ErrorAction SilentlyContinue
if (-not $cached) {
    Say "Attenzione: non trovo il pacchetto nel profilo; controlla Strumenti > Gestione estensioni." `
        "Warning: the package is not in the profile cache; check Tools > Extension Manager."
}

Say "" ""
Say "Fatto. Apri $($office.Name) Writer: trovi la barra OpenOfficeAI e il menu AI." `
    "Done. Open $($office.Name) Writer: you will find the OpenOfficeAI toolbar and the AI menu."
Say "Scegli il modello con il tasto AI Impostazioni (ingranaggio)." "Choose the model with the AI Settings (gear) button."
