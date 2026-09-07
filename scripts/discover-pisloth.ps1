[CmdletBinding()]
param(
    [string]$TargetName = "pisloth.local",
    [int]$TimeoutMs = 1500
)

$addresses = @(
    # Omitting -Type is intentional: Windows may bypass mDNS for an explicit A query.
    Resolve-DnsName -Name $TargetName -ErrorAction SilentlyContinue |
        Where-Object { $_.Type -eq "A" -and $_.IPAddress } |
        Select-Object -ExpandProperty IPAddress -Unique
)

if ($addresses.Count -eq 0) {
    [ordered]@{
        hostname = $TargetName
        found = $false
        ipv4 = @()
        ssh = $false
    } | ConvertTo-Json
    exit 1
}

$sshAvailable = $false
foreach ($address in $addresses) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connected = $client.ConnectAsync($address, 22).Wait($TimeoutMs)
        if ($connected -and $client.Connected) {
            $sshAvailable = $true
            break
        }
    }
    catch {
        # Discovery is informational; an unreachable port is reported below.
    }
    finally {
        $client.Dispose()
    }
}

[ordered]@{
    hostname = $TargetName
    found = $true
    ipv4 = $addresses
    ssh = $sshAvailable
} | ConvertTo-Json

if (-not $sshAvailable) {
    exit 2
}
