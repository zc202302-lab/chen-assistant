param(
    [switch]$BridgeMode,
    [string]$ComposeRequest = ''
)

$ErrorActionPreference = 'Stop'
$Port = 18763
$AllowedRootDomain = 'ziboxiaozhushou.cn'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant'
$InstalledScript = Join-Path $InstallDir 'chen_foxmail_helper.ps1'
$MailDir = Join-Path $InstallDir 'FoxmailDrafts'

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

function Safe-EmlName([string]$Name) {
    if (-not $Name) { return 'payment.eml' }
    foreach ($c in [IO.Path]::GetInvalidFileNameChars()) {
        $Name = $Name.Replace([string]$c, '_')
    }
    if (-not $Name.ToLowerInvariant().EndsWith('.eml')) { $Name += '.eml' }
    if ($Name.Length -gt 120) { $Name = $Name.Substring(0, 116) + '.eml' }
    return $Name
}

function Get-FoxmailMapiDll {
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64)) {
        $base = $null
        $key = $null
        try {
            $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
            $key = $base.OpenSubKey('SOFTWARE\Clients\Mail\Foxmail')
            if ($null -ne $key) {
                $value = [string]$key.GetValue('DLLPath', '')
                if ($value) {
                    $value = [Environment]::ExpandEnvironmentVariables($value)
                    if (Test-Path -LiteralPath $value) { return $value }
                }
            }
        } catch {
        } finally {
            if ($null -ne $key) { $key.Close() }
            if ($null -ne $base) { $base.Close() }
        }
    }
    return ''
}

function Get-FoxmailExe {
    foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64)) {
        $base = $null
        $key = $null
        try {
            $base = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, $view)
            $key = $base.OpenSubKey('SOFTWARE\Clients\Mail\Foxmail\shell\open\command')
            if ($null -ne $key) {
                $command = [string]$key.GetValue('', '')
                if ($command) {
                    $match = [regex]::Match($command, '^\s*"([^"]+Foxmail\.exe)"', 'IgnoreCase')
                    if (-not $match.Success) { $match = [regex]::Match($command, '^\s*([^\s]+Foxmail\.exe)', 'IgnoreCase') }
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

    $mapi = Get-FoxmailMapiDll
    if ($mapi) {
        $dir = Split-Path -Parent $mapi
        for ($i = 0; $i -lt 3 -and $dir; $i++) {
            $candidate = Join-Path $dir 'Foxmail.exe'
            if (Test-Path -LiteralPath $candidate) { return $candidate }
            $parent = Split-Path -Parent $dir
            if ($parent -eq $dir) { break }
            $dir = $parent
        }
    }
    return ''
}

function Ensure-WindowTools {
    if ('ChenFoxmailWindowTools' -as [type]) { return }
    Add-Type -ReferencedAssemblies 'System.Windows.Forms' -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public static class ChenFoxmailWindowTools
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

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    public static WindowInfo[] GetFoxmailWindows()
    {
        var foxIds = new HashSet<int>();
        foreach (var p in Process.GetProcessesByName("Foxmail")) foxIds.Add(p.Id);
        var result = new List<WindowInfo>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hWnd)) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (!foxIds.Contains((int)pid)) return true;
            var sb = new StringBuilder(512);
            GetWindowText(hWnd, sb, sb.Capacity);
            result.Add(new WindowInfo { Handle = hWnd.ToInt64(), ProcessId = (int)pid, Title = sb.ToString() });
            return true;
        }, IntPtr.Zero);
        return result.ToArray();
    }
}
'@
}

function Get-FoxmailWindows {
    Ensure-WindowTools
    return @([ChenFoxmailWindowTools]::GetFoxmailWindows())
}

function Build-MailtoUri([string]$Recipient, [string]$Subject, [string]$Body) {
    $recipientPart = [Uri]::EscapeDataString($Recipient)
    $parts = New-Object 'System.Collections.Generic.List[string]'
    if ($Subject) { $parts.Add('subject=' + [Uri]::EscapeDataString($Subject)) }
    if ($Body) {
        $htmlBody = $Body.Replace("`r`n", '<br>').Replace("`n", '<br>').Replace("`r", '<br>')
        $parts.Add('body=' + [Uri]::EscapeDataString($htmlBody))
    }
    $query = if ($parts.Count -gt 0) { '?' + ($parts -join '&') } else { '' }
    return 'mailto:' + $recipientPart + $query
}

function Invoke-FoxmailCompose([string]$RequestPath) {
    $payload = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $recipient = Decode-B64Text ([string]$payload.recipient_b64)
    $subject = Decode-B64Text ([string]$payload.subject_b64)
    $body = Decode-B64Text ([string]$payload.body_b64)
    $attachmentName = Safe-AttachmentName (Decode-B64Text ([string]$payload.attachment_filename_b64))
    $attachmentBytes = [Convert]::FromBase64String([string]$payload.attachment_content_base64)
    if ($attachmentBytes.Length -lt 1) { return 94 }

    $foxmailExe = Get-FoxmailExe
    if (-not $foxmailExe) { return 93 }

    # Use a unique folder for every compose operation, but preserve the exact
    # customer-defined file name inside that folder. Foxmail displays the base
    # file name of the clipboard attachment, so prefixing the file itself would
    # incorrectly leak our temporary timestamp into the visible attachment name.
    New-Item -ItemType Directory -Force -Path $MailDir | Out-Null
    $prefix = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $composeDir = Join-Path $MailDir $prefix
    New-Item -ItemType Directory -Force -Path $composeDir | Out-Null
    $attachmentPath = Join-Path $composeDir $attachmentName
    [IO.File]::WriteAllBytes($attachmentPath, $attachmentBytes)

    $before = @{}
    foreach ($w in (Get-FoxmailWindows)) { $before[[string]$w.Handle] = $true }

    $mailto = Build-MailtoUri $recipient $subject $body
    Start-Process -FilePath $foxmailExe -ArgumentList @($mailto) | Out-Null

    $composeWindow = $null
    $deadline = (Get-Date).AddSeconds(7)
    while ((Get-Date) -lt $deadline -and $null -eq $composeWindow) {
        Start-Sleep -Milliseconds 250
        foreach ($w in (Get-FoxmailWindows)) {
            if (-not $before.ContainsKey([string]$w.Handle)) {
                $composeWindow = $w
                break
            }
        }
    }

    if ($null -eq $composeWindow) { return 91 }

    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $files = New-Object System.Collections.Specialized.StringCollection
        [void]$files.Add($attachmentPath)
        [System.Windows.Forms.Clipboard]::SetFileDropList($files)

        $hwnd = [IntPtr]::new([long]$composeWindow.Handle)
        [void][ChenFoxmailWindowTools]::ShowWindow($hwnd, 9)
        Start-Sleep -Milliseconds 250
        [void][ChenFoxmailWindowTools]::SetForegroundWindow($hwnd)
        Start-Sleep -Milliseconds 350
        [System.Windows.Forms.SendKeys]::SendWait('^v')
        Start-Sleep -Milliseconds 500
        return 0
    } catch {
        return 92
    }
}

function Get-ComposeErrorText([int]$Code) {
    switch ($Code) {
        0 { return 'success' }
        91 { return 'Foxmail compose window was not detected after mailto launch' }
        92 { return 'Foxmail compose window opened but TXT attachment paste failed' }
        93 { return 'Foxmail.exe was not found' }
        94 { return 'TXT attachment payload was empty' }
        95 { return 'compose helper timed out' }
        default { return "Foxmail helper error $Code" }
    }
}

if ($ComposeRequest) {
    try {
        $result = [int](Invoke-FoxmailCompose $ComposeRequest)
        exit $result
    } catch {
        exit 99
    }
}

if (-not $BridgeMode) {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -like '*chen_foxmail_helper.ps1*' -and
            $_.CommandLine -like '*-BridgeMode*'
        } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 350

    Copy-Item -Force $PSCommandPath $InstalledScript

    $Startup = [Environment]::GetFolderPath('Startup')
    $ShortcutPath = Join-Path $Startup 'ChenAssistant-Foxmail-Helper.lnk'
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = 'powershell.exe'
    $Shortcut.Arguments = "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$InstalledScript`" -BridgeMode"
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.Description = 'Chen Assistant Foxmail local helper'
    $Shortcut.Save()

    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', "`"$InstalledScript`"", '-BridgeMode'
    )

    Start-Sleep -Milliseconds 900
    $foxmailExe = Get-FoxmailExe
    Write-Host ''
    Write-Host 'Chen Assistant Foxmail helper installed.' -ForegroundColor Green
    Write-Host "Install directory: $InstallDir"
    Write-Host 'It will start automatically when you sign in to Windows.'
    if ($foxmailExe) {
        Write-Host "Direct Foxmail compose: $foxmailExe" -ForegroundColor Green
    } else {
        Write-Host 'Foxmail.exe was not found.' -ForegroundColor Yellow
    }
    Write-Host 'Compose mode: Foxmail mailto + automatic TXT clipboard attachment'
    Write-Host ''
    Write-Host 'Return to Chen Assistant and refresh the page.'
    Read-Host 'Press Enter to close'
    exit 0
}

New-Item -ItemType Directory -Force -Path $MailDir | Out-Null
$FoxmailExe = Get-FoxmailExe

try {
    $listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $Port)
    $listener.Start()
} catch {
    exit 0
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
        return @{ Method = $parts[0].ToUpperInvariant(); Path = $parts[1]; Headers = $headers; TooLarge = $true; Body = '' }
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
    return @{ Method = $parts[0].ToUpperInvariant(); Path = $parts[1]; Headers = $headers; TooLarge = $false; Body = $body }
}

Get-ChildItem -Path $MailDir -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            if (-not [Net.IPAddress]::IsLoopback($client.Client.RemoteEndPoint.Address)) { continue }
            $stream = $client.GetStream()
            $req = Read-Request $stream
            if ($null -eq $req) { Write-Response $stream 400 (ConvertTo-CompactJson @{ ok = $false }); continue }

            $origin = ''
            if ($req.Headers.ContainsKey('origin')) { $origin = $req.Headers['origin'] }
            if (-not (Test-AllowedOrigin $origin)) { Write-Response $stream 403 (ConvertTo-CompactJson @{ ok = $false; error = 'origin denied' }); continue }
            if ($req.TooLarge) { Write-Response $stream 413 (ConvertTo-CompactJson @{ ok = $false; error = 'payload too large' }) $origin; continue }
            if ($req.Method -eq 'OPTIONS') { Write-Response $stream 204 '' $origin; continue }

            if ($req.Method -eq 'GET' -and $req.Path -eq '/health') {
                Write-Response $stream 200 (ConvertTo-CompactJson @{
                    ok = $true
                    name = 'Chen Foxmail Helper'
                    version = '0.7'
                    compose = $true
                    foxmail_direct = [bool]$FoxmailExe
                    verified_dispatch = $true
                    compose_mode = 'mailto-clipboard'
                    attachment_filename_exact = $true
                }) $origin
                continue
            }

            if ($req.Method -eq 'POST' -and $req.Path -eq '/compose') {
                try {
                    if (-not $FoxmailExe) { throw 'Foxmail.exe was not found' }
                    $payload = $req.Body | ConvertFrom-Json
                    foreach ($name in @('subject_b64', 'attachment_filename_b64', 'attachment_content_base64')) {
                        if (-not $payload.$name) { throw "missing $name" }
                    }
                    $requestFile = Join-Path $MailDir ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-compose.json')
                    [IO.File]::WriteAllText($requestFile, $req.Body, [Text.Encoding]::UTF8)

                    $process = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru -ArgumentList @(
                        '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', "`"$InstalledScript`"",
                        '-ComposeRequest', "`"$requestFile`""
                    )
                    if (-not $process.WaitForExit(10000)) {
                        try { $process.Kill() } catch {}
                        $code = 95
                    } else {
                        $code = [int]$process.ExitCode
                    }

                    if ($code -eq 0) {
                        Write-Response $stream 200 (ConvertTo-CompactJson @{
                            ok = $true
                            verified = $true
                            mode = 'foxmail-mailto-clipboard'
                            state = 'compose-opened-and-attachment-pasted'
                            attachment_filename_exact = $true
                        }) $origin
                    } else {
                        Write-Response $stream 500 (ConvertTo-CompactJson @{
                            ok = $false
                            error = (Get-ComposeErrorText $code)
                            code = $code
                        }) $origin
                    }
                } catch {
                    Write-Response $stream 500 (ConvertTo-CompactJson @{ ok = $false; error = $_.Exception.Message }) $origin
                }
                continue
            }

            if ($req.Method -eq 'POST' -and $req.Path -eq '/open') {
                try {
                    $payload = $req.Body | ConvertFrom-Json
                    $fileName = Safe-EmlName (Decode-B64Text ([string]$payload.filename_b64))
                    $mailBytes = [Convert]::FromBase64String([string]$payload.content_base64)
                    if ($mailBytes.Length -lt 20) { throw 'empty mail payload' }
                    $path = Join-Path $MailDir ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + $fileName)
                    [IO.File]::WriteAllBytes($path, $mailBytes)
                    Start-Process -FilePath $path
                    Write-Response $stream 200 (ConvertTo-CompactJson @{ ok = $true; mode = 'eml' }) $origin
                } catch {
                    Write-Response $stream 500 (ConvertTo-CompactJson @{ ok = $false; error = $_.Exception.Message }) $origin
                }
                continue
            }

            Write-Response $stream 404 (ConvertTo-CompactJson @{ ok = $false; error = 'not found' }) $origin
        } finally {
            try { $client.Close() } catch {}
        }
    }
} finally {
    $listener.Stop()
}