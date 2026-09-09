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

function Get-MapiErrorText([int]$Code) {
    switch ($Code) {
        0 { return 'success' }
        1 { return 'user aborted' }
        2 { return 'general MAPI failure' }
        3 { return 'MAPI logon failed' }
        4 { return 'disk full' }
        5 { return 'insufficient memory' }
        6 { return 'access denied' }
        8 { return 'too many sessions' }
        9 { return 'too many files' }
        10 { return 'too many recipients' }
        11 { return 'attachment not found' }
        12 { return 'attachment could not be opened' }
        13 { return 'unknown recipient' }
        14 { return 'bad recipient type' }
        17 { return 'message text too large' }
        18 { return 'invalid session' }
        19 { return 'message type not supported' }
        20 { return 'ambiguous recipient' }
        22 { return 'network failure' }
        24 { return 'invalid recipients' }
        25 { return 'MAPI operation not supported' }
        90 { return 'helper exception' }
        default { return "MAPI error $Code" }
    }
}

function Ensure-WindowProbeType {
    if ('ChenFoxmailWindowProbe' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class ChenFoxmailWindowProbe
{
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    public static int CountVisibleForPids(int[] processIds)
    {
        if (processIds == null || processIds.Length == 0) return 0;
        var ids = new HashSet<int>(processIds);
        int count = 0;
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam)
        {
            if (!IsWindowVisible(hWnd)) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (ids.Contains((int)pid)) count++;
            return true;
        }, IntPtr.Zero);
        return count;
    }
}
'@
}

function Get-FoxmailVisibleWindowCount {
    Ensure-WindowProbeType
    $ids = @(Get-Process -Name Foxmail -ErrorAction SilentlyContinue | ForEach-Object { [int]$_.Id })
    if ($ids.Count -eq 0) { return 0 }
    return [ChenFoxmailWindowProbe]::CountVisibleForPids([int[]]$ids)
}

function Invoke-FoxmailCompose([string]$RequestPath) {
    $payload = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $recipient = Decode-B64Text ([string]$payload.recipient_b64)
    $subject = Decode-B64Text ([string]$payload.subject_b64)
    $body = Decode-B64Text ([string]$payload.body_b64)
    $attachmentName = Safe-AttachmentName (Decode-B64Text ([string]$payload.attachment_filename_b64))
    $attachmentBytes = [Convert]::FromBase64String([string]$payload.attachment_content_base64)
    if ($attachmentBytes.Length -lt 1) { throw 'empty attachment payload' }

    New-Item -ItemType Directory -Force -Path $MailDir | Out-Null
    $prefix = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $attachmentPath = Join-Path $MailDir ($prefix + '-' + $attachmentName)
    [IO.File]::WriteAllBytes($attachmentPath, $attachmentBytes)

    $foxmailDll = Get-FoxmailMapiDll
    if (-not $foxmailDll) { throw 'Foxmail MAPI DLL not found' }

    if (-not ('ChenFoxmailMapi' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;

public static class ChenFoxmailMapi
{
    private const int MAPI_LOGON_UI = 0x00000001;
    private const int MAPI_NEW_SESSION = 0x00000002;
    private const int MAPI_DIALOG = 0x00000008;
    private const int MAPI_TO = 1;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    private struct MapiMessage
    {
        public uint reserved;
        [MarshalAs(UnmanagedType.LPStr)] public string subject;
        [MarshalAs(UnmanagedType.LPStr)] public string noteText;
        [MarshalAs(UnmanagedType.LPStr)] public string messageType;
        [MarshalAs(UnmanagedType.LPStr)] public string dateReceived;
        [MarshalAs(UnmanagedType.LPStr)] public string conversationID;
        public uint flags;
        public IntPtr originator;
        public uint recipCount;
        public IntPtr recips;
        public uint fileCount;
        public IntPtr files;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    private struct MapiRecipDesc
    {
        public uint reserved;
        public uint recipClass;
        [MarshalAs(UnmanagedType.LPStr)] public string name;
        [MarshalAs(UnmanagedType.LPStr)] public string address;
        public uint eIDSize;
        public IntPtr entryID;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
    private struct MapiFileDesc
    {
        public uint reserved;
        public uint flags;
        public uint position;
        [MarshalAs(UnmanagedType.LPStr)] public string pathName;
        [MarshalAs(UnmanagedType.LPStr)] public string fileName;
        public IntPtr fileType;
    }

    [UnmanagedFunctionPointer(CallingConvention.StdCall, CharSet = CharSet.Ansi)]
    private delegate int MapiSendMailDelegate(
        IntPtr session,
        IntPtr uiParam,
        ref MapiMessage message,
        int flags,
        int reserved
    );

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibrary(string fileName);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)]
    private static extern IntPtr GetProcAddress(IntPtr module, string procName);

    [DllImport("kernel32.dll")]
    private static extern bool FreeLibrary(IntPtr module);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern bool SetDllDirectory(string pathName);

    public static int Compose(
        string mapiDllPath,
        string recipient,
        string subject,
        string body,
        string attachmentPath,
        string attachmentName)
    {
        IntPtr module = IntPtr.Zero;
        IntPtr recipPtr = IntPtr.Zero;
        IntPtr filePtr = IntPtr.Zero;
        try
        {
            if (string.IsNullOrWhiteSpace(mapiDllPath) || !File.Exists(mapiDllPath))
                throw new InvalidOperationException("Foxmail MAPI DLL is missing.");

            var dllDir = Path.GetDirectoryName(mapiDllPath);
            if (!string.IsNullOrWhiteSpace(dllDir)) SetDllDirectory(dllDir);
            module = LoadLibrary(mapiDllPath);
            if (module == IntPtr.Zero)
                throw new InvalidOperationException("Cannot load Foxmail MAPI DLL. Win32=" + Marshal.GetLastWin32Error());

            IntPtr proc = GetProcAddress(module, "MAPISendMail");
            if (proc == IntPtr.Zero) proc = GetProcAddress(module, "MAPISendMail@20");
            if (proc == IntPtr.Zero)
                throw new InvalidOperationException("Foxmail MAPISendMail export was not found.");

            var send = (MapiSendMailDelegate)Marshal.GetDelegateForFunctionPointer(
                proc,
                typeof(MapiSendMailDelegate)
            );

            var msg = new MapiMessage
            {
                subject = subject ?? string.Empty,
                noteText = body ?? string.Empty,
                recipCount = 0,
                recips = IntPtr.Zero,
                fileCount = 0,
                files = IntPtr.Zero
            };

            if (!string.IsNullOrWhiteSpace(recipient))
            {
                var recip = new MapiRecipDesc
                {
                    recipClass = MAPI_TO,
                    name = recipient,
                    address = recipient.IndexOf(':') >= 0 ? recipient : "SMTP:" + recipient
                };
                recipPtr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(MapiRecipDesc)));
                Marshal.StructureToPtr(recip, recipPtr, false);
                msg.recipCount = 1;
                msg.recips = recipPtr;
            }

            if (!string.IsNullOrWhiteSpace(attachmentPath) && File.Exists(attachmentPath))
            {
                var file = new MapiFileDesc
                {
                    position = unchecked((uint)-1),
                    pathName = attachmentPath,
                    fileName = attachmentName
                };
                filePtr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(MapiFileDesc)));
                Marshal.StructureToPtr(file, filePtr, false);
                msg.fileCount = 1;
                msg.files = filePtr;
            }

            int flags = MAPI_LOGON_UI | MAPI_NEW_SESSION | MAPI_DIALOG;
            return send(IntPtr.Zero, IntPtr.Zero, ref msg, flags, 0);
        }
        finally
        {
            if (recipPtr != IntPtr.Zero)
            {
                Marshal.DestroyStructure(recipPtr, typeof(MapiRecipDesc));
                Marshal.FreeHGlobal(recipPtr);
            }
            if (filePtr != IntPtr.Zero)
            {
                Marshal.DestroyStructure(filePtr, typeof(MapiFileDesc));
                Marshal.FreeHGlobal(filePtr);
            }
            if (module != IntPtr.Zero) FreeLibrary(module);
            SetDllDirectory(null);
        }
    }
}
'@
    }

    return [ChenFoxmailMapi]::Compose(
        $foxmailDll,
        $recipient,
        $subject,
        $body,
        $attachmentPath,
        $attachmentName
    )
}

if ($ComposeRequest) {
    try {
        $result = [int](Invoke-FoxmailCompose $ComposeRequest)
        if ($result -eq 0) { exit 0 }
        if ($result -lt 1 -or $result -gt 89) { exit 89 }
        exit $result
    } catch {
        exit 90
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
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Milliseconds 350

    Copy-Item -Force $PSCommandPath $InstalledScript

    $Startup = [Environment]::GetFolderPath('Startup')
    $ShortcutPath = Join-Path $Startup 'ChenAssistant-Foxmail-Helper.lnk'
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = 'powershell.exe'
    $Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$InstalledScript`" -BridgeMode"
    $Shortcut.WorkingDirectory = $InstallDir
    $Shortcut.Description = 'Chen Assistant Foxmail local helper'
    $Shortcut.Save()

    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$InstalledScript`"", '-BridgeMode'
    )

    Start-Sleep -Milliseconds 900
    $foxmailDll = Get-FoxmailMapiDll
    Write-Host ''
    Write-Host 'Chen Assistant Foxmail helper installed.' -ForegroundColor Green
    Write-Host "Install directory: $InstallDir"
    Write-Host 'It will start automatically when you sign in to Windows.'
    if ($foxmailDll) {
        Write-Host "Direct Foxmail MAPI: $foxmailDll" -ForegroundColor Green
    } else {
        Write-Host 'Direct Foxmail MAPI was not found.' -ForegroundColor Yellow
    }
    Write-Host 'Compose dispatch verification: enabled'
    Write-Host ''
    Write-Host 'Return to Chen Assistant and refresh the page.'
    Read-Host 'Press Enter to close'
    exit 0
}

New-Item -ItemType Directory -Force -Path $MailDir | Out-Null
$FoxmailMapiDll = Get-FoxmailMapiDll

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
    if ($bodyBytes.Length -gt 0) {
        $Stream.Write($bodyBytes, 0, $bodyBytes.Length)
    }
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
            $key = $line.Substring(0, $colon).Trim().ToLowerInvariant()
            $value = $line.Substring($colon + 1).Trim()
            $headers[$key] = $value
        }
    }

    $length = 0
    if ($headers.ContainsKey('content-length')) {
        [void][int]::TryParse($headers['content-length'], [ref]$length)
    }

    if ($length -gt 12000000) {
        return @{
            Method = $parts[0].ToUpperInvariant()
            Path = $parts[1]
            Headers = $headers
            TooLarge = $true
            Body = ''
        }
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

    return @{
        Method = $parts[0].ToUpperInvariant()
        Path = $parts[1]
        Headers = $headers
        TooLarge = $false
        Body = $body
    }
}

Get-ChildItem -Path $MailDir -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            if (-not [Net.IPAddress]::IsLoopback($client.Client.RemoteEndPoint.Address)) { continue }

            $stream = $client.GetStream()
            $req = Read-Request $stream
            if ($null -eq $req) {
                Write-Response $stream 400 (ConvertTo-CompactJson @{ ok = $false })
                continue
            }

            $origin = ''
            if ($req.Headers.ContainsKey('origin')) { $origin = $req.Headers['origin'] }

            if (-not (Test-AllowedOrigin $origin)) {
                Write-Response $stream 403 (ConvertTo-CompactJson @{ ok = $false; error = 'origin denied' })
                continue
            }

            if ($req.TooLarge) {
                Write-Response $stream 413 (ConvertTo-CompactJson @{ ok = $false; error = 'payload too large' }) $origin
                continue
            }

            if ($req.Method -eq 'OPTIONS') {
                Write-Response $stream 204 '' $origin
                continue
            }

            if ($req.Method -eq 'GET' -and $req.Path -eq '/health') {
                Write-Response $stream 200 (ConvertTo-CompactJson @{
                    ok = $true
                    name = 'Chen Foxmail Helper'
                    version = '0.5'
                    compose = $true
                    foxmail_direct = [bool]$FoxmailMapiDll
                    verified_dispatch = $true
                }) $origin
                continue
            }

            if ($req.Method -eq 'POST' -and $req.Path -eq '/compose') {
                try {
                    if (-not $FoxmailMapiDll) { throw 'Foxmail MAPI DLL not found' }
                    $payload = $req.Body | ConvertFrom-Json
                    foreach ($name in @('subject_b64', 'attachment_filename_b64', 'attachment_content_base64')) {
                        if (-not $payload.$name) { throw "missing $name" }
                    }

                    $requestFile = Join-Path $MailDir ((Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-compose.json')
                    [IO.File]::WriteAllText($requestFile, $req.Body, [Text.Encoding]::UTF8)
                    $beforeWindows = Get-FoxmailVisibleWindowCount

                    $composePowerShell = Join-Path $env:WINDIR 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
                    if (-not (Test-Path $composePowerShell)) { $composePowerShell = 'powershell.exe' }
                    $process = Start-Process -FilePath $composePowerShell -WindowStyle Hidden -PassThru -ArgumentList @(
                        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$InstalledScript`"",
                        '-ComposeRequest', "`"$requestFile`""
                    )

                    $exitedQuickly = $process.WaitForExit(1800)
                    if (-not $exitedQuickly) {
                        Write-Response $stream 200 (ConvertTo-CompactJson @{
                            ok = $true
                            mode = 'foxmail-direct-mapi'
                            verified = $true
                            state = 'dialog-active'
                        }) $origin
                        continue
                    }

                    $exitCode = [int]$process.ExitCode
                    if ($exitCode -ne 0) {
                        $errorText = Get-MapiErrorText $exitCode
                        Write-Response $stream 500 (ConvertTo-CompactJson @{
                            ok = $false
                            error = "Foxmail MAPI failed: $errorText (code $exitCode)"
                            code = $exitCode
                        }) $origin
                        continue
                    }

                    Start-Sleep -Milliseconds 700
                    $afterWindows = Get-FoxmailVisibleWindowCount
                    if ($afterWindows -gt $beforeWindows) {
                        Write-Response $stream 200 (ConvertTo-CompactJson @{
                            ok = $true
                            mode = 'foxmail-direct-mapi'
                            verified = $true
                            state = 'new-window-detected'
                        }) $origin
                    } else {
                        Write-Response $stream 500 (ConvertTo-CompactJson @{
                            ok = $false
                            error = 'Foxmail MAPI returned success but no compose window was detected'
                            code = 0
                        }) $origin
                    }
                } catch {
                    Write-Response $stream 500 (ConvertTo-CompactJson @{
                        ok = $false
                        error = $_.Exception.Message
                    }) $origin
                }
                continue
            }

            if ($req.Method -eq 'POST' -and $req.Path -eq '/open') {
                try {
                    $payload = $req.Body | ConvertFrom-Json
                    $decodedName = Decode-B64Text ([string]$payload.filename_b64)
                    $fileName = Safe-EmlName $decodedName
                    $mailBytes = [Convert]::FromBase64String([string]$payload.content_base64)
                    if ($mailBytes.Length -lt 20) { throw 'empty mail payload' }

                    $prefix = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
                    $path = Join-Path $MailDir ($prefix + '-' + $fileName)
                    [IO.File]::WriteAllBytes($path, $mailBytes)
                    Start-Process -FilePath $path
                    Write-Response $stream 200 (ConvertTo-CompactJson @{ ok = $true; mode = 'eml' }) $origin
                } catch {
                    Write-Response $stream 500 (ConvertTo-CompactJson @{
                        ok = $false
                        error = $_.Exception.Message
                    }) $origin
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
