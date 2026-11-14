# Changelog

Todas as mudanças notáveis neste projeto serão documentadas neste arquivo.

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
