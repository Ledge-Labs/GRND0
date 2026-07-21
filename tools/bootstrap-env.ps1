# SPDX-License-Identifier: MPL-2.0
[CmdletBinding()]
param(
    [string]$Example = ".env.example",
    [string]$Output = ".env"
)

$ErrorActionPreference = "Stop"
if (Test-Path -LiteralPath $Output) {
    throw "The output environment file already exists."
}
if (-not (Test-Path -LiteralPath $Example)) {
    throw "The environment example is absent."
}

function New-Token([int]$Bytes = 32) {
    $buffer = [byte[]]::new($Bytes)
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($buffer) } finally { $generator.Dispose() }
    return -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

$apiKey = New-Token
$gatewayToken = New-Token
$capabilityToken = New-Token
$giteaPassword = New-Token 24
$giteaEmail = "operator-$($giteaPassword.Substring(0, 8))$([char]64)localhost.invalid"
$lines = Get-Content -LiteralPath $Example | ForEach-Object {
    if ($_ -eq "GRND0_API_KEY=") { "GRND0_API_KEY=$apiKey" }
    elseif ($_ -eq "GRND0_GATEWAY_TOKEN=") { "GRND0_GATEWAY_TOKEN=$gatewayToken" }
    elseif ($_ -eq "GRND0_CAPABILITY_TOKEN=") { "GRND0_CAPABILITY_TOKEN=$capabilityToken" }
    elseif ($_ -eq "GRND0_GITEA_PASSWORD=") { "GRND0_GITEA_PASSWORD=$giteaPassword" }
    elseif ($_ -eq "GRND0_GITEA_EMAIL=") { "GRND0_GITEA_EMAIL=$giteaEmail" }
    else { $_ }
}
[System.IO.File]::WriteAllLines((Join-Path (Get-Location) $Output), $lines, [System.Text.UTF8Encoding]::new($false))
Write-Output "Environment credentials generated."
