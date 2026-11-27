# Changelog

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

## [1.1.0] - 2026-11-27

### Bloco 0 — Fundação Compartilhada (Cofre v2, Credenciais Padrão & Migração SQLite)
- **Cofre Unificado (`backend/app/services/secret_vault.py`)**: extração do cofre criptografado para serviço compartilhado usando `cryptography` (**PBKDF2-HMAC-SHA256 600k + AES-256-GCM** com autenticação AAD em formato `version: 2`), mantendo leitura retrocompatível das entradas `v1.0.0` e `keyring` primário no OS.
- **Credenciais Padrão vs Personalizadas (`default_credentials_service.py` + `/api/credentials/defaults`)**: suporte a credenciais padrão locais (nunca built-in no código) por tipo de conexão (`postgres`, `sftp`, `jasperserver`), incluindo `default_dbname` (geral/ambulatorial/hospitalar), `default_remote_base_dir` e herança via `credential_mode = 'default' | 'custom'`.
- **Migração SQLite v1.0 → v1.1 (`sqlite_store.py`)**: migração idempotente com preservação de projetos existentes adicionando `project_kind`, `source_origin_json`, `default_db_profile_id`, `client_system_id`, `entry_mode` ampliado (`blank_report`, `sftp_import`, `jasperserver_import`), tabela `agent_sessions` e descoberta de databases (`GET /api/db/profiles/{id}/databases`).

### Bloco 1 — Modo Relatório Livre, SQL Workbench & MCP Read-Only, Parâmetros `$P{}` e Sessão Contínua
- **SQL Workbench & Schema Explorer Read-Only (`pg_schema_inspector.py` + `SqlDbView`)**: listagem de schemas, tabelas/views, inspeção de colunas/PK/FK/classes Java e preview `SELECT` estritamente `READ ONLY` (`statement_timeout`, `LIMIT 1..200`, bloqueio de DDL/DML e `ROLLBACK` incondicional) + sincronização bidirecional `<queryString>` ↔ `sql_select`.
- **3 Novas Ferramentas MCP Read-Only (`db_tools.py`)**: `list_db_tables`, `describe_db_table` e `preview_db_select` (teto de 20 linhas), totalizando 11 ferramentas MCP.
- **Parâmetros Dinâmicos `$P{}` & Preview `db_live` (`jrxml/parameters.py`, `jasper_preview.py`, `ReportParamsBar`)**: detecção automática de parâmetros no `.jrxml`, persistência local por projeto e execução Live direta no Jasper Daemon JVM sem reescrita CTE.
- **Skill `manutencao_relatorio` & Continuidade de Sessão**: skill dedicada carregada automaticamente em projetos `free_report` e retomada/reset de sessão nos 4 harnesses (`agy`, `claude`, `codex`, `opencode`).

### Bloco 2 — Conector SSH/SFTP (`sftp_service.py` + `api/sftp.py`)
- Perfis SFTP com `default`/`custom`, senha ou chave PEM (RSA/Ed25519/ECDSA), trava `read_only` padrão em `PRD`, navegador remoto com proteção contra path traversal, importação de `.jrxml` e decompilação automática de `.jasper` via JVM Daemon, e deploy em 2 etapas (padrão `jrxml_only`, opções `both` e `jasper_only`, compilação JVM obrigatória, diff, `deploy_token` de uso único e backup `.bak.<timestamp>` + cópia local).

### Bloco 3 — Conector JasperReports Server (`jasperserver_service.py` + `api/jasperserver.py`)
- Cliente REST v2 (`POST /rest_v2/login`, `JSESSIONID` + fallback Basic + re-login 401, `username|org`, `serverInfo`, `resources`, inspeção de `Report Unit`), importação com resolução híbrida de subreports (`{uri}_files/*` e compartilhados `repo:/...` compilados localmente) e publicação segura em 2 etapas (update de `main_jrxml` com backup local ou criação de nova `Report Unit` com seleção de DataSource).

### Bloco 4 — Aba de Clientes Multi-Sistema & Sincronização do Portal Logado (`client_catalog_service.py` + `ClientsView`)
- Nova aba **Clientes** no topo do Studio com modelo 1:N (`client_units` → `client_systems`: Ambulatorial, Hospitalar, Painel, Compras, DEV/HML/PRD), link web clicável (`system_url`), atalhos diretos para criar Relatório Livre ou importar de SFTP/JasperServer e aba **Credenciais Padrão** em Configurações.
- Sincronização local sob demanda via sessão autenticada do colaborador no navegador (Bookmarklet/Snippet ou upload `.json`/`.html` com preview de diff antes de aplicar), mantendo **zero** URLs internas, clientes ou credenciais no repositório.

---

## [1.0.0] - 2026-11-25

### Fase 1 — Fundação Backend, Workspaces SQLite & Núcleo Salutem
- **Arquitetura Web FastAPI (`backend/app/`)**: transição do aplicativo desktop PySide6 para a plataforma web local/containerizada **Salutem Ficha Studio**.
- **Workspaces Persistentes em SQLite (WAL)**: gestão de projetos (modos `pdf`, `json` e `jrxml`), histórico imutável de revisões de artefatos com restauração, e máquina de estados dos 3 Gates (`gate1_json`, `gate2_sql_insert`, `gate3_jrxml`).
- **Núcleo Salutem Migrado e Testado**: validação dos 11 tipos de campo, geradores determinísticos de SQL `INSERT` (`DO $$`) e `SELECT` Jasper Reports, além de catálogo de subreports padrão (`cabecalho_retrato`, `cabecalho_paisagem`, `dados_paciente`, `rodape_retrato`) com suporte a overrides customizados.
- **Inspeção de PDF & API REST**: extração de metadados/geometria via `PyMuPDF`, endpoints `/api/health`, `/api/projects`, `/api/subreports`, `/api/settings` e documentação Swagger `/docs`.

### Fase 2 — Harnesses IA, MCP, PostgreSQL Vault & Jasper Daemon JVM
- **Orquestração de Harnesses IA & Skills Embutidas**: detecção e integração com `agy`, `opencode`, `claude` e `codex`, acompanhada das skills clínicas Salutem e servidor MCP para fluxo assistido com 2 Gates.
- **Serviço PostgreSQL Seguro (`psycopg` v3 + Cofre)**: CRUD de perfis de banco de dados com senhas protegidas em cofre (`keyring` / `FICHA_STUDIO_VAULT_KEY`), teste de conexão com latência/versão, trava de perfil somente leitura, execução **Dry-Run** (rollback automático) e **Commit** transacional com captura de `template_db_id`.
- **Jasper Daemon JVM (`java-engine/` -> `resources/bin/jasper-daemon.jar`)**: motor Java 17+ persistente para compilação `.jrxml`, diagnóstico de erros, geração de preview PDF em modo **Mock** ou **Live** (PostgreSQL), scaffold JRXML e exportação de pacote ZIP completo.

### Fase 3 — Interface Web SPA (React 19 + TypeScript + Tailwind v4)
- **Dashboard de Projetos, Visão Geral & Configurações**: criação de projetos via upload de PDF, JSON ou JRXML, controle visual dos 3 Gates, restauração de revisões, visualizador do PDF original e central de configurações (Perfis PostgreSQL, Subreports `.jasper`, Harnesses/Skills e Preferências).
- **Form Builder Visual (DnD) & Editor JSON**: edição arrasta-e-solta (`@dnd-kit`) dos campos e seções sincronizada em tempo real com **Monaco Editor**.
- **Workbench SQL & Banco de Dados**: editores `INSERT` e `SELECT` com opções avançadas de geração, seletor de perfil PostgreSQL, guarda visual de **Dry-Run / Commit** e inspetor de colunas.
- **Jasper Studio Light**: editor `.jrxml` com diagnósticos e live-reload, visualizador **PDF.js** com seleção de regiões para anotações, alternância Mock/Live e download do pacote ZIP.
- **Suíte Frontend (`Vitest` + Testing Library)**: cobertura automatizada dos fluxos de projetos, configurações, Form Builder, SQL/DB e Jasper Studio.

### Fase 4 — Launchers Locais, Docker Multi-Stage & Documentação v1.0.0
- **Launchers Windows PowerShell 5.1+**:
  - `scripts/start_local.ps1`: validação de `.venv` e `java`, build automático da SPA (`frontend/dist`), seleção automática de porta livre, healthcheck `/api/health`, abertura automática do navegador e encerramento limpo com `Ctrl+C`.
  - `scripts/start_network.ps1`: inicialização em rede local (`0.0.0.0:8000`) com detecção automática do IPv4 da LAN para acesso compartilhado por outros computadores na rede interna.
  - `scripts/dev.ps1`: inicialização paralela de `uvicorn --reload` e Vite dev server com URLs centralizadas e limpeza de árvore de processos ao sair.
- **Harnesses IA, MCP & Atualização Automática (sem F5)**:
  - Acoplamento automático do servidor MCP nativo (`salutem_studio`, 8 ferramentas com `annotations` e UTF-8/stdio seguro no Windows) e flags headless de permissão nos 4 harnesses (`agy`, `claude`, `codex` e `opencode`), incluindo proteção contra o limite de 32 KB de linha de comando no Windows para Claude Code na fase `jrxml`.
  - Proteção no parser e no orquestrador contra ferramentas presas em `"running"` e contra falsos `GATE_REQUEST` em turnos interrompidos.
  - Atualização reativa automática no Form Builder, Editor JSON, SQL & DB Workbench, Jasper Studio (incluindo re-renderização automática do Preview) e Histórico de Revisões assim que o agente altera qualquer artefato — sem precisar recarregar a página (`F5`).
- **Empacotamento Docker Multi-Stage & Compose**:
  - `Dockerfile` multi-stage (`node:22-alpine` + `python:3.13-slim-bookworm` com `openjdk-17-jre-headless`, fontes DejaVu/Liberation, `libpq5`, `curl`, usuário não-root `studio`, `/data` persistente e `HEALTHCHECK`).
  - `.dockerignore` otimizado e `docker-compose.yml` com volume nomeado `studio_data:/data` e variável `FICHA_STUDIO_VAULT_KEY`.
- **Documentação & Testes de Empacotamento**: `README.md` reescrito para `v1.0.0`, `CHANGELOG.md` consolidado e suíte `backend/tests/test_packaging_artifacts.py` garantindo os contratos de empacotamento e sintaxe dos launchers.

---

## [0.2.0] - 2026-11-14

### Adicionado
- **Nova Interface Gráfica em PySide6 (`MainWindow`)**:
  - Reescrita completa da interface substituindo o legado Tkinter por PySide6.
  - `QSplashScreen` nativo com logo arredondado, tempo mínimo de exibição e transição fade-out suave.
  - Navegação em 5 etapas no Wizard (`LandingPage`, `JsonEditorPage`, `QuestionsPage`, `SqlInsertPage`, `SqlSelectPage`) com atalhos globais (`Ctrl+1` a `Ctrl+5`, `Ctrl+N`, `Ctrl+O`, `Ctrl+S`, `F1`, `Ctrl+,`, `Ctrl+Q`).
  - Painel inferior acoplável (`QDockWidget`) com abas de **Output/Log**, **Validação** e **Propriedades**, além de `StatusBar` com indicadores de linha/coluna, encoding, tema e versão.
  - Componente de notificações flutuantes `Toast` empilhável com barra de progresso e auto-dismiss.
- **Sistema de Temas Dual (`ThemeService` + `ThemeSwitch`)**:
  - 4 temas globais da aplicação (`Claro`, `Escuro`, `Alto Contraste`, `Sistema`) via QSS.
  - 5 paletas de cores para os editores (`VSCode`, `Monokai`, `Dracula`, `GitHub`, `Solarized`) carregadas de `src/resources/editor_themes/*.json`.
- **Editor SQL Nativo (`SqlEditorWidget`)**:
  - Baseado em `QPlainTextEdit` + `SqlSyntaxHighlighter` (sem dependência de `QScintilla`), com realce de sintaxe para PostgreSQL e parâmetros Jasper Reports (`$P{}`, `$X{}`, `$P!{}`).
  - Margem lateral com numeração de linhas (`LineNumberArea`), configuração de tabulação (`tab_size`), exibição de espaços/tabs (`show_whitespace`) e zoom.
  - Busca incremental e substituição integradas com atalhos `Ctrl+F`, `Ctrl+H`, `F3` e `Shift+F3`.
- **Opções Avançadas e Persistência na Geração de SELECT Jasper (`SqlSelectPage`)**:
  - 4 estilos de formatação booleana (`COALESCE/BOOL_OR`, `'X'/''`, `'SIM'/'NÃO'`, `1/0`).
  - 3 modos de nomenclatura de colunas (`{pergunta}_{label}`, `label_only` como padrão, `label_sufixo`).
  - Controles para inclusão de observações (`_obs`), comentários de metadados e seleção granular dos 4 blocos adicionais (`Cabeçalho`, `Paciente`, `Profissional`, `Atendimento`).
  - Atualização automática do preview SQL em tempo real e persistência entre sessões via `ConfigService` (`QSettings` + JSON).
- **Auto-Updater Integrado com GitHub Releases (`UpdateService` + `UpdateDialog`)**:
  - Verificação assíncrona em background ao iniciar o aplicativo (respeitando intervalo de 24h e opção de ignorar versão).
  - Botão **"Verificar Agora"** e exibição da data/hora da última verificação em **Configurações → Geral**.
  - Diálogo de atualização com renderização de Release Notes em Markdown, download com barra de progresso e script `.bat` para substituição automática do executável no Windows.
- **Central de Configurações (`SettingsDialog`) e Serviços**:
  - Diálogo modal organizado em 5 páginas (`Geral`, `Tema`, `Editor SQL`, `Regex`, `Ajuda`).
  - Sincronização reativa de fonte, tamanho, tabulação, números de linha e espaços em branco nos editores JSON e SQL.
- **Empacotamento, Scripts de Build e Suíte de Testes Headless**:
  - `build.spec` otimizado para PyInstaller (`onefile`, `windowed`) e scripts `scripts/build_local.ps1` e `scripts/build_local.sh`.
  - Suíte automatizada com 41 testes (`pytest` em modo `offscreen`) cobrindo core, páginas do wizard, configurações e auto-updater.

### Alterado / Corrigido
- **Unificação dos 11 Tipos de Campo Salutem**: alinhamento entre `QuestionsPage`, `sql_insert.py` e `sql_select.py` (`BOOLEANO`, `BOOLEANO_RADIO`, `COMBO`, `COMBO_MULTI`, `TEXTO`, `TEXTO_LONGO`, `DATA`, `HORA`, `NUMERICO`, `TITULO`, `CID`).
- **Remoção do Legado Tkinter e QScintilla**: removidos os módulos obsoletos `src/gui/*_tab.py`, `src/gui/landing.py`, `src/gui/json_editor.py` e dependências conflitantes de `QScintilla`, reduzindo o tamanho e estabilizando o executável final.
- **Workflow CI/CD (`.github/workflows/build.yml`)**: atualizado para instalar `requirements.txt`, rodar a suíte `pytest` headless antes do build e empacotar via `build.spec`.

---

## [0.1.0] - 2026-11-05

### Adicionado
- Versão inicial com tela de boas-vindas e download da `SKILL.md`.
- Editor JSON com validação estrutural, formatação e conversão UPPERCASE.
- Visualização de Perguntas & Respostas, geração de SQL INSERT (`DO $$`) e SELECT Jasper Reports.
