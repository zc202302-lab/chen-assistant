param(
    [switch]$BridgeMode,
    [string]$ComposeRequest = ''
)

$ErrorActionPreference = 'Stop'
$Port = 18763
$AllowedRootDomain = 'ziboxiaozhushou.cn'
$InstallDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant'
$MailDir = Join-Path $InstallDir 'FoxmailDrafts'

function ConvertTo-CompactJson($Value) { return ($Value | ConvertTo-Json -Compress) }
function Decode-B64Text([string]$Value) {
    if ([string]::IsNullOrEmpty($Value)) { return '' }
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}
function Safe-AttachmentName([string]$Name) {
    if (-not $Name) { return 'payment.txt' }
    foreach ($c in [IO.Path]::GetInvalidFileNameChars()) { $Name = $Name.Replace([string]$c, '_') }
    if ($Name.Length -gt 120) { $Name = $Name.Substring(0, 120) }
    return $Name
}
function Safe-EmlName([string]$Name) {
    if (-not $Name) { return 'payment.eml' }
    foreach ($c in [IO.Path]::GetInvalidFileNameChars()) { $Name = $Name.Replace([string]$c, '_') }
    if (-not $Name.ToLowerInvariant().EndsWith('.eml')) { $Name += '.eml' }
    return $Name
}

function Get-FoxmailClientInfo {
    $views = @([Microsoft.Win32.RegistryView]::Registry32,[Microsoft.Win32.RegistryView]::Registry64)
    foreach ($view in $views) {
        $base=$null; $key=$null
        try {
            $base=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,$view)
            $key=$base.OpenSubKey('SOFTWARE\Clients\Mail\Foxmail')
            if ($null -ne $key) {
                $dll=[Environment]::ExpandEnvironmentVariables([string]$key.GetValue('DLLPath',''))
                if ($dll -and (Test-Path -LiteralPath $dll)) {
                    $dir=Split-Path -Parent $dll
                    $exe=Join-Path $dir 'Foxmail.exe'
                    if (-not (Test-Path -LiteralPath $exe)) { $exe='' }
                    return @{ Dll=$dll; Exe=$exe }
                }
            }
        } catch {} finally { if($key){$key.Close()}; if($base){$base.Close()} }
    }
    return @{ Dll=''; Exe='' }
}

function Ensure-FoxmailRunning([string]$ExePath) {
    $p=Get-Process -Name Foxmail -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $p -and $ExePath) {
        Start-Process -FilePath $ExePath | Out-Null
        for($i=0;$i -lt 40;$i++) {
            Start-Sleep -Milliseconds 150
            $p=Get-Process -Name Foxmail -ErrorAction SilentlyContinue | Select-Object -First 1
            if($p){break}
        }
    }
    if (-not $p) { throw 'Foxmail process is not running' }
    for($i=0;$i -lt 30;$i++) {
        $p.Refresh()
        if($p.MainWindowHandle -ne 0){ break }
        Start-Sleep -Milliseconds 150
    }
    return $p
}

function Ensure-WindowProbeType {
    if ('ChenFoxmailWindowProbeV06' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public static class ChenFoxmailWindowProbeV06 {
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);
    public static string[] Snapshot(int[] processIds) {
        var ids=new HashSet<int>(processIds ?? new int[0]); var result=new List<string>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lp) {
            if(!IsWindowVisible(hWnd)) return true; uint pid; GetWindowThreadProcessId(hWnd,out pid);
            if(!ids.Contains((int)pid)) return true; var sb=new StringBuilder(512); GetWindowText(hWnd,sb,sb.Capacity);
            result.Add(hWnd.ToInt64().ToString()+"|"+sb.ToString()); return true;
        },IntPtr.Zero); return result.ToArray();
    }
}
'@
}
function Get-FoxmailWindowSnapshot {
    Ensure-WindowProbeType
    $ids=@(Get-Process -Name Foxmail -ErrorAction SilentlyContinue | ForEach-Object {[int]$_.Id})
    if($ids.Count -eq 0){ return @() }
    return @([ChenFoxmailWindowProbeV06]::Snapshot([int[]]$ids))
}
function Wait-NewFoxmailWindow([string[]]$Before,[int]$TimeoutMs=6000) {
    $known=@{}; foreach($x in $Before){$known[$x.Split('|')[0]]=$true}
    $loops=[Math]::Max(1,[int]($TimeoutMs/200))
    for($i=0;$i -lt $loops;$i++) {
        Start-Sleep -Milliseconds 200
        foreach($x in (Get-FoxmailWindowSnapshot)) {
            $id=$x.Split('|')[0]
            if(-not $known.ContainsKey($id)){ return $x }
        }
    }
    return ''
}

function Ensure-MapiType {
    if ('ChenFoxmailMapiV06' -as [type]) { return }
    Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
public static class ChenFoxmailMapiV06 {
    private const int MAPI_LOGON_UI=0x1, MAPI_DIALOG=0x8, MAPI_TO=1;
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Ansi)] private struct MapiMessage { public uint reserved; [MarshalAs(UnmanagedType.LPStr)] public string subject; [MarshalAs(UnmanagedType.LPStr)] public string noteText; [MarshalAs(UnmanagedType.LPStr)] public string messageType; [MarshalAs(UnmanagedType.LPStr)] public string dateReceived; [MarshalAs(UnmanagedType.LPStr)] public string conversationID; public uint flags; public IntPtr originator; public uint recipCount; public IntPtr recips; public uint fileCount; public IntPtr files; }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Ansi)] private struct MapiRecipDesc { public uint reserved; public uint recipClass; [MarshalAs(UnmanagedType.LPStr)] public string name; [MarshalAs(UnmanagedType.LPStr)] public string address; public uint eIDSize; public IntPtr entryID; }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Ansi)] private struct MapiFileDesc { public uint reserved; public uint flags; public uint position; [MarshalAs(UnmanagedType.LPStr)] public string pathName; [MarshalAs(UnmanagedType.LPStr)] public string fileName; public IntPtr fileType; }
    [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Ansi)] private delegate int SendDelegate(IntPtr session,IntPtr uiParam,ref MapiMessage message,int flags,int reserved);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] private static extern IntPtr LoadLibrary(string f);
    [DllImport("kernel32.dll",CharSet=CharSet.Ansi,SetLastError=true)] private static extern IntPtr GetProcAddress(IntPtr m,string n);
    [DllImport("kernel32.dll")] private static extern bool FreeLibrary(IntPtr m);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] private static extern bool SetDllDirectory(string p);
    public static int Compose(string dll,string recipient,string subject,string body,string attachmentPath,string attachmentName,IntPtr parent) {
        IntPtr module=IntPtr.Zero, recipPtr=IntPtr.Zero, filePtr=IntPtr.Zero;
        try {
            if(string.IsNullOrWhiteSpace(dll)||!File.Exists(dll)) throw new InvalidOperationException("MAPI DLL missing");
            var dir=Path.GetDirectoryName(dll); if(!string.IsNullOrWhiteSpace(dir)) SetDllDirectory(dir);
            module=LoadLibrary(dll); if(module==IntPtr.Zero) throw new InvalidOperationException("Cannot load MAPI DLL");
            IntPtr proc=GetProcAddress(module,"MAPISendMail"); if(proc==IntPtr.Zero) proc=GetProcAddress(module,"MAPISendMail@20"); if(proc==IntPtr.Zero) throw new InvalidOperationException("MAPISendMail not found");
            var send=(SendDelegate)Marshal.GetDelegateForFunctionPointer(proc,typeof(SendDelegate));
            var msg=new MapiMessage { subject=subject??"", noteText=body??"", recipCount=0, recips=IntPtr.Zero, fileCount=0, files=IntPtr.Zero };
            if(!string.IsNullOrWhiteSpace(recipient)) { var r=new MapiRecipDesc { recipClass=MAPI_TO,name=recipient,address=recipient.IndexOf(':')>=0?recipient:"SMTP:"+recipient }; recipPtr=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(MapiRecipDesc))); Marshal.StructureToPtr(r,recipPtr,false); msg.recipCount=1; msg.recips=recipPtr; }
            if(!string.IsNullOrWhiteSpace(attachmentPath)&&File.Exists(attachmentPath)) { var f=new MapiFileDesc { position=unchecked((uint)-1),pathName=attachmentPath,fileName=attachmentName }; filePtr=Marshal.AllocHGlobal(Marshal.SizeOf(typeof(MapiFileDesc))); Marshal.StructureToPtr(f,filePtr,false); msg.fileCount=1; msg.files=filePtr; }
            return send(IntPtr.Zero,parent,ref msg,MAPI_LOGON_UI|MAPI_DIALOG,0);
        } finally {
            if(recipPtr!=IntPtr.Zero){Marshal.DestroyStructure(recipPtr,typeof(MapiRecipDesc));Marshal.FreeHGlobal(recipPtr);} if(filePtr!=IntPtr.Zero){Marshal.DestroyStructure(filePtr,typeof(MapiFileDesc));Marshal.FreeHGlobal(filePtr);} if(module!=IntPtr.Zero)FreeLibrary(module); SetDllDirectory(null);
        }
    }
}
'@
}

function Invoke-FoxmailComposeVerified([object]$Payload) {
    $recipient=Decode-B64Text ([string]$Payload.recipient_b64)
    $subject=Decode-B64Text ([string]$Payload.subject_b64)
    $body=Decode-B64Text ([string]$Payload.body_b64)
    $attachmentName=Safe-AttachmentName (Decode-B64Text ([string]$Payload.attachment_filename_b64))
    $attachmentBytes=[Convert]::FromBase64String([string]$Payload.attachment_content_base64)
    if($attachmentBytes.Length -lt 1){throw 'empty attachment payload'}
    New-Item -ItemType Directory -Force -Path $MailDir | Out-Null
    $attachmentPath=Join-Path $MailDir ((Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'-'+$attachmentName)
    [IO.File]::WriteAllBytes($attachmentPath,$attachmentBytes)
    $info=Get-FoxmailClientInfo
    if(-not $info.Dll){throw 'Foxmail MAPI DLL not found'}
    $proc=Ensure-FoxmailRunning $info.Exe
    $parent=[IntPtr]$proc.MainWindowHandle
    Ensure-MapiType
    $before=Get-FoxmailWindowSnapshot
    $result=[ChenFoxmailMapiV06]::Compose($info.Dll,$recipient,$subject,$body,$attachmentPath,$attachmentName,$parent)
    $newWindow=Wait-NewFoxmailWindow $before 6500
    if($newWindow){ return @{ok=$true;mode='foxmail-direct-mapi';state='compose-window-detected';code=$result;window=$newWindow} }
    $systemMapi=Join-Path $env:WINDIR 'System32\mapi32.dll'
    if(Test-Path -LiteralPath $systemMapi){
        $before2=Get-FoxmailWindowSnapshot
        $result2=[ChenFoxmailMapiV06]::Compose($systemMapi,$recipient,$subject,$body,$attachmentPath,$attachmentName,$parent)
        $newWindow2=Wait-NewFoxmailWindow $before2 6500
        if($newWindow2){ return @{ok=$true;mode='system-mapi';state='compose-window-detected';code=$result2;window=$newWindow2} }
    }
    throw "MAPI returned but no Foxmail compose window appeared (direct code $result)"
}

function Test-AllowedOrigin([string]$Origin) {
    if([string]::IsNullOrWhiteSpace($Origin)){return $false}
    try { $u=New-Object System.Uri($Origin); $h=$u.Host.ToLowerInvariant(); if($h -eq '127.0.0.1' -or $h -eq 'localhost'){return $true}; return (($u.Scheme -eq 'https' -or $u.Scheme -eq 'http') -and ($h -eq $AllowedRootDomain -or $h.EndsWith('.'+$AllowedRootDomain))) } catch { return $false }
}
function Write-Response($Stream,[int]$Status,[string]$Body,[string]$Origin='') {
    if($null -eq $Body){$Body=''}; $bytes=[Text.Encoding]::UTF8.GetBytes($Body); $text="HTTP/1.1 $Status $(if($Status -eq 200){'OK'}elseif($Status -eq 204){'No Content'}elseif($Status -eq 403){'Forbidden'}elseif($Status -eq 404){'Not Found'}else{'Error'})`r`nContent-Type: application/json; charset=utf-8`r`nContent-Length: $($bytes.Length)`r`nCache-Control: no-store`r`nConnection: close`r`n"; if($Origin){$text+="Access-Control-Allow-Origin: $Origin`r`nAccess-Control-Allow-Methods: GET, POST, OPTIONS`r`nAccess-Control-Allow-Headers: Content-Type`r`nAccess-Control-Allow-Private-Network: true`r`nVary: Origin`r`n"}; $text+="`r`n"; $hb=[Text.Encoding]::ASCII.GetBytes($text); $Stream.Write($hb,0,$hb.Length); if($bytes.Length){$Stream.Write($bytes,0,$bytes.Length)}; $Stream.Flush()
}
function Read-Request($Stream) {
    $reader=New-Object IO.StreamReader($Stream,[Text.Encoding]::ASCII,$false,4096,$true); $line=$reader.ReadLine(); if(-not $line){return $null}; $parts=$line.Split(' '); $headers=@{}; while($true){$l=$reader.ReadLine(); if($null -eq $l -or $l -eq ''){break}; $c=$l.IndexOf(':'); if($c -gt 0){$headers[$l.Substring(0,$c).Trim().ToLowerInvariant()]=$l.Substring($c+1).Trim()}}; $len=0; if($headers.ContainsKey('content-length')){[void][int]::TryParse($headers['content-length'],[ref]$len)}; if($len -gt 12000000){throw 'payload too large'}; $body=''; if($len -gt 0){$chars=New-Object 'char[]' $len; $off=0; while($off -lt $len){$n=$reader.Read($chars,$off,$len-$off); if($n -le 0){break};$off+=$n};$body=New-Object string($chars,0,$off)}; return @{Method=$parts[0].ToUpperInvariant();Path=$parts[1];Headers=$headers;Body=$body}
}

if($ComposeRequest){ try{$payload=Get-Content -LiteralPath $ComposeRequest -Raw -Encoding UTF8|ConvertFrom-Json; $r=Invoke-FoxmailComposeVerified $payload; if($r.ok){exit 0};exit 89}catch{exit 90} }
if(-not $BridgeMode){ Write-Host 'Chen Foxmail Helper v0.6 is intended to run in BridgeMode.'; exit 0 }
New-Item -ItemType Directory -Force -Path $MailDir | Out-Null
$listener=New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback,$Port); try{$listener.Start()}catch{exit 0}
try {
 while($true){$client=$listener.AcceptTcpClient(); try{$stream=$client.GetStream();$req=Read-Request $stream;if($null -eq $req){continue};$origin='';if($req.Headers.ContainsKey('origin')){$origin=$req.Headers['origin']};if(-not(Test-AllowedOrigin $origin)){Write-Response $stream 403 (ConvertTo-CompactJson @{ok=$false;error='origin denied'});continue};if($req.Method -eq 'OPTIONS'){Write-Response $stream 204 '' $origin;continue};if($req.Method -eq 'GET' -and $req.Path -eq '/health'){Write-Response $stream 200 (ConvertTo-CompactJson @{ok=$true;name='Chen Foxmail Helper';version='0.6';compose=$true;verified_compose=$true}) $origin;continue};if($req.Method -eq 'POST' -and $req.Path -eq '/compose'){try{$payload=$req.Body|ConvertFrom-Json;$r=Invoke-FoxmailComposeVerified $payload;Write-Response $stream 200 (ConvertTo-CompactJson $r) $origin}catch{Write-Response $stream 500 (ConvertTo-CompactJson @{ok=$false;error=$_.Exception.Message}) $origin};continue};if($req.Method -eq 'POST' -and $req.Path -eq '/open'){try{$payload=$req.Body|ConvertFrom-Json;$name=Safe-EmlName (Decode-B64Text ([string]$payload.filename_b64));$bytes=[Convert]::FromBase64String([string]$payload.content_base64);$path=Join-Path $MailDir ((Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'-'+$name);[IO.File]::WriteAllBytes($path,$bytes);Start-Process -FilePath $path;Write-Response $stream 200 (ConvertTo-CompactJson @{ok=$true;mode='eml'}) $origin}catch{Write-Response $stream 500 (ConvertTo-CompactJson @{ok=$false;error=$_.Exception.Message}) $origin};continue};Write-Response $stream 404 (ConvertTo-CompactJson @{ok=$false;error='not found'}) $origin}finally{try{$client.Close()}catch{}} }
} finally {$listener.Stop()}
