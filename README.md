# Salutem Ficha Studio `v1.0.0`

Plataforma web local e containerizada para engenharia completa de fichas clínicas Salutem: da extração assistida por IA a partir de PDFs até o **Form Builder visual**, geração e execução segura de **SQL INSERT/SELECT no PostgreSQL** e design/preview de relatórios **JasperReports (`.jrxml` / PDF)** com exportação em pacote ZIP.

---

## Arquitetura em 3 Camadas

```text
+-------------------------------------------------------------------+
|  1. Frontend Web SPA (React 19 + TypeScript + Vite + Tailwind)    |
|     - Dashboard de Projetos & Revisões / Gates                    |
|     - Form Builder Drag-and-Drop (@dnd-kit) + Monaco JSON Sync    |
|     - Editor SQL (INSERT / SELECT) + Dry-Run / Commit Guard       |
|     - Jasper Studio Light + PDF.js Viewer + Seleção de Regiões    |
+---------------------------------+---------------------------------+
                                  | HTTP / REST (/api/*)
+---------------------------------v---------------------------------+
|  2. Backend API & Core (FastAPI + Uvicorn + SQLite WAL)           |
|     - Workspaces persistentes, artefatos versionados e 3 Gates    |
|     - Orquestração de Harnesses IA (AGY, OpenCode, Claude, Codex) |
|     - Skills Salutem embutidas + Servidor MCP + PyMuPDF Geometry  |
|     - Geradores SQL INSERT/SELECT + PostgreSQL Vault (psycopg 3)  |
|     - Scaffold/Diagnóstico JRXML + Empacotador ZIP                |
+---------------------------------+---------------------------------+
                                  | IPC / Subprocesso Persistente
+---------------------------------v---------------------------------+
|  3. Jasper Daemon JVM (Java 17+ · resources/bin/jasper-daemon.jar)|
|     - Compilação JasperReports (.jrxml -> .jasper)                |
|     - 4 subreports padrão + overrides customizados (.jasper)      |
|     - Renderização de PDF em modo Mock ou Live (PostgreSQL)       |
+-------------------------------------------------------------------+
```

---

## Principais Funcionalidades

- **Extração IA com 2 Gates + MCP**:
  - Fluxo guiado a partir de `source.pdf`, importação direta de `.json` ou `.jrxml`.
  - Suporte aos harnesses **AGY**, **OpenCode**, **Claude** e **Codex**, com skills Salutem embutidas, inspeção geométrica de PDF via `PyMuPDF` e integração MCP.
  - Controle explícito de aprovação por etapas (`gate1_json`, `gate2_sql_insert`, `gate3_jrxml`) e histórico de revisões com restauração de versões anteriores.
- **Form Builder Visual (DnD) & Editor JSON**:
  - Edição visual com drag-and-drop (`@dnd-kit`) para os 11 tipos de campo Salutem (`BOOLEANO`, `BOOLEANO_RADIO`, `COMBO`, `COMBO_MULTI`, `TEXTO`, `TEXTO_LONGO`, `DATA`, `HORA`, `NUMERICO`, `TITULO`, `CID`).
  - Sincronização bidirecional com **Monaco Editor**, validação estrutural e normalização de textos.
- **SQL INSERT (`DO $$`) & SELECT Jasper com Dry-Run / Commit**:
  - Geração determinística de script `INSERT` (`DO $$`) e `SELECT` Jasper configurável (estilos booleanos, nomenclatura de colunas, observações e blocos auxiliares).
  - Perfis de conexão PostgreSQL com senhas protegidas em cofre (`keyring` / `FICHA_STUDIO_VAULT_KEY`), modo somente leitura para proteção de produção, execução **Dry-Run** (rollback automático) e **Commit** transacional com captura de `template_db_id`.
- **Jasper Studio Light com PDF.js & Pacote ZIP**:
  - Scaffold e edição de `.jrxml` com diagnóstico de compilação e live-reload via **Jasper Daemon JVM**.
  - Visualização integrada via **PDF.js**, seleção visual de regiões para anotações/ajustes, preview com dados simulados (**Mock**) ou reais (**Live**) e gerenciamento de subreports `.jasper` (`cabecalho_retrato`, `cabecalho_paisagem`, `dados_paciente`, `rodape_retrato` + overrides).
  - Exportação de pacote **ZIP** pronto para implantação com JSON, SQL INSERT, SQL SELECT, JRXML e `.jasper` compilado.

---

## Requisitos

| Componente | Versão Mínima | Observações |
| --- | --- | --- |
| **Python** | 3.11+ (rec. 3.13) | Backend FastAPI, SQLite WAL, PyMuPDF e psycopg 3 |
| **Node.js / npm** | 20+ (Docker usa 22) | Necessário para desenvolvimento ou rebuild da SPA (`frontend/dist`) |
| **Java JRE/JDK** | 17+ | Necessário para o Jasper Daemon JVM (compilação `.jrxml` e preview PDF) |
| **Docker & Compose** | 24+ / v2 | Opcional, para execução containerizada sem instalar Python/Node/Java no host |

---

## Como Rodar Localmente (Windows PowerShell 5.1+)

### 1. Preparação inicial (primeira execução)

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install -r backend\requirements.txt
npm --prefix frontend ci
```

### 2. Launcher Local de Produção (`scripts/start_local.ps1`)

Compila o bundle SPA automaticamente caso `frontend/dist/index.html` ainda não exista, encontra uma porta livre a partir de `8000`, inicia o servidor FastAPI com a SPA embutida, aguarda `/api/health` responder `HTTP 200` e abre o navegador padrão:

```powershell
.\scripts\start_local.ps1
```

Parâmetros opcionais:

```powershell
# Forçar recompilação do frontend, usar porta inicial 8080, não abrir navegador e definir pasta de dados
.\scripts\start_local.ps1 -Port 8080 -RebuildFrontend -NoBrowser -DataDir "D:\salutem-data"
```

| Parâmetro | Padrão | Descrição |
| --- | --- | --- |
| `-Port` | `8000` | Porta TCP inicial (avança automaticamente se estiver ocupada) |
| `-RebuildFrontend` | `$false` | Força `npm --prefix frontend run build` antes de subir o servidor |
| `-NoBrowser` | `$false` | Evita abrir o navegador automaticamente após `/api/health` retornar 200 |
| `-DataDir` | `workspaces/` | Define `FICHA_STUDIO_DATA_DIR` para persistência de projetos e `studio.db` |

### 3. Launcher de Rede Local — LAN (`scripts/start_network.ps1`)

Sobe o Studio ouvindo em `0.0.0.0:8000` (porta fixa `8000` liberada na rede), detecta automaticamente o IP IPv4 local da máquina e exibe a URL de rede (`http://<IP-DA-REDE>:8000`) para acesso por outras pessoas na intranet:

```powershell
.\scripts\start_network.ps1
```

### 4. Modo Desenvolvimento (`scripts/dev.ps1`)

Sobe em paralelo o **Backend FastAPI** com `--reload` e o **Frontend Vite** com HMR (proxy `/api` -> backend) e encerra ambos de forma limpa com `Ctrl+C`:

```powershell
.\scripts\dev.ps1
```

Parâmetros opcionais:

```powershell
.\scripts\dev.ps1 -ApiPort 8000 -WebPort 5173
```

URLs exibidas durante o desenvolvimento:
- **Frontend Vite**: `http://127.0.0.1:5173`
- **Backend API**: `http://127.0.0.1:8000`
- **Swagger `/docs`**: `http://127.0.0.1:8000/docs`

---

## Como Rodar com Docker Compose

O repositório inclui um `Dockerfile` multi-stage (`node:22-alpine` para compilar a SPA + `python:3.13-slim-bookworm` com `openjdk-17-jre-headless` e usuário não-root `studio`) e um `docker-compose.yml` pronto para uso com volume persistente `/data`.

```powershell
# Opcional: defina uma chave forte para criptografia do cofre de perfis PostgreSQL
$env:FICHA_STUDIO_VAULT_KEY = "sua-chave-secreta-forte"

docker compose up --build -d
```

- **Aplicação Web & API**: `http://127.0.0.1:8000`
- **Healthcheck**: `http://127.0.0.1:8000/api/health`
- **Swagger UI**: `http://127.0.0.1:8000/docs`
- **Volume persistente**: `studio_data` montado em `/data` (`FICHA_STUDIO_DATA_DIR=/data`)

Para acompanhar logs e encerrar:

```powershell
docker compose logs -f studio
docker compose down
```

---

## Executando as Suítes de Testes

### Backend (`pytest`)

No Windows PowerShell:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
.\.venv\Scripts\pytest.exe
```

Para validar apenas os artefatos de empacotamento, Docker e scripts:

```powershell
$env:PYTHONPATH = "$PWD\backend;$PWD"
.\.venv\Scripts\pytest.exe backend/tests/test_packaging_artifacts.py
```

### Frontend (`vitest` e `typecheck`)

```powershell
npm --prefix frontend run typecheck
npm --prefix frontend test
```
