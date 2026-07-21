# SPDX-License-Identifier: MPL-2.0
[CmdletBinding()]
param(
    [string]$Pack = "reference-chat",
    [string]$ModelsRoot = "./models",
    [string]$PacksRoot = "./packs",
    [string]$Catalog = "./configs/GRND0_MODEL_CATALOG.json",
    [Parameter(Mandatory = $true)][string]$LlamaSwap,
    [Parameter(Mandatory = $true)][string]$LlamaServer,
    [string]$Output = "./.grnd0/llama-swap-gpu.yaml",
    [int]$Port = 9292,
    [switch]$Background
)

$ErrorActionPreference = "Stop"

foreach ($path in @($LlamaSwap, $LlamaServer)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required inference executable is absent: $path"
    }
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}
$occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($occupied) {
    throw "The requested inference port is already in use."
}

$outputPath = [System.IO.Path]::GetFullPath($Output)
$outputDirectory = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

& uv run python tools/grnd0_models.py generate $Pack `
    --models-root $ModelsRoot `
    --packs-root $PacksRoot `
    --catalog $Catalog `
    --output $outputPath `
    --require-models `
    --runtime windows-host `
    --engine llama.cpp-vulkan `
    --server-command ([System.IO.Path]::GetFullPath($LlamaServer))
if ($LASTEXITCODE -ne 0) {
    throw "Inference configuration generation failed."
}

$arguments = @("--config", $outputPath, "--listen", ":$Port")
if ($Background) {
    $logPath = Join-Path $outputDirectory "llama-swap-gpu.log"
    $errorPath = Join-Path $outputDirectory "llama-swap-gpu.err.log"
    $process = Start-Process `
        -FilePath ([System.IO.Path]::GetFullPath($LlamaSwap)) `
        -ArgumentList $arguments `
        -RedirectStandardOutput $logPath `
        -RedirectStandardError $errorPath `
        -PassThru `
        -WindowStyle Hidden
    [System.IO.File]::WriteAllText(
        (Join-Path $outputDirectory "llama-swap-gpu.pid"),
        [string]$process.Id,
        [System.Text.Encoding]::ASCII
    )
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($health.StatusCode -eq 200) {
                Write-Output "GPU inference proxy ready at http://127.0.0.1:$Port"
                exit 0
            }
        } catch {
            if ($process.HasExited) {
                throw "GPU inference proxy exited during startup. Inspect $errorPath."
            }
        }
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "GPU inference proxy health check timed out. Inspect $errorPath."
}

& ([System.IO.Path]::GetFullPath($LlamaSwap)) @arguments
exit $LASTEXITCODE
