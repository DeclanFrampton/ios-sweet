$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$source = Join-Path $PSScriptRoot 'PhoneControls.cs'
$outputDirectory = Join-Path $env:LOCALAPPDATA 'iOSSweet/PhoneControls'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$output = Join-Path $outputDirectory 'PhoneControls.exe'
if (!(Test-Path -LiteralPath $output) -or (Get-Item -LiteralPath $source).LastWriteTimeUtc -gt (Get-Item -LiteralPath $output).LastWriteTimeUtc) {
    & $compiler /nologo /target:winexe /platform:x64 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll "/out:$output" $source
    if ($LASTEXITCODE -ne 0) { throw 'Phone controls compilation failed' }
}
Start-Process -FilePath $output
