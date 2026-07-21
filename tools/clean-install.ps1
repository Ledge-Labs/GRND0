# SPDX-License-Identifier: MPL-2.0
[CmdletBinding()]
param([switch]$KeepRunning)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath "docker-compose.yml")) {
    throw "clean-install.ps1 must run from the repository root"
}
if (Test-Path -LiteralPath ".env") {
    throw "clean-install proof requires an absent .env"
}

& .\tools\bootstrap-env.ps1 -Example .env.example -Output .env
$lines = Get-Content -LiteralPath .env | ForEach-Object {
    if ($_ -match '^GRND0_STUB_MODE=') { 'GRND0_STUB_MODE=true' } else { $_ }
}
[System.IO.File]::WriteAllLines((Join-Path (Get-Location) ".env"), $lines, [System.Text.UTF8Encoding]::new($false))
$apiKey = (($lines | Where-Object { $_ -match '^GRND0_API_KEY=' }) -split '=', 2)[1]

try {
    docker compose up --build -d --wait
    if ($LASTEXITCODE -ne 0) { throw "core startup failed" }
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/healthz" -TimeoutSec 10
    if ($health.status -ne "ok") { throw "health contract failed" }
    $inference = Invoke-RestMethod -Uri "http://127.0.0.1:9292/v1/models" -TimeoutSec 10
    if ($inference.object -ne "list") { throw "local inference service health failed" }
    $headers = @{ Authorization = "Bearer $apiKey" }
    $body = @{ model = "reference-chat"; messages = @(@{ role = "user"; content = "clean-install" }) } | ConvertTo-Json -Depth 4
    $chat = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/chat/completions" -Headers $headers -ContentType "application/json" -Body $body -TimeoutSec 30
    $chatText = [string]$chat.choices[0].message.content
    if (-not $chatText.StartsWith("stub:clean-install")) { throw "stub chat contract failed" }
    if (([regex]::Matches($chatText, '(?m)^-\s+\S')).Count -lt 2) { throw "focused branch-offer contract failed" }
    if ($chat.grnd0_receipt.plan.deliverable -ne "answer") { throw "typed plan contract failed" }
    if ($chat.grnd0_receipt.route.Count -lt 4) { throw "conversation loop did not execute its named harnesses" }
    if ($chat.grnd0_receipt.discourse.commit_count -ne 1) { throw "discourse commit invariant failed" }
    $sessionId = $chat.grnd0_receipt.session_id
    $state = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health/discourse-state?session_id=$sessionId" -Headers $headers -TimeoutSec 10
    if ($state.current_turn -ne 1) { throw "discourse state inspection failed" }
    $last = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health/last-turn?session_id=$sessionId" -Headers $headers -TimeoutSec 10
    if ($last.turn_id -ne $chat.id) { throw "last-turn receipt inspection failed" }
    $lanes = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/lanes" -Headers $headers -TimeoutSec 10
    if (($lanes.lanes.backend_kind | Select-Object -Unique) -ne "local") { throw "local-first lane default failed" }
    $proof = [ordered]@{
        schema = "grnd0.clean-install-proof.v1"
        status = "green"
        python = "3.12"
        checks = @("fresh_environment", "core_start", "healthz_200", "local_inference_healthy", "local_lane_default", "typed_plan", "stub_chat_turn", "focused_branch_offer", "single_discourse_commit", "receipt_inspection")
        response_model = $chat.model
    }
    $proof | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath artifacts\clean-install-proof.json -Encoding utf8
    Write-Output "Clean-install proof green."
}
finally {
    if (-not $KeepRunning) {
        docker compose down --volumes --remove-orphans
    }
}
