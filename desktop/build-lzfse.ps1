<# Maintainer build: LLVM-MinGW x64 and Git required. Normal users run start.cmd. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory,[string]$Clang='clang')
$ErrorActionPreference='Stop'
$commit='e634ca58b4821d9f3d560cdc6df5dec02ffc93fd'
$out=[IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $out|Out-Null
$work=Join-Path $out ('lzfse-build-'+[Guid]::NewGuid().ToString('N'))
git clone https://github.com/lzfse/lzfse.git $work
if($LASTEXITCODE){throw 'Open-source LZFSE clone failed'}
git -C $work checkout --detach $commit
if($LASTEXITCODE -or (git -C $work rev-parse HEAD).Trim() -ne $commit){throw 'LZFSE revision verification failed'}
$target=Join-Path $out 'lzfse.exe'
if(Test-Path -LiteralPath $target){throw 'Preserving existing decoder; select an empty output folder'}
$sources=Get-ChildItem -LiteralPath (Join-Path $work 'src') -Filter '*.c'|ForEach-Object{$_.FullName}
& $Clang --target=x86_64-w64-windows-gnu -O2 -DNDEBUG -static '-Wl,--no-insert-timestamp' -I (Join-Path $work 'src') @sources -o $target
if($LASTEXITCODE){throw 'LLVM-MinGW native decoder build failed'}
New-Item -ItemType Directory -Force -Path (Join-Path $out 'licenses')|Out-Null
Copy-Item -LiteralPath (Join-Path $work 'LICENSE') -Destination (Join-Path $out 'licenses/lzfse-LICENSE')
@{repository='https://github.com/lzfse/lzfse';commit=$commit;compiler=(& $Clang --version | Out-String);sha256=(Get-FileHash $target -Algorithm SHA256).Hash.ToLowerInvariant()}|
    ConvertTo-Json|Set-Content -LiteralPath (Join-Path $out 'licenses/lzfse-build.json') -Encoding UTF8
Write-Output ('BUILT_WINDOWS_LZFSE='+$target)
