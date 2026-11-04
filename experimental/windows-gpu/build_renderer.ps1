param(
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [int]$Jobs=1
)
$ErrorActionPreference='Stop'
if($Jobs -lt 1){throw 'Jobs must be positive'}
$sourcePath=(Resolve-Path -LiteralPath $SourceRoot).Path
$renderer=Join-Path $sourcePath 'reims-windows-16k'
if(-not (Get-Command link.exe -ErrorAction SilentlyContinue)){throw 'Run from an x64 Visual Studio Developer PowerShell'}
$env:CARGO_BUILD_JOBS="$Jobs"
$env:CMAKE_BUILD_PARALLEL_LEVEL="$Jobs"
Push-Location $renderer
try {
    cargo +1.98.1-x86_64-pc-windows-msvc build --profile ios-perf -p reims-vgpu-c --no-default-features --features vulkan,guest-page-16k
    if($LASTEXITCODE -ne 0){throw 'Renderer build failed'}
} finally {Pop-Location}
$dist=Join-Path $sourcePath 'reims-win-dist'
if(Test-Path -LiteralPath "$dist/lib/reims_vgpu_c.dll"){
    throw 'Distribution already exists; preserve it and choose a new source/destination before deployment'
}
New-Item -ItemType Directory -Path "$dist/lib/pkgconfig","$dist/include" -Force | Out-Null
foreach($name in @('reims_vgpu_c.dll','reims_vgpu_c.pdb','reims_vgpu_c.dll.lib')){
    Copy-Item -LiteralPath "$renderer/target/ios-perf/$name" -Destination "$dist/lib/$name"
}
Copy-Item -LiteralPath "$renderer/crates/reims-vgpu-c/include/reims_vgpu.h" -Destination "$dist/include/reims_vgpu.h"
$prefix=$dist.Replace('\','/')
$pc=@'
prefix=PREFIX_VALUE
libdir=${prefix}/lib
includedir=${prefix}/include
Name: reims-vgpu
Description: Experimental native Windows fixed16KiB GPU renderer
Version: 0.1.0
Libs: -L${libdir} -l:reims_vgpu_c.dll.lib
Cflags: -I${includedir}
'@
$pc.Replace('PREFIX_VALUE',$prefix) | Set-Content -LiteralPath "$dist/lib/pkgconfig/reims-vgpu.pc" -Encoding utf8
Get-FileHash -Algorithm SHA256 -LiteralPath "$dist/lib/reims_vgpu_c.dll","$dist/lib/reims_vgpu_c.pdb" | ConvertTo-Json | Set-Content "$dist/build-hashes.json"
