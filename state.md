# Estado Atual do Projeto — Salutem Ficha Studio (`v1.0.0`)

> **Última atualização:** 2026-11-26  
> **Branch principal:** `main`  
> **Release publicada:** [`v1.0.0`](https://github.com/fernandocalisto/automatizador-fichas/releases/tag/v1.0.0)  
> **Status geral:** **Pronto para produção (Fases 1 a 4 + Release Readiness concluídas e validadas em CI/CD)**

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

---

## 3. Baseline de Qualidade & Verificação (`v1.0.0`)

| Camada | Comando / Pipeline | Resultado Atual |
| :--- | :--- | :--- |
| **Backend (Python + JVM real + MCP)** | `.\.venv\Scripts\pytest.exe` | **117 passed** |
| **Frontend Typecheck** | `npm --prefix frontend run typecheck` | **0 erros** |
| **Frontend Unit/Component** | `npm --prefix frontend test` | **11 arquivos, 49 passed** |
| **Frontend Production Build** | `npm --prefix frontend run build` | **OK** (`frontend/dist/`) |
| **CLI Real `agy.exe`** | `AgyHarness` + `--input-format stream-json --output-format stream-json` | **OK** (`text_delta`, `gate_request`, `done`, `conversation_id`, `usage`) |
| **E2E Navegador** | FastAPI + JVM real (`v1.0.0`, 8 MCP tools, F5 hash, crop PNG + thumbnail, Claro/Escuro) | **OK** (0 erros de console) |
| **GitHub Actions CI & Release** | [Run #45749319313](https://github.com/fernandocalisto/automatizador-fichas/actions/runs/45749319313) (`v1.0.0`) | **4/4 jobs verdes** + asset `salutem-ficha-studio-v1.0.0.zip` publicado |

---

## 4. Como Executar

### Uso local (Windows)
```powershell
.\scripts\start_local.ps1
```
*(Sobe o FastAPI servindo `frontend/dist/` em `http://127.0.0.1:8000` e abre o navegador automaticamente.)*

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
agy mcp add salutem-ficha-studio .\.venv\Scripts\python.exe -- -m backend.app.mcp_tools.mcp_server
```

---

## 5. Backlog Pós-1.0.0 (Melhorias Futuras Opcionais)

- **UI de Regras OCR / Regex Customizadas**: expor o motor já pronto em `backend/app/core/custom_regex.py` como nova aba em `Configurações` para cadastro e teste de substituições OCR.
- **Reuso de `--conversation` no `AgyHarness`**: persistir `conversation_id` por projeto/fase no SQLite para retomar sessões nativas do `agy` entre turnos subsequentes (reduzindo latência e tokens de contexto).
- **Atualização de Actions no CI**: migrar `actions/checkout@v4`, `actions/setup-node@v4`, `actions/setup-java@v4` e `actions/upload-artifact@v4` para as versões nativas de Node 24 (`v5`/`v6`) para eliminar os avisos de deprecação do GitHub Actions.
- **Code-splitting do bundle frontend**: dividir `monaco` / `pdfjs-dist` via `manualChunks` no `vite.config.ts` para reduzir o chunk principal (`index-*.js` ~575 kB).
- **Limpeza de branches remotas/locais antigas**: remover branches de feature já mergeadas (`feat/v1-web-studio`, `feat/v1.0.0-release-readiness`, `feat/e3-*`, `feat/e4-*`) caso não sejam mais necessárias para referência.
