[CmdletBinding()]
param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $root ".venv"
$venvPython = Join-Path $venv "Scripts/python.exe"

& $Python -m venv $venv
if ($LASTEXITCODE -ne 0) { throw "Falha ao criar .venv com $Python" }
& $venvPython -m pip install --require-hashes -r (Join-Path $root "requirements.lock")
if ($LASTEXITCODE -ne 0) { throw "Falha ao instalar requirements.lock" }
git -C $root config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) { throw "Falha ao ativar hooks versionados" }
Write-Output "Ambiente pronto: $venvPython"
