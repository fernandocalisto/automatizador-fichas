---
name: extrator-ficha-clinica-salutem
description: Extrai, classifica e estrutura fichas e formularios clinicos (PDFs, imagens ou textos) para o banco de dados PostgreSQL do sistema hospitalar Salutem. Use quando o usuario enviar um documento de ficha clinica, prontuario ou relatorio medico e pedir para mapear perguntas e respostas, validar tipos de campos, gerar o JSON estruturado da ficha ou criar queries SQL de insercao para template_ficha_clinica, pergunta_template_ficha_clinica e resposta_template_ficha_clinica.
---
# Extrator de Ficha Clinica Salutem

Converte documentos de fichas clinicas (PDFs, imagens ou textos) em estruturas validadas (JSON e SQL PostgreSQL) compativeis com o motor de formularios dinamicos do sistema hospitalar Salutem.

## Quando Usar

  * O usuario envia um PDF, imagem ou texto de uma ficha clinica, prontuario, anamnese ou evolucao medica para cadastrar no banco de dados.
  * O usuario pede para classificar perguntas e respostas de um relatorio nas tabelas `template_ficha_clinica`, `pergunta_template_ficha_clinica` e `resposta_template_ficha_clinica`.
  * O usuario solicita a geracao do arquivo JSON intermediario ou das queries SQL (`INSERT`, `unnest`, `generate_series` ou bloco `DO $$`) para inserir templates de fichas clinicas no PostgreSQL.

## Contexto Completo da Arquitetura de Banco de Dados (PostgreSQL)

O modulo de fichas clinicas do sistema Salutem opera no schema `public` com tres tabelas relacionais hierarquicas (1:N:N). Todas as chaves primarias (`id`) utilizam `nextval` automaticos via sequences do PostgreSQL e nunca devem ser preenchidas manualmente nos comandos `INSERT`.

    public.template_ficha_clinica (1)
      └── public.pergunta_template_ficha_clinica (N)
            └── public.resposta_template_ficha_clinica (N)

### 1. Tabela `public.template_ficha_clinica` (19 colunas)

Armazena o cabecalho, configuracoes de impressao, assinatura e regras globais do documento.

  * `id` (`bigint`, `NOT NULL`, `nextval('template_ficha_clinica_id_seq'::regclass)`): Chave primaria gerada pelo banco. Omitir no `INSERT`.
  * `nome` (`character varying`, `NULL`): Titulo oficial da ficha clinica exibido no sistema.
  * `ativo` (`boolean`, `NULL`): Define se a ficha esta ativa para uso. Padrao: `true`.
  * `descricao` (`character varying`, `NULL`): Descricao sucinta da finalidade da ficha.
  * `fatura_cid` (`boolean`, `NULL`): Indica se fatura diagnostico CID. Padrao: `false`.
  * `importa_historico` (`boolean`, `NULL`): Importa dados de atendimentos anteriores. Padrao: `false`.
  * `exporta_historico` (`boolean`, `NULL`): Exporta dados para atendimentos futuros. Padrao: `false`.
  * `sae` (`boolean`, `NULL`): Sistematizacao da Assistencia de Enfermagem. Padrao: `false`.
  * `receituario` (`boolean`, `NULL`): Comportamento de receituario medico. Padrao: `false`.
  * `layout` (`character varying`, `NULL`): Define o motor visual. Valor obrigatorio: `'ficha-clinica'` (sempre tudo em minusculo).
  * `quantidade_pagina` (`integer`, `NULL`): Quantidade de paginas do template. REGRA OBRIGATÓRIA: Deve ser SEMPRE 1 no JSON, independentemente de quantas páginas físicas o PDF ou documento possua.
  * `codigo_ficha` (`character varying`, `NULL`): Codigo identificador interno gerado automaticamente pelo banco de dados. REGRA OBRIGATÓRIA: Não precisa ser inserido no JSON (deve ser omitido).
  * `importa_historico_ficha_clinica` (`boolean`, `NOT NULL`): Unica coluna booleana com restricao `NOT NULL` na tabela. Deve sempre receber `false` (ou `true` se exigido), nunca `NULL`.
  * `ficha_alta` (`boolean`, `NULL`): Sinaliza documento de alta hospitalar. Padrao: `false`.
  * `orientacao` (`character varying`, `NULL`): Orientacao da pagina. Valores aceitos: `'RETRATO'` (padrao na maioria absoluta dos casos) ou `'PAISAGEM'` (sempre em maiusculas).
  * `solicita_assinatura_ao_salvar` (`boolean`, `NULL`): Exige assinatura digital ao salvar. Padrao: `false`.
  * `posicao_assinatura` (`character varying`, `NULL`): Local da assinatura no PDF. Valores aceitos: `'RODAPE'` (padrao na maioria dos casos) ou `'LATERAL'` (sempre em maiusculas).
  * `integracao_mevo` (`boolean`, `NULL`): Ativa prescricao digital Mevo. Padrao: `false`.
  * `atendimento_oci` (`boolean`, `NULL`): Ativa fluxo de atendimento OCI. Padrao: `false`.

### 2. Tabela `public.pergunta_template_ficha_clinica` (5 colunas)

Representa tanto os divisores visuais de secao quanto os enunciados das perguntas que agrupam respostas.

  * `id` (`bigint`, `NOT NULL`, `nextval('pergunta_template_ficha_clinica_id_seq'::regclass)`): Chave primaria gerada pelo banco. Omitir no `INSERT`.
  * `nome` (`character varying`, `NULL`): Enunciado da pergunta ou texto do cabecalho de secao.
  * `template_ficha_clinica_id` (`bigint`, `NULL`): Chave estrangeira apontando para `template_ficha_clinica.id`.
  * `titulo` (`boolean`, `NULL`):
      * Quando `true`: Atua estritamente como cabecalho visual divisor de secao, imitando as divisoes do PDF original (ex: `"IDENTIFICACAO DO PACIENTE"`, `"EXAME FISICO"`). Registros com `titulo = true` nao devem ter respostas vinculadas (`respostas: []`).
      * Quando `false`: Representa uma pergunta real ou bloco de campos e deve possuir pelo menos uma resposta vinculada na tabela filha.
  * `ordenacao` (`integer`, `NULL`): Inteiro sequencial (1, 2, 3...) que determina a ordem vertical de exibicao na ficha.

### 3. Tabela `public.resposta_template_ficha_clinica` (20 colunas)

Representa cada campo de entrada, linha de texto ou alternativa de selecao pertencente a uma pergunta.

  * `id` (`bigint`, `NOT NULL`, `nextval('resposta_template_ficha_clinica_id_seq'::regclass)`): Chave primaria gerada pelo banco. Omitir no `INSERT`.
  * `label` (`character varying`, `NULL`): Rotulo visivel do campo ou texto da opcao selecionavel. Pode ser string vazia (`''`) quando a pergunta exigir apenas linhas abertas para digitacao livre sem subtitulo.
  * `tipo_campo` (`character varying`, `NULL`): Define o componente renderizado na tela. Nunca deve ser `NULL` (valores nulos no banco sao erros de cadastro).
  * `valor_numerico` (`double precision`, `NULL`): Valor numerico padrao pre-preenchido. Padrao: `NULL`.
  * `valor_texto` (`character varying`, `NULL`): Texto padrao pre-preenchido. Padrao: `NULL`.
  * `valor_booleano` (`boolean`, `NULL`): Estado booleano inicial. Padrao: `NULL`.
  * `valor_data` (`date`, `NULL`): Data fixa inicial. Padrao: `NULL`.
  * `valor_hora` (`time without time zone`, `NULL`): Horario fixo inicial. Padrao: `NULL`.
  * `pergunta_template_ficha_clinica_id` (`bigint`, `NULL`): Chave estrangeira apontando para `pergunta_template_ficha_clinica.id`.
  * `cid_codigo` (`character varying`, `NULL`): Codigo CID especifico amarrado ao item. Padrao: `NULL`.
  * `campo_obrigatorio` (`boolean`, `NULL`): Exige preenchimento antes de salvar a ficha. Padrao: `false`.
  * `importa_historico` (`boolean`, `NULL`): Recupera resposta de fichas anteriores do paciente. Padrao: `false`.
  * `ordenacao` (`integer`, `NULL`): Inteiro sequencial (1, 2, 3...) que ordena os itens dentro da mesma pergunta.
  * `observacao` (`boolean`, `NULL`): Quando `true`, abre um campo de texto livre adicional na interface do sistema hospitalar para o profissional escrever contexto complementar sobre a resposta.
  * `procedimento_codigo` (`character varying`, `NULL`): Codigo de procedimento pre-vinculado. Padrao: `NULL`.
  * `minimo` (`integer`, `NULL`): Valor ou limite minimo do campo. Padrao: `0` (alterar somente se solicitado).
  * `exame_id` (`bigint`, `NULL`): Referencia a um exame especifico do catalogo. Padrao: `NULL`.
  * `referencia` (`integer`, `NULL`): Codigo de referencia auxiliar. Padrao: `NULL`.
  * `valor_data_atual` (`boolean`, `NULL`): Preenche o campo `DATA` automaticamente com a data do atendimento. Padrao: `NULL` ou `false`.
  * `valor_hora_atual` (`boolean`, `NULL`): Preenche o campo `HORA` automaticamente com a hora do atendimento. Padrao: `NULL` ou `false`.

## Dicionario Estrito de `tipo_campo` e Regras de Agrupamento Visual

A coluna `tipo_campo` aceita exclusivamente os 11 valores em maiusculas abaixo:
1. `COMBOBOX`
2. `BOOLEANO`
3. `BOOLEANO_RADIO`
4. `TEXTO`
5. `NUMERICO`
6. `DATA`
7. `HORA`
8. `CID`
9. `PROCEDIMENTO`
10. `PROCEDIMENTO_CID`
11. `EXAME`

## Passo a Passo do Fluxo de Trabalho (Protocolo Obrigatorio)

### Etapa 1: Extracao Visual e Tabela de Revisao
1. Ler o documento completo.
2. Separar divisores (`titulo: true`) de perguntas reais (`titulo: false`).
3. Apresentar tabela Markdown com Ordem, Nome, Labels, `tipo_campo` e Flags.
4. Formular perguntas de confirmacao.

### Etapa 2: Consolidacao dos Ajustes
Aplicar decisoes informadas pelo usuario.

### Etapa 3: Geracao do JSON Estruturado (ou Query SQL)
Gerar o JSON final conforme o schema abaixo.

```json
{
  "template": {
    "nome": "NOME DA FICHA CLINICA",
    "descricao": "Descricao sucinta da ficha",
    "ativo": true,
    "layout": "ficha-clinica",
    "orientacao": "RETRATO",
    "posicao_assinatura": "RODAPE",
    "quantidade_pagina": 1,
    "importa_historico_ficha_clinica": false,
    "importa_historico": false,
    "exporta_historico": false,
    "fatura_cid": false,
    "sae": false,
    "receituario": false,
    "ficha_alta": false,
    "solicita_assinatura_ao_salvar": false,
    "integracao_mevo": false,
    "atendimento_oci": false
  },
  "perguntas": [
    ...
  ]
}
```

## Padroes Oficiais de Geracao SQL (PostgreSQL)

### Padrao 1: Multiplas opcoes do mesmo tipo (`unnest` com `WITH ORDINALITY`)
### Padrao 2: Multiplas linhas de texto em branco (`generate_series`)
### Padrao 3: Respostas heterogeneas ou com flags especificas (`VALUES`)

## Armadilhas Comuns e Regras Criticas (Gotchas)
  * `quantidade_pagina`: SEMPRE 1 no JSON.
  * `codigo_ficha`: gerado automaticamente pelo banco de dados, omitir do JSON.
  * `layout`: `'ficha-clinica'` (minusculo).
  * `orientacao`: `'RETRATO'` ou `'PAISAGEM'` (maiusculo).
  * `posicao_assinatura`: `'RODAPE'` ou `'LATERAL'` (maiusculo).
  * `importa_historico_ficha_clinica`: NOT NULL, sempre `false` (ou `true`), nunca NULL.
  * Proibicao de `tipo_campo: null`.
