param(
    [string]$Vid = "1D6B",
    [string]$ProductId = "0105",
    [string]$MainLayout = "jp_106",
    [string]$SubLayout = "us_101",
    [string]$MainInterface = "MI_00",
    [string]$SubInterface = "MI_02",
    [switch]$DeviceParameters,
    [switch]$Apply,
    [switch]$Clear,
    [switch]$List
)

$ErrorActionPreference = "Stop"

function Normalize-Hex4($Value, $Name) {
    $v = ($Value -replace "^0x", "").ToUpperInvariant()
    if ($v -notmatch "^[0-9A-F]{4}$") {
        throw "$Name must be a 4-digit hex value"
    }
    return $v
}

function Layout-Values($Layout) {
    switch (($Layout -replace "-", "_").ToLowerInvariant()) {
        "jp_106" { return @{ Type = 7; Subtype = 2 } }
        "jis" { return @{ Type = 7; Subtype = 2 } }
        "us_101" { return @{ Type = 7; Subtype = 0 } }
        "us" { return @{ Type = 7; Subtype = 0 } }
        "none" { return $null }
        default { throw "Unknown layout: $Layout" }
    }
}

function Get-MatchingKeyboardKeys($Vid, $ProductId, $Interface) {
    $root = "HKLM:\SYSTEM\CurrentControlSet\Enum\HID"
    $pattern = "VID_${Vid}&PID_${ProductId}"
    Get-ChildItem $root -Recurse -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -like "*$pattern*" -and $_.Name -like "*$Interface*"
    } | Where-Object {
        $p = Get-ItemProperty -Path $_.PsPath -ErrorAction SilentlyContinue
        $ids = @($p.HardwareID) -join ";"
        ($p.DeviceDesc -match "Keyboard") -or ($ids -match "HID_DEVICE_SYSTEM_KEYBOARD|UP:0001_U:0006")
    }
}

function Show-Key($Key) {
    $p = Get-ItemProperty -Path $Key.PsPath -ErrorAction SilentlyContinue
    [pscustomobject]@{
        RegistryPath = $Key.Name
        DeviceDesc = $p.DeviceDesc
        HardwareID = (@($p.HardwareID) -join ";")
        KeyboardTypeOverride = $p.KeyboardTypeOverride
        KeyboardSubtypeOverride = $p.KeyboardSubtypeOverride
        DeviceParametersOverrideKeyboardType = (Get-ItemProperty -Path (Join-Path $Key.PsPath "Device Parameters") -Name OverrideKeyboardType -ErrorAction SilentlyContinue).OverrideKeyboardType
        DeviceParametersOverrideKeyboardSubtype = (Get-ItemProperty -Path (Join-Path $Key.PsPath "Device Parameters") -Name OverrideKeyboardSubtype -ErrorAction SilentlyContinue).OverrideKeyboardSubtype
    }
}

function Apply-Layout($Keys, $LayoutName, $Label) {
    $values = Layout-Values $LayoutName
    foreach ($key in $Keys) {
        $dp = Join-Path $key.PsPath "Device Parameters"
        if ($null -eq $values) {
            Remove-ItemProperty -Path $key.PsPath -Name KeyboardTypeOverride -ErrorAction SilentlyContinue
            Remove-ItemProperty -Path $key.PsPath -Name KeyboardSubtypeOverride -ErrorAction SilentlyContinue
            Remove-ItemProperty -Path $dp -Name OverrideKeyboardType -ErrorAction SilentlyContinue
            Remove-ItemProperty -Path $dp -Name OverrideKeyboardSubtype -ErrorAction SilentlyContinue
            Write-Output "${Label} cleared: $($key.Name)"
            continue
        }
        New-ItemProperty -Path $key.PsPath -Name KeyboardTypeOverride -PropertyType DWord -Value $values.Type -Force | Out-Null
        New-ItemProperty -Path $key.PsPath -Name KeyboardSubtypeOverride -PropertyType DWord -Value $values.Subtype -Force | Out-Null
        if ($DeviceParameters) {
            if (-not (Test-Path $dp)) {
                New-Item -Path $dp -Force | Out-Null
            }
            New-ItemProperty -Path $dp -Name OverrideKeyboardType -PropertyType DWord -Value $values.Type -Force | Out-Null
            New-ItemProperty -Path $dp -Name OverrideKeyboardSubtype -PropertyType DWord -Value $values.Subtype -Force | Out-Null
        }
        Write-Output "${Label} set ${LayoutName}: $($key.Name)"
    }
}

$Vid = Normalize-Hex4 $Vid "Vid"
$ProductId = Normalize-Hex4 $ProductId "ProductId"

$mainKeys = @(Get-MatchingKeyboardKeys $Vid $ProductId $MainInterface)
$subKeys = @(Get-MatchingKeyboardKeys $Vid $ProductId $SubInterface)

Write-Output "Target VID/PID: VID_$Vid PID_$ProductId"
Write-Output "Main interface: $MainInterface ($($mainKeys.Count) keyboard key(s))"
Write-Output "Sub interface:  $SubInterface ($($subKeys.Count) keyboard key(s))"

if ($List -or (-not $Apply -and -not $Clear)) {
    $mainKeys + $subKeys | ForEach-Object { Show-Key $_ } | Format-List
}

if ($Clear) {
    Apply-Layout $mainKeys "none" "main"
    Apply-Layout $subKeys "none" "sub"
}

if ($Apply) {
    Apply-Layout $mainKeys $MainLayout "main"
    Apply-Layout $subKeys $SubLayout "sub"
    Write-Output "Disconnect/reconnect the USB gadget, or disable/enable the keyboard devices, before judging behavior."
}
