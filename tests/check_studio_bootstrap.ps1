# Offline tests. Never downloads, runs a dependency, installs WebView2 or starts QEMU.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '..\tools\Studio-Bootstrap.psm1') -Force -DisableNameChecking
$root=Join-Path ([IO.Path]::GetTempPath()) ('iossweet-bootstrap-test-'+[Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root)|Out-Null
function Must-Fail([scriptblock]$Action) {
    $failed=$false
    try{& $Action|Out-Null}catch{$failed=$true}
    if(-not $failed){throw 'Expected the unsafe operation to be rejected.'}
}
try {
    $inside=Assert-StudioChild $root (Join-Path $root 'safe.txt')
    if(-not $inside.StartsWith($root)){throw 'Unexpected safe path'}
    Must-Fail { Assert-StudioChild $root (Join-Path $root '..\escape.txt') }
    $bad=Join-Path $root 'traversal.zip'
    $zip=[IO.Compression.ZipFile]::Open($bad,[IO.Compression.ZipArchiveMode]::Create)
    try{$e=$zip.CreateEntry('../escape.txt');$s=$e.Open();$s.WriteByte(65);$s.Dispose()}finally{$zip.Dispose()}
    Must-Fail { Expand-StudioZip $bad (Join-Path $root 'bad-extraction') }
    $good=Join-Path $root 'good.zip'
    $zip=[IO.Compression.ZipFile]::Open($good,[IO.Compression.ZipArchiveMode]::Create)
    try{$e=$zip.CreateEntry('assets/sample.txt');$s=$e.Open();$s.WriteByte(66);$s.Dispose()}finally{$zip.Dispose()}
    $expanded=Join-Path $root 'safe-extraction'
    Expand-StudioZip $good $expanded
    if([IO.File]::ReadAllText((Join-Path $expanded 'assets/sample.txt')) -ne 'B'){throw 'Safe ZIP extraction failed'}
    Must-Fail { Expand-StudioZip $good $expanded }
    $runtime=Join-Path $root 'mock-runtime';[IO.Directory]::CreateDirectory($runtime)|Out-Null
    $files=[ordered]@{}
    $names=@('python/python.exe','python/pythonw.exe','python/python314._pth','assets/rcodesign.exe',
        'assets/qemu/qemu-system-aarch64.exe','assets/qemu/qemu-system-x86_64.exe','assets/manifest.json',
        'file1','file2','file3','file4')
    foreach($name in $names){
        $p=Join-Path $runtime $name;[IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($p))|Out-Null
        [IO.File]::WriteAllText($p,'synthetic test content');$files[$name]=Get-StudioHash $p
    }
    $inventory=Join-Path $runtime 'runtime-manifest.json'
    @{schema=1;version='test';files=$files}|ConvertTo-Json -Depth 4|Set-Content -LiteralPath $inventory -Encoding UTF8
    $pin=Get-StudioHash $inventory
    if(-not(Test-StudioRuntime $runtime $pin)){throw 'Valid synthetic inventory rejected'}
    [IO.File]::WriteAllText((Join-Path $runtime 'python/python.exe'),'tampered')
    if(Test-StudioRuntime $runtime $pin){throw 'Tampered dependency was accepted'}
    if(Test-StudioRuntime $runtime ('0'*64)){throw 'Wrong inventory pin was accepted'}
    $tokens=$null;$errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '..\tools\Start-Studio.ps1'),[ref]$tokens,[ref]$errors)
    if($errors.Count){throw ($errors.Message -join '; ')}
    Write-Output 'BOOTSTRAP_BOUNDARY_TESTS_PASS'
}finally{
    # Test scratch only: absolute, unique and directly under the OS temp folder.
    $expected=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    $actual=[IO.Path]::GetFullPath($root)
    if($actual.StartsWith($expected,[StringComparison]::OrdinalIgnoreCase) -and
       [IO.Path]::GetFileName($actual).StartsWith('iossweet-bootstrap-test-')){
        Remove-Item -LiteralPath $actual -Recurse -Force
    }
}
