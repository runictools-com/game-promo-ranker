[CmdletBinding()]
param([switch]$NoDeploy)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$python = 'C:/Users/eep0x10/scoop/apps/python/current/python.exe'
Push-Location $repo
try {
    & $python -m unittest discover -v
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    foreach ($file in @('static/app.js','static/discovery.js','static/releases.js')) {
        node --check $file
        if ($LASTEXITCODE -ne 0) { throw "Syntax failed: $file" }
    }
    git diff --check
    if ($LASTEXITCODE -ne 0) { throw 'Whitespace check failed' }
    if ($NoDeploy) { return }
    if (git status --porcelain) { throw 'Commit reviewed changes before deployment' }
    & C:/Users/eep0x10/bin/codex-prod-preflight.ps1 gamepromo
    if ($LASTEXITCODE -ne 0) { throw 'Production preflight failed' }
    $revision = (git rev-parse HEAD).Trim()
    if ($revision -notmatch '^[0-9a-f]{40}$') { throw 'Invalid revision' }
    git push origin HEAD:main
    if ($LASTEXITCODE -ne 0) { throw 'Push failed' }
    $remoteFile = "/tmp/gamepromo-release-$revision.sh"
    scp -i C:/Users/eep0x10/.ssh/do_deploy deploy/remote-release.sh "deploy@187.127.28.169:$remoteFile"
    if ($LASTEXITCODE -ne 0) { throw 'Release upload failed' }
    ssh -i C:/Users/eep0x10/.ssh/do_deploy deploy@187.127.28.169 bash $remoteFile $revision
    if ($LASTEXITCODE -ne 0) { throw 'Remote release or one collector failed; inspect log and status before retrying' }
} finally { Pop-Location }
