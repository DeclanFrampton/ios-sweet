@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Start-IosSweet-Apps.ps1"
if errorlevel 1 pause
