<#
.SYNOPSIS
    Launcher de desenvolvimento do Salutem Ficha Studio (Backend FastAPI + Frontend Vite).

.DESCRIPTION
    Valida .venv e frontend/node_modules, sobe o backend FastAPI com hot-reload
    (uvicorn --reload) e o Vite dev server em paralelo, exibindo as URLs locais
    e encerrando ambos os processos de forma limpa ao pressionar Ctrl+C.

.PARAMETER ApiPort
    Porta TCP do backend FastAPI (padrao: 8000).

.PARAMETER WebPort
    Porta TCP do servidor Vite (padrao: 5173).
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Stop-ProcessTree {
    param([int]$ProcessId)

    if ($ProcessId -le 0) {
        return
    }

    try {
        $children = Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            Stop-ProcessTree -ProcessId $child.ProcessId
        }
    } catch {
        # Fallback silencioso se WMI/CIM nao estiver disponivel
    }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    } catch {
        # Processo ja encerrado
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Salutem Ficha Studio - Modo Desenvolvimento" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Validar .venv
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Host "[ERRO] Ambiente virtual Python nao encontrado em:" -ForegroundColor Red
    Write-Host "       $PythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "Crie o ambiente virtual e instale as dependencias:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor White
    Write-Host "  .\.venv\Scripts\pip.exe install -r backend\requirements.txt" -ForegroundColor White
    exit 1
}

# 2. Validar frontend/node_modules e npm
$FrontendNodeModules = Join-Path $ProjectRoot "frontend\node_modules"
if (-not (Test-Path -LiteralPath $FrontendNodeModules)) {
    Write-Host "[ERRO] Dependencias do frontend nao encontradas em:" -ForegroundColor Red
    Write-Host "       $FrontendNodeModules" -ForegroundColor Red
    Write-Host ""
    Write-Host "Instale as dependencias antes de rodar em modo dev:" -ForegroundColor Yellow
    Write-Host "  npm --prefix frontend ci" -ForegroundColor White
    exit 1
}

$NpmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($null -eq $NpmCmd) {
    $NpmCmd = Get-Command npm -ErrorAction SilentlyContinue
}
if ($null -eq $NpmCmd) {
    Write-Host "[ERRO] npm nao encontrado no PATH. Instale Node.js 20+." -ForegroundColor Red
    exit 1
}

$JavaCmd = Get-Command java -ErrorAction SilentlyContinue
if ($null -eq $JavaCmd) {
    Write-Warning "Java nao encontrado no PATH. O Jasper Daemon (preview PDF) requer Java 17+."
}

# 3. Configurar ambiente Python
$env:PYTHONPATH = "$ProjectRoot\backend;$ProjectRoot"

$BackendProcess = $null
$FrontendProcess = $null

try {
    Write-Host "[DEV] Iniciando Backend FastAPI (uvicorn --reload) na porta $ApiPort..." -ForegroundColor Cyan
    $BackendArgs = @(
        "-m", "uvicorn",
        "backend.app.main:app",
        "--host", "127.0.0.1",
        "--port", "$ApiPort",
        "--reload"
    )
    $BackendProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $BackendArgs `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -PassThru

    Write-Host "[DEV] Iniciando Frontend Vite na porta $WebPort..." -ForegroundColor Cyan
    $FrontendArgs = @(
        "--prefix", "frontend",
        "run", "dev",
        "--",
        "--port", "$WebPort"
    )
    $FrontendProcess = Start-Process `
        -FilePath $NpmCmd.Source `
        -ArgumentList $FrontendArgs `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -PassThru

    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  Servidores de desenvolvimento ativos:" -ForegroundColor Green
    Write-Host "  Frontend Vite : http://127.0.0.1:$WebPort" -ForegroundColor White
    Write-Host "  Backend API   : http://127.0.0.1:$ApiPort" -ForegroundColor White
    Write-Host "  Swagger /docs : http://127.0.0.1:$ApiPort/docs" -ForegroundColor White
    Write-Host "  Pressione Ctrl+C para encerrar ambos os servidores." -ForegroundColor DarkGray
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""

    while ((-not $BackendProcess.HasExited) -and (-not $FrontendProcess.HasExited)) {
        Start-Sleep -Milliseconds 300
    }

    if ($BackendProcess.HasExited) {
        Write-Warning "Backend FastAPI encerrou (exit code $($BackendProcess.ExitCode)). Encerrando sessao dev..."
    }
    if ($FrontendProcess.HasExited) {
        Write-Warning "Frontend Vite encerrou (exit code $($FrontendProcess.ExitCode)). Encerrando sessao dev..."
    }
} finally {
    Write-Host ""
    Write-Host "[STOP] Encerrando processos de desenvolvimento..." -ForegroundColor Yellow

    if ($null -ne $FrontendProcess -and (-not $FrontendProcess.HasExited)) {
        Stop-ProcessTree -ProcessId $FrontendProcess.Id
    }
    if ($null -ne $BackendProcess -and (-not $BackendProcess.HasExited)) {
        Stop-ProcessTree -ProcessId $BackendProcess.Id
    }

    Write-Host "[STOP] Backend e Frontend encerrados." -ForegroundColor DarkGray
}
