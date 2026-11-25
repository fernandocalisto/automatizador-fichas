---
name: extrator-ficha-clinica-salutem
description: Extrai, classifica e estrutura fichas e formularios clinicos (PDFs, imagens ou textos) para o banco de dados PostgreSQL do sistema hospitalar Salutem. Use quando o usuario enviar um documento de ficha clinica, prontuario ou relatorio medico e pedir para mapear perguntas e respostas, validar tipos de campos, gerar o JSON estruturado da ficha ou criar queries SQL de insercao para template_ficha_clinica, pergunta_template_ficha_clinica e resposta_template_ficha_clinica.
---
# Extrator de Ficha Clinica Salutem

Converte documentos de fichas clinicas (PDFs, imagens ou textos) em estruturas validadas (JSON e SQL PostgreSQL) compativeis com o motor de formularios dinamicos do sistema hospitalar Salutem.

## Quando Usar

- O usuario envia um PDF, imagem ou texto de uma ficha clinica, prontuario, anamnese ou evolucao medica para cadastrar no banco de dados.
- O usuario pede para classificar perguntas e respostas de um relatorio nas tabelas `template_ficha_clinica`, `pergunta_template_ficha_clinica` e `resposta_template_ficha_clinica`.
- O usuario solicita a geracao do arquivo JSON intermediario ou das queries SQL (`INSERT`, `unnest`, `generate_series` ou bloco `DO $$`) para inserir templates de fichas clinicas no PostgreSQL.

## Regras de Negocio e Aprendizados Criticos

1. **Agrupamento de `BOOLEANO_RADIO`:**
   - Botoes do tipo `BOOLEANO_RADIO` pertencentes a mesma `pergunta_template_ficha_clinica` sao agrupados pelo front-end do Salutem como um grupo de radio mutuamente exclusivo unico.
   - **NUNCA** coloque opcoes de radio independentes na mesma pergunta (por exemplo: "Esta gravida? Sim/Nao" e "Algum aborto? Sim/Nao"). Se ficarem sob a mesma pergunta, o sistema permitira selecionar apenas uma opcao entre todas as quatro.
   - Sempre que houver dois ou mais pares/grupos de radio independentes em uma mesma linha do formulario fisico, divida-os em perguntas (`pergunta_template_ficha_clinica`) separadas.

2. **Opcao "Outros" ou Itens com Complemento Textual:**
   - Quando um item (como "Outros:", "Medicamentos:", ou uma comorbidade especifica) precisa ser assinalado e acompanhado de texto explicativo, defina:
     - `tipo_campo`: `"BOOLEANO"`
     - `observacao`: `true`
   - Isso permite que o usuario marque a caixa de selecao na interface do Salutem e abra automaticamente o campo de texto de observacao para detalhamento, mantendo a coerencia sem a necessidade de um campo `TEXTO` desvinculado solto.

3. **Padrao de Entrega e Autorizacao de JSON:**
   - **NUNCA** gerar ou exibir o JSON estruturado nem criar arquivo JSON para download sem a solicitacao ou autorizacao explicita do usuario.
   - Na etapa inicial ou avaliacao da ficha, apresente apenas a analise clinica textual, o mapeamento detalhado das secoes, perguntas, tipos de campos sugeridos e consideracoes tecnicas.
   - Somente gere e apresente o JSON (ou arquivo `.json` para download) quando o usuario autorizar ou solicitar explicitamente.

4. **Estrutura do JSON - Chave Principal `template`:**
   - No JSON estruturado do Salutem, a chave principal do objeto de cabecalho da ficha DEVE ser obrigatoriamente `"template"` (e **NUNCA** `"template_ficha_clinica"`).
   - A estrutura raiz deve seguir sempre este padrao:
     ```json
     {
       "template": {
         "nome": "...",
         "descricao": "...",
         "layout": "ficha-clinica",
         ...
       },
       "perguntas": [ ... ]
     }
     ```

5. **Tratamento de Campos de CID e Exames:**
   - Quando especificado CID nativo: utilizar `tipo_campo: "CID"`.
   - Quando exames complementares forem apenas anotacao livre: utilizar `tipo_campo: "TEXTO"`. Se vinculados ao catalogo do sistema: `tipo_campo: "EXAME"`.

## Contexto Completo da Arquitetura de Banco de Dados (PostgreSQL)

O modulo de fichas clinicas do sistema Salutem opera no schema `public` com tres tabelas relacionais hierarquicas (1:N:N). Todas as chaves primarias (`id`) utilizam `nextval` automaticos via sequences do PostgreSQL e nunca devem ser preenchidas manualmente nos comandos `INSERT`.

    public.template_ficha_clinica (1)
      └── public.pergunta_template_ficha_clinica (N)
            └── public.resposta_template_ficha_clinica (N)

### 1. Tabela `public.template_ficha_clinica` (19 colunas)

- `id` (`bigint`, `NOT NULL`): Sequence automatica. Omitir no INSERT.
- `nome` (`character varying`, `NULL`): Titulo oficial da ficha clinica.
- `ativo` (`boolean`, `NULL`): Padrao `true`.
- `descricao` (`character varying`, `NULL`): Descricao sucinta da finalidade.
- `fatura_cid` (`boolean`, `NULL`): Padrao `false`.
- `importa_historico` (`boolean`, `NULL`): Padrao `false`.
- `exporta_historico` (`boolean`, `NULL`): Padrao `false`.
- `sae` (`boolean`, `NULL`): Padrao `false`.
- `receituario` (`boolean`, `NULL`): Padrao `false`.
- `layout` (`character varying`, `NULL`): Valor obrigatorio `'ficha-clinica'` (minusculo).
- `quantidade_pagina` (`integer`, `NULL`): SEMPRE `1` no JSON.
- `codigo_ficha` (`character varying`, `NULL`): Omitir do JSON (gerado pelo banco).
- `importa_historico_ficha_clinica` (`boolean`, `NOT NULL`): Sempre `false` (ou `true`), nunca NULL.
- `ficha_alta` (`boolean`, `NULL`): Padrao `false`.
- `orientacao` (`character varying`, `NULL`): `'RETRATO'` ou `'PAISAGEM'`.
- `solicita_assinatura_ao_salvar` (`boolean`, `NULL`): Padrao `false`.
- `posicao_assinatura` (`character varying`, `NULL`): `'RODAPE'` ou `'LATERAL'`.
- `integracao_mevo` (`boolean`, `NULL`): Padrao `false`.
- `atendimento_oci` (`boolean`, `NULL`): Padrao `false`.

### 2. Tabela `public.pergunta_template_ficha_clinica` (5 colunas)

- `id` (`bigint`, `NOT NULL`): Sequence automatica.
- `nome` (`character varying`, `NULL`): Enunciado da pergunta ou titulo da secao.
- `template_ficha_clinica_id` (`bigint`, `NULL`): FK.
- `titulo` (`boolean`, `NULL`):
  - `true`: Divisor de secao (respostas vazias `[]`).
  - `false`: Pergunta real com respostas vinculadas.
- `ordenacao` (`integer`, `NULL`): Inteiro sequencial (1, 2, 3...).

### 3. Tabela `public.resposta_template_ficha_clinica` (20 colunas)

- `id` (`bigint`, `NOT NULL`): Sequence automatica.
- `label` (`character varying`, `NULL`): Rotulo visivel do campo.
- `tipo_campo` (`character varying`, `NULL`): Exclusivamente um dos 11 tipos validos.
- `valor_numerico` (`double precision`, `NULL`): Padrao `null`.
- `valor_texto` (`character varying`, `NULL`): Padrao `null`.
- `valor_booleano` (`boolean`, `NULL`): Padrao `null`.
- `valor_data` (`date`, `NULL`): Padrao `null`.
- `valor_hora` (`time without time zone`, `NULL`): Padrao `null`.
- `pergunta_template_ficha_clinica_id` (`bigint`, `NULL`): FK.
- `cid_codigo` (`character varying`, `NULL`): Padrao `null`.
- `campo_obrigatorio` (`boolean`, `NULL`): Padrao `false`.
- `importa_historico` (`boolean`, `NULL`): Padrao `false`.
- `ordenacao` (`integer`, `NULL`): Sequencial (1, 2, 3...).
- `observacao` (`boolean`, `NULL`): `true` quando permite campo de texto complementar.
- `procedimento_codigo` (`character varying`, `NULL`): Padrao `null`.
- `minimo` (`integer`, `NULL`): Padrao `0`.
- `exame_id` (`bigint`, `NULL`): Padrao `null`.
- `referencia` (`integer`, `NULL`): Padrao `null`.
- `valor_data_atual` (`boolean`, `NULL`): Padrao `false` ou `null`.
- `valor_hora_atual` (`boolean`, `NULL`): Padrao `false` ou `null`.

## Dicionario Estrito de `tipo_campo`

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
