<#
.SYNOPSIS
    Launcher local de rede (LAN) do Salutem Ficha Studio (Windows PowerShell 5.1+).

.DESCRIPTION
    Inicia o servidor FastAPI/Uvicorn ouvindo em 0.0.0.0 na porta 8000 (padrao),
    permitindo que outras pessoas na mesma rede acessem o Studio pelo IP da rede
    desta maquina. Valida .venv, Java, build do frontend, verifica a disponibilidade
    da porta, aguarda /api/health responder HTTP 200 e exibe os enderecos de acesso
    local e de rede (LAN).

.PARAMETER Port
    Porta TCP desejada para acesso na rede (padrao: 8000).

.PARAMETER BindHost
    Endereco de bind do Uvicorn (padrao: 0.0.0.0 para aceitar conexoes da rede).

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
    [string]$BindHost = "0.0.0.0",
    [switch]$RebuildFrontend,
    [switch]$NoBrowser,
    [string]$DataDir = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Test-PortAvailable {
    param(
        [int]$CheckPort
    )

    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $CheckPort)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Get-LanIPv4Addresses {
    $ips = @()

    try {
        if (Get-Command Get-NetIPAddress -ErrorAction SilentlyContinue) {
            $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.IPAddress -notlike "127.*" -and
                    $_.IPAddress -notlike "169.254.*" -and
                    $_.InterfaceAlias -notmatch "Loopback|vEthernet|WSL|Docker|VirtualBox|VMware"
                } |
                Sort-Object -Property InterfaceMetric
            foreach ($item in $candidates) {
                if ($ips -notcontains $item.IPAddress) {
                    $ips += $item.IPAddress
                }
            }
        }
    } catch {
        # Fallback abaixo via .NET NetworkInterface
    }

    if ($ips.Count -eq 0) {
        try {
            $nics = [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
                Where-Object {
                    $_.OperationalStatus -eq [System.Net.NetworkInformation.OperationalStatus]::Up -and
                    $_.NetworkInterfaceType -ne [System.Net.NetworkInformation.NetworkInterfaceType]::Loopback
                }
            foreach ($nic in $nics) {
                if ($nic.Name -match "vEthernet|WSL|Docker|VirtualBox|VMware") {
                    continue
                }
                foreach ($ua in $nic.GetIPProperties().UnicastAddresses) {
                    if ($ua.Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
                        $addr = $ua.Address.IPAddressToString
                        if ($addr -notlike "127.*" -and $addr -notlike "169.254.*" -and ($ips -notcontains $addr)) {
                            $ips += $addr
                        }
                    }
                }
            }
        } catch {
            # Ignora falha de descoberta de IP
        }
    }

    return $ips
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
Write-Host "  Salutem Ficha Studio - Launcher de Rede Local (LAN)" -ForegroundColor Cyan
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

# 4. Validar porta fixa de rede (padrao 8000)
if (-not (Test-PortAvailable -CheckPort $Port)) {
    Write-Host "[ERRO] A porta $Port ja esta em uso nesta maquina." -ForegroundColor Red
    Write-Host "       Encerre o processo que ocupa a porta $Port ou informe outra porta com -Port <numero>." -ForegroundColor Yellow
    exit 1
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

$LanIPs = @(Get-LanIPv4Addresses)
$LocalUrl = "http://127.0.0.1:$Port"
$HealthUrl = "$LocalUrl/api/health"
$ServerProcess = $null

try {
    Write-Host "[START] Iniciando Salutem Ficha Studio em ${BindHost}:${Port} (acesso em rede)..." -ForegroundColor Cyan

    $UvicornArgs = @(
        "-m", "uvicorn",
        "backend.app.main:app",
        "--host", "$BindHost",
        "--port", "$Port"
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
        Write-Host "  Salutem Ficha Studio pronto em REDE LOCAL (LAN)!" -ForegroundColor Green
        Write-Host "  Acesso Local  : $LocalUrl" -ForegroundColor White
        if ($LanIPs.Count -gt 0) {
            foreach ($ip in $LanIPs) {
                Write-Host "  Acesso Rede   : http://${ip}:${Port}" -ForegroundColor Cyan
            }
        } else {
            Write-Host "  Acesso Rede   : http://<SEU-IP-LOCAL>:$Port" -ForegroundColor Cyan
        }
        Write-Host "  API Health    : $HealthUrl" -ForegroundColor White
        Write-Host "  Swagger /docs : $LocalUrl/docs" -ForegroundColor White
        Write-Host "  Aviso         : Compartilhe apenas em rede interna confiavel (sem login)." -ForegroundColor Yellow
        Write-Host "  Pressione Ctrl+C para encerrar com seguranca." -ForegroundColor DarkGray
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host ""

        if (-not $NoBrowser) {
            Start-Process $LocalUrl
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
