# Spec: Tela Inicial (Carregamento de JSON) + Editor com Abas

## Fluxo Geral
1. **Tela Inicial (Landing)**: Interface simples onde o usuário:
   - Baixa o arquivo da SKILL (botão + tooltip explicativo)
   - Lê breve explicação de como usar a skill
   - Carrega o JSON (arquivo .json) OU cola da área de transferência
2. **Após JSON válido carregado**: A interface muda para uma janela com abas:
   - **Aba 1 – Editar JSON**: Visualização/edição do JSON completo (com conversão UPPERCASE nos campos de texto)
   - **Aba 2 – Perguntas & Respostas**: Visualização em árvore/accordion das perguntas detectadas; ao expandir uma pergunta, mostra todas as suas respostas com todas as informações; campos editáveis (textos → UPPERCASE, booleanos → checkbox) que atualizam o JSON interno

## Detalhamento da Tela Inicial (Landing)

### Elementos UI
- **Título**: "Automatizador de Fichas – Carregar JSON"
- **Botão "Baixar Skill"**: Faz download do arquivo `SKILL.md` (ou `.json` se houver versão) que está na pasta de recursos do projeto.
  - **Tooltip (hover)**: Texto explicativo:
    > "Esta skill ensina a IA a extrair fichas clínicas de PDFs/imagens/texto e gerar o JSON estruturado esperado pelo sistema.
    > 
    > **Como usar:**
    > 1. Baixe este arquivo.
    > 2. Anexe/o envie para a IA de sua preferência (Claude, ChatGPT, modelos gratuitos via OpenRouter, etc.).
    > 3. Envie o PDF da ficha clínica para a IA.
    > 4. A IA, seguindo a skill, vai conversar com você para validar campos, tipos, labels, etc.
    > 5. Quando vocês chegarem a um acordo, a IA gerará o JSON final.
    > 6. Copie/cole ou carregue esse JSON aqui."
- **Área de explicação curta** (label/texto fixo abaixo do botão): Resumo dos passos acima (2-3 linhas).
- **Botão "Carregar JSON de Arquivo"**: Abre diálogo para selecionar `.json`.
- **Botão "Colar JSON da Área de Transferência"**: Lê o clipboard, valida JSON, se OK avança.
- **Status/Feedback**: Label na parte inferior mostrando "Aguardando JSON…" ou erro de validação.

### Comportamento
- Ao clicar em "Carregar JSON de Arquivo" ou "Colar JSON da Área de Transferência":
  - Valida JSON (bem-formado, estrutura esperada: `template` + `perguntas`).
  - Se inválido: mostra `messagebox.showerror` com detalhe (linha/coluna).
  - Se válido: **oculta a tela inicial** e **abre a janela principal com abas** (ou troca o frame para o notebook de abas), passando o JSON parseado para as abas.

## Detalhamento da Janela Principal (Após JSON Carregado)

### Estrutura
- `tkinter.ttk.Notebook` com duas abas:
  1. **Editar JSON**
  2. **Perguntas & Respostas**

### Aba 1 – Editar JSON
- Mesma funcionalidade do `JsonEditorApp` anterior:
  - `ScrolledText` editável com fonte monoespacada, undo.
  - Botões: "Validar & Formatar", "Salvar JSON como…", "Voltar à Tela Inicial".
  - Ao validar/salvar: aplica `uppercase_target_fields` nos campos `label`, `labels`, `name`, `description` (recursivo).
  - JSON atualizado internamente e refletido na Aba 2 em tempo real (ou ao trocar de aba).

### Aba 2 – Perguntas & Respostas
- **Painel esquerdo (ou superior)**: Lista de perguntas (título = `nome` da pergunta). Cada item é expansível (accordion) – pode usar `ttk.Treeview` com `open/close` ou frames colapsáveis.
- **Ao expandir uma pergunta**: Mostra tabela/grid com todas as respostas dessa pergunta.
  - Colunas: `label` (editável, UPPERCASE), `tipo_campo` (somente leitura), `campo_obrigatorio` (checkbox), `observacao` (checkbox), `importa_historico` (checkbox), `valor_data_atual` (checkbox), `valor_hora_atual` (checkbox), `ordenacao` (somente leitura ou editável se necessário), demais campos relevantes do JSON.
- **Edição visual**:
  - Textos (`label`): `Entry` ou `Text` curto; ao perder foco → converte para UPPERCASE e atualiza JSON.
  - Booleanos: `Checkbutton` vinculado ao valor no JSON; mudança imediata atualiza JSON.
- **Botão "Aplicar Alterações"** (opcional, se quiser confirmação explícita) ou atualização automática.
- **Botão "Voltar à Tela Inicial"**: Descarta alterações não salvas e retorna à landing.

## Requisitos Técnicos
- **Único ponto de verdade do JSON**: Um dicionário Python (`dict`) mantido na classe principal (`MainApp`) e compartilhado entre as abas.
- **Função `uppercase_target_fields`** reutilizada (mesma do spec anterior).
- **Validação de estrutura mínima**: JSON deve conter chaves `template` (dict) e `perguntas` (list). Se não, avisa que não é um JSON de ficha clínica válido.
- **Recursos embutidos**: O arquivo `SKILL.md` deve ser incluído no build (PyInstaller `--add-data`) e lido via `resource_path` para o botão de download.
- **Arquitetura**: 
  - `src/main.py` – ponto de entrada, cria `MainApp` (herda de `tk.Tk` ou controla frames).
  - `src/gui/landing.py` – tela inicial (frame).
  - `src/gui/json_editor_tab.py` – aba de edição JSON.
  - `src/gui/perguntas_tab.py` – aba de perguntas & respostas.
  - `src/utils/resource_path.py` – helper para assets no exe.
  - `src/utils/json_utils.py` – `uppercase_target_fields`, validação de estrutura.

## Fora do Escopo (Para Futuras Specs)
- Geração de SQL INSERT (perguntas).
- Geração de SELECT Jasper Reports.
- Externalização de regex.
- Updater GitHub Releases.
- Code signing.

## Critérios de Aceite
1. Ao abrir o exe: vê a tela inicial com botão baixar skill, explicação, botões carregar/colar JSON.
2. Tooltip do botão "Baixar Skill" mostra o texto explicativo completo.
3. Carregar JSON inválido → erro claro.
4. Carregar JSON válido → transição suave para janela com duas abas.
5. Aba Editar JSON: edita, valida, formata, aplica UPPERCASE nos campos alvo, salva arquivo.
6. Aba Perguntas & Respostas: lista perguntas expansíveis, mostra respostas com campos editáveis (textos → UPPERCASE, booleanos → checkbox), alterações refletem no JSON compartilhado.
7. Botão "Voltar à Tela Inicial" funciona nas duas abas.
