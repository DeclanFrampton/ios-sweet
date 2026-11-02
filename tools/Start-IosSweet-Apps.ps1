<#
.SYNOPSIS
  Open the locally verified iOS Sweet app-test guest and its localhost panel.
.DESCRIPTION
  Uses an ignored, machine-local manifest. Never stops another VM, modifies
  an iOS disk, downloads firmware, or creates Apple developer credentials.
  The original Start-IosSweet-Windows.ps1 remains the baseline fallback.
#>
[CmdletBinding()]
param([switch]$NoBrowser,[switch]$CheckOnly)
$ErrorActionPreference='Stop'
$repo=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtime=Join-Path $repo 'windows-runtime'
$manifestPath=Join-Path $runtime 'state\app-install-test.json'
if(-not(Test-Path -LiteralPath $manifestPath)){
  throw 'No locally prepared app-test manifest exists. The project does not distribute Apple images or preinstalled apps.'
}
$manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
if($manifest.schema -ne 1 -or $manifest.bundleId -ne 'com.iosnova'){
  throw 'Unrecognised local app-test manifest. Refusing to select a guest.'
}
function Resolve-PrivateFile([string]$relative){
  if([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative)){
    throw 'Private manifest paths must be relative to the repository.'
  }
  $resolved=(Resolve-Path -LiteralPath (Join-Path $repo $relative)).Path
  if(-not $resolved.StartsWith(($runtime.TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase)){
    throw 'Private app-test path escaped the runtime directory.'
  }
  $item=Get-Item -LiteralPath $resolved
  if($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)){
    throw 'App-test inputs must be regular private files.'
  }
  return $resolved
}
$overlay=Resolve-PrivateFile ([string]$manifest.overlay)
$kernel=Resolve-PrivateFile ([string]$manifest.kernel)
$bridgeConfig=Resolve-PrivateFile ([string]$manifest.bridgeConfig)
if([IO.Path]::GetExtension($overlay) -ne '.qcow2'){throw 'Expected a QCOW2 test overlay'}
$kernelHash=([string]$manifest.kernelSha256).ToLowerInvariant()
if($kernelHash -notmatch '^[0-9a-f]{64}$' -or
   (Get-FileHash -LiteralPath $kernel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $kernelHash){
  throw 'The app-test kernel does not match its verified checksum.'
}
$configuration=Get-Content -LiteralPath $bridgeConfig -Raw|ConvertFrom-Json
if($configuration.Token -notmatch '^[0-9a-f]{64}$' -or
   $configuration.BundleId -ne 'com.iosnova' -or
   $configuration.BundlePath -ne '/Applications/iOSNova.app'){
  throw 'The private bridge configuration does not match the verified app.'
}
$configuration=$null # never write the capability to stdout or command arguments
Write-Host 'Verified local app-test configuration and pinned kernel.'
if($CheckOnly){return}

$python=(Get-Command python.exe -ErrorAction Stop).Source
$activePath=Join-Path $runtime 'state\active-native.json'
$qemuPath=Join-Path $runtime 'qemu\qemu-system-aarch64.exe'
function Assert-ExpectedGuest {
  $processes=@(Get-CimInstance Win32_Process -Filter "Name='qemu-system-aarch64.exe'")
  if($processes.Count -ne 1 -or -not(Test-Path -LiteralPath $activePath)){
    throw 'Expected exactly one recorded native iOS Sweet guest.'
  }
  $active=Get-Content -LiteralPath $activePath -Raw|ConvertFrom-Json
  if($active.qemu_pid -ne $processes[0].ProcessId -or $active.cpus -ne 2 -or
     $active.kernel_sha256 -ne $kernelHash -or
     -not [string]::Equals($processes[0].ExecutablePath,$qemuPath,[StringComparison]::OrdinalIgnoreCase)){
    throw 'A different emulator is running. Stop it cleanly before selecting the app test.'
  }
  $run=[IO.Path]::GetFullPath([string]$active.run)
  $stateRoot=Join-Path $runtime 'state'
  if(-not $run.StartsWith(($stateRoot.TrimEnd('\')+'\'),[StringComparison]::OrdinalIgnoreCase)){
    throw 'Unexpected active run directory.'
  }
  $arguments=Get-Content -LiteralPath (Join-Path $run 'command.json') -Raw|ConvertFrom-Json
  $fileArgument=@($arguments|Where-Object{$_ -match '^if=none,id=iosroot,'})
  if($fileArgument.Count -ne 1){throw 'Cannot verify the active guest disk'}
  $match=[regex]::Match([string]$fileArgument[0],'(?:^|,)file=([^,]+)')
  if(-not $match.Success -or
     -not [string]::Equals($match.Groups[1].Value.Replace('/','\'),$overlay,[StringComparison]::OrdinalIgnoreCase)){
    throw 'The active guest is using a different disk. It has been left untouched.'
  }
  return $active
}
$running=@(Get-CimInstance Win32_Process -Filter "Name='qemu-system-aarch64.exe'")
if($running.Count){
  $active=Assert-ExpectedGuest
  Write-Host ('Reusing the app-test guest, PID '+$active.qemu_pid+'.')
}else{
  $controllers=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'"|
    Where-Object{$_.CommandLine -match 'iossweet-native-windows.py'})
  if($controllers.Count){throw 'An iOS Sweet controller is still starting or stopping; no second instance was launched.'}
  $native=Join-Path $PSScriptRoot 'iossweet-native-windows.py'
  $logs=Join-Path $runtime 'logs'
  $stamp=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
  $stdout=Join-Path $logs ('app-test-'+$stamp+'.stdout.log')
  $stderr=Join-Path $logs ('app-test-'+$stamp+'.stderr.log')
  $arguments='"'+$native+'" --cpus 2 --srgb-display --kernel "'+$kernel+
    '" --kernel-sha256 '+$kernelHash+' --overlay "'+$overlay+'" --no-browser'
  $controller=Start-Process -FilePath $python -ArgumentList $arguments -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $ready=$false
  for($i=0;$i -lt 40;$i++){
    if($controller.HasExited){
      if(Test-Path -LiteralPath $stderr){Get-Content -LiteralPath $stderr -Tail 10|Write-Host}
      throw 'The native guest did not start. The existing RAM and singleton safeguards remain enforced.'
    }
    try{
      $active=Assert-ExpectedGuest
      $status=Invoke-RestMethod 'http://127.0.0.1:8108/status.json' -TimeoutSec 2
      if($status.mode -eq 'Native Windows QEMU' -and $status.cores -eq 2){$ready=$true;break}
    }catch{}
    Start-Sleep -Milliseconds 500
  }
  if(-not $ready){throw 'The guest has not reached viewer readiness. Inspect the app-test logs; no additional guest was started.'}
  Write-Host ('Started the verified app-test guest, PID '+$active.qemu_pid+'.')
}

$panel=Join-Path $PSScriptRoot 'guest-install\server.py'
$listeners=@(Get-NetTCPConnection -LocalPort 8109 -State Listen -ErrorAction SilentlyContinue)
if($listeners.Count){
  $pids=@($listeners.OwningProcess|Select-Object -Unique)
  if($pids.Count -ne 1){throw 'Port 8109 has unexpected listeners; left unchanged'}
  $owner=Get-CimInstance Win32_Process -Filter ('ProcessId='+$pids[0])
  if($owner.Name -ne 'python.exe' -or -not $owner.CommandLine.Contains($panel) -or
     -not $owner.CommandLine.Contains($bridgeConfig)){
    throw 'Port 8109 is owned by a different service. It has not been changed.'
  }
}else{
  $stamp=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
  $logs=Join-Path $runtime 'logs'
  Start-Process -FilePath $python -ArgumentList ('"'+$panel+'" --config "'+$bridgeConfig+'" --port 8109') `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs ('app-panel-'+$stamp+'.stdout.log')) `
    -RedirectStandardError (Join-Path $logs ('app-panel-'+$stamp+'.stderr.log'))|Out-Null
  Start-Sleep -Seconds 1
}
Write-Host 'App controls: http://127.0.0.1:8109/'
Write-Host 'iPhone screen: http://127.0.0.1:8108/'
Write-Host 'The app-test guest uses local development signing, not an Apple-registered hardware UDID.'
if(-not $NoBrowser){Start-Process 'http://127.0.0.1:8109/'}
