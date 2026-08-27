param([string[]]$PytestArgs = @())

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw 'Create the project .venv and install .[dev] first; see README.md.'
}
# pytest clears --basetemp. Always choose a fresh, dedicated path, never the repo.
$pytestRunDir = Join-Path ([IO.Path]::GetTempPath()) ('coding-agent-pytest-' + [guid]::NewGuid().ToString('N'))
Push-Location -LiteralPath $repoRoot
try {
    & $pythonExecutable -m pytest tests -q --basetemp $pytestRunDir -o "cache_dir=$pytestRunDir-cache" @PytestArgs
    $testExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $testExitCode
