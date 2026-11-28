<#
.SYNOPSIS
    Launcher local de producao do Salutem Ficha Studio (Windows PowerShell 5.1+).

.DESCRIPTION
    Valida dependencias locais (.venv, Java, build do frontend), encontra uma porta livre
    a partir de -Port, inicia o servidor FastAPI/Uvicorn com a SPA embutida, aguarda
    /api/health responder HTTP 200 e abre automaticamente o navegador padrao.

.PARAMETER Port
    Porta TCP inicial desejada (padrao: 8000). Se ocupada, avanca automaticamente.

.PARAMETER RebuildFrontend
    Forca a recompilacao do bundle SPA (frontend/dist) antes de iniciar o servidor.

.PARAMETER NoBrowser
    Nao abre o navegador automaticamente apos o servidor ficar saudavel.

.PARAMETER DataDir
    Diretorio persistente opcional para FICHA_STUDIO_DATA_DIR (workspaces e studio.db).
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$RebuildFrontend,
    [switch]$NoBrowser,
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Find-AvailablePort {
    param(
        [int]$StartPort,
        [int]$MaxAttempts = 100
    )

    for ($offset = 0; $offset -lt $MaxAttempts; $offset++) {
        $candidate = $StartPort + $offset
        $listener = $null
        try {
            $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $candidate)
            $listener.Start()
            return $candidate
        } catch {
            continue
        } finally {
            if ($null -ne $listener) {
                $listener.Stop()
            }
        }
    }

    throw "Nenhuma porta TCP disponivel encontrada entre $StartPort e $($StartPort + $MaxAttempts - 1)."
}

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

function Test-FrontendBuildStale {
    param(
        [string]$FrontendPath,
        [string]$IndexHtmlPath
    )

    if (-not (Test-Path -LiteralPath $IndexHtmlPath)) {
        return $true
    }

    $DistTimestamp = (Get-Item -LiteralPath $IndexHtmlPath).LastWriteTimeUtc
    $PackageJsonPath = Join-Path $FrontendPath "package.json"
    if (Test-Path -LiteralPath $PackageJsonPath) {
        if ((Get-Item -LiteralPath $PackageJsonPath).LastWriteTimeUtc -gt $DistTimestamp) {
            return $true
        }
    }

    $SrcDir = Join-Path $FrontendPath "src"
    if (Test-Path -LiteralPath $SrcDir) {
        $NewerFile = Get-ChildItem -LiteralPath $SrcDir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTimeUtc -gt $DistTimestamp } |
            Select-Object -First 1
        if ($null -ne $NewerFile) {
            return $true
        }
    }

    return $false
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Salutem Ficha Studio - Launcher Local (Producao)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 1. Validar ambiente virtual Python e pacotes obrigatorios
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    Write-Host "[ERRO] Ambiente virtual Python nao encontrado em:" -ForegroundColor Red
    Write-Host "       $PythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "Crie o ambiente virtual e instale as dependencias antes de continuar:" -ForegroundColor Yellow
    Write-Host "  python -m venv .venv" -ForegroundColor White
    Write-Host "  .\.venv\Scripts\pip.exe install -r backend\requirements.txt" -ForegroundColor White
    exit 1
}

& $PythonExe -c "import cryptography, paramiko" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERRO] Dependencias Python obrigatorias ausentes no .venv (cryptography / paramiko)." -ForegroundColor Red
    Write-Host "       Se voce acabou de atualizar via 'git pull', sincronize backend\requirements.txt:" -ForegroundColor Yellow
    Write-Host "       .\.venv\Scripts\pip.exe install -r backend\requirements.txt" -ForegroundColor White
    exit 1
}

# 2. Verificar Java (opcional para JSON/SQL, obrigatorio para Jasper Daemon / Preview PDF)
$JavaCmd = Get-Command java -ErrorAction SilentlyContinue
if ($null -eq $JavaCmd) {
    Write-Warning "Java nao encontrado no PATH. O Jasper Daemon (preview PDF e compilacao .jrxml) ficara indisponivel ate instalar Java 17+."
} else {
    Write-Host "[OK] Java detectado: $($JavaCmd.Source)" -ForegroundColor DarkGray
}

# 3. Garantir build atualizado do frontend SPA (frontend/dist/index.html)
$FrontendDir = Join-Path $ProjectRoot "frontend"
$FrontendNodeModules = Join-Path $FrontendDir "node_modules"
$FrontendIndexHtml = Join-Path $FrontendDir "dist\index.html"
$DistExists = Test-Path -LiteralPath $FrontendIndexHtml
$FrontendStale = $false
if ($DistExists -and (-not $RebuildFrontend)) {
    $FrontendStale = Test-FrontendBuildStale -FrontendPath $FrontendDir -IndexHtmlPath $FrontendIndexHtml
}

if ($RebuildFrontend -or (-not $DistExists) -or $FrontendStale) {
    if ($FrontendStale) {
        Write-Host "[BUILD] Alteracoes recentes em frontend\src ou frontend\package.json detectadas; recompilando bundle SPA..." -ForegroundColor Yellow
    }

    $NpmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $NpmCmd) {
        $NpmCmd = Get-Command npm -ErrorAction SilentlyContinue
    }
    if ($null -eq $NpmCmd) {
        if ($DistExists -and (-not $RebuildFrontend)) {
            Write-Warning "Node.js/npm nao encontrado no PATH; servindo frontend\dist existente (pode estar desatualizado apos git pull)."
        } else {
            Write-Host "[ERRO] Node.js/npm nao encontrado no PATH e frontend/dist/index.html nao existe." -ForegroundColor Red
            Write-Host "Instale Node.js 20+ e execute novamente este script." -ForegroundColor Yellow
            exit 1
        }
    } else {
        if (-not (Test-Path -LiteralPath $FrontendNodeModules)) {
            Write-Host "[BUILD] Instalando dependencias do frontend (npm --prefix frontend ci)..." -ForegroundColor Yellow
            & $NpmCmd.Source --prefix frontend ci
            if ($LASTEXITCODE -ne 0) {
                Write-Error "Falha ao instalar dependencias do frontend (exit code $LASTEXITCODE)."
                exit $LASTEXITCODE
            }
        }

        Write-Host "[BUILD] Compilando bundle SPA (npm --prefix frontend run build)..." -ForegroundColor Yellow
        & $NpmCmd.Source --prefix frontend run build
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Falha ao compilar o frontend (exit code $LASTEXITCODE)."
            exit $LASTEXITCODE
        }

        if (-not (Test-Path -LiteralPath $FrontendIndexHtml)) {
            Write-Error "Build concluido, mas $FrontendIndexHtml nao foi gerado."
            exit 1
        }
        Write-Host "[OK] Frontend compilado em frontend\dist" -ForegroundColor Green
    }
} else {
    Write-Host "[OK] Bundle SPA atualizado detectado (use -RebuildFrontend para forcar recompilacao)." -ForegroundColor DarkGray
}

# 4. Selecionar porta livre a partir de $Port
$ActivePort = Find-AvailablePort -StartPort $Port
if ($ActivePort -ne $Port) {
    Write-Warning "Porta $Port em uso. Usando porta disponivel $ActivePort."
}

# 5. Configurar variaveis de ambiente
$env:PYTHONPATH = "$ProjectRoot\backend;$ProjectRoot"
if (-not [string]::IsNullOrWhiteSpace($DataDir)) {
    $ResolvedDataDir = [System.IO.Path]::GetFullPath($DataDir)
    if (-not (Test-Path -LiteralPath $ResolvedDataDir)) {
        New-Item -ItemType Directory -Path $ResolvedDataDir -Force | Out-Null
    }
    $env:FICHA_STUDIO_DATA_DIR = $ResolvedDataDir
    Write-Host "[OK] FICHA_STUDIO_DATA_DIR = $ResolvedDataDir" -ForegroundColor DarkGray
}

$BaseUrl = "http://127.0.0.1:$ActivePort"
$HealthUrl = "$BaseUrl/api/health"
$ServerProcess = $null

try {
    Write-Host "[START] Iniciando Salutem Ficha Studio em $BaseUrl ..." -ForegroundColor Cyan

    $UvicornArgs = @(
        "-m", "uvicorn",
        "backend.app.main:app",
        "--host", "127.0.0.1",
        "--port", "$ActivePort"
    )

    $ServerProcess = Start-Process `
        -FilePath $PythonExe `
        -ArgumentList $UvicornArgs `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -PassThru

    # 6. Polling curto de saude (/api/health) ate 20 segundos
    $Healthy = $false
    $Deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $Deadline) {
        if ($ServerProcess.HasExited) {
            Write-Error "Servidor FastAPI encerrou inesperadamente (exit code $($ServerProcess.ExitCode))."
            exit 1
        }

        try {
            $Response = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($Response.StatusCode -eq 200) {
                $Healthy = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 400
        }
    }

    if (-not $Healthy) {
        Write-Warning "Tempo limite (20s) aguardando $HealthUrl responder HTTP 200. O servidor permanecera em execucao para diagnostico."
    } else {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host "  Salutem Ficha Studio pronto!" -ForegroundColor Green
        Write-Host "  Aplicacao Web : $BaseUrl" -ForegroundColor White
        Write-Host "  API Health    : $HealthUrl" -ForegroundColor White
        Write-Host "  Swagger /docs : $BaseUrl/docs" -ForegroundColor White
        Write-Host "  Pressione Ctrl+C para encerrar com seguranca." -ForegroundColor DarkGray
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""

        if (-not $NoBrowser) {
            Start-Process $BaseUrl
        }
    }

    # 7. Manter anexado ao console aguardando Ctrl+C ou encerramento do servidor
    while (-not $ServerProcess.HasExited) {
        Start-Sleep -Milliseconds 300
    }
} finally {
    if ($null -ne $ServerProcess -and (-not $ServerProcess.HasExited)) {
        Write-Host ""
        Write-Host "[STOP] Encerrando Salutem Ficha Studio (PID $($ServerProcess.Id))..." -ForegroundColor Yellow
        Stop-ProcessTree -ProcessId $ServerProcess.Id
        Write-Host "[STOP] Servidor encerrado." -ForegroundColor DarkGray
    }
}
