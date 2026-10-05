param([string]$Bridge = 'E:\ChenBridge')
$ErrorActionPreference = 'Stop'
$repo = 'zc202302-lab/chen-assistant'
$branch = 'feat/number-inbox-cloud-batch-export'
Add-Type -AssemblyName System.IO.Compression.FileSystem
function Run-Gh([string[]]$Arguments, [int]$Seconds) {
    $output = Join-Path $env:TEMP ([guid]::NewGuid().ToString() + '.out')
    $errors = $output + '.err'
    try {
        $process = Start-Process -FilePath (Get-Command gh).Source -ArgumentList $Arguments -NoNewWindow -PassThru -RedirectStandardOutput $output -RedirectStandardError $errors
        $elapsed = 0
        while (-not $process.WaitForExit(10000)) {
            $elapsed += 10
            Write-Host "仍在等待 GitHub，已用 $elapsed 秒……"
            if ($elapsed -ge $Seconds) {
                $process.Kill()
                $process.WaitForExit()
                throw '本次下载超时，60 秒后自动重试；原程序和数据保持不变。'
            }
        }
        if ($process.ExitCode -ne 0) { throw (Get-Content $errors -Raw) }
        return (Get-Content $output -Raw)
    } finally {
        Remove-Item $output,$errors -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "本机同步已启动，共享目录：$Bridge"
if (-not (Test-Path -LiteralPath $Bridge -PathType Container)) { throw '共享文件夹不存在，请确认路径。' }
$updates = Join-Path $Bridge 'updates'
New-Item -ItemType Directory -Force -Path $updates | Out-Null
while ($true) {
    $stage = Join-Path $env:TEMP ([guid]::NewGuid().ToString())
    try {
        Write-Host '正在检查最新版……'
        $runs = Run-Gh @('run','list','--repo',$repo,'--workflow','cloud-member-add-agent.yml','--branch',$branch,'--status','success','--limit','1','--json','databaseId,headSha') 60 | ConvertFrom-Json
        if (-not $runs) { throw '还没有可下载的成功构建。' }
        $revision = $runs[0].headSha
        $pointer = Join-Path $updates 'latest.json'
        $previous = if (Test-Path $pointer) { (Get-Content $pointer -Raw | ConvertFrom-Json).version } else { '' }
        if ($previous -eq $revision) {
            Write-Host '共享目录已是最新版；60 秒后再检查。'
        } else {
            New-Item -ItemType Directory -Path $stage | Out-Null
            Write-Host '正在下载更新包，最多等待 5 分钟……'
            $null = Run-Gh @('run','download',"$($runs[0].databaseId)",'--repo',$repo,'--name','CloudMemberAddAgent','--dir',$stage) 300
            $package = Join-Path $stage 'CloudMemberAddAgent.zip'
            $zip = [IO.Compression.ZipFile]::OpenRead($package)
            try {
                $entry = $zip.GetEntry('version.json')
                if (-not $entry) { throw '包中缺少版本文件。' }
                $reader = New-Object IO.StreamReader($entry.Open())
                try { $version = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
                if ($version.version -ne $revision) { throw '安装包版本不一致。' }
            } finally { $zip.Dispose() }
            $part = Join-Path $updates ($revision + '.part')
            $target = Join-Path $updates ($revision + '.zip')
            Write-Host '下载完成，正在写入共享目录……'
            Copy-Item -LiteralPath $package -Destination $part -Force
            Move-Item -LiteralPath $part -Destination $target -Force
            $manifest = @{version=$revision;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
            $temporary = Join-Path $updates 'latest.tmp'
            $manifest | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding ascii
            Move-Item -LiteralPath $temporary -Destination $pointer -Force
            Write-Host '本机已同步更新包。保持窗口打开，以后自动检查。'
        }
    } catch { Write-Host "同步未完成：$($_.Exception.Message)" }
    finally { Remove-Item -LiteralPath $stage -Recurse -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 60
}
