@echo off
setlocal
rem Run from any working directory. ExecutionPolicy applies only to this process.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Start-Studio.ps1" %*
exit /b %errorlevel%
