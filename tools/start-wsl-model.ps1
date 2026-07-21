# SPDX-License-Identifier: MPL-2.0
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$WslServerPath,
    [Parameter(Mandatory = $true)][string]$WslModelPath,
    [string]$Distro = "",
    [string]$WslUser = "root",
    [int]$Port = 9300,
    [int]$HealthTimeoutSeconds = 120,
    [string[]]$ServerArguments = @()
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw "WSL is unavailable."
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}
if ($HealthTimeoutSeconds -lt 1 -or $HealthTimeoutSeconds -gt 900) {
    throw "Health timeout must be between 1 and 900 seconds."
}
foreach ($path in @($WslServerPath, $WslModelPath)) {
    if ($path -notmatch '^/[A-Za-z0-9._/+\-]+$') {
        throw "WSL executable and model paths must be absolute and shell-safe."
    }
}
if ($WslUser -notmatch '^[A-Za-z_][A-Za-z0-9_-]*$') {
    throw "WSL user contains unsupported characters."
}
foreach ($argument in $ServerArguments) {
    if ($argument -notmatch '^[A-Za-z0-9._:/=+\-]+$') {
        throw "A server argument contains unsupported shell characters."
    }
}

if (-not $Distro) {
    $Distro = (
        wsl.exe --list --quiet |
            ForEach-Object { ($_ -replace '\x00', '').Trim() } |
            Where-Object { $_ } |
            Select-Object -First 1
    )
}
if (-not $Distro -or $Distro -notmatch '^[A-Za-z0-9._+\-]+$') {
    throw "A valid WSL distribution is required."
}

$occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($occupied) {
    throw "The requested model port is already in use."
}

& wsl.exe -d $Distro -u $WslUser -- sh -lc "test -x '$WslServerPath' -a -f '$WslModelPath'"
if ($LASTEXITCODE -ne 0) {
    throw "The WSL server executable or model is absent."
}

$stateRoot = Join-Path (Get-Location) ".grnd0"
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$scriptName = "grnd0-model-$Port.sh"
$wslScriptPath = "/tmp/$scriptName"
$wslLogPath = "/tmp/grnd0-model-$Port.log"
$tokens = @(
    $WslServerPath,
    "--model", $WslModelPath,
    "--host", "0.0.0.0",
    "--port", [string]$Port
) + $ServerArguments
$command = ($tokens | ForEach-Object { "'$_'" }) -join " "
$launchScript = "#!/bin/sh`nexec $command >> '$wslLogPath' 2>&1`n"

$distributionRoot = "\\wsl.localhost\$Distro"
$relativeScriptPath = $wslScriptPath.TrimStart('/') -replace '/', '\'
$windowsScriptPath = Join-Path $distributionRoot $relativeScriptPath
[System.IO.File]::WriteAllText(
    $windowsScriptPath,
    $launchScript,
    [System.Text.UTF8Encoding]::new($false)
)
& wsl.exe -d $Distro -u $WslUser -- chmod 700 $wslScriptPath
if ($LASTEXITCODE -ne 0) {
    throw "The WSL launch script could not be prepared."
}

$process = Start-Process wsl.exe `
    -ArgumentList @("-d", $Distro, "-u", $WslUser, "--", "sh", $wslScriptPath) `
    -PassThru `
    -WindowStyle Hidden
[System.IO.File]::WriteAllText(
    (Join-Path $stateRoot "wsl-model-$Port.pid"),
    [string]$process.Id,
    [System.Text.Encoding]::ASCII
)

$deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
do {
    Start-Sleep -Milliseconds 500
    if ($process.HasExited) {
        throw "The WSL model process exited during startup. Inspect $wslLogPath in $Distro."
    }
    try {
        $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.StatusCode -eq 200) {
            Write-Output "WSL model ready at http://127.0.0.1:$Port/v1"
            exit 0
        }
    } catch {
    }
} while ([DateTime]::UtcNow -lt $deadline)

throw "The WSL model health check timed out. Inspect $wslLogPath in $Distro."
