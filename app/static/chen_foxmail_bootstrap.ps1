param(
    [switch]$Watch
)

$ErrorActionPreference = 'Stop'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant'
$BootstrapPath = Join-Path $InstallDir 'chen_foxmail_bootstrap.ps1'
$HelperPath = Join-Path $InstallDir 'chen_foxmail_helper.ps1'
$BootstrapUrl = 'https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_bootstrap.ps1'
$HelperUrl = 'https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_helper_v09.ps1'
$StartupName = 'ChenAssistant-Foxmail-Helper.lnk'
$BootstrapVersion = '1.0'
$UpdateIntervalMinutes = 5
$WatchIntervalSeconds = 20

try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Get-BridgeProcesses {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -like '*chen_foxmail_helper*.ps1*' -and
        $_.CommandLine -like '*-BridgeMode*'
    })
}

function Get-WatchProcesses {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.ProcessId -ne $PID -and
        $_.CommandLine -and
        $_.CommandLine -like '*chen_foxmail_bootstrap.ps1*' -and
        $_.CommandLine -like '*-Watch*'
    })
}

function Stop-Bridge {
    foreach ($proc in (Get-BridgeProcesses)) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500

    # Historical helpers were sometimes launched directly from versioned files such
    # as chen_foxmail_helper_v07.ps1 / v08.ps1. If one of those still owns 18763,
    # terminate only when the listener process command line is clearly one of our
    # Chen Foxmail helper scripts.
    try {
        $listeners = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 18763 -State Listen -ErrorAction SilentlyContinue)
        foreach ($listener in $listeners) {
            $owner = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [int]$listener.OwningProcess) -ErrorAction SilentlyContinue
            if ($owner -and $owner.CommandLine -and
                $owner.CommandLine -like '*chen_foxmail_helper*.ps1*' -and
                $owner.CommandLine -like '*-BridgeMode*') {
                Stop-Process -Id $owner.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {}
    Start-Sleep -Milliseconds 500
}

function Get-BridgePowerShell {
    $native = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $native) { return $native }
    return 'powershell.exe'
}

function Start-Bridge {
    if (-not (Test-Path -LiteralPath $HelperPath)) { return $false }
    if ((Get-BridgeProcesses).Count -gt 0) { return $true }
    $bridgePowerShell = Get-BridgePowerShell
    Start-Process -FilePath $bridgePowerShell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', "`"$HelperPath`"", '-BridgeMode'
    )
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 150
        if ((Get-BridgeProcesses).Count -gt 0) {
            try {
                $health = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:18763/health' -Headers @{Origin='https://assistant.ziboxiaozhushou.cn'} -TimeoutSec 2
                if ($health.ok -eq $true -and $health.version -eq '0.9') { return $true }
            } catch {}
        }
    }
    return $false
}

function Start-Watchdog {
    foreach ($proc in (Get-WatchProcesses)) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 250
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', "`"$BootstrapPath`"", '-Watch'
    )
}

function Test-BootstrapFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $bytes = [IO.File]::ReadAllBytes($Path)
        if ($bytes.Length -lt 1000) { return $false }
        if (($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) { return $false }
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $Path,
            [ref]$tokens,
            [ref]$errors
        ) | Out-Null
        if ($errors.Count -gt 0) { return $false }
        $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::ASCII)
        foreach ($required in @(
            '$BootstrapVersion',
            'function Update-Bootstrap',
            'function Update-Helper',
            'function Start-Bridge',
            'chen_foxmail_helper_v09.ps1'
        )) {
            if (-not $text.Contains($required)) { return $false }
        }
        return $true
    } catch {
        return $false
    }
}

function Update-Bootstrap {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $download = Join-Path $InstallDir 'chen_foxmail_bootstrap.update.ps1'
    Remove-Item -Force -ErrorAction SilentlyContinue $download
    try {
        $uri = $BootstrapUrl + '?autoupdate=' + [DateTime]::UtcNow.Ticks
        Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $download -TimeoutSec 20
        if (-not (Test-BootstrapFile $download)) { throw 'Downloaded bootstrap failed validation.' }
        $newHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash
        $oldHash = ''
        if (Test-Path -LiteralPath $BootstrapPath) {
            try { $oldHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $BootstrapPath).Hash } catch {}
        }
        if ($newHash -eq $oldHash -and $oldHash) {
            Remove-Item -Force -ErrorAction SilentlyContinue $download
            return $false
        }
        Copy-Item -Force -LiteralPath $download -Destination $BootstrapPath
        Remove-Item -Force -ErrorAction SilentlyContinue $download
        return $true
    } catch {
        Remove-Item -Force -ErrorAction SilentlyContinue $download
        return $false
    }
}
function Test-HelperFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $bytes = [IO.File]::ReadAllBytes($Path)
        if ($bytes.Length -lt 1000) { return $false }
        if (($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) { return $false }
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile(
            $Path,
            [ref]$tokens,
            [ref]$errors
        ) | Out-Null
        if ($errors.Count -gt 0) { return $false }
        $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::ASCII)
        foreach ($marker in @(
            '[switch]$BridgeMode',
            "HelperVersion = '0.9'",
            "AllowedRootDomain = 'ziboxiaozhushou.cn'",
            "Path -eq '/compose'",
            'Build-MailtoUri',
            'Set-AttachmentClipboard',
            "attachment_mode='clipboard-file-drop'",
            "mode = 'foxmail-exe-mailto-clipboard-ready'"
        )) {
            if (-not $text.Contains($marker)) { return $false }
        }
        return $true
    } catch {
        return $false
    }
}

function Update-Helper {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $download = Join-Path $InstallDir 'chen_foxmail_helper.download.ps1'
    $staged = Join-Path $InstallDir 'chen_foxmail_helper.new.ps1'
    Remove-Item -Force -ErrorAction SilentlyContinue $download, $staged
    $uri = $HelperUrl + '?autoupdate=' + [DateTime]::UtcNow.Ticks
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $download -TimeoutSec 20
        if (-not (Test-HelperFile $download)) { throw 'Downloaded helper failed validation.' }
        $newHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash
        $oldHash = ''
        if (Test-Path -LiteralPath $HelperPath) {
            try { $oldHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $HelperPath).Hash } catch {}
        }
        if ($newHash -eq $oldHash -and $oldHash) {
            Remove-Item -Force -ErrorAction SilentlyContinue $download
            return $false
        }
        Copy-Item -Force -LiteralPath $download -Destination $staged
        if (-not (Test-HelperFile $staged)) { throw 'Staged helper failed validation.' }
        Copy-Item -Force -LiteralPath $staged -Destination $HelperPath
        Remove-Item -Force -ErrorAction SilentlyContinue $download, $staged
        return $true
    } catch {
        Remove-Item -Force -ErrorAction SilentlyContinue $download, $staged
        return $false
    }
}

function Install-Bootstrap {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    $source = $null
    if ($PSCommandPath -and (Test-Path -LiteralPath $PSCommandPath)) {
        $source = [IO.Path]::GetFullPath($PSCommandPath)
    }

    $target = [IO.Path]::GetFullPath($BootstrapPath)
    if ($source) {
        if (-not $source.Equals($target, [StringComparison]::OrdinalIgnoreCase)) {
            Copy-Item -Force -LiteralPath $source -Destination $BootstrapPath
        }
    } else {
        $download = Join-Path $InstallDir 'chen_foxmail_bootstrap.download.ps1'
        Remove-Item -Force -ErrorAction SilentlyContinue $download
        try {
            $uri = $BootstrapUrl + '?install=' + [DateTime]::UtcNow.Ticks
            Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $download -TimeoutSec 20
            $bytes = [IO.File]::ReadAllBytes($download)
            if ($bytes.Length -lt 1000) { throw 'Downloaded bootstrap is unexpectedly small.' }
            if (($bytes | Where-Object { $_ -gt 127 }).Count -gt 0) { throw 'Downloaded bootstrap is not ASCII-safe.' }
            $tokens = $null
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $download,
                [ref]$tokens,
                [ref]$errors
            ) | Out-Null
            if ($errors.Count -gt 0) { throw 'Downloaded bootstrap failed PowerShell syntax validation.' }
            Copy-Item -Force -LiteralPath $download -Destination $BootstrapPath
        } finally {
            Remove-Item -Force -ErrorAction SilentlyContinue $download
        }
    }

    $startup = [Environment]::GetFolderPath('Startup')
    $shortcutPath = Join-Path $startup $StartupName
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = 'powershell.exe'
    $shortcut.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$BootstrapPath`" -Watch"
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = 'Chen Assistant Foxmail auto updater and watchdog'
    $shortcut.Save()
}

if (-not $Watch) {
    Install-Bootstrap
    $updated = Update-Helper
    Stop-Bridge
    $started = Start-Bridge
    Start-Watchdog
    Write-Host ''
    Write-Host ('Chen Assistant Windows helper bootstrap v' + $BootstrapVersion + ' installed.') -ForegroundColor Green
    Write-Host "Install directory: $InstallDir"
    Write-Host ('Latest helper downloaded: ' + $(if ($updated) { 'yes' } else { 'already current or network unavailable' }))
    Write-Host ('Helper running: ' + $(if ($started) { 'yes' } else { 'no' }))
    Write-Host ('Bridge PowerShell: ' + (Get-BridgePowerShell))
    Write-Host 'Foxmail launch mode: direct Foxmail.exe + mailto; TXT is placed on the Windows file clipboard.'
    Write-Host 'In the Foxmail compose window, press Ctrl+V to add the TXT attachment. Explorer is not opened.'
    Write-Host 'The helper never auto-sends mail.'
    Write-Host ''
    Write-Host 'Return to Chen Assistant and refresh the page.'
    Read-Host 'Press Enter to close'
    exit 0
}

$lastUpdate = [DateTime]::MinValue
while ($true) {
    try {
        if (((Get-Date) - $lastUpdate).TotalMinutes -ge $UpdateIntervalMinutes) {
            $bootstrapChanged = Update-Bootstrap
            if ($bootstrapChanged) {
                Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
                    '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $BootstrapPath + '"'), '-Watch'
                )
                exit 0
            }
            $helperChanged = Update-Helper
            $lastUpdate = Get-Date
            if ($helperChanged) { Stop-Bridge }
        }
    } catch {}
    try { [void](Start-Bridge) } catch {}
    Start-Sleep -Seconds $WatchIntervalSeconds
}
