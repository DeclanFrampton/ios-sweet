# Shared bootstrap functions. Importing this module changes nothing on disk.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.IO.Compression

function Assert-StudioPath {
    param([Parameter(Mandatory)][string]$Path)
    $full=[IO.Path]::GetFullPath($Path)
    if($full.Length -lt 8 -or $full -eq [IO.Path]::GetPathRoot($full)) { throw 'A dedicated local directory is required.' }
    $p=New-Object IO.DirectoryInfo($full)
    while($null -ne $p) {
        if($p.Exists -and ($p.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw ('Runtime/data folders must not traverse a junction or symlink: '+$p.FullName)
        }
        $p=$p.Parent
    }
    return $full
}

function Assert-StudioChild {
    param([string]$Root,[string]$Path)
    $base=[IO.Path]::GetFullPath($Root).TrimEnd('\')+'\'
    $full=[IO.Path]::GetFullPath($Path)
    if(-not $full.StartsWith($base,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe path outside the dependency cache.' }
    return $full
}

function Get-StudioHash {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-StudioDownload {
    param([string]$Url,[string]$Destination,[string]$Sha256,[long]$ExpectedBytes)
    $uri=[Uri]$Url
    if($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com' -or
       -not $uri.AbsolutePath.StartsWith('/danhol86/ios-sweet/releases/download/')) {
        throw 'Runtime downloads must come from a pinned release in the project repository.'
    }
    if($Sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Invalid runtime checksum in source lock file.' }
    if(Test-Path -LiteralPath $Destination) {
        if((Get-Item -LiteralPath $Destination).Length -eq $ExpectedBytes -and (Get-StudioHash $Destination) -eq $Sha256) {
            Write-Host '  Reusing the verified dependency download.'
            return
        }
        # Preserve unexpected files rather than deleting/reusing their contents.
        Move-Item -LiteralPath $Destination -Destination ($Destination+'.invalid-'+[Guid]::NewGuid().ToString('N'))
    }
    [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
    $temporary=$Destination+'.partial-'+[Guid]::NewGuid().ToString('N')
    $savedProgress=$ProgressPreference
    try {
        $ProgressPreference='SilentlyContinue'
        for($attempt=1;$attempt -le 3;$attempt++) {
            try {
                Write-Host ('  Downloading runtime dependencies ('+[math]::Round($ExpectedBytes/1MB)+' MB), attempt '+$attempt+'...')
                Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $temporary -TimeoutSec 1200
                if((Get-Item -LiteralPath $temporary).Length -ne $ExpectedBytes) { throw 'Download length does not match the pinned release.' }
                if((Get-StudioHash $temporary) -ne $Sha256) { throw 'Downloaded runtime failed SHA-256 verification. Nothing was executed.' }
                Move-Item -LiteralPath $temporary -Destination $Destination
                return
            } catch {
                if($attempt -eq 3) { throw }
                Write-Host ('  Download failed: '+$_.Exception.Message)
                Start-Sleep -Seconds (2*$attempt)
            }
        }
    } finally {
        $ProgressPreference=$savedProgress
        if(Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Expand-StudioZip {
    param([string]$Archive,[string]$Destination)
    $root=Assert-StudioPath $Destination
    if(Test-Path -LiteralPath $root) { throw 'Extraction requires a new staging directory.' }
    [IO.Directory]::CreateDirectory($root)|Out-Null
    $zip=[IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        if($zip.Entries.Count -gt 20000) { throw 'Runtime archive contains too many files.' }
        $seen=New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        [long]$total=0
        foreach($entry in $zip.Entries) {
            $name=$entry.FullName
            if([string]::IsNullOrEmpty($name) -or $name.Contains(':') -or $name.Contains('\') -or
               $name.StartsWith('/') -or ($name.Split('/') -contains '..') -or ($name.Split('/') -contains '.')) {
                throw 'Unsafe path in runtime ZIP.'
            }
            if((($entry.ExternalAttributes -shr 16) -band 61440) -eq 40960) { throw 'Runtime ZIP must not contain symlinks.' }
            $total+=$entry.Length
            if($total -gt 3GB) { throw 'Runtime ZIP exceeds the extraction limit.' }
            $target=Assert-StudioChild $root (Join-Path $root $name)
            if(-not $seen.Add($target)) { throw 'Duplicate/case-colliding runtime path.' }
            if($name.EndsWith('/')) { [IO.Directory]::CreateDirectory($target)|Out-Null;continue }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))|Out-Null
            $input=$entry.Open()
            $output=New-Object IO.FileStream($target,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
            try { $input.CopyTo($output) } finally { $output.Dispose();$input.Dispose() }
        }
    } finally { $zip.Dispose() }
}

function Test-StudioRuntime {
    param([string]$Runtime,[string]$InventorySha256)
    $inventory=Join-Path $Runtime 'runtime-manifest.json'
    if(-not(Test-Path -LiteralPath $inventory)) { return $false }
    if((Get-StudioHash $inventory) -ne $InventorySha256) { return $false }
    $manifest=Get-Content -LiteralPath $inventory -Raw|ConvertFrom-Json
    if($manifest.schema -ne 1 -or @($manifest.files.PSObject.Properties).Count -lt 10) { return $false }
    foreach($entry in $manifest.files.PSObject.Properties) {
        if($entry.Value -notmatch '^[0-9a-f]{64}$') { throw 'Invalid runtime file checksum.' }
        $file=Assert-StudioChild $Runtime (Join-Path $Runtime $entry.Name)
        if(-not(Test-Path -LiteralPath $file -PathType Leaf)) { return $false }
        if((Get-Item -LiteralPath $file).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
        if((Get-StudioHash $file) -ne $entry.Value) { return $false }
    }
    foreach($required in @('python/python.exe','python/pythonw.exe','python/python314._pth','assets/rcodesign.exe',
        'assets/qemu/qemu-system-aarch64.exe','assets/qemu/qemu-system-x86_64.exe','assets/manifest.json')) {
        if(-not $manifest.files.PSObject.Properties[$required]) { return $false }
    }
    return $true
}

function Test-StudioWebView {
    $path='Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    foreach($hive in @([Microsoft.Win32.RegistryHive]::CurrentUser,[Microsoft.Win32.RegistryHive]::LocalMachine)) {
        foreach($view in @([Microsoft.Win32.RegistryView]::Registry32,[Microsoft.Win32.RegistryView]::Registry64)) {
            $base=$null;$key=$null
            try {
                $base=[Microsoft.Win32.RegistryKey]::OpenBaseKey($hive,$view);$key=$base.OpenSubKey($path)
                if($null -ne $key) {
                    $version=$key.GetValue('pv')
                    if($version -and [version]$version -gt [version]'0.0.0.0') { return $true }
                }
            } finally { if($key){$key.Dispose()};if($base){$base.Dispose()} }
        }
    }
    return $false
}

function Install-StudioWebView {
    param([string]$Cache)
    if(Test-StudioWebView) { Write-Host '  Microsoft WebView2 is already available.';return }
    Write-Host '  Downloading the missing Microsoft WebView2 runtime from Microsoft...'
    $file=Join-Path $Cache ('MicrosoftEdgeWebview2Setup-'+[Guid]::NewGuid().ToString('N')+'.exe')
    try {
        Invoke-WebRequest -UseBasicParsing 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $file -TimeoutSec 180
        $sig=Get-AuthenticodeSignature -LiteralPath $file
        if($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
            throw 'The WebView2 download is not correctly signed by Microsoft. Nothing was executed.'
        }
        # No RunAs/UAC elevation: Microsoft's bootstrapper supports per-user installation.
        $process=Start-Process -FilePath $file -ArgumentList '/silent /install' -PassThru -WindowStyle Hidden
        if(-not $process.WaitForExit(600000)) { throw 'Microsoft WebView2 has not finished installing; check its setup before retrying.' }
        if(-not(Test-StudioWebView)) { throw ('Microsoft WebView2 is still unavailable (exit '+$process.ExitCode+').') }
    } finally {
        if(Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force -ErrorAction SilentlyContinue }
    }
}

Export-ModuleMember -Function Assert-StudioPath,Assert-StudioChild,Get-StudioHash,Get-StudioDownload,Expand-StudioZip,Test-StudioRuntime,Test-StudioWebView,Install-StudioWebView
