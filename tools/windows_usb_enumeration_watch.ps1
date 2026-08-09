#requires -Version 5.1

<#
.SYNOPSIS
Observe one HIDloom USB composite device across an externally initiated reboot.

.DESCRIPTION
This watcher is read-only with respect to Plug and Play devices. It takes
Get-PnpDevice -PresentOnly snapshots and subscribes to bounded
__InstanceOperationEvent notifications for Win32_PnPEntity. Only exact,
normalized HID child prefixes affect the verdict. It never enables, disables,
restarts, removes, updates, or installs a device or driver, and it never
reboots the target.

The shared JSON and Markdown reports contain only normalized instance prefixes
(for example HID\VID_1234&PID_5678&MI_00&COL01), not the machine-specific suffix
that follows the second backslash in a Windows PnP instance ID.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{4}$')]
    [string]$VendorId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9A-Fa-f]{4}$')]
    [string]$ProductId,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputDirectory,

    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$')]
    [string]$OutputPrefix,

    [ValidateRange(5, 900)]
    [int]$DurationSec = 120,

    [ValidateRange(50, 2000)]
    [int]$PollIntervalMs = 200
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RequiredSelectors = @(
    'MI_00&COL01',
    'MI_01',
    'MI_02'
)

$ExitBaselineMissing = 20
$ExitInitialDisconnectMissing = 21
$ExitNoReadd = 22
$ExitPostReadyDisconnect = 23
$ExitFinalNotReady = 24
$ExitInternalError = 70
$WmiWithinSec = 0.5

function ConvertTo-NormalizedInstancePrefix {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstanceId
    )

    $parts = $InstanceId.ToUpperInvariant() -split '\\'
    if ($parts.Count -lt 2) {
        return $parts[0]
    }
    return '{0}\{1}' -f $parts[0], $parts[1]
}

function Get-ExpectedHidPrefixes {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Vid,

        [Parameter(Mandatory = $true)]
        [string]$ProductId,

        [Parameter(Mandatory = $true)]
        [string[]]$Selectors
    )

    return @(
        foreach ($selector in $Selectors) {
            'HID\VID_{0}&PID_{1}&{2}' -f $Vid, $ProductId, $selector
        }
    )
}

function Get-TargetSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Vid,

        [Parameter(Mandatory = $true)]
        [string]$ProductId,

        [Parameter(Mandatory = $true)]
        [string[]]$Selectors,

        [Parameter(Mandatory = $true)]
        [string[]]$ExpectedPrefixes,

        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Stopwatch]$Stopwatch
    )

    $needle = 'VID_{0}&PID_{1}' -f $Vid, $ProductId
    $devices = @(
        Get-PnpDevice -PresentOnly -ErrorAction Stop |
            Where-Object { [string]$_.InstanceId -like ('*{0}*' -f $needle) } |
            ForEach-Object {
                [pscustomobject][ordered]@{
                    instance_prefix = ConvertTo-NormalizedInstancePrefix -InstanceId ([string]$_.InstanceId)
                    class = [string]$_.Class
                    status = ([string]$_.Status).ToUpperInvariant()
                }
            } |
            Sort-Object instance_prefix, class, status -Unique
    )

    $selectorStates = @(
        for ($index = 0; $index -lt $Selectors.Count; $index++) {
            $selector = $Selectors[$index]
            $expectedPrefix = $ExpectedPrefixes[$index]
            $matching = @(
                $devices | Where-Object {
                    $_.instance_prefix -eq $expectedPrefix
                }
            )
            $ready = @($matching | Where-Object { $_.status -eq 'OK' }).Count -gt 0
            [pscustomobject][ordered]@{
                selector = $selector
                expected_instance_prefix = $expectedPrefix
                ready = $ready
                instance_prefixes = @(
                    $matching | ForEach-Object { $_.instance_prefix } | Sort-Object -Unique
                )
                statuses = @(
                    $matching | ForEach-Object { $_.status } | Sort-Object -Unique
                )
            }
        }
    )

    [pscustomobject][ordered]@{
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        elapsed_ms = [Math]::Round($Stopwatch.Elapsed.TotalMilliseconds, 3)
        present_only = $true
        all_ready = @($selectorStates | Where-Object { -not $_.ready }).Count -eq 0
        selectors = $selectorStates
        devices = $devices
    }
}

function Get-SnapshotSignature {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Snapshot
    )

    return (@(
        $Snapshot.selectors | ForEach-Object {
            '{0}={1}:{2}:{3}' -f $_.selector, $_.ready,
                ($_.instance_prefixes -join ','), ($_.statuses -join ',')
        }
    ) -join '|')
}

function Add-WatchTransition {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.ArrayList]$Transitions,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Phase,

        [Parameter(Mandatory = $true)]
        [double]$ElapsedMs
    )

    [void]$Transitions.Add([pscustomobject][ordered]@{
        transition = $Name
        phase = $Phase
        elapsed_ms = [Math]::Round($ElapsedMs, 3)
    })
}

function Update-WatchState {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$State,

        [Parameter(Mandatory = $true)]
        [object]$Snapshot,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.ArrayList]$Transitions
    )

    $ready = [bool]$Snapshot.all_ready
    $elapsed = [double]$Snapshot.elapsed_ms
    switch ([string]$State['phase']) {
        'waiting_for_initial_disconnect' {
            if (-not $ready) {
                $State['phase'] = 'waiting_for_first_ready'
                $State['initial_disconnect_observed'] = $true
                $State['initial_disconnect_elapsed_ms'] = $elapsed
                Add-WatchTransition -Transitions $Transitions -Name 'initial_disconnect' `
                    -Phase ([string]$State['phase']) -ElapsedMs $elapsed
            }
        }
        'waiting_for_first_ready' {
            if ($ready) {
                $State['phase'] = 'first_ready'
                $State['first_readd_ready'] = $true
                $State['first_ready_elapsed_ms'] = $elapsed
                Add-WatchTransition -Transitions $Transitions -Name 'first_readd_ready' `
                    -Phase ([string]$State['phase']) -ElapsedMs $elapsed
            }
        }
        'first_ready' {
            if (-not $ready) {
                $State['phase'] = 'post_ready_disconnect'
                $State['post_ready_disconnect'] = $true
                $State['post_ready_disconnect_elapsed_ms'] = $elapsed
                Add-WatchTransition -Transitions $Transitions -Name 'post_first_ready_disconnect' `
                    -Phase ([string]$State['phase']) -ElapsedMs $elapsed
            }
        }
        'post_ready_disconnect' {
            if ($ready -and -not [bool]$State['post_ready_readd']) {
                $State['post_ready_readd'] = $true
                $State['post_ready_readd_elapsed_ms'] = $elapsed
                Add-WatchTransition -Transitions $Transitions -Name 'post_first_ready_readd' `
                    -Phase ([string]$State['phase']) -ElapsedMs $elapsed
            }
        }
        default {
            throw 'unknown watcher phase: {0}' -f $State['phase']
        }
    }
}

function Update-WatchStateFromDeletion {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$State,

        [Parameter(Mandatory = $true)]
        [double]$ElapsedMs,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.ArrayList]$Transitions
    )

    switch ([string]$State['phase']) {
        'waiting_for_initial_disconnect' {
            $State['phase'] = 'waiting_for_first_ready'
            $State['initial_disconnect_observed'] = $true
            $State['initial_disconnect_elapsed_ms'] = $ElapsedMs
            Add-WatchTransition -Transitions $Transitions -Name 'initial_disconnect_event' `
                -Phase ([string]$State['phase']) -ElapsedMs $ElapsedMs
        }
        'first_ready' {
            $firstReadyElapsedMs = $State['first_ready_elapsed_ms']
            if (
                $null -ne $firstReadyElapsedMs -and
                $ElapsedMs -le [double]$firstReadyElapsedMs
            ) {
                $State['delayed_initial_deletion_event_count'] =
                    [int]$State['delayed_initial_deletion_event_count'] + 1
                return
            }
            $State['phase'] = 'post_ready_disconnect'
            $State['post_ready_disconnect'] = $true
            $State['post_ready_disconnect_elapsed_ms'] = $ElapsedMs
            Add-WatchTransition -Transitions $Transitions -Name 'post_first_ready_disconnect_event' `
                -Phase ([string]$State['phase']) -ElapsedMs $ElapsedMs
        }
        'waiting_for_first_ready' { }
        'post_ready_disconnect' { }
        default {
            throw 'unknown watcher phase for deletion event: {0}' -f $State['phase']
        }
    }
}

function Receive-TargetPnpEvents {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceIdentifier,

        [Parameter(Mandatory = $true)]
        [string[]]$ExpectedPrefixes,

        [Parameter(Mandatory = $true)]
        [DateTime]$StartedAtUtc,

        [Parameter(Mandatory = $true)]
        [System.Diagnostics.Stopwatch]$Stopwatch,

        [Parameter(Mandatory = $true)]
        [hashtable]$State,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.ArrayList]$Transitions,

        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [System.Collections.ArrayList]$EventRecords
    )

    foreach ($pnpEvent in @(Get-Event -SourceIdentifier $SourceIdentifier -ErrorAction SilentlyContinue)) {
        try {
            $dequeuedAtUtc = [DateTime]::UtcNow
            $dequeuedElapsedMs = [Math]::Round($Stopwatch.Elapsed.TotalMilliseconds, 3)
            $newEvent = $pnpEvent.SourceEventArgs.NewEvent
            $operationClass = [string]$newEvent.CimSystemProperties.ClassName
            $targetInstance = $newEvent.TargetInstance
            $deviceId = [string]$targetInstance.DeviceID
            $instancePrefix = ConvertTo-NormalizedInstancePrefix -InstanceId $deviceId

            if ($ExpectedPrefixes -notcontains $instancePrefix) {
                $State['ignored_pnp_event_count'] = [int]$State['ignored_pnp_event_count'] + 1
                continue
            }

            $operation = switch ($operationClass) {
                '__InstanceCreationEvent' { 'creation' }
                '__InstanceDeletionEvent' { 'deletion' }
                '__InstanceModificationEvent' { 'modification' }
                default { 'unexpected' }
            }
            if ($operation -eq 'unexpected') {
                throw 'unexpected PnP operation event class: {0}' -f $operationClass
            }

            try {
                $eventAtUtc = [DateTime]::FromFileTimeUtc([int64]$newEvent.TIME_CREATED)
            }
            catch {
                $eventAtUtc = $pnpEvent.TimeGenerated.ToUniversalTime()
            }
            $eventElapsedMs = [Math]::Max(
                0.0,
                [Math]::Round(($eventAtUtc - $StartedAtUtc).TotalMilliseconds, 3)
            )
            [void]$EventRecords.Add([pscustomobject][ordered]@{
                operation = $operation
                expected_instance_prefix = $instancePrefix
                event_utc = $eventAtUtc.ToString('o')
                event_elapsed_ms = $eventElapsedMs
                dequeued_at_utc = $dequeuedAtUtc.ToString('o')
                dequeued_elapsed_ms = $dequeuedElapsedMs
                dequeue_delay_ms = [Math]::Round(($dequeuedAtUtc - $eventAtUtc).TotalMilliseconds, 3)
            })

            if ($operation -in @('creation', 'deletion')) {
                $watcherReadyElapsedMs = $State['watcher_ready_elapsed_ms']
                if (
                    $null -eq $watcherReadyElapsedMs -or
                    $eventElapsedMs -lt [double]$watcherReadyElapsedMs
                ) {
                    $State['target_operation_before_ready'] = $true
                }
            }

            if ($operation -eq 'deletion') {
                Update-WatchStateFromDeletion -State $State -ElapsedMs $eventElapsedMs `
                    -Transitions $Transitions
            }
        }
        finally {
            Remove-Event -EventIdentifier $pnpEvent.EventIdentifier -ErrorAction SilentlyContinue
        }
    }
}

function ConvertTo-MarkdownCell {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value) {
        return ''
    }
    return ([string]$Value).Replace('|', '\|').Replace("`r", ' ').Replace("`n", ' ')
}

function Format-ElapsedMs {
    param([AllowNull()][object]$Value)

    if ($null -eq $Value) {
        return ''
    }
    return ([double]$Value).ToString('0.000', [Globalization.CultureInfo]::InvariantCulture)
}

function Add-SnapshotMarkdown {
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [System.Collections.Generic.List[string]]$Lines,

        [Parameter(Mandatory = $true)]
        [string]$Title,

        [AllowNull()][object]$Snapshot
    )

    [void]$Lines.Add(('## {0}' -f $Title))
    [void]$Lines.Add('')
    [void]$Lines.Add('| selector | exact expected HID prefix | ready | normalized instance prefixes | statuses |')
    [void]$Lines.Add('| --- | --- | --- | --- | --- |')
    if ($null -eq $Snapshot) {
        [void]$Lines.Add('| (snapshot unavailable) | | false | | |')
    }
    else {
        foreach ($item in $Snapshot.selectors) {
            [void]$Lines.Add(('| {0} | {1} | {2} | {3} | {4} |' -f
                (ConvertTo-MarkdownCell $item.selector),
                (ConvertTo-MarkdownCell $item.expected_instance_prefix),
                ([bool]$item.ready).ToString().ToLowerInvariant(),
                (ConvertTo-MarkdownCell ($item.instance_prefixes -join '<br>')),
                (ConvertTo-MarkdownCell ($item.statuses -join ', '))))
        }
    }
    [void]$Lines.Add('')
}

function ConvertTo-WatchMarkdown {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Payload
    )

    $lines = [System.Collections.Generic.List[string]]::new()
    [void]$lines.Add('# Windows USB Enumeration Watch')
    [void]$lines.Add('')
    [void]$lines.Add(('- result: `{0}`' -f $Payload.result))
    [void]$lines.Add(('- reason: `{0}`' -f $Payload.reason))
    [void]$lines.Add(('- exit_code: `{0}`' -f $Payload.exit_code))
    [void]$lines.Add(('- started_at_utc: `{0}`' -f $Payload.started_at_utc))
    [void]$lines.Add(('- VID:PID: `{0}:{1}`' -f $Payload.target.vendor_id, $Payload.target.product_id))
    [void]$lines.Add(('- duration_sec: `{0}`' -f $Payload.watch.duration_sec))
    [void]$lines.Add(('- poll_interval_ms: `{0}`' -f $Payload.watch.poll_interval_ms))
    [void]$lines.Add(('- initial_disconnect_ms: `{0}`' -f (Format-ElapsedMs $Payload.watch.initial_disconnect_elapsed_ms)))
    [void]$lines.Add(('- first_readd_ready_ms: `{0}`' -f (Format-ElapsedMs $Payload.watch.first_ready_elapsed_ms)))
    [void]$lines.Add(('- post_first_ready_disconnect: `{0}`' -f ([bool]$Payload.checks.post_first_ready_disconnect_zero -eq $false)))
    [void]$lines.Add('')
    [void]$lines.Add('This report is observation-only. The watcher does not reboot a target or change a PnP device or driver.')
    [void]$lines.Add('Instance IDs are normalized before output; machine-specific suffixes are not recorded.')
    [void]$lines.Add('')

    Add-SnapshotMarkdown -Lines $lines -Title 'Baseline PresentOnly Snapshot' -Snapshot $Payload.baseline
    Add-SnapshotMarkdown -Lines $lines -Title 'Final PresentOnly Snapshot' -Snapshot $Payload.final

    [void]$lines.Add('## State Transitions')
    [void]$lines.Add('')
    [void]$lines.Add('| elapsed_ms | transition | resulting phase |')
    [void]$lines.Add('| ---: | --- | --- |')
    if (@($Payload.transitions).Count -eq 0) {
        [void]$lines.Add('| | (none) | |')
    }
    else {
        foreach ($transition in $Payload.transitions) {
            [void]$lines.Add(('| {0} | {1} | {2} |' -f
                (Format-ElapsedMs $transition.elapsed_ms),
                (ConvertTo-MarkdownCell $transition.transition),
                (ConvertTo-MarkdownCell $transition.phase)))
        }
    }
    [void]$lines.Add('')

    [void]$lines.Add('## Target PnP Instance Operation Timing')
    [void]$lines.Add('')
    [void]$lines.Add('| event_utc | event_elapsed_ms | dequeued_elapsed_ms | dequeue_delay_ms | operation | exact normalized prefix |')
    [void]$lines.Add('| --- | ---: | ---: | ---: | --- | --- |')
    if (@($Payload.pnp_instance_events).Count -eq 0) {
        [void]$lines.Add('| | | | | (none) | |')
    }
    else {
        foreach ($eventRecord in $Payload.pnp_instance_events) {
            [void]$lines.Add(('| {0} | {1} | {2} | {3} | {4} | {5} |' -f
                (ConvertTo-MarkdownCell $eventRecord.event_utc),
                (Format-ElapsedMs $eventRecord.event_elapsed_ms),
                (Format-ElapsedMs $eventRecord.dequeued_elapsed_ms),
                (Format-ElapsedMs $eventRecord.dequeue_delay_ms),
                (ConvertTo-MarkdownCell $eventRecord.operation),
                (ConvertTo-MarkdownCell $eventRecord.expected_instance_prefix)))
        }
    }
    [void]$lines.Add('')

    [void]$lines.Add('## Checks')
    [void]$lines.Add('')
    foreach ($name in @(
        'baseline_ready',
        'target_operation_before_ready_zero',
        'initial_disconnect_observed',
        'first_readd_ready',
        'post_first_ready_disconnect_zero',
        'final_ready'
    )) {
        $checkValue = [bool]$Payload.checks.PSObject.Properties[$name].Value
        [void]$lines.Add(('- {0}: `{1}`' -f $name, $checkValue.ToString().ToLowerInvariant()))
    }
    [void]$lines.Add('')

    return (($lines -join "`n") + "`n")
}

function Write-AtomicReportBundle {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Directory,

        [Parameter(Mandatory = $true)]
        [string]$Prefix,

        [Parameter(Mandatory = $true)]
        [string]$JsonText,

        [Parameter(Mandatory = $true)]
        [string]$MarkdownText
    )

    if (-not (Test-Path -LiteralPath $Directory -PathType Container)) {
        [void](New-Item -ItemType Directory -Path $Directory -Force)
    }
    $resolved = (Resolve-Path -LiteralPath $Directory).Path
    $bundlePath = Join-Path $resolved $Prefix
    if (Test-Path -LiteralPath $bundlePath) {
        throw 'refusing to overwrite an existing watcher report bundle: {0}' -f $Prefix
    }

    $temporarySuffix = [Guid]::NewGuid().ToString('N')
    $temporaryDirectory = Join-Path $resolved ('.{0}.{1}.tmp' -f $Prefix, $temporarySuffix)
    $jsonTemporary = Join-Path $temporaryDirectory 'report.json'
    $markdownTemporary = Join-Path $temporaryDirectory 'report.md'
    $encoding = [Text.UTF8Encoding]::new($false)
    try {
        [void](New-Item -ItemType Directory -Path $temporaryDirectory)
        [IO.File]::WriteAllText($jsonTemporary, $JsonText, $encoding)
        [IO.File]::WriteAllText($markdownTemporary, $MarkdownText, $encoding)
        Move-Item -LiteralPath $temporaryDirectory -Destination $bundlePath
    }
    catch {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            [IO.Directory]::Delete($temporaryDirectory, $true)
        }
        throw
    }

    return [pscustomobject]@{
        bundle = $bundlePath
        json = Join-Path $bundlePath 'report.json'
        markdown = Join-Path $bundlePath 'report.md'
    }
}

$VendorId = $VendorId.ToUpperInvariant()
$ProductId = $ProductId.ToUpperInvariant()
$ExpectedHidPrefixes = Get-ExpectedHidPrefixes -Vid $VendorId -ProductId $ProductId `
    -Selectors $RequiredSelectors
if ([string]::IsNullOrWhiteSpace($OutputPrefix)) {
    $OutputPrefix = 'hidloom-windows-usb-watch-{0}' -f [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
}

$startedAtUtcDate = [DateTime]::UtcNow
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$startedAtUtc = $startedAtUtcDate.ToString('o')
$sourceIdentifier = 'hidloom-usb-watch-{0}' -f [Guid]::NewGuid().ToString('N')
$subscriptionRegistered = $false
$baseline = $null
$finalSnapshot = $null
$internalError = ''
$exitCode = $ExitInternalError
$reason = 'collector_error'
$snapshots = [System.Collections.ArrayList]::new()
$transitions = [System.Collections.ArrayList]::new()
$pnpInstanceEvents = [System.Collections.ArrayList]::new()
$eventDrainGraceMs = [int][Math]::Ceiling(($WmiWithinSec * 1000.0) + $PollIntervalMs)
$state = @{
    phase = 'waiting_for_initial_disconnect'
    watcher_ready_elapsed_ms = $null
    target_operation_before_ready = $false
    ignored_pnp_event_count = 0
    delayed_initial_deletion_event_count = 0
    initial_disconnect_observed = $false
    initial_disconnect_elapsed_ms = $null
    first_readd_ready = $false
    first_ready_elapsed_ms = $null
    post_ready_disconnect = $false
    post_ready_disconnect_elapsed_ms = $null
    post_ready_readd = $false
    post_ready_readd_elapsed_ms = $null
}

try {
    $withinText = $WmiWithinSec.ToString('0.0', [Globalization.CultureInfo]::InvariantCulture)
    $query = "SELECT * FROM __InstanceOperationEvent WITHIN $withinText WHERE TargetInstance ISA 'Win32_PnPEntity'"
    [void](Register-CimIndicationEvent -Namespace 'root/cimv2' -Query $query `
        -SourceIdentifier $sourceIdentifier)
    $subscriptionRegistered = $true

    $baseline = Get-TargetSnapshot -Vid $VendorId -ProductId $ProductId `
        -Selectors $RequiredSelectors -ExpectedPrefixes $ExpectedHidPrefixes `
        -Stopwatch $stopwatch
    [void]$snapshots.Add($baseline)
    $lastSignature = Get-SnapshotSignature -Snapshot $baseline

    if (-not [bool]$baseline.all_ready) {
        $exitCode = $ExitBaselineMissing
        $reason = 'baseline_missing_required_selector'
    }
    else {
        Add-WatchTransition -Transitions $transitions -Name 'baseline_ready' `
            -Phase ([string]$state['phase']) -ElapsedMs ([double]$baseline.elapsed_ms)

        Receive-TargetPnpEvents -SourceIdentifier $sourceIdentifier `
            -ExpectedPrefixes $ExpectedHidPrefixes -StartedAtUtc $startedAtUtcDate `
            -Stopwatch $stopwatch -State $state -Transitions $transitions `
            -EventRecords $pnpInstanceEvents
        $armedSnapshot = Get-TargetSnapshot -Vid $VendorId -ProductId $ProductId `
            -Selectors $RequiredSelectors -ExpectedPrefixes $ExpectedHidPrefixes `
            -Stopwatch $stopwatch
        $armedSignature = Get-SnapshotSignature -Snapshot $armedSnapshot
        if ($armedSignature -ne $lastSignature) {
            [void]$snapshots.Add($armedSnapshot)
            $lastSignature = $armedSignature
        }
        Update-WatchState -State $state -Snapshot $armedSnapshot -Transitions $transitions

        if ([bool]$state['target_operation_before_ready'] -or -not [bool]$armedSnapshot.all_ready) {
            $exitCode = $ExitBaselineMissing
            $reason = 'target_changed_while_arming'
        }
        else {
            $watchArmedElapsedMs = $stopwatch.Elapsed.TotalMilliseconds
            $state['watcher_ready_elapsed_ms'] = $watchArmedElapsedMs
            Write-Host ('WATCHER_READY VID_{0}&PID_{1} duration={2}s' -f $VendorId, $ProductId, $DurationSec)

            $deadlineMs = $watchArmedElapsedMs + ($DurationSec * 1000.0)
            while ($stopwatch.Elapsed.TotalMilliseconds -lt $deadlineMs) {
                Start-Sleep -Milliseconds $PollIntervalMs

                Receive-TargetPnpEvents -SourceIdentifier $sourceIdentifier `
                    -ExpectedPrefixes $ExpectedHidPrefixes -StartedAtUtc $startedAtUtcDate `
                    -Stopwatch $stopwatch -State $state -Transitions $transitions `
                    -EventRecords $pnpInstanceEvents

                $snapshot = Get-TargetSnapshot -Vid $VendorId -ProductId $ProductId `
                    -Selectors $RequiredSelectors -ExpectedPrefixes $ExpectedHidPrefixes `
                    -Stopwatch $stopwatch
                $signature = Get-SnapshotSignature -Snapshot $snapshot
                if ($signature -ne $lastSignature) {
                    [void]$snapshots.Add($snapshot)
                    $lastSignature = $signature
                }
                Update-WatchState -State $state -Snapshot $snapshot -Transitions $transitions
            }

            Start-Sleep -Milliseconds $eventDrainGraceMs
            Receive-TargetPnpEvents -SourceIdentifier $sourceIdentifier `
                -ExpectedPrefixes $ExpectedHidPrefixes -StartedAtUtc $startedAtUtcDate `
                -Stopwatch $stopwatch -State $state -Transitions $transitions `
                -EventRecords $pnpInstanceEvents

            $finalSnapshot = Get-TargetSnapshot -Vid $VendorId -ProductId $ProductId `
                -Selectors $RequiredSelectors -ExpectedPrefixes $ExpectedHidPrefixes `
                -Stopwatch $stopwatch
            $finalSignature = Get-SnapshotSignature -Snapshot $finalSnapshot
            if ($finalSignature -ne $lastSignature) {
                [void]$snapshots.Add($finalSnapshot)
            }
            Update-WatchState -State $state -Snapshot $finalSnapshot -Transitions $transitions

            if ([bool]$state['target_operation_before_ready']) {
                $exitCode = $ExitBaselineMissing
                $reason = 'target_changed_before_watcher_ready'
            }
            elseif ([bool]$state['post_ready_disconnect']) {
                $exitCode = $ExitPostReadyDisconnect
                $reason = 'post_first_ready_disconnect_observed'
            }
            elseif (-not [bool]$state['initial_disconnect_observed']) {
                $exitCode = $ExitInitialDisconnectMissing
                $reason = 'initial_disconnect_not_observed'
            }
            elseif (-not [bool]$state['first_readd_ready']) {
                $exitCode = $ExitNoReadd
                $reason = 'no_readd_before_timeout'
            }
            elseif (-not [bool]$finalSnapshot.all_ready) {
                $exitCode = $ExitFinalNotReady
                $reason = 'final_required_selector_not_ready'
            }
            else {
                $exitCode = 0
                $reason = 'pass'
            }
        }
    }
}
catch {
    $exitCode = $ExitInternalError
    $reason = 'collector_error'
    $internalError = $_.Exception.Message
}
finally {
    if ($subscriptionRegistered) {
        Unregister-Event -SourceIdentifier $sourceIdentifier -ErrorAction SilentlyContinue
        foreach ($queuedEvent in @(Get-Event -SourceIdentifier $sourceIdentifier -ErrorAction SilentlyContinue)) {
            Remove-Event -EventIdentifier $queuedEvent.EventIdentifier -ErrorAction SilentlyContinue
        }
    }
    if ($null -eq $finalSnapshot) {
        try {
            $finalSnapshot = Get-TargetSnapshot -Vid $VendorId -ProductId $ProductId `
                -Selectors $RequiredSelectors -ExpectedPrefixes $ExpectedHidPrefixes `
                -Stopwatch $stopwatch
        }
        catch {
            if ([string]::IsNullOrEmpty($internalError)) {
                $internalError = $_.Exception.Message
            }
        }
    }
}

$baselineReady = $null -ne $baseline -and [bool]$baseline.all_ready
$finalReady = $null -ne $finalSnapshot -and [bool]$finalSnapshot.all_ready
$payload = [pscustomobject][ordered]@{
    schema = 'hidloom.windows-usb-enumeration-watch.v1'
    result = $(if ($exitCode -eq 0) { 'pass' } else { 'fail' })
    exit_code = $exitCode
    reason = $reason
    started_at_utc = $startedAtUtc
    completed_at_utc = [DateTime]::UtcNow.ToString('o')
    target = [pscustomobject][ordered]@{
        vendor_id = $VendorId
        product_id = $ProductId
        required_selectors = $RequiredSelectors
        expected_hid_prefixes = $ExpectedHidPrefixes
        instance_id_output = 'normalized_prefix_without_machine_suffix'
    }
    watch = [pscustomobject][ordered]@{
        duration_sec = $DurationSec
        poll_interval_ms = $PollIntervalMs
        wmi_within_sec = $WmiWithinSec
        event_drain_grace_ms = $eventDrainGraceMs
        observed_elapsed_ms = [Math]::Round($stopwatch.Elapsed.TotalMilliseconds, 3)
        watcher_ready_elapsed_ms = $state['watcher_ready_elapsed_ms']
        ignored_pnp_event_count = [int]$state['ignored_pnp_event_count']
        delayed_initial_deletion_event_count = [int]$state['delayed_initial_deletion_event_count']
        final_phase = [string]$state['phase']
        initial_disconnect_elapsed_ms = $state['initial_disconnect_elapsed_ms']
        first_ready_elapsed_ms = $state['first_ready_elapsed_ms']
        post_ready_disconnect_elapsed_ms = $state['post_ready_disconnect_elapsed_ms']
        post_ready_readd_elapsed_ms = $state['post_ready_readd_elapsed_ms']
    }
    checks = [pscustomobject][ordered]@{
        baseline_ready = $baselineReady
        target_operation_before_ready_zero = -not [bool]$state['target_operation_before_ready']
        initial_disconnect_observed = [bool]$state['initial_disconnect_observed']
        first_readd_ready = [bool]$state['first_readd_ready']
        post_first_ready_disconnect_zero = -not [bool]$state['post_ready_disconnect']
        final_ready = $finalReady
    }
    baseline = $baseline
    final = $finalSnapshot
    transitions = @($transitions)
    state_snapshots = @($snapshots)
    pnp_instance_events = @($pnpInstanceEvents)
    internal_error = $internalError
}

$jsonText = ($payload | ConvertTo-Json -Depth 10) + "`n"
$markdownText = ConvertTo-WatchMarkdown -Payload $payload
try {
    $published = Write-AtomicReportBundle -Directory $OutputDirectory -Prefix $OutputPrefix `
        -JsonText $jsonText -MarkdownText $markdownText
    Write-Host ('REPORT_BUNDLE {0}' -f $published.bundle)
    Write-Host ('JSON_REPORT {0}' -f $published.json)
    Write-Host ('MARKDOWN_REPORT {0}' -f $published.markdown)
}
catch {
    [Console]::Error.WriteLine(
        ('failed to publish watcher report bundle atomically: {0}' -f $_.Exception.Message)
    )
    exit $ExitInternalError
}

exit $exitCode
