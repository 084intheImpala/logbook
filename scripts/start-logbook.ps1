# Starts the logbook on a Windows 10 PC that runs Docker inside WSL2 (NAT mode).
#
# 1. starts WSL + Docker and brings the containers up
# 2. keeps WSL alive (it shuts down when idle)
# 3. points a Windows port proxy at WSL's current internal IP, so other PCs can
#    reach the app at http://<this-pc-ip>:8000
#
# Needs administrator rights (netsh portproxy). Installed by install-autostart.ps1.

$ErrorActionPreference = 'Stop'
$Port = 8000
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$LogFile = Join-Path $PSScriptRoot 'start-logbook.log'

function Log($msg) {
    $line = "$(Get-Date -Format 's')  $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

try {
    $wslDir = (wsl wslpath -a ($ProjectDir -replace '\\', '/')).Trim()
    Log "Project: $ProjectDir  (WSL: $wslDir)"

    # Wait until WSL answers, then start Docker and the containers.
    $bash = @'
service docker start >/dev/null 2>&1
for i in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 2; done
cd 'WSLDIR' && docker compose up -d
'@ -replace 'WSLDIR', $wslDir
    $bash = $bash -replace "`r", ''
    # docker compose reports progress on stderr; don't let that abort the script.
    $ErrorActionPreference = 'Continue'
    wsl -u root -- bash -c $bash 2>&1 | ForEach-Object { Log "docker: $_" }
    $dockerExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($dockerExit -ne 0) { throw "docker compose failed (exit code $dockerExit)" }

    # WSL stops its VM when nothing is running in it; keep one process alive.
    $alive = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
        Where-Object { $_.CommandLine -match 'sleep infinity' }
    if (-not $alive) {
        Start-Process wsl -ArgumentList '-u', 'root', '--', 'sleep', 'infinity' -WindowStyle Hidden
        Log 'Started WSL keep-alive'
    }

    # Point the port proxy at WSL's current IP (it changes after every restart).
    $wslIp = ((wsl -u root -- hostname -I).Trim() -split '\s+')[0]
    if (-not $wslIp) { throw 'Could not get the WSL IP address' }
    netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port 2>&1 | Out-Null
    netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$Port connectaddress=$wslIp connectport=$Port | Out-Null
    Log "Port proxy: 0.0.0.0:$Port -> ${wslIp}:$Port"

    # Check the app answers.
    $ok = $false
    foreach ($i in 1..15) {
        try {
            Invoke-WebRequest -Uri "http://localhost:$Port/" -UseBasicParsing -TimeoutSec 3 | Out-Null
            $ok = $true; break
        } catch {
            # A 4xx still means the app is up.
            if ($_.Exception.Response) { $ok = $true; break }
            Start-Sleep -Seconds 2
        }
    }
    if ($ok) { Log "Logbook is answering on port $Port" }
    else { Log "WARNING: nothing answered on http://localhost:$Port/ - try: sudo docker compose restart app" }
} catch {
    Log "ERROR: $_"
    exit 1
}
