param([switch]$BridgeMode)

$ErrorActionPreference = 'Stop'
$Port = 18763
$AllowedRootDomain = 'ziboxiaozhushou.cn'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant'
$InstalledScript = Join-Path $InstallDir 'chen_foxmail_helper.ps1'
$MailDir = Join-Path $InstallDir 'FoxmailDrafts'

if (-not $BridgeMode) {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Copy-Item -Force $PSCommandPath $InstalledScript

    $Startup = [Environment]::GetFolderPath('Startup')
    $ShortcutPath = Join-Path $Startup '晨的助手-Foxmail助手.lnk'
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = 'powershell.exe'
    $Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$InstalledScript`" -BridgeMode"
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.Description = '晨的助手 Foxmail 本地助手'
    $Shortcut.Save()

    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$InstalledScript`"", '-BridgeMode'
    )

    Start-Sleep -Milliseconds 700
    Write-Host ''
    Write-Host '晨的助手 Foxmail 本地助手已安装。' -ForegroundColor Green
    Write-Host "安装目录：$InstallDir"
    Write-Host '以后登录 Windows 时会自动启动。'
    Write-Host '请确保 .eml 文件默认使用 Foxmail 打开。'
    Write-Host ''
    Write-Host '现在回到晨的助手网页刷新即可。'
    Read-Host '按回车键关闭窗口'
    exit 0
}

New-Item -ItemType Directory -Force -Path $MailDir | Out-Null

# Prevent duplicate helpers. If another instance already owns the port, exit.
try {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
    $listener.Start()
} catch {
    exit 0
}

function Test-AllowedOrigin([string]$Origin) {
    if ([string]::IsNullOrWhiteSpace($Origin)) { return $false }
    try {
        $uri = [Uri]$Origin
        $hostName = $uri.Host.ToLowerInvariant()
        if ($hostName -eq '127.0.0.1' -or $hostName -eq 'localhost') { return $true }
        if ($uri.Scheme -notin @('https', 'http')) { return $false }
        return $hostName -eq $AllowedRootDomain -or $hostName.EndsWith('.' + $AllowedRootDomain)
    } catch {
        return $false
    }
}

function Write-Response {
    param(
        [System.Net.Sockets.NetworkStream]$Stream,
        [int]$StatusCode,
        [string]$Body,
        [string]$Origin = ''
    )
    $statusText = switch ($StatusCode) {
        200 { 'OK' }
        204 { 'No Content' }
        400 { 'Bad Request' }
        403 { 'Forbidden' }
        404 { 'Not Found' }
        413 { 'Payload Too Large' }
        500 { 'Internal Server Error' }
        default { 'Error' }
    }
    $bodyBytes = [Text.Encoding]::UTF8.GetBytes($Body)
    $headers = New-Object System.Collections.Generic.List[string]
    $headers.Add("HTTP/1.1 $StatusCode $statusText")
    $headers.Add('Content-Type: application/json; charset=utf-8')
    $headers.Add("Content-Length: $($bodyBytes.Length)")
    $headers.Add('Cache-Control: no-store')
    $headers.Add('Connection: close')
    if ($Origin) {
        $headers.Add("Access-Control-Allow-Origin: $Origin")
        $headers.Add('Access-Control-Allow-Methods: GET, POST, OPTIONS')
        $headers.Add('Access-Control-Allow-Headers: Content-Type')
        $headers.Add('Access-Control-Allow-Private-Network: true')
        $headers.Add('Vary: Origin')
    }
    $headerBytes = [Text.Encoding]::ASCII.GetBytes((($headers -join "`r`n") + "`r`n`r`n"))
    $Stream.Write($headerBytes, 0, $headerBytes.Length)
    if ($bodyBytes.Length) { $Stream.Write($bodyBytes, 0, $bodyBytes.Length) }
    $Stream.Flush()
}

function Read-Request([System.Net.Sockets.NetworkStream]$Stream) {
    $reader = New-Object IO.StreamReader($Stream, [Text.Encoding]::ASCII, $false, 4096, $true)
    $requestLine = $reader.ReadLine()
    if (-not $requestLine) { return $null }
    $parts = $requestLine.Split(' ')
    if ($parts.Length -lt 2) { return $null }
    $headers = @{}
    while ($true) {
        $line = $reader.ReadLine()
        if ($null -eq $line -or $line -eq '') { break }
        $colon = $line.IndexOf(':')
        if ($colon -gt 0) {
            $headers[$line.Substring(0, $colon).Trim().ToLowerInvariant()] = $line.Substring($colon + 1).Trim()
        }
    }
    $length = 0
    if ($headers.ContainsKey('content-length')) { [void][int]::TryParse($headers['content-length'], [ref]$length) }
    if ($length -gt 12000000) {
        return @{ Method=$parts[0].ToUpperInvariant(); Path=$parts[1]; Headers=$headers; TooLarge=$true; Body='' }
    }
    $body = ''
    if ($length -gt 0) {
        $chars = New-Object char[] $length
        $offset = 0
        while ($offset -lt $length) {
            $n = $reader.Read($chars, $offset, $length - $offset)
            if ($n -le 0) { break }
            $offset += $n
        }
        $body = New-Object string($chars, 0, $offset)
    }
    return @{ Method=$parts[0].ToUpperInvariant(); Path=$parts[1]; Headers=$headers; TooLarge=$false; Body=$body }
}

function Safe-FileName([string]$Name) {
    if (-not $Name) { return 'payment.eml' }
    foreach ($c in [IO.Path]::GetInvalidFileNameChars()) { $Name = $Name.Replace([string]$c, '_') }
    if (-not $Name.ToLowerInvariant().EndsWith('.eml')) { $Name += '.eml' }
    if ($Name.Length -gt 120) { $Name = $Name.Substring(0, 116) + '.eml' }
    return $Name
}

Get-ChildItem -Path $MailDir -Filter '*.eml' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            if (-not [Net.IPAddress]::IsLoopback($client.Client.RemoteEndPoint.Address)) { continue }
            $stream = $client.GetStream()
            $req = Read-Request $stream
            if ($null -eq $req) { Write-Response $stream 400 '{"ok":false}'; continue }
            $origin = if ($req.Headers.ContainsKey('origin')) { $req.Headers['origin'] } else { '' }
            if (-not (Test-AllowedOrigin $origin)) { Write-Response $stream 403 '{"ok":false,"error":"origin denied"}'; continue }
            if ($req.TooLarge) { Write-Response $stream 413 '{"ok":false,"error":"payload too large"}' $origin; continue }
            if ($req.Method -eq 'OPTIONS') { Write-Response $stream 204 '' $origin; continue }
            if ($req.Method -eq 'GET' -and $req.Path -eq '/health') {
                Write-Response $stream 200 '{"ok":true,"name":"Chen Foxmail Helper","version":"0.1"}' $origin
                continue
            }
            if ($req.Method -eq 'POST' -and $req.Path -eq '/open') {
                try {
                    $payload = $req.Body | ConvertFrom-Json
                    $fileName = Safe-FileName ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$payload.filename_b64)))
                    $mailBytes = [Convert]::FromBase64String([string]$payload.content_base64)
                    if ($mailBytes.Length -lt 20) { throw 'empty mail payload' }
                    $path = Join-Path $MailDir ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + $fileName)
                    [IO.File]::WriteAllBytes($path, $mailBytes)
                    Start-Process -FilePath $path
                    Write-Response $stream 200 '{"ok":true}' $origin
                } catch {
                    Write-Response $stream 500 '{"ok":false,"error":"open failed"}' $origin
                }
                continue
            }
            Write-Response $stream 404 '{"ok":false,"error":"not found"}' $origin
        } finally {
            try { $client.Close() } catch {}
        }
    }
} finally {
    $listener.Stop()
}
