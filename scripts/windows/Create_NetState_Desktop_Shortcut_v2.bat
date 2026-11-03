@echo off
setlocal EnableExtensions
set "LAUNCHER=%~dp0Launch_NetState_Reconciler_v2.bat"
if not exist "%LAUNCHER%" (
    echo ERROR: Launch_NetState_Reconciler_v2.bat is not beside this file.
    echo Keep both launcher files together.
    pause
    exit /b 1
)
set "NSR_LAUNCHER=%LAUNCHER%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$launcher = $env:NSR_LAUNCHER; $desktop = [Environment]::GetFolderPath('Desktop'); $link = Join-Path $desktop 'NetState Reconciler.lnk'; $shell = New-Object -ComObject WScript.Shell; $shortcut = $shell.CreateShortcut($link); $shortcut.TargetPath = $launcher; $shortcut.WorkingDirectory = Split-Path $launcher; $shortcut.Description = 'Launch Cisco Packet Tracer, Packet Tracer MCP, and NetState Reconciler'; $shortcut.Save(); Write-Host ('Created: ' + $link)"
if errorlevel 1 (
    echo Could not create the desktop shortcut.
    pause
    exit /b 1
)
echo.
echo Desktop shortcut created: NetState Reconciler
pause
