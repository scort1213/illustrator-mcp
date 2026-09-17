param([string]$Python = 'python', [string]$VenvPath = (Join-Path $PSScriptRoot '.venv'))
$ErrorActionPreference = 'Stop'
function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe" }
}
Invoke-Checked $Python @('-c', 'import sys; assert sys.version_info[:2] == (3,12), "Use Python 3.12 for the tested baseline"')
if (Test-Path -LiteralPath $VenvPath) { throw "Choose a new empty environment path: $VenvPath" }
Invoke-Checked $Python @('-m', 'venv', $VenvPath)
$venvPython = Join-Path $VenvPath 'Scripts\python.exe'
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--require-hashes', '-r', (Join-Path $PSScriptRoot 'requirements.txt'))
Invoke-Checked $venvPython @('-m', 'pip', 'install', '--no-deps', $PSScriptRoot)
Invoke-Checked $venvPython @('-m', 'pip', 'check')
Write-Host 'Installed. Configure the MCP client to start this executable with: -m illustrator'
Write-Host $venvPython
