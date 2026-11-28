# Estado Atual do Projeto — Salutem Ficha Studio (`v1.1.1`)

> **Última atualização:** 2026-11-28  
> **Branch principal:** `main` (`v1.1.1`)  
> **Release anterior publicada:** [`v1.0.0`](https://github.com/fernandocalisto/automatizador-fichas/releases/tag/v1.0.0)  
> **Plano detalhado executado:** [`implementation_plan_v1.1.md`](./implementation_plan_v1.1.md) + Redesign UX / `repo:` / SSH `.key` + Rodada QA `v1.1.1` + Preview/Fontes JVM/AGY Quente  
> **Status geral:** **`v1.1.1` estabilizada e validada ponta a ponta em `main` (Motor `repo:/...` + fontes JVM com negrito/itálico reais, SSH `.key`, `Início`, `Ctrl+K`, Clientes Master-Detail, Jasper Studio com Preview ampliado/popover `Ajustes (N)`, Configurações e Pool AGY quente com seletor de Modelo + Effort)**

---

## 1. Visão Geral da Arquitetura

O **Salutem Ficha Studio** substituiu integralmente a GUI legada em PySide6 por uma estação de trabalho web unificada em 3 camadas:

1. **Frontend Web (`frontend/`)**: React 19 + TypeScript + Vite 6 + Tailwind CSS v4 + Monaco Editor + `@dnd-kit` + `pdfjs-dist` v5 + Vitest.
   - Compilado em `frontend/dist/` e servido diretamente pelo FastAPI em produção/uso local (ou via Vite em `:5173` com proxy `/api` em desenvolvimento).
2. **Backend FastAPI (`backend/app/`)**: Python 3.13+ + SQLite (WAL) + workspaces em disco + `psycopg` (PostgreSQL) + `paramiko` (SSH/SFTP) + `httpx` (JasperReports Server REST v2) + OS Keyring / `SecretVaultService` AES-256-GCM + `pymupdf` + Orquestrador de Agentes (`AgentHarness` + SSE/WebSocket + Servidor MCP stdio JSON-RPC 2.0 com **11 ferramentas**).
3. **Jasper Daemon JVM (`java-engine/` + `resources/bin/jasper-daemon.jar`)**: Motor Java baseado em JasperReports `6.21.3` com modo HTTP residente (`--action serve` em `127.0.0.1`), resolução nativa de URIs `repo:/...` (`RepoSchemeRepositoryService`), compilação/exportação em ~80–200ms e os 4 subreports `.jasper` built-in em `resources/subreports/`.

---

## 2. Entregas Concluídas por Fase

### Fase 1 — Fundação, Core SQL & Workspace de Projetos
- Migração e evolução do Core Salutem em `backend/app/core/`:
  - `sql_insert.py`: geração `DO $$` + validação sintática PostgreSQL.
  - `sql_select.py`: geração de `SELECT` Jasper (`$P{id}` padrão / `${id}` opcional, estilos booleanos, `_obs`, metadados 1:1).
  - `json_utils.py`: normalização UPPERCASE (preservando códigos/booleanos), validação estrutural dos 11 tipos Salutem, auditoria de avisos clínicos e helpers CRUD/reorder do Form Builder.
  - `custom_regex.py`: motor validado de regras customizadas de higienização OCR.
- Persistência em `backend/app/db/sqlite_store.py` (WAL) e `backend/app/services/workspace_service.py`:
  - Projetos multi-entrada (`pdf`, `json`, `jrxml`), revisões imutáveis com restauração, histórico de chat por fase e 3 gates humanos (`gate1_json`, `gate2_sql_insert`, `gate3_jrxml`).
- Gestão dos 4 subreports padrão (`cabecalho_retrato.jasper`, `cabecalho_paisagem.jasper`, `dados_paciente.jasper`, `rodape_retrato.jasper`) + overrides customizados em `backend/app/services/subreport_service.py`.
- Skills oficiais embutidas em `backend/app/skills/extrator_ficha/SKILL.md` e `backend/app/skills/gerador_jrxml/SKILL.md`.

### Fase 2 — Jasper Daemon JVM, Motor JRXML, PostgreSQL & Preview Híbrido
- `java-engine/` com `DaemonServer.java` (`--action serve`), suporte a `JRMapCollectionDataSource` com coerção automática de tipos e gerenciador Python `backend/app/services/jasper_daemon.py`.
- Motor JRXML em `backend/app/jrxml/`:
  - `scaffolder.py`: geração determinística de `.jrxml` base (`RETRATO 595x842` e `PAISAGEM 842x595`, 36 fields padrão + fields das perguntas + UUIDv4).
  - `linter.py`: auditoria estrita Fase 4 (bem-formação XML, `isBlankWhenNull="true"`, expressões seguras, UUIDs únicos, fields/params declarados, limites geométricos de banda e ordem XSD).
  - `builder.py`: helpers Python de alto nível (`DetailBandBuilder`).
  - `mock_data.py`: geração dos 3 cenários fictícios (`full`, `stress`, `blank`), subreports mock offline e reescritor de preview híbrido (`db_hybrid` via CTE / `offline` em memória).
- Governança PostgreSQL em `backend/app/services/postgres_service.py` e `backend/app/api/database.py`:
  - CRUD de perfis com senhas protegidas no Windows Credential Manager (`keyring`) + fallback criptografado (`.vault.json` via `FICHA_STUDIO_VAULT_KEY`).
  - Flag `read_only`, **Dry-Run obrigatório (`BEGIN/ROLLBACK`)** emitindo token SHA-256 à prova de adulteração, `COMMIT` validado atualizando `template_db_id` + `gate2_sql_insert` e `inspect-select` (`LIMIT 0` → OID/classe Java).

### Fase 3 — Frontend Web Studio (`frontend/src/`)
- **Design System & Shell**: temas Claro (*Prontuário Claro*) e Escuro (*Console Cirúrgico*), componentes reutilizáveis (`Button`, `Badge`, `Card`, `Dialog`, `Tabs`, `Switch`, `Toast`, `SplitPane`, `CodeEditor` Monaco), `StudioShell` com indicadores `API`/`JVM` e persistência de navegação no `F5` via hash URL (`#project=<id>&section=<section>`).
- **Projetos & Configurações (`features/projects/`, `features/settings/`)**: Dashboard com busca/filtro, modal de criação (`PDF`/`JSON`/`JRXML`), visão geral com gates/revisões/restore/PDF original e Configurações (perfis PG + teste de latência, subreports `.jasper`, harnesses e skills).
- **Form Builder (`features/form-builder/`)**: CRUD e drag-and-drop (`@dnd-kit`) de perguntas/seções e respostas (11 tipos Salutem + opções `COMBOBOX`), sincronizado em tempo real com Monaco JSON, avisos clínicos e conferência do PDF original.
- **SQL & Banco (`features/sql-db/`)**: Monaco SQL (`INSERT` / `SELECT`), diff com revisão salva, regeneração configurável, validação sintática, fluxo estrito de 2 etapas Dry-Run → invalidação automática ao editar → diálogo de confirmação → COMMIT, e tabela `inspect-select`.
- **Jasper Studio Light (`features/jasper-studio/`)**: Monaco XML, Scaffold, Linter clicável por linha, compilação JVM, live-reload, preview real **PDF.js** (+ fallback PNG) nos 3 cenários (`full`/`stress`/`blank`) e modos (`auto`/`offline`/`db_hybrid`), seleção retangular visual com recorte PNG automático (`POST /jasper/preview/crop-feedback`), botão 1-clique **Abrir Chat IA** e exportação do pacote `<slug>_entrega_salutem.zip`.

### Fase 4 & Release Readiness — Agentes, Streaming SSE/WS, MCP & Empacotamento
- **Harnesses & Protocolo Real `agy`**: `AgyHarness` (SDK + CLI headless oficial `--input-format stream-json --output-format stream-json --add-dir --mode plan|accept-edits --print-timeout`), `OpenCodeHarness`, `ClaudeCodeHarness` e `CodexHarness`.
- **8 Ferramentas Determinísticas MCP + Servidor Stdio (`backend/app/mcp_tools/`)**:
  - `inspect_clinical_pdf`, `render_pdf_preview_pages`, `crop_pdf_feedback_region`, `get_salutem_skill`, `extract_pdf_geometry`, `save_validated_json`, `validate_and_compile_jrxml`, `render_preview_images` (todas expostas em `GET /api/mcp-tools`).
  - Servidor MCP stdio JSON-RPC 2.0 executável via `python -m backend.app.mcp_tools.mcp_server`.
- **Orquestrador & Chat IA (`backend/app/services/agent_orchestrator.py`, `backend/app/api/agent.py`, `frontend/src/features/agent-chat/`)**:
  - Controle estrito de 2 Gates (`gate1_json` / `gate3_jrxml`), streaming SSE (`POST /agent/stream`) e WebSocket (`WS /agent/ws`), sincronização automática de artefatos gravados no workspace em Gate 2, inclusão automática de recortes PNG de feedback visual em `image_paths`.
  - `AgentChatDrawer` acoplável com *reflow* em desktop (`xl:pr-[440px]`), raciocínio e *tool calls* colapsáveis, thumbnails de recortes visuais e banner de aprovação rápida (**"Autorizar e gerar artefato (Autorizado)"**).
- **Empacotamento & CI/CD**:
  - Launchers Windows PowerShell 5.1: `scripts/start_local.ps1` (auto-build + abertura do navegador) e `scripts/dev.ps1` (FastAPI `--reload` + Vite HMR).
  - `Dockerfile` multi-stage (`node:22-alpine` + `python:3.13-slim-bookworm` + `openjdk-17-jre-headless` + fontes), `.dockerignore` e `docker-compose.yml`.
  - `.github/workflows/build.yml` validando `backend-tests`, `frontend-tests`, `docker-validate` (build + `/api/health`) e publicando automaticamente o bundle portátil `.zip` na GitHub Release em tags `v*`.

### Melhorias Pós-1.0.0 já entregues em `main` (`bc6212a`, `4437952`)
- **AGY CLI + MCP nativo funcional**:
  - `AgyHarness` configurado com `--dangerously-skip-permissions` por padrão (`AGY_SKIP_PERMISSIONS`) e provisionamento automático do plugin de workspace `.agents/plugins/salutem/` (`studio` → namespace `salutem_studio`, com `disabled: false`, `disabledTools: []`, `alwaysAllow` e remoção de pastas legadas duplicadas).
  - `StudioMcpServer` hardened para pipes no Windows (`readline()` sem read-ahead buffer + `reconfigure(encoding="utf-8")`) e `annotations` MCP padrão nas 8 ferramentas em `studio_tools.py`.
  - Proteção no parser e no orquestrador contra ferramentas presas em `"running"` e contra falsos `GATE_REQUEST` / *"Análise concluída"* em turnos abortados sem texto; detecção de revisões salvas diretamente via MCP sem duplicação.
- **Padronização dos outros 3 Harnesses (MCP + permissões headless)**:
  - **Claude Code (`claude_harness.py`)**: `--mcp-config`, `--dangerously-skip-permissions` (`CLAUDE_SKIP_PERMISSIONS`), prevenção do estouro de 32 KB no Windows (`WinError 206`) na fase `jrxml` enviando prompts longos via `.claude/studio_system_prompt.md` + `stdin`, e encerramento seguro de tools pendentes.
  - **OpenAI Codex (`codex_harness.py`)**: `--skip-git-repo-check`, sandbox por Gate (`read-only` no Gate 1; `--dangerously-bypass-approvals-and-sandbox` no Gate 2 via `CODEX_SKIP_PERMISSIONS`), injeção do MCP via `-c mcp_servers.salutem_studio.*` e suporte a `file_change` no JSONL.
  - **OpenCode (`opencode_harness.py`)**: materialização de `opencode.json` com MCP `salutem_studio` e permissões por Gate (excluído do scanner de artefatos clínicos).
- **Atualização automática da interface sem F5**:
  - Backend emite `latest_artifacts` nos eventos `workspace_sync` e `DONE`, e marca `exports/latest_preview.json` com `stale: true` + `jrxml_version`/`jrxml_sha256` ao salvar nova revisão `.jrxml`.
  - Frontend propaga `onArtifactSynced` / `artifactSyncTick` e observa `project.latest_artifacts` em `FormBuilderView`, `SqlDbView`, `JasperStudioView` (recarregando Monaco + disparando re-renderização automática do Preview com a nova revisão) e `ProjectOverviewView` (revisões).
- **Quick Wins de Hardening, Imports & Build**:
  - CORS endurecido em `backend/app/main.py` via `STUDIO_CORS_ORIGINS` (padrão restrito a `localhost` / `127.0.0.1`; wildcard `*` sem `allow_credentials`).
  - Cofre fallback em `backend/app/services/postgres_service.py` rejeitando placeholders inseguros (`change-me-in-production`) e remoção do default literal no `docker-compose.yml`.
  - Permissões do GitHub Actions (`.github/workflows/build.yml`) restringidas para `contents: read` global e `contents: write` exclusivo no job `release`.
  - Padronização dos imports diretos `from app.*` → `from backend.app.*` nos harnesses e testes.
  - `frontend/vite.config.ts` atualizado com `ws: true` no proxy `/api` e `manualChunks` (`vendor-react`, `vendor-monaco`, `vendor-pdfjs`, `vendor-dndkit`, `vendor-icons`).
  - Limpeza de worktrees e branches locais já mergeadas (`feat/e3-*`, `feat/e4-*`, `swarm-*`, `feat/v1-*`).

### `v1.1.0` — Report Workbench Completo, Conectores & Hub de Clientes
- **Bloco 0 — Fundação Compartilhada (`secret_vault.py`, `default_credentials_service.py`, `sqlite_store.py`)**:
  - Cofre unificado com **PBKDF2-HMAC-SHA256 (600k) + AES-256-GCM** (formato v2 retrocompatível com v1) e `keyring` do OS.
  - Credenciais padrão locais (nunca built-in no repositório) por tipo (`postgres`, `sftp`, `jasperserver`) com herança `credential_mode = 'default' | 'custom'` e descoberta de databases (`GET /api/db/profiles/{id}/databases`).
  - Migração idempotente SQLite v1.0 → v1.1 adicionando `project_kind`, `source_origin_json`, `default_db_profile_id`, `client_system_id`, `entry_mode` ampliado e tabela `agent_sessions`.
- **Bloco 1 — Modo Relatório Livre, SQL Workbench/MCP Read-Only, `$P{}` Live & Sessão Contínua**:
  - Projetos `free_report` sem etapas exclusivas de ficha clínica, SQL Workbench + Schema Explorer read-only (`pg_schema_inspector.py`), 3 novas ferramentas MCP (`list_db_tables`, `describe_db_table`, `preview_db_select`, totalizando **11 ferramentas**), parâmetros dinâmicos `$P{}` com preview `db_live`, skill `manutencao_relatorio` e retomada/reset de sessão nos 4 harnesses.
- **Bloco 2 — Conector SSH/SFTP (`sftp_service.py`, `api/sftp.py`)**:
  - Perfis SFTP com `read_only` padrão em `PRD`, navegador remoto, importação `.jrxml` / decompilação `.jasper` via JVM e deploy em 2 etapas (padrão `jrxml_only`, compilação JVM, diff, token de uso único e backup `.bak.<timestamp>`).
- **Bloco 3 — Conector JasperReports Server REST v2 (`jasperserver_service.py`, `api/jasperserver.py`)**:
  - Autenticação `/rest_v2/login` + `JSESSIONID`/Basic, navegador de pastas/`Report Units`, importação com subreports e publicação controlada em 2 etapas (update de `main_jrxml` ou criação de nova `Report Unit`).
- **Bloco 4 — Hub de Clientes Multi-Sistema & Sincronização do Portal Logado (`client_catalog_service.py`, `ClientsView`)**:
  - Modelo 1:N (`client_units` → `client_systems`: Ambulatorial, Hospitalar, Painel, Compras, DEV/HML/PRD), links web clicáveis, parser compatível com o payload real camelCase (`/api/management/data`) via snippet/upload na sessão autenticada do colaborador, mantendo **zero** URLs internas, clientes ou credenciais no Git.

### `v1.1.1` — Motor Nativo `repo:/...`, Suporte SSH `.key` & Redesign UX para Usuários Leigos
- **Motor Nativo `repo:/...` na JVM & Auto-Fetch (`RepoSchemeRepositoryService.java`, `JasperProcessor.java`, `jasperserver_service.py`, `jasper_preview.py`)**:
  - Resolução nativa de `repo:/...` no `jasper-daemon.jar` (sem alterar o `.jrxml` original), descoberta recursiva de subreports/imagens/estilos/`.jrtx` e `reportUnit` usados como subreport, espelhamento em `report_unit_resources/repo/` + cache compartilhado por servidor, inclusão em todos os modos de preview (`offline`, `db_hybrid`, `db_live`), auto-fetch sob demanda e endpoints `GET/POST /jasper/repo-resources` e `sync-repo-resources`.
- **Suporte a Arquivo `.key` SSH (Padrão & por Perfil)**:
  - Upload de `.key`/`.pem` no cofre AES-256-GCM (`private_key_filename`) + caminho local opcional em disco (`private_key_path`), com suporte a OpenSSH, RSA, Ed25519 e ECDSA em `DefaultCredentialsTab` e `SftpProfilesTab`.
- **Redesign Geral da Interface para Usuários Leigos & Ferramentas de Busca**:
  - Tela **`Início`** guiada (`HomeView`) com 3 cartões de tarefa, ★ Clientes Favoritos, Trabalhos Recentes e guia rápido de primeiro uso.
  - Cabeçalho **Dual-Mode** (`StudioShell`) sem abas desabilitadas, **Busca Global `Ctrl+K`** (`CommandPalette`) e seletores buscáveis (`SearchableSelect`).
  - **Clientes Master-Detail** (`ClientsView`) com exploradores inline full-height (`JasperServerBrowser` e `SftpBrowser`), última pasta lembrada, pastas favoritas e abertura em **1 clique / duplo clique** direto no Studio.
  - **Jasper Studio Visual-First** (`Visual (Preview + IA)` como padrão para `free_report`, `Dividido`, `Só Código`), menu `Exportar ▾`, chip `repo:/...`, botão contextual de publicação e preview inicial inteligente para `$P{}` obrigatórios.
  - **Configurações** (`SettingsView`) com sidebar categorizada e busca + filtro de ambiente + paginação (25/página) para grandes catálogos de conexões.

#### Rodada QA `v1.1.1` — Integridade, Navegação, Configurações & Clientes (`65302e3`, `1fd006f`, `bd7b87c`)
- **Integridade de Projetos & Exportação**: `blank_report` inicializado com `.jrxml` válido + fallback `/jrxml/scaffold`; `export-bundle` sempre regenerando o PDF quando `stale`/hash divergir e totalmente compatível com projetos `JRXML-only`.
- **Validações & Higiene Backend**: `422` em `base_url` do JasperServer, validação de chave PEM SSH, esquema `http(s)` obrigatório em `system_url`, bloqueio de `SELECT ... INTO` pré-conexão + HTTP `502` coerente e limpeza automática de FKs órfãs ao excluir perfis.
- **Versão, Branding & Launchers**: `APP_VERSION = "1.1.1"`, `favicon.svg` e launchers PowerShell 5.1 detectando `frontend/dist` desatualizado e dependências `.venv`.
- **Configurações, Seletores & Navegação**: modal PostgreSQL com `Ambiente`, `Modo de Credenciais` e **Descobrir bancos** (`GET /api/db/profiles/{id}/databases`); `SearchableSelect` em SQL Workbench, Deploy Modals e `ClientSystemFormDialog`; `Ctrl+K` com deep-link filtrado; Guia Rápido abrindo `default_credentials`; eliminação da race 404 do PDF.js; Assistente IA dedicado em `free_report`; escolha de tipo em `Importar JRXML`; ajustes de layout `1280×800` e higiene de hash URL.

#### Preview PDF Ampliado, Negrito/Itálico JVM & Agente AGY Quente (`a05c2d1`, `cad7b5d`, `0ca6eed`)
- **Fontes reais na JVM (`jasper-daemon.jar`)**: empacotamento de `jasperreports-fonts` + `salutem-fonts.xml` com `DejaVu Sans` (`Regular`/`Bold`/`Oblique`/`BoldOblique`) embutidas no PDF, eliminando o fallback `Helvetica` sem negrito/itálico.
- **Preview PDF & Anotações Visuais**: `PreviewControlBar` clínico em 1 linha (`Exportar ▾`), zoom `Ajustar à página` / `Largura` (até `220%`) / `200%` + modo `Tela cheia` (`Esc`); popover compacto `Ajustes (N)` substituindo a gaveta inferior, com resolução manual/automática (`POST /jasper/feedback/resolve`) e ocultação automática das caixas após sync de revisão JRXML.
- **Agente AGY Quente & Controle de Modelo/Effort**: `AgyPersistentSessionPool` + pré-aquecimento via `/agent/warmup`; descoberta `GET /api/harnesses/{id}/models` + seletor de **Modelo + Effort (`--effort`)** e badge do modelo na resposta; PNGs de `uploads/source.pdf` anexados automaticamente na fase `jrxml` e prompts delta enxutos em sessões retomadas.

---

## 3. Baseline de Qualidade & Verificação (`main`)

| Camada | Comando / Pipeline | Resultado Atual |
| :--- | :--- | :--- |
| **Backend (Python + JVM real + MCP)** | `.\.venv\Scripts\pytest.exe` | **205 passed** |
| **Frontend Typecheck** | `npm --prefix frontend run typecheck` | **0 erros** |
| **Frontend Unit/Component** | `npm --prefix frontend test` | **15 arquivos, 88 passed** |
| **Frontend Production Build** | `npm --prefix frontend run build` | **OK** (`frontend/dist/`, `v1.1.1`) |
| **CLI Real `agy.exe`** | `AgyHarness` + `--input-format stream-json --output-format stream-json --dangerously-skip-permissions` | **OK** (streaming + MCP `salutem_studio`) |
| **E2E Navegador** | FastAPI + JVM real (`v1.0.0`, 8 MCP tools, F5 hash, crop PNG + thumbnail, Claro/Escuro) | **OK** (0 erros de console) |
| **GitHub Actions CI & Release** | [Run #45749319313](https://github.com/fernandocalisto/automatizador-fichas/actions/runs/45749319313) (`v1.0.0`) | **4/4 jobs verdes** + asset `salutem-ficha-studio-v1.0.0.zip` publicado |

---

## 4. Como Executar

### Uso local (Windows)
```powershell
.\scripts\start_local.ps1
```
*(Sobe o FastAPI servindo `frontend/dist/` em `http://127.0.0.1:8000` e abre o navegador automaticamente.)*

### Uso local em rede — LAN (Windows, porta `8000` em `0.0.0.0`)
```powershell
.\scripts\start_network.ps1
```
*(Expõe o Studio na porta `8000` para acesso na rede interna via `http://<IP-DA-REDE>:8000`.)*

### Desenvolvimento (Backend `--reload` + Vite HMR)
```powershell
.\scripts\dev.ps1
```

### Docker (Servidor Interno)
```bash
docker compose up --build -d
```

### Servidor MCP Stdio (para integração direta em CLIs como `agy`, `claude`, `codex`)
```powershell
.\.venv\Scripts\python.exe -m backend.app.mcp_tools.mcp_server
```
Exemplo de registro no `agy`:
```powershell
agy mcp add salutem_studio .\.venv\Scripts\python.exe -- -m backend.app.mcp_tools.mcp_server
```

---

## 5. Decisões Arquiteturais & Backlog Futuro (`v1.2+` / Sob Demanda)

Decisões estratégicas consolidadas na entrega `v1.1.1`:

- **Posicionamento — AI-First Report & Form Workbench acessível para usuários leigos**: foco em leveza, velocidade (~150ms), navegação guiada sem jargão desnecessário (`Início`, `Ctrl+K`, 1 clique em Clientes → Studio, modo `Visual (Preview + IA)` padrão) e IA integrada com visão + acesso read-only ao schema do banco.
- **Segurança & Privacidade (Zero Dados Corporativos no Git)**: nenhuma URL interna, cliente, IP, senha ou chave `.key` é versionada no código — credenciais padrão/personalizadas e catálogos sincronizados ficam estritamente locais (OS Keyring / `SecretVaultService` AES-256-GCM / `workspaces/` gitignored).
- **Foco 100% em utilidade diária (Ambulatorial + Hospitalar)**: cobre fichas ambulatoriais via **SFTP** (incluindo chaves `.key`) e relatórios Hospitalares/gerais via **JasperReports Server (`Report Unit` + `repo:/...` nativo na JVM)**.

### Backlog Futuro / Adiado (`v1.2+` / Sob Demanda)
- **Contas multiusuário, Login (`STUDIO_AUTH_ENABLED`) & Trava Otimista (`409`)**: adiado por tempo indeterminado até haver demanda formal de servidor compartilhado.
- **BYOK simplificado (API Key Claude/OpenAI/Gemini)** na UI de Configurações (sem exigir contas multiusuário).
- **Engenharia Reversa de `template_ficha_clinica` (PostgreSQL Ambulatorial → `ficha.json`)**.
- **UI de Regras OCR / Regex Customizadas**: expor `backend/app/core/custom_regex.py` em *Configurações*.
- **Comparação visual lado a lado**: modo split *PDF Original vs Preview Jasper* e biblioteca de blocos JRXML.
- **Atualização de Actions no CI**: migrar `actions/*@v4` para versões nativas de Node 24 (`v5`/`v6`).
