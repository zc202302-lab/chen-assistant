$ErrorActionPreference = 'Stop'

$Port = 18763
$AllowedRootDomain = 'ziboxiaozhushou.cn'
$MailDir = Join-Path $env:LOCALAPPDATA 'ChenAssistant\FoxmailDrafts'
New-Item -ItemType Directory -Force -Path $MailDir | Out-Null

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
        [string]$Origin = '',
        [string]$ContentType = 'application/json; charset=utf-8'
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
    $headers.Add("Content-Type: $ContentType")
    $headers.Add("Content-Length: $($bodyBytes.Length)")
    $headers.Add('Cache-Control: no-store')
    $headers.Add('Connection: close')
    if (-not [string]::IsNullOrWhiteSpace($Origin)) {
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

function Read-Request {
    param([System.Net.Sockets.NetworkStream]$Stream)

    $reader = New-Object IO.StreamReader($Stream, [Text.Encoding]::ASCII, $false, 4096, $true)
    $requestLine = $reader.ReadLine()
    if ([string]::IsNullOrWhiteSpace($requestLine)) { return $null }

    $parts = $requestLine.Split(' ')
    if ($parts.Length -lt 2) { return $null }
    $method = $parts[0].ToUpperInvariant()
    $path = $parts[1]

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

    $contentLength = 0
    if ($headers.ContainsKey('content-length')) {
        [void][int]::TryParse($headers['content-length'], [ref]$contentLength)
    }
    if ($contentLength -gt 12000000) {
        return @{ Method = $method; Path = $path; Headers = $headers; TooLarge = $true; Body = '' }
    }

    $body = ''
    if ($contentLength -gt 0) {
        # Browser payload is deliberately ASCII-only JSON: file name and EML bytes
        # are Base64. Therefore Content-Length bytes == characters here.
        $chars = New-Object char[] $contentLength
        $offset = 0
        while ($offset -lt $contentLength) {
            $n = $reader.Read($chars, $offset, $contentLength - $offset)
            if ($n -le 0) { break }
            $offset += $n
        }
        $body = New-Object string($chars, 0, $offset)
    }

    return @{ Method = $method; Path = $path; Headers = $headers; TooLarge = $false; Body = $body }
}

function Safe-FileName([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name)) { return 'payment.eml' }
    foreach ($c in [IO.Path]::GetInvalidFileNameChars()) {
        $Name = $Name.Replace([string]$c, '_')
    }
    if (-not $Name.ToLowerInvariant().EndsWith('.eml')) { $Name += '.eml' }
    if ($Name.Length -gt 120) { $Name = $Name.Substring(0, 116) + '.eml' }
    return $Name
}

function Open-Eml([string]$Path) {
    # Prefer Windows file association. If .eml is associated with Foxmail, this
    # opens directly in Foxmail as an editable draft (X-Unsent: 1).
    Start-Process -FilePath $Path
}

# Remove old temporary drafts after seven days.
Get-ChildItem -Path $MailDir -Filter '*.eml' -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
$listener.Start()
Write-Host "Chen Assistant Foxmail Bridge listening on 127.0.0.1:$Port"

try {
    while ($true) {
        $client = $listener.AcceptTcpClient()
        try {
            if (-not [Net.IPAddress]::IsLoopback($client.Client.RemoteEndPoint.Address)) {
                $client.Close()
                continue
            }

            $stream = $client.GetStream()
            $req = Read-Request -Stream $stream
            if ($null -eq $req) {
                Write-Response -Stream $stream -StatusCode 400 -Body '{"ok":false,"error":"bad request"}'
                continue
            }

            $origin = ''
            if ($req.Headers.ContainsKey('origin')) { $origin = $req.Headers['origin'] }
            if (-not (Test-AllowedOrigin $origin)) {
                Write-Response -Stream $stream -StatusCode 403 -Body '{"ok":false,"error":"origin denied"}'
                continue
            }

            if ($req.TooLarge) {
                Write-Response -Stream $stream -StatusCode 413 -Body '{"ok":false,"error":"payload too large"}' -Origin $origin
                continue
            }

            if ($req.Method -eq 'OPTIONS') {
                Write-Response -Stream $stream -StatusCode 204 -Body '' -Origin $origin
                continue
            }

            if ($req.Method -eq 'GET' -and $req.Path -eq '/health') {
                Write-Response -Stream $stream -StatusCode 200 -Body '{"ok":true,"name":"Chen Foxmail Bridge","version":"0.1"}' -Origin $origin
                continue
            }

            if ($req.Method -eq 'POST' -and $req.Path -eq '/open') {
                try {
                    $payload = $req.Body | ConvertFrom-Json
                    $nameBytes = [Convert]::FromBase64String([string]$payload.filename_b64)
                    $filename = Safe-FileName ([Text.Encoding]::UTF8.GetString($nameBytes))
                    $mailBytes = [Convert]::FromBase64String([string]$payload.content_base64)
                    if ($mailBytes.Length -lt 20) { throw 'empty mail payload' }

                    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
                    $path = Join-Path $MailDir ($stamp + '-' + $filename)
                    [IO.File]::WriteAllBytes($path, $mailBytes)
                    Open-Eml $path
                    Write-Response -Stream $stream -StatusCode 200 -Body '{"ok":true}' -Origin $origin
                } catch {
                    $msg = ($_.Exception.Message -replace '[\r\n"]', ' ')
                    Write-Response -Stream $stream -StatusCode 500 -Body ('{"ok":false,"error":"' + $msg + '"}') -Origin $origin
                }
                continue
            }

            Write-Response -Stream $stream -StatusCode 404 -Body '{"ok":false,"error":"not found"}' -Origin $origin
        } catch {
            try {
                if ($stream) { Write-Response -Stream $stream -StatusCode 500 -Body '{"ok":false,"error":"bridge error"}' }
            } catch {}
        } finally {
            try { $client.Close() } catch {}
        }
    }
} finally {
    $listener.Stop()
}
