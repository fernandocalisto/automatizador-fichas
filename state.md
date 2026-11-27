# Estado Atual do Projeto — Salutem Ficha Studio (`v1.1.1`)

> **Última atualização:** 2026-11-27  
> **Branch principal:** `main` (`v1.1.1`)  
> **Release anterior publicada:** [`v1.0.0`](https://github.com/fernandocalisto/automatizador-fichas/releases/tag/v1.0.0)  
> **Plano detalhado executado:** [`implementation_plan_v1.1.md`](./implementation_plan_v1.1.md) + Redesign UX / `repo:` / SSH `.key` (`v1.1.1`)  
> **Status geral:** **`v1.1.1` implementada e validada ponta a ponta (Motor Nativo `repo:/...` na JVM, SSH `.key` padrão/por perfil, Tela `Início`, Busca Global `Ctrl+K`, Clientes Master-Detail com 1-click JasperServer/SFTP, Jasper Studio Visual-First e Configurações com sidebar/busca/paginação)**

---

## 1. Visão Geral da Arquitetura

O **Salutem Ficha Studio** substituiu integralmente a GUI legada em PySide6 por uma estação de trabalho web unificada em 3 camadas:

1. **Frontend Web (`frontend/`)**: React 19 + TypeScript + Vite 6 + Tailwind CSS v4 + Monaco Editor + `@dnd-kit` + `pdfjs-dist` v5 + Vitest.
   - Compilado em `frontend/dist/` e servido diretamente pelo FastAPI em produção/uso local (ou via Vite em `:5173` com proxy `/api` em desenvolvimento).
2. **Backend FastAPI (`backend/app/`)**: Python 3.13 + SQLite (WAL) + workspaces em disco + `psycopg` (PostgreSQL) + OS Keyring / Cofre criptografado + `pymupdf` + Orquestrador de Agentes (`AgentHarness` + SSE/WebSocket + Servidor MCP stdio JSON-RPC 2.0).
3. **Jasper Daemon JVM (`java-engine/` + `resources/bin/jasper-daemon.jar`)**: Motor Java baseado em JasperReports `6.21.3` com modo HTTP residente (`--action serve` em `127.0.0.1`), compilação/exportação em ~80–200ms e os 4 subreports `.jasper` built-in em `resources/subreports/`.

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

---

## 3. Baseline de Qualidade & Verificação (`main`)

| Camada | Comando / Pipeline | Resultado Atual |
| :--- | :--- | :--- |
| **Backend (Python + JVM real + MCP)** | `.\.venv\Scripts\pytest.exe` | **177 passed** |
| **Frontend Typecheck** | `npm --prefix frontend run typecheck` | **0 erros** |
| **Frontend Unit/Component** | `npm --prefix frontend test` | **15 arquivos, 68 passed** |
| **Frontend Production Build** | `npm --prefix frontend run build` | **OK** (`frontend/dist/`) |
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

## 5. Decisões Arquiteturais & Escopo Futuro (`v1.1` — Ver `implementation_plan_v1.1.md`)

Decisões estratégicas atualizadas em **2026-11-27** (detalhamento completo em [`implementation_plan_v1.1.md`](./implementation_plan_v1.1.md)):

- **Posicionamento — AI-First Report & Form Workbench**: não tentar clonar os painéis visuais legados do Jaspersoft Studio; maximizar **leveza, velocidade (~150ms), zero fricção e IA integrada com visão + acesso read-only ao schema do banco**.
- **Foco 100% em utilidade diária (Ambulatorial + Hospitalar)**: eliminar 4 ferramentas pesadas/manuais (~~Jaspersoft Studio~~, ~~DataGrip~~, ~~cadastro manual de templates~~ e ~~Tabby/FileZilla~~), cobrindo fichas ambulatoriais via **SFTP** e relatórios Hospitalares/gerais via **JasperReports Server (`Report Unit`)**.
- **Contas multiusuário / Login (`STUDIO_AUTH_ENABLED`)**: **adiado por tempo indeterminado** para concentrar todo esforço em produtividade real antes de adicionar gestão de usuários.
- **Portal interno de gestão de unidades**: preparar interface plugável (`UnitCatalogProvider`) para sincronização futura automática de PostgreSQL, SFTP e JasperServer de todas as unidades assim que o formato de exposição dos dados for levantado.

---

### Milestone `v1.1` — Report Workbench Completo (4 Blocos Incrementais)
1. **Bloco 1 — Modo Relatório Livre + SQL Workbench & MCP de Schema + Parâmetros Dinâmicos + Sessão Contínua**:
   - Novo `project_kind="free_report"` pulando Form Builder/`INSERT` ambulatorial; SQL Workbench Read-Only (schemas, tabelas, colunas, PK/FK e `SELECT` seguro com `LIMIT 50`); 3 novas MCP tools (`list_db_tables`, `describe_db_table`, `preview_db_select`); Preview Live (`db_live`) com parâmetros `$P{...}` dinâmicos; continuidade de sessão nos 4 harnesses (`agent_sessions`) e skill `manutencao_relatorio`.
2. **Bloco 2 — Conector SSH/SFTP (`paramiko`)**:
   - Substitui Tabby/FileZilla para fichas ambulatoriais: perfis no cofre (`read_only` padrão em PRD), navegador SFTP, importação de `.jrxml` ou decompilação automática de `.jasper` via JVM Daemon, e deploy em 2 etapas (compilação JVM obrigatória + diff + backup remoto `.bak.<timestamp>`).
3. **Bloco 3 — Conector JasperReports Server (`Report Unit` — REST v2)**:
   - Portado dos contratos validados em `fernandocalisto/jasper-reports-tools`: perfis no cofre, navegador de pastas/`Report Units`, importação completa (`main_jrxml` + subreports/recursos em `_files/` + input controls) e deploy controlado com diff + backup.
4. **Bloco 4 — Hardening do Cofre (`cryptography`) & Gancho do Catálogo de Unidades**:
   - Extração para `secret_vault.py` com **AES-256-GCM** (retrocompatível com `.vault.json` v1) e interface `UnitCatalogProvider` pronta para sincronizar unidades do site interno de gestão.

---

### Backlog Futuro / Adiado (`v1.x` / Sob Demanda)
- **Contas multiusuário, Login (`STUDIO_AUTH_ENABLED`) & Trava Otimista (`409`)**: adiado por tempo indeterminado até haver demanda formal de servidor compartilhado.
- **BYOK simplificado (API Key Claude/OpenAI/Gemini)** na UI de Configurações (sem exigir contas multiusuário).
- **Engenharia Reversa de `template_ficha_clinica` (PostgreSQL Ambulatorial → `ficha.json`)**.
- **UI de Regras OCR / Regex Customizadas**: expor `backend/app/core/custom_regex.py` em *Configurações*.
- **Comparação visual lado a lado**: modo split *PDF Original vs Preview Jasper* e biblioteca de blocos JRXML.
- **Atualização de Actions no CI**: migrar `actions/*@v4` para versões nativas de Node 24 (`v5`/`v6`).
