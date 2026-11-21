#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^[a-zA-Z0-9_=+.-]{1,32}$')]
    [string]$Tunnel,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$programDirectory = [Environment]::GetFolderPath('ProgramFiles')
$wg = Join-Path $programDirectory 'WireGuard\wg.exe'
if (-not (Test-Path -LiteralPath $wg)) { throw 'WireGuard for Windows is required.' }
if (-not $Check) {
    $folder = Join-Path $programDirectory 'WgvpsFailover'
    New-Item -Path $folder -ItemType Directory -Force | Out-Null
    $script = Join-Path $folder 'wireguard-failover.ps1'
    Copy-Item -LiteralPath $PSCommandPath -Destination $script -Force
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -Tunnel `"$Tunnel`" -Check"
    $action = New-ScheduledTaskAction -Execute $powershell -Argument $arguments
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(10) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName "WgvpsFailover-$Tunnel" -User SYSTEM -RunLevel Highest -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    return
}

# Query only public peer information. Leave inactive tunnels alone.
if ((Get-Service -Name ('WireGuardTunnel$' + $Tunnel) -ErrorAction SilentlyContinue).Status -ne 'Running') { return }
$endpoints = @(& $wg show $Tunnel endpoints 2>$null)
if ($LASTEXITCODE -ne 0 -or $endpoints.Count -ne 1) { return }
if ($endpoints[0] -notmatch '^(\S+)\s+((?:\d+\.){3}\d+):(51820|51821)$') { return }
$peer, $address, $port = $Matches[1], $Matches[2], $Matches[3]
$handshake = & $wg show $Tunnel latest-handshakes
if ($LASTEXITCODE -ne 0 -or $handshake -notmatch ('^' + [regex]::Escape($peer) + '\s+(\d+)$')) { return }
if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$Matches[1] -lt 180) { return }

# Give a newly activated tunnel time to handshake before changing its endpoint.
$initial = $endpoints[0]
$ping = New-Object System.Net.NetworkInformation.Ping
try {
    foreach ($attempt in 1..3) {
        try {
            if ($ping.Send('10.66.77.1', 2000).Status -eq 'Success') { return }
        } catch [System.Net.NetworkInformation.PingException] {}
        Start-Sleep -Seconds 5
    }
} finally { $ping.Dispose() }
$current = & $wg show $Tunnel endpoints
if ($LASTEXITCODE -ne 0 -or $current -ne $initial) { return }
$handshake = & $wg show $Tunnel latest-handshakes
if ($LASTEXITCODE -ne 0 -or $handshake -notmatch ('^' + [regex]::Escape($peer) + '\s+(\d+)$')) { return }
if ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$Matches[1] -lt 180) { return }
$next = if ($port -eq '51820') { 51821 } else { 51820 }
& $wg set $Tunnel peer $peer endpoint "${address}:$next"
exit $LASTEXITCODE
