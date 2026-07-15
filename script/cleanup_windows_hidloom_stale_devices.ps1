#Requires -RunAsAdministrator
param(
    [string]$Pattern = "VID_1D6B&PID_0105"
)

$ErrorActionPreference = "Continue"

$logPath = Join-Path (Get-Location) "windows-hidloom-stale-device-cleanup.log"
Start-Transcript -Path $logPath -Append | Out-Null

Write-Output "HIDloom stale device cleanup"
Write-Output "Pattern: $Pattern"
Write-Output ""

$stale = @(Get-PnpDevice | Where-Object {
    $_.InstanceId -match [regex]::Escape($Pattern) -and $_.Status -eq "Unknown"
} | Sort-Object InstanceId)

Write-Output "Stale device instances found: $($stale.Count)"
foreach ($device in $stale) {
    Write-Output "Removing: $($device.InstanceId)"
    & pnputil /remove-device "$($device.InstanceId)"
}

Write-Output ""
Write-Output "Scanning devices..."
& pnputil /scan-devices

Write-Output ""
Write-Output "Remaining matching devices:"
Get-PnpDevice | Where-Object {
    $_.InstanceId -match [regex]::Escape($Pattern)
} | Sort-Object Status,Class,InstanceId |
    Select-Object Status,Class,FriendlyName,InstanceId |
    Format-List

Write-Output ""
Write-Output "Log: $logPath"
Stop-Transcript | Out-Null

Read-Host "Press Enter to close"
