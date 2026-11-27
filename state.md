# Estado Atual do Projeto — Salutem Ficha Studio (`v1.0.0` → Roadmap `v1.1–v1.3`)

> **Última atualização:** 2026-11-26  
> **Branch principal:** `main` (`4437952`)  
> **Release publicada:** [`v1.0.0`](https://github.com/fernandocalisto/automatizador-fichas/releases/tag/v1.0.0)  
> **Status geral:** **Em produção local + pós-1.0.0 em `main` (Harnesses/MCP padronizados e auto-refresh sem F5); Roadmap `v1.1` → `v1.3` definido**

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
| **Backend (Python + JVM real + MCP)** | `.\.venv\Scripts\pytest.exe` | **123 passed** |
| **Frontend Typecheck** | `npm --prefix frontend run typecheck` | **0 erros** |
| **Frontend Unit/Component** | `npm --prefix frontend test` | **11 arquivos, 49 passed** |
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

## 5. Decisões Arquiteturais & Escopo Futuro (Roadmap `v1.1` → `v1.3`)

Decisões estratégicas alinhadas para evolução do Salutem Ficha Studio:

- **Modelo de Implantação — Híbrido**: manter a experiência local zero-fricção no Windows (`scripts/start_local.ps1`, sem tela de login) e evoluir o modo servidor compartilhado em Docker/Linux na rede interna.
- **Autenticação & Concorrência no Servidor**:
  - Login local (usuário/senha + papéis `admin` e `member`) ativado exclusivamente no modo servidor via `STUDIO_AUTH_ENABLED=true`.
  - Projetos compartilhados entre a equipe com auditoria real de autor (`created_by`, `decided_by`, logs de commit/deploy).
  - Manter **SQLite (WAL)** como banco interno do Studio (adequado para ~5–30 usuários simultâneos) adicionando **trava otimista de revisão** (`expected_version` → HTTP `409 Conflict`) para evitar sobrescritas concorrentes.
- **Contas de IA (Harnesses) no Servidor**:
  - Suportar **conta geral da empresa** (padrão/fallback administrável) **+** **conta pessoal opcional por usuário**.
  - Isolamento por `HOME` dedicado dentro do volume persistente (`/data/homes/company/` e `/data/homes/users/<user_id>/`) para contas OAuth (`agy`, `claude`, `codex`, `opencode`), com **fluxo guiado na UI** (*Device Code* / colar URL ou código de autorização OAuth) **+** opção de **API Key (BYOK)** no mesmo perfil, protegida no cofre (`FICHA_STUDIO_VAULT_KEY`).
- **Ciclo Completo de Fichas Existentes (Engenharia Reversa + Deploy)**:
  - Integrar tanto a estrutura clínica no **PostgreSQL Salutem** quanto os arquivos `.jrxml`/`.jasper` e subreports hospedados nos **servidores SSH/SFTP** e no **JasperReports Server (JasperServer)** — com importação direta para o Studio e deploy controlado por Gate humano + backup automático (`.bak`).

---

### Milestone `v1.1` — Confiabilidade IA/MCP, Sessão Contínua & Engenharia Reversa PostgreSQL
1. **Confiabilidade MCP & JRXML**:
   - Validar em ambiente real todas as 8 ferramentas MCP sob o namespace `salutem_studio` (em especial `validate_and_compile_jrxml` e `render_preview_images` na fase `jrxml` do AGY) e garantir erro claro/fallback quando algum servidor MCP falhar.
   - Garantir que o fluxo `PDF → JSON → SQL → JRXML → Preview` conclua sem passos manuais extras em todos os 4 harnesses.
2. **Continuidade de Sessão dos Agentes**:
   - Persistir `conversation_id` / `session_id` / `thread_id` por `(project_id, phase, harness)` no SQLite para retomar sessões nativas (`agy --conversation`, `claude --resume`, `codex exec resume`, `opencode`) entre turnos — reduzindo drasticamente latência e consumo de tokens, com botão "Nova sessão" no chat.
3. **Engenharia Reversa do PostgreSQL Salutem (`entry_mode="db_import"`)**:
   - Novo fluxo no modal de criação de projeto: selecionar um perfil PostgreSQL, listar/buscar fichas existentes em `template_ficha_clinica` e importar em modo **somente leitura** (`template` + `perguntas` + `respostas`) gerando automaticamente `ficha.json`, `SELECT` Jasper e base pronta para criar/ajustar o `.jrxml` (ou clonar como novo template via `INSERT`).
   - *(Evolução opcional v1.1.x)*: gerador de SQL de migração/diff (`UPDATE` + `INSERT` de novas perguntas/respostas) com Dry-Run obrigatório para evoluir templates existentes no banco.

---

### Milestone `v1.2` — Modo Servidor Multiusuário, Contas OAuth/BYOK & Docker com CLIs
1. **Usuários, Login & Auditoria (`STUDIO_AUTH_ENABLED=true`)**:
   - Tabela `users` (hash Argon2/bcrypt, papéis `admin` e `member`, sessão JWT em cookie HttpOnly) + tela de login e gestão de usuários pelo Admin.
   - No modo local (`STUDIO_AUTH_ENABLED=false`, padrão em `start_local.ps1`), o acesso continua direto sem login.
   - Registrar autor real em revisões, aprovações de Gate e execuções de Dry-Run/Commit SQL.
2. **Trava Otimista de Revisões**:
   - Incluir `expected_version` nas mutações de artefatos (`json`, `sql_*`, `jrxml`) retornando `409 Conflict` com alerta claro na UI caso outro membro da equipe tenha salvo uma versão mais nova antes.
3. **Contas de Harness no Servidor (Empresa + Pessoal)**:
   - Cofre de credenciais por escopo (`company` vs `user_id`) e gestão de diretórios `HOME` isolados (`/data/homes/...`).
   - Tela em *Configurações → Minha Conta / IA* permitindo escolher *"Conta geral da empresa"* ou *"Minha conta"*, autenticar via fluxo guiado OAuth (*Device Code* / URL de autorização) ou informar API Key (BYOK), com indicador de status por harness.
   - `Dockerfile` e `docker-compose.yml` atualizados com suporte aos CLIs de IA na imagem runtime e volume persistente para `/data/homes`.

---

### Milestone `v1.3` — Integração SSH/SFTP & JasperReports Server
1. **Perfis de Servidores de Relatórios (Cofre Seguro)**:
   - CRUD em *Configurações* para perfis **SSH/SFTP** (host, porta, usuário, senha ou chave privada SSH no cofre, diretório remoto base de `.jrxml`/`.jasper` e subreports, flag `read_only` / ambiente `HML`/`PRD`).
   - CRUD para perfis **JasperReports Server** (URL base, organização, usuário/senha ou token no cofre, caminho base de relatórios no repositório, flag `read_only` / ambiente `HML`/`PRD`).
2. **Importação Direta de Fichas Existentes**:
   - Navegador de arquivos SFTP / árvore de recursos JasperServer para importar `.jrxml` (e sincronizar subreports `.jasper`) diretamente para um projeto do Studio — podendo combinar no mesmo projeto a estrutura importada do PostgreSQL (`v1.1`) + o `.jrxml` real puxado do servidor.
3. **Deploy Controlado com Gate Humano & Backup Automático**:
   - Fluxo de publicação em 2 etapas (semelhante ao Dry-Run → Commit do PostgreSQL): pré-checagem de compilação JVM + diff com o arquivo remoto + aprovação explícita de Gate + **backup automático (`.bak` com timestamp)** antes de sobrescrever o `.jrxml`/`.jasper` no SFTP ou fazer upload via REST API no JasperServer (bloqueado em perfis `read_only`).

---

### Backlog Técnico & Melhorias Contínuas (`v1.x`)
- **UI de Regras OCR / Regex Customizadas**: expor o motor já pronto em `backend/app/core/custom_regex.py` como nova aba em *Configurações* para cadastro e teste de substituições OCR.
- **Comparação visual lado a lado**: modo split *PDF Original vs Preview Jasper* no Jasper Studio Light e biblioteca de blocos/templates JRXML reutilizáveis.
- **Atualização de Actions no CI**: migrar `actions/checkout@v4`, `actions/setup-node@v4`, `actions/setup-java@v4` e `actions/upload-artifact@v4` para versões nativas de Node 24 (`v5`/`v6`).
- **Migração criptográfica do cofre fallback**: evoluir `_EncryptedVault` para `cryptography` (AES-256-GCM / Fernet) antes do armazenamento de API Keys BYOK e credenciais SFTP/JasperServer (`v1.2`/`v1.3`).
