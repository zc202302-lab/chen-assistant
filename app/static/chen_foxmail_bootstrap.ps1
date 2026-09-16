param(
    [switch]$Watch
)

$ErrorActionPreference = 'Stop'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant'
$BootstrapPath = Join-Path $InstallDir 'chen_foxmail_bootstrap.ps1'
$HelperPath = Join-Path $InstallDir 'chen_foxmail_helper.ps1'
$HelperUrl = 'https://assistant.ziboxiaozhushou.cn/static/chen_foxmail_helper_v07.ps1'
$StartupName = 'ChenAssistant-Foxmail-Helper.lnk'
$UpdateIntervalMinutes = 30
$WatchIntervalSeconds = 20

try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

function Get-BridgeProcesses {
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and
        $_.CommandLine -like '*chen_foxmail_helper.ps1*' -and
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
    Start-Sleep -Milliseconds 350
}

function Get-BridgePowerShell {
    # v0.7 does not load Foxmail MAPI. Use the normal interactive Windows
    # PowerShell process so mailto launch, foreground control and clipboard work
    # in the signed-in desktop session regardless of Foxmail bitness.
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
    Start-Sleep -Milliseconds 1000
    return ((Get-BridgeProcesses).Count -gt 0)
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
            "$HelperVersion = '0.7'",
            "AllowedRootDomain = 'ziboxiaozhushou.cn'",
            "Path -eq '/compose'",
            'Build-MailtoUri',
            'Set-AttachmentClipboard',
            "mode = 'foxmail-exe-mailto-clipboard'"
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
    $source = [IO.Path]::GetFullPath($PSCommandPath)
    $target = [IO.Path]::GetFullPath($BootstrapPath)
    if (-not $source.Equals($target, [StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -Force -LiteralPath $source -Destination $BootstrapPath
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
    Write-Host 'Chen Assistant Windows helper v0.7 bootstrap installed.' -ForegroundColor Green
    Write-Host "Install directory: $InstallDir"
    Write-Host ('Latest helper downloaded: ' + $(if ($updated) { 'yes' } else { 'already current or network unavailable' }))
    Write-Host ('Helper running: ' + $(if ($started) { 'yes' } else { 'no' }))
    Write-Host ('Bridge PowerShell: ' + (Get-BridgePowerShell))
    Write-Host 'Foxmail launch mode: direct Foxmail.exe + mailto + clipboard attachment.'
    Write-Host 'Simple MAPI is not used by v0.7.'
    Write-Host ''
    Write-Host 'Return to Chen Assistant and refresh the page.'
    Read-Host 'Press Enter to close'
    exit 0
}

$lastUpdate = [DateTime]::MinValue
while ($true) {
    try {
        if (((Get-Date) - $lastUpdate).TotalMinutes -ge $UpdateIntervalMinutes) {
            $changed = Update-Helper
            $lastUpdate = Get-Date
            if ($changed) { Stop-Bridge }
        }
    } catch {}
    try { [void](Start-Bridge) } catch {}
    Start-Sleep -Seconds $WatchIntervalSeconds
}
