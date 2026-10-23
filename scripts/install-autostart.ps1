# Run once in an administrator PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\scripts\install-autostart.ps1
#
# Registers a scheduled task that runs start-logbook.ps1 every time the current
# user logs in, and makes sure the firewall allows port 8000.

$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw 'Run this in an administrator PowerShell.' }

$script = Join-Path $PSScriptRoot 'start-logbook.ps1'
$user = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName 'Logbook autostart' -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Write-Host "Task 'Logbook autostart' registered for $user (runs at logon)."

if (-not (Get-NetFirewallRule -DisplayName 'Logbook 8000' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName 'Logbook 8000' -Direction Inbound -Protocol TCP `
        -LocalPort 8000 -Action Allow | Out-Null
    Write-Host 'Firewall rule added for TCP 8000.'
}

Write-Host 'Starting the logbook now...'
& $script
