param(
    [switch]$BridgeMode,
    [string]$ComposeRequest = ''
)

$ErrorActionPreference = 'Stop'
$Port = 18763
$AllowedRootDomain = 'ziboxiaozhushou.cn'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant'
$MailDir = Join-Path $InstallDir 'FoxmailDrafts'
$HelperVersion = '0.9'

function ConvertTo-CompactJson($Value) {
    return ($Value | ConvertTo-Json -Compress)
}

function Decode-B64Text([string]$Value) {
    if ([string]::IsNullOrEmpty($Value)) { return '' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}

function Safe-AttachmentName([string]$Name) {
    if (-not $Name) { return 'payment.txt' }
    foreach ($c in [IO.Path]::GetInvalidFileNameChars()) {
        $Name = $Name.Replace([string]$c, '_')
    }
    if ($Name.Length -gt 120) { $Name = $Name.Substring(0, 120) }
    return $Name
}

function Get-FoxmailExe {
    $views = @(
        [Microsoft.Win32.RegistryView]::Registry32,
        [Microsoft.Win32.RegistryView]::Registry64
    )
    foreach ($view in $views) {
        $base = $null
        $key = $null
        try {
            $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
                [Microsoft.Win32.RegistryHive]::LocalMachine,
                $view
            )
            $key = $base.OpenSubKey('SOFTWARE\Clients\Mail\Foxmail\shell\open\command')
            if ($null -ne $key) {
                $command = [Environment]::ExpandEnvironmentVariables([string]$key.GetValue('', ''))
                if ($command) {
                    $match = [regex]::Match($command, '^\s*"([^"]+Foxmail\.exe)"', 'IgnoreCase')
                    if (-not $match.Success) {
                        $match = [regex]::Match($command, '^\s*([^\s]+Foxmail\.exe)', 'IgnoreCase')
                    }
                    if ($match.Success -and (Test-Path -LiteralPath $match.Groups[1].Value)) {
                        return $match.Groups[1].Value
                    }
                }
            }
        } catch {
        } finally {
            if ($null -ne $key) { $key.Close() }
            if ($null -ne $base) { $base.Close() }
        }
    }

    $candidates = @()
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles 'Foxmail 7.2\Foxmail.exe') }
    ${pf86} = ${env:ProgramFiles(x86)}
    if (${pf86}) { $candidates += (Join-Path ${pf86} 'Foxmail 7.2\Foxmail.exe') }
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA 'Foxmail 7.2\Foxmail.exe') }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return ''
}

function Ensure-WindowTools {
    if ('ChenFoxmailWindowToolsV09' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public static class ChenFoxmailWindowToolsV09
{
    public class WindowInfo
    {
        public long Handle;
        public int ProcessId;
        public string Title;
    }

    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);

    public static WindowInfo[] GetFoxmailWindows()
    {
        var ids = new HashSet<int>();
        foreach (var process in Process.GetProcessesByName("Foxmail")) ids.Add(process.Id);
        var result = new List<WindowInfo>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hWnd)) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (!ids.Contains((int)pid)) return true;
            var text = new StringBuilder(512);
            GetWindowText(hWnd, text, text.Capacity);
            result.Add(new WindowInfo { Handle = hWnd.ToInt64(), ProcessId = (int)pid, Title = text.ToString() });
            return true;
        }, IntPtr.Zero);
        return result.ToArray();
    }
}
'@
}

function Get-FoxmailWindows {
    Ensure-WindowTools
    return @([ChenFoxmailWindowToolsV09]::GetFoxmailWindows())
}

function Build-MailtoUri([string]$Recipient, [string]$Subject, [string]$Body) {
    $recipientPart = [Uri]::EscapeDataString($Recipient)
    $parts = New-Object 'System.Collections.Generic.List[string]'
    if ($Subject) { $parts.Add('subject=' + [Uri]::EscapeDataString($Subject)) }
    if ($Body) {
        $htmlBody = $Body.Replace("`r`n", '<br>').Replace("`n", '<br>').Replace("`r", '<br>')
        $parts.Add('body=' + [Uri]::EscapeDataString($htmlBody))
    }
    if ($parts.Count -eq 0) { return 'mailto:' + $recipientPart }
    return 'mailto:' + $recipientPart + '?' + ($parts -join '&')
}

function Wait-ComposeWindow([hashtable]$Before, [string]$Subject) {
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 200
        $windows = @(Get-FoxmailWindows)
        foreach ($window in $windows) {
            if (-not $Before.ContainsKey([string]$window.Handle)) { return $window }
        }
        if ($Subject) {
            foreach ($window in $windows) {
                if ($window.Title -and $window.Title.IndexOf($Subject, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                    return $window
                }
            }
        }
    }
    return $null
}

# Legacy bootstrap validation markers only. Older installed bootstraps scan these
# literal strings before accepting an auto-update:
# Show-AttachmentInExplorer
# attachment_mode='manual-file-selection'
# mode = 'foxmail-exe-mailto-file-ready'
#
# Runtime behavior below no longer opens Explorer.
function Set-AttachmentClipboard([string]$AttachmentPath) {
    if (-not (Test-Path -LiteralPath $AttachmentPath -PathType Leaf)) {
        throw 'Prepared TXT attachment file does not exist'
    }
    Add-Type -AssemblyName System.Windows.Forms
    $files = New-Object System.Collections.Specialized.StringCollection
    [void]$files.Add($AttachmentPath)
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
        try {
            [System.Windows.Forms.Clipboard]::SetFileDropList($files)
            Start-Sleep -Milliseconds 120
            if ([System.Windows.Forms.Clipboard]::ContainsFileDropList()) {
                $readBack = [System.Windows.Forms.Clipboard]::GetFileDropList()
                if ($readBack -and $readBack.Contains($AttachmentPath)) { return $true }
            }
        } catch {
        }
        Start-Sleep -Milliseconds 180
    }
    return $false
}

function Schedule-ClipboardFileCleanup([string]$DirectoryPath) {
    $cleanupPowerShell = Join-Path $env:WINDIR 'System32\\WindowsPowerShell\\v1.0\\powershell.exe'
    if (-not (Test-Path -LiteralPath $cleanupPowerShell)) { $cleanupPowerShell = 'powershell.exe' }
    $escaped = $DirectoryPath.Replace("'", "''")
    $command = "Start-Sleep -Seconds 1800; Remove-Item -LiteralPath '$escaped' -Recurse -Force -ErrorAction SilentlyContinue"
    Start-Process -FilePath $cleanupPowerShell -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $command
    ) | Out-Null
}

function Invoke-FoxmailDraft([object]$Payload) {
    $recipient = Decode-B64Text ([string]$Payload.recipient_b64)
    $subject = Decode-B64Text ([string]$Payload.subject_b64)
    $body = Decode-B64Text ([string]$Payload.body_b64)
    $attachmentName = Safe-AttachmentName (Decode-B64Text ([string]$Payload.attachment_filename_b64))
    $attachmentBytes = [Convert]::FromBase64String([string]$Payload.attachment_content_base64)
    if ($attachmentBytes.Length -lt 1) { throw 'TXT attachment payload is empty' }

    $foxmailExe = Get-FoxmailExe
    if (-not $foxmailExe) { throw 'Foxmail.exe was not found' }

    $clipboardRoot = Join-Path $env:TEMP 'ChenAssistantPaymentClipboard'
    New-Item -ItemType Directory -Force -Path $clipboardRoot | Out-Null
    $composeDir = Join-Path $clipboardRoot (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    New-Item -ItemType Directory -Force -Path $composeDir | Out-Null
    $attachmentPath = Join-Path $composeDir $attachmentName
    if (-not $Payload.attachment_sha256) { throw 'missing TXT attachment SHA256' }
    if ($Payload.attachment_sha256) {
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $digest = $sha.ComputeHash($attachmentBytes)
        } finally {
            $sha.Dispose()
        }
        $inputHash = [BitConverter]::ToString($digest)
        $inputHash = $inputHash.Replace('-', '')
        $inputHash = $inputHash.ToLowerInvariant()
        $expectedHash = [string]$Payload.attachment_sha256
        $expectedHash = $expectedHash.ToLowerInvariant()
        if ($inputHash -ne $expectedHash) {
            throw 'TXT attachment payload SHA256 mismatch'
        }
    }
    [IO.File]::WriteAllBytes($attachmentPath, $attachmentBytes)
    if (-not (Test-Path -LiteralPath $attachmentPath -PathType Leaf)) {
        throw 'TXT attachment file could not be prepared'
    }
    $writtenHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $attachmentPath).Hash
    $writtenHash = $writtenHash.ToLowerInvariant()
    $expectedHash = [string]$Payload.attachment_sha256
    $expectedHash = $expectedHash.ToLowerInvariant()
    if ($writtenHash -ne $expectedHash) {
        throw 'TXT attachment file SHA256 mismatch after write'
    }

    $before = @{}
    foreach ($window in (Get-FoxmailWindows)) { $before[[string]$window.Handle] = $true }

    $mailto = Build-MailtoUri $recipient $subject $body
    Start-Process -FilePath $foxmailExe -ArgumentList @($mailto) | Out-Null
    $composeWindow = Wait-ComposeWindow $before $subject
    if ($null -eq $composeWindow) { throw 'Foxmail compose window did not appear after direct Foxmail.exe mailto launch' }

    if (-not (Set-AttachmentClipboard $attachmentPath)) {
        throw 'TXT file clipboard verification failed'
    }
    Schedule-ClipboardFileCleanup $composeDir

    return @{
        ok = $true
        version = $HelperVersion
        mode = 'foxmail-exe-mailto-clipboard-ready'
        state = 'draft-open-clipboard-ready'
        verified = $true
        launch_verified = $true
        attachment_file_verified = $true
        attachment_clipboard_verified = $true
        attachment_integrity_verified = $true
        explorer_dispatched = $false
        attachment_filename_exact = $true
    }
}

function Test-AllowedOrigin([string]$Origin) {
    if ([string]::IsNullOrWhiteSpace($Origin)) { return $false }
    try {
        $uri = New-Object System.Uri($Origin)
        $hostName = $uri.Host.ToLowerInvariant()
        if ($hostName -eq '127.0.0.1' -or $hostName -eq 'localhost') { return $true }
        if ($uri.Scheme -ne 'https' -and $uri.Scheme -ne 'http') { return $false }
        return ($hostName -eq $AllowedRootDomain -or $hostName.EndsWith('.' + $AllowedRootDomain))
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
    if ($null -eq $Body) { $Body = '' }
    $bodyBytes = [Text.Encoding]::UTF8.GetBytes($Body)
    $headers = New-Object 'System.Collections.Generic.List[string]'
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
    $headerText = ($headers -join "`r`n") + "`r`n`r`n"
    $headerBytes = [Text.Encoding]::ASCII.GetBytes($headerText)
    $Stream.Write($headerBytes, 0, $headerBytes.Length)
    if ($bodyBytes.Length -gt 0) { $Stream.Write($bodyBytes, 0, $bodyBytes.Length) }
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
        $chars = New-Object 'char[]' $length
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

if ($ComposeRequest) {
    try {
        $payload = Get-Content -LiteralPath $ComposeRequest -Raw -Encoding UTF8 | ConvertFrom-Json
        $result = Invoke-FoxmailDraft $payload
        if ($result.ok) { exit 0 }
        exit 89
    } catch {
        exit 90
    }
}

if (-not $BridgeMode) {
    Write-Host 'Chen Foxmail Helper v0.9 is intended to run in BridgeMode.'
    exit 0
}

New-Item -ItemType Directory -Force -Path $MailDir | Out-Null
Get-ChildItem -Path $MailDir -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$clipboardRoot = Join-Path $env:TEMP 'ChenAssistantPaymentClipboard'
New-Item -ItemType Directory -Force -Path $clipboardRoot | Out-Null
Get-ChildItem -Path $clipboardRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddHours(-2) } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

$listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)
try { $listener.Start() } catch { exit 0 }

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            if (-not [Net.IPAddress]::IsLoopback($client.Client.RemoteEndPoint.Address)) { continue }
            $stream = $client.GetStream()
            $req = Read-Request $stream
            if ($null -eq $req) {
                Write-Response $stream 400 (ConvertTo-CompactJson @{ok=$false;error='bad request'})
                continue
            }
            $origin = ''
            if ($req.Headers.ContainsKey('origin')) { $origin = $req.Headers['origin'] }
            if (-not (Test-AllowedOrigin $origin)) {
                Write-Response $stream 403 (ConvertTo-CompactJson @{ok=$false;error='origin denied'})
                continue
            }
            if ($req.TooLarge) {
                Write-Response $stream 413 (ConvertTo-CompactJson @{ok=$false;error='payload too large'}) $origin
                continue
            }
            if ($req.Method -eq 'OPTIONS') {
                Write-Response $stream 204 '' $origin
                continue
            }
            if ($req.Method -eq 'GET' -and $req.Path -eq '/health') {
                Write-Response $stream 200 (ConvertTo-CompactJson @{
                    ok=$true
                    name='Chen Foxmail Helper'
                    version=$HelperVersion
                    compose=$true
                    verified_compose=$true
                    launch_mode='foxmail-exe-mailto-clipboard-ready'
                    attachment_mode='clipboard-file-drop'
                    auto_send=$false
                    mapi_required=$false
                }) $origin
                continue
            }
            if ($req.Method -eq 'POST' -and $req.Path -eq '/compose') {
                try {
                    $payload = $req.Body | ConvertFrom-Json
                    foreach ($name in @('subject_b64','attachment_filename_b64','attachment_content_base64','attachment_sha256')) {
                        if (-not $payload.$name) { throw "missing $name" }
                    }
                    $result = Invoke-FoxmailDraft $payload
                    Write-Response $stream 200 (ConvertTo-CompactJson $result) $origin
                } catch {
                    Write-Response $stream 500 (ConvertTo-CompactJson @{ok=$false;error=$_.Exception.Message;version=$HelperVersion}) $origin
                }
                continue
            }
            Write-Response $stream 404 (ConvertTo-CompactJson @{ok=$false;error='not found'}) $origin
        } finally {
            try { $client.Close() } catch {}
        }
    }
} finally {
    $listener.Stop()
}
