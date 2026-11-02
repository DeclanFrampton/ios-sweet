<#
.SYNOPSIS
  Clone the repository and run .\start.cmd. No app installer, Python, Docker,
  compiler, SDK, signing account, GitHub login or global PATH change required.
.PARAMETER PrepareOnly
  Download/check all runtime dependencies and run the same source preflight,
  without opening a window, starting QEMU or downloading Apple firmware.
.PARAMETER DataDirectory
  Optional private device-data location. Defaults to .studio\data in the clone.
#>
[CmdletBinding()]
param([switch]$PrepareOnly,[string]$DataDirectory='')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$lock=$null;$transcript=$false
try {
    if(-not [Environment]::Is64BitOperatingSystem -or
       ($env:PROCESSOR_ARCHITECTURE -match 'ARM') -or ($env:PROCESSOR_ARCHITEW6432 -match 'ARM')) {
        throw 'This preview supports Windows 10/11 x64 on Intel or AMD. Windows ARM, macOS and Linux are not yet supported.'
    }
    if([Environment]::OSVersion.Version.Build -lt 19041) { throw 'Windows 10 version 2004 or later (or Windows 11) is required.' }
    Import-Module (Join-Path $PSScriptRoot 'Studio-Bootstrap.psm1') -Force -DisableNameChecking
    $cache=Assert-StudioPath (Join-Path $repo '.studio')
    foreach($path in @($cache,(Join-Path $cache 'logs'),(Join-Path $cache 'downloads'),(Join-Path $cache 'runtime'))) {
        $null=Assert-StudioPath $path
        [IO.Directory]::CreateDirectory($path)|Out-Null
    }
    try { $lock=New-Object IO.FileStream((Join-Path $cache 'bootstrap.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
    catch { throw 'Another Studio bootstrap is preparing this clone. Let it finish; no duplicate setup was started.' }
    $log=Join-Path $cache ('logs\bootstrap-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
    Start-Transcript -LiteralPath $log -Force|Out-Null;$transcript=$true
    Write-Host ''
    Write-Host 'iOS Sweet Studio - run from source' -ForegroundColor Cyan
    Write-Host 'No Studio installer. Dependencies stay in this clone; your system Python/PATH are not changed.'
    $spec=Get-Content -LiteralPath (Join-Path $repo 'desktop\runtime-lock.json') -Raw|ConvertFrom-Json
    if($spec.schema -ne 1 -or $spec.platform -ne 'windows-x64' -or $spec.version -notmatch '^[a-zA-Z0-9._-]{3,80}$') {
        throw 'Invalid runtime lock file in this checkout.'
    }
    $runtime=Assert-StudioChild (Join-Path $cache 'runtime') (Join-Path (Join-Path $cache 'runtime') $spec.version)
    $null=Assert-StudioPath $runtime
    if(Test-Path -LiteralPath $runtime) {
        Write-Host '[1/4] Verifying cached runtime dependencies...'
        if(-not(Test-StudioRuntime $runtime $spec.inventorySha256)) {
            throw ('The dependency cache has changed or is incomplete. Close Studio, rename only "'+$runtime+'", and rerun start.cmd. Your .studio\data folder must be kept.')
        }
    } else {
        Write-Host '[1/4] Preparing runtime dependencies...'
        $drive=New-Object IO.DriveInfo([IO.Path]::GetPathRoot($cache))
        if($drive.AvailableFreeSpace -lt 3GB) { throw 'At least 3 GB free space is needed for runtime dependencies (device creation needs more).' }
        $download=Join-Path (Join-Path $cache 'downloads') ($spec.version+'.zip')
        Get-StudioDownload $spec.archiveUrl $download $spec.archiveSha256 ([long]$spec.archiveBytes)
        $stage=Assert-StudioChild (Join-Path $cache 'runtime') ($runtime+'.staging-'+[Guid]::NewGuid().ToString('N'))
        Write-Host '  Expanding the verified dependencies...'
        Expand-StudioZip $download $stage
        if(-not(Test-StudioRuntime $stage $spec.inventorySha256)) { throw 'Extracted runtime failed verification; no executable was started.' }
        Move-Item -LiteralPath $stage -Destination $runtime
    }
    Write-Host '[2/4] Checking the embedded display dependency...'
    Install-StudioWebView (Join-Path $cache 'downloads')
    $settings=Join-Path $cache 'settings.json'
    if($DataDirectory) {
        $data=Assert-StudioPath $DataDirectory
    } elseif(Test-Path -LiteralPath $settings) {
        $saved=Get-Content -LiteralPath $settings -Raw|ConvertFrom-Json
        if(-not($saved.dataDirectory -is [string]) -or $saved.dataDirectory.Length -gt 4096) {
            throw 'Invalid clone-local data location in .studio/settings.json.'
        }
        $data=Assert-StudioPath $saved.dataDirectory
    } else {
        $data=Assert-StudioPath (Join-Path $cache 'data')
    }
    if($data.StartsWith($runtime.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or $data -eq $runtime) {
        throw 'Device data cannot be stored inside a versioned dependency runtime.'
    }
    [IO.Directory]::CreateDirectory($data)|Out-Null
    [IO.Directory]::CreateDirectory((Join-Path $data 'logs'))|Out-Null
    $settingsTemp=$settings+'.new'
    @{dataDirectory=$data}|ConvertTo-Json|Set-Content -LiteralPath $settingsTemp -Encoding UTF8
    Move-Item -LiteralPath $settingsTemp -Destination $settings -Force
    $env:IOS_SWEET_HOME=$data
    $env:IOS_SWEET_ASSET_ROOT=Join-Path $runtime 'assets'
    $env:PYTHONNOUSERSITE='1'
    $env:PYTHONDONTWRITEBYTECODE='1'
    $python=Join-Path $runtime 'python\python.exe'
    $guiPython=Join-Path $runtime 'python\pythonw.exe'
    $entry=Join-Path $repo 'desktop\source_entry.py'
    Write-Host '[3/4] Testing the downloaded runtime against the current source...'
    & $python -u $entry --check-runtime
    if($LASTEXITCODE -ne 0) { throw 'Runtime preflight failed. See the error above and bootstrap log.' }
    if($PrepareOnly) {
        Write-Host '[4/4] Ready. Dependency preparation passed; no iPhone or firmware download was started.' -ForegroundColor Green
        Write-Host ('Private device data: '+$data)
    } else {
        Write-Host '[4/4] Opening iOS Sweet Studio...'
        $mutex=$null
        if([Threading.Mutex]::TryOpenExisting('Local\IOSSweetStudioDesktop',[ref]$mutex)) {
            $mutex.Dispose()
            Write-Host 'Studio is already open. The running app and iPhone have been left untouched.' -ForegroundColor Green
        } else {
            $stdout=Join-Path $data 'logs\desktop.stdout.log'
            $stderr=Join-Path $data 'logs\desktop.stderr.log'
            # pythonw has no console to leave open. This is the user's visible
            # interactive application, not a hidden helper: SW_HIDE would also
            # hide its first native window on Windows.
            $process=Start-Process -FilePath $guiPython -ArgumentList ('-u "'+$entry+'"') -WorkingDirectory $repo -PassThru -WindowStyle Normal -RedirectStandardOutput $stdout -RedirectStandardError $stderr
            $ready=$false
            for($i=0;$i -lt 80;$i++) {
                if($process.HasExited) {
                    $details=if(Test-Path -LiteralPath $stderr){(Get-Content -LiteralPath $stderr -Tail 12) -join "`n"}else{''}
                    throw ('Studio exited during startup. '+$details)
                }
                $state=Join-Path $data 'state\desktop.json'
                if(Test-Path -LiteralPath $state) {
                    try {
                        $session=Get-Content -LiteralPath $state -Raw|ConvertFrom-Json
                        if([int]$session.pid -eq $process.Id -and $session.uiReady -eq $true) {
                            $r=Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:'+$session.port+'/') -TimeoutSec 2
                            $process.Refresh()
                            if($r.StatusCode -eq 200 -and $r.Content.Contains('iOS Sweet Studio') -and $process.MainWindowHandle -ne [IntPtr]::Zero){$ready=$true;break}
                        }
                    } catch { }
                }
                Start-Sleep -Milliseconds 500
            }
            if(-not $ready) { throw ('Studio did not report readiness. Check '+$stderr+'. No second copy was started.') }
            Write-Host 'Studio is open. On first use, approve the in-app Apple firmware download to create your iPhone.' -ForegroundColor Green
            Write-Host ('Private device data: '+$data)
            Write-Host 'Run the same .\start.cmd command next time; verified dependencies are reused.'
        }
    }
} catch {
    Write-Host ''
    Write-Host ('Studio could not start: '+$_.Exception.Message) -ForegroundColor Red
    Write-Host ('Logs: '+(Join-Path $repo '.studio\logs'))
    exit 1
} finally {
    if($transcript){Stop-Transcript|Out-Null}
    if($lock){$lock.Dispose()}
}
