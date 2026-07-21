# SPDX-License-Identifier: MPL-2.0
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

$ErrorActionPreference = "Stop"
if ($Arguments.Count -lt 1 -or $Arguments[0] -ne "models") {
    throw "Usage: .\grnd0.ps1 models <pull|generate|status> <pack>"
}
& uv run python tools/grnd0_models.py @($Arguments | Select-Object -Skip 1)
exit $LASTEXITCODE
