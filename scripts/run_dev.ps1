param(
    [int]$Port = 8000,
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Ambiente virtual não encontrado em $PythonExe. Crie o .venv primeiro."
    exit 1
}

$env:PYTHONPATH = "$ProjectRoot\backend;$ProjectRoot"
Write-Host "Iniciando Salutem Ficha Studio API em http://127.0.0.1:$Port ..." -ForegroundColor Cyan
Write-Host "Swagger Interativo: http://127.0.0.1:$Port/docs" -ForegroundColor Green

if ($NoReload) {
    & $PythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port
} else {
    & $PythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port --reload
}
