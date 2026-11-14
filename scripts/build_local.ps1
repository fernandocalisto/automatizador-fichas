$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Push-Location $ProjectRoot
try {
    Write-Host "==> Executando suite de testes (headless)..." -ForegroundColor Cyan
    $env:QT_QPA_PLATFORM = "offscreen"
    python -m pytest -c pytest.ini tests
    if ($LASTEXITCODE -ne 0) {
        throw "Testes falharam com código $LASTEXITCODE"
    }

    Write-Host "==> Compilando executável com PyInstaller (build.spec)..." -ForegroundColor Cyan
    python -m PyInstaller --clean --noconfirm build.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller falhou com código $LASTEXITCODE"
    }

    $ExePath = Join-Path $ProjectRoot "dist\AutomatizadorFichas.exe"
    if (-not (Test-Path $ExePath)) {
        throw "Executável não encontrado em $ExePath"
    }

    $SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 2)
    Write-Host "==> Build concluído: $ExePath ($SizeMB MB)" -ForegroundColor Green
} finally {
    Pop-Location
}
