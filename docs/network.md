# Finding PiSloth on Wi-Fi

Use the mDNS hostname instead of a remembered DHCP address:

```powershell
.\scripts\discover-pisloth.ps1
ssh pi@pisloth.local
```

The discovery command resolves PiSloth's current IPv4 address and checks TCP
port 22. It does not store or transmit an SSH password. This continues to work
when the router changes the subnet or gives the robot another address, provided
the PC and Pi can reach each other and mDNS is available.

Observed on 2026-09-07:

- hostname: `pisloth.local`
- current address: `192.168.0.22` (informational, not configuration)
- Wi-Fi MAC: `D8:3A:DD:21:40:A2`
- SSH ED25519 fingerprint:
  `SHA256:PFs+EmfC+A8mbt6XDkAsh9BvP91Vrp2WMT3kBbXP7A8`

The fingerprint identifies the SSH server even if its IP changes. Stop and
investigate if SSH presents a different fingerprint after an ordinary network
change. A deliberate OS re-image generates a new key and must be recorded
separately.

For an additional convenience layer, the router can reserve one address for the
MAC above. The hostname remains the primary connection method because it does
not depend on a particular `192.168.x.x` subnet.
