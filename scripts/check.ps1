[CmdletBinding()]
param([string]$Python)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$venvPython = Join-Path $root ".venv/Scripts/python.exe"
$pythonExe = if ($Python) { $Python } elseif (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }

Push-Location $root
try {
    & $pythonExe -m unittest discover -v
    if ($LASTEXITCODE -ne 0) { throw "Testes Python falharam" }
    & $pythonExe verify_release.py
    if ($LASTEXITCODE -ne 0) { throw "Contrato de release falhou" }
    foreach ($file in @("static/app.js", "static/discovery.js", "static/releases.js", "static/motion.js")) {
        node --check $file
        if ($LASTEXITCODE -ne 0) { throw "Sintaxe JavaScript falhou: $file" }
    }
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw "git diff --check falhou" }
} finally {
    Pop-Location
}
Write-Output "CHECKS OK"
