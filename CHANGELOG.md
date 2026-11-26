# Changelog

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

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
  - `scripts/dev.ps1`: inicialização paralela de `uvicorn --reload` e Vite dev server com URLs centralizadas e limpeza de árvore de processos ao sair.
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
