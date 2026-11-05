#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador de Script SQL PostgreSQL INSERT para Fichas Clínicas Salutem (src/core/sql_insert.py).

Implementa `generate_insert_sql()` conforme `spec_sql_perguntas.md` e `gerar_sql-v2.py`:
- Bloco anônimo `DO $$ DECLARE v_template_id bigint; v_pergunta_id bigint; BEGIN ... END $$;`
- Higienização de OCR (`HOMOGLIFOS_OCR`, `CORRECOES_OCR_EXATAS`, `PADROES_OCR_REGEX`)
- Conversão obrigatória para UPPERCASE em `template.nome`, `pergunta.nome` e `resposta.label`
- `quantidade_pagina = 1` fixo, `layout = 'ficha-clinica'` (minúsculo), `orientacao` e `posicao_assinatura` em UPPERCASE
- Validação estrita de `tipo_campo` contra os 11 valores válidos do Salutem
- Três padrões de inserção de respostas:
  1. `generate_series` (1 resposta TEXTO com label vazio e `quantidade_linhas >= 1`, sem colunas extras)
  2. `unnest(ARRAY[...]) WITH ORDINALITY` (lista homogênea de respostas sem colunas extras)
  3. `VALUES` (heterogêneas ou com colunas polimórficas/extras preenchidas)
"""

from __future__ import annotations

import re
from typing import Any

TIPOS_VALIDOS = {
    "BOOLEANO",
    "BOOLEANO_RADIO",
    "CID",
    "COMBOBOX",
    "DATA",
    "EXAME",
    "HORA",
    "NUMERICO",
    "PROCEDIMENTO",
    "PROCEDIMENTO_CID",
    "TEXTO",
}

# Mapa de caracteres homóglifos (Grego / Cirílico -> Latino) comuns em OCR de PDFs
HOMOGLIFOS_OCR = str.maketrans({
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I",
    "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T",
    "Υ": "Y", "Χ": "X", "α": "a", "ο": "o", "ν": "v",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x",
    "\u00a0": " ",  # Non-breaking space -> espaço normal
    "\u200b": "",   # Zero-width space -> remover
})

# Dicionário de correções exatas de OCR que preserva 100% do sentido clínico
CORRECOES_OCR_EXATAS = {
    "Equipo de Bonba de Infusão": "Equipo de Bomba de Infusão",
    "Extensão de faço": "Extensão de faco",
    "Hidrocortizona 100mg - 500mg": "Hidrocortisona 100mg - 500mg",
    "Ondasentrona": "Ondansetrona",
    "Alcool 70%": "Álcool 70%",
    "Cupula": "Cúpula",
    "Acido acético 2% e 5%": "Ácido acético 2% e 5%",
    "Xylocaina 1% gel": "Xylocaína 1% gel",
    "Xylocaina 2% S/V": "Xylocaína 2% S/V",
    "Marcaina Pesada": "Marcaína Pesada",
    "Cânula Endotraquial No": "Cânula Endotraqueal No",
    "Fentanil -2 ml": "Fentanil 2 ml",
}

# Versão case-insensitive das correções exatas para funcionar mesmo se o JSON já estiver em UPPERCASE
_CORRECOES_OCR_EXATAS_UPPER = {
    k.upper(): v for k, v in CORRECOES_OCR_EXATAS.items()
}

# Substituições seguras por palavras/termos isolados (case-insensitive onde aplicável)
PADROES_OCR_REGEX = [
    (re.compile(r"\bBonba\b", re.IGNORECASE), "Bomba"),
    (re.compile(r"\bHidrocortizona\b", re.IGNORECASE), "Hidrocortisona"),
    (re.compile(r"\bOndasentrona\b", re.IGNORECASE), "Ondansetrona"),
    (re.compile(r"\bEndotraquial\b", re.IGNORECASE), "Endotraqueal"),
    (re.compile(r"\bExtensão de faço\b", re.IGNORECASE), "Extensão de faco"),
]

COLUNAS_EXTRAS = (
    "valor_numerico",
    "valor_texto",
    "valor_booleano",
    "valor_data",
    "valor_hora",
    "cid_codigo",
    "procedimento_codigo",
    "exame_id",
    "referencia",
    "valor_data_atual",
    "valor_hora_atual",
)


def _obter_obrigatorio(resposta: dict[str, Any]) -> Any:
    """
    Obtém o valor booleano de obrigatoriedade da resposta, suportando tanto
    `campo_obrigatorio` (padrão da tabela/spec) quanto `obrigatorio` (templates JSON legados).
    """
    if "campo_obrigatorio" in resposta and resposta["campo_obrigatorio"] is not None:
        return resposta["campo_obrigatorio"]
    return resposta.get("obrigatorio")


def limpar_ocr_texto(
    texto: str | None,
    forcar_maiusculo: bool = False,
    aplicar_ocr: bool = True,
) -> str:
    """
    Higieniza artefatos de OCR (homóglifos gregos/cirílicos, espaços invisíveis e
    erros ortográficos de digitalização) e aplica conversão opcional para MAIÚSCULAS.
    """
    if texto is None:
        return ""

    limpo = str(texto)

    if aplicar_ocr:
        # 1. Converte homóglifos Unicode (ex: letra grega Nu 'Ν' U+039D -> 'N' latino)
        limpo = limpo.translate(HOMOGLIFOS_OCR)

        # 2. Normaliza espaços múltiplos e remove espaços nas extremidades
        limpo = re.sub(r"[ \t]+", " ", limpo).strip()

        # 3. Aplica dicionário de correções exatas conhecidas (preservando case ou via lookup uppercase)
        if limpo in CORRECOES_OCR_EXATAS:
            limpo = CORRECOES_OCR_EXATAS[limpo]
        elif limpo.upper() in _CORRECOES_OCR_EXATAS_UPPER:
            correcao = _CORRECOES_OCR_EXATAS_UPPER[limpo.upper()]
            limpo = correcao.upper() if limpo.isupper() else correcao

        # 4. Aplica padrões seguros de regex para termos médicos com erro de OCR
        for padrao, substituto in PADROES_OCR_REGEX:
            limpo = padrao.sub(substituto, limpo)

    # 5. Converte para MAIÚSCULAS quando exigido (nomes e labels)
    if forcar_maiusculo:
        limpo = limpo.upper()

    return limpo


def sql_str(
    valor: Any,
    aplicar_ocr: bool = False,
    forcar_maiusculo: bool = False,
) -> str:
    """Formata string ou None para literal SQL com escape seguro de aspas simples."""
    if valor is None:
        return "NULL"
    if aplicar_ocr or forcar_maiusculo:
        texto = limpar_ocr_texto(
            str(valor),
            forcar_maiusculo=forcar_maiusculo,
            aplicar_ocr=aplicar_ocr,
        )
    else:
        texto = str(valor)
    texto_escapado = texto.replace("'", "''")
    return f"'{texto_escapado}'"


def sql_bool(valor: Any, padrao: bool = False) -> str:
    """Formata booleano para literal SQL ('true' ou 'false')."""
    if valor is None:
        return "true" if padrao else "false"
    return "true" if bool(valor) else "false"


def sql_num(valor: Any, padrao: Any = None) -> str:
    """Formata número ou None para literal SQL."""
    if valor is None:
        return "NULL" if padrao is None else str(padrao)
    return str(valor)


def usa_colunas_extras(respostas: list[dict[str, Any]]) -> bool:
    """Verifica se alguma resposta da pergunta preenche colunas polimórficas/extras."""
    for r in respostas:
        if any(r.get(k) is not None for k in COLUNAS_EXTRAS):
            return True
    return False


def eh_lista_homogenea(
    respostas: list[dict[str, Any]],
    aplicar_ocr: bool = True,
) -> bool:
    """
    Verifica se todas as respostas compartilham o mesmo tipo_campo e as mesmas
    flags (obrigatorio/campo_obrigatorio, importa_historico, observacao, minimo),
    permitindo usar o padrão unnest(ARRAY[...]) WITH ORDINALITY.
    """
    if not respostas or usa_colunas_extras(respostas):
        return False

    ref = respostas[0]
    assinatura_ref = (
        str(ref.get("tipo_campo") or "").upper(),
        bool(_obter_obrigatorio(ref) or False),
        bool(ref.get("importa_historico", False)),
        bool(ref.get("observacao", False)),
        int(ref.get("minimo", 0) if ref.get("minimo") is not None else 0),
    )

    for r in respostas:
        qtd_linhas = int(r.get("quantidade_linhas", 1) if r.get("quantidade_linhas") is not None else 1)
        if qtd_linhas > 1:
            return False
        assinatura_atual = (
            str(r.get("tipo_campo") or "").upper(),
            bool(_obter_obrigatorio(r) or False),
            bool(r.get("importa_historico", False)),
            bool(r.get("observacao", False)),
            int(r.get("minimo", 0) if r.get("minimo") is not None else 0),
        )
        if assinatura_atual != assinatura_ref:
            return False

    return True


def eh_serie_texto_vazio(
    respostas: list[dict[str, Any]],
    aplicar_ocr: bool = True,
) -> bool:
    """
    Verifica se a pergunta consiste em 1 resposta do tipo TEXTO com label vazio
    e quantidade_linhas >= 1 (sem colunas extras) para gerar generate_series(1, N).
    """
    if len(respostas) != 1 or usa_colunas_extras(respostas):
        return False
    r = respostas[0]
    qtd_linhas = int(r.get("quantidade_linhas", 1) if r.get("quantidade_linhas") is not None else 1)
    return (
        str(r.get("tipo_campo") or "").upper() == "TEXTO"
        and limpar_ocr_texto(r.get("label", ""), aplicar_ocr=aplicar_ocr) == ""
        and qtd_linhas >= 1
    )


def generate_insert_sql(
    json_data: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> str:
    """
    Recebe o dicionário JSON de ficha clínica e retorna o script SQL PostgreSQL completo
    (bloco `DO $$ ... END $$;`), sem modificar `json_data`.

    Parâmetros:
        json_data: Dicionário contendo 'template' (dict) e 'perguntas' (list).
        options: Dicionário opcional de flags de configuração futura:
            - clean_ocr (bool, default True)
            - force_uppercase (bool, default True)
            - use_generate_series (bool, default True)
            - use_unnest (bool, default True)
            - include_comments (bool, default True)

    Levanta:
        ValueError: Se a estrutura do JSON for inválida ou se houver `tipo_campo` fora dos 11 válidos.
    """
    if not isinstance(json_data, dict) or not json_data:
        raise ValueError("JSON inválido ou vazio: esperado um objeto contendo 'template' e 'perguntas'.")

    if "template" not in json_data or not isinstance(json_data.get("template"), dict):
        raise ValueError("Estrutura JSON inválida: a chave 'template' (objeto) é obrigatória.")

    if "perguntas" not in json_data or not isinstance(json_data.get("perguntas"), list):
        raise ValueError("Estrutura JSON inválida: a chave 'perguntas' (lista) é obrigatória.")

    opts = options or {}
    clean_ocr: bool = bool(opts.get("clean_ocr", True))
    force_upper: bool = bool(opts.get("force_uppercase", True))
    use_gen_series: bool = bool(opts.get("use_generate_series", True))
    use_unnest_opt: bool = bool(opts.get("use_unnest", True))
    include_comments: bool = bool(opts.get("include_comments", True))

    t = json_data.get("template", {})
    perguntas = json_data.get("perguntas", [])

    raw_template_nome = t.get("nome")
    if raw_template_nome is None or str(raw_template_nome).strip() == "":
        raw_template_nome = "NOVA FICHA CLÍNICA"

    nome_template_limpo = limpar_ocr_texto(
        str(raw_template_nome),
        forcar_maiusculo=force_upper,
        aplicar_ocr=clean_ocr,
    )
    nome = sql_str(
        raw_template_nome,
        aplicar_ocr=clean_ocr,
        forcar_maiusculo=force_upper,
    )
    descricao = sql_str(
        t.get("descricao"),
        aplicar_ocr=clean_ocr,
        forcar_maiusculo=False,
    )
    ativo = sql_bool(t.get("ativo"), True)
    layout = sql_str("ficha-clinica")  # Regra obrigatória: sempre 'ficha-clinica' (minúsculo)
    orientacao_raw = str(t.get("orientacao") or "RETRATO").strip().upper()
    orientacao = sql_str(orientacao_raw if orientacao_raw else "RETRATO")
    pos_assinatura_raw = str(t.get("posicao_assinatura") or "RODAPE").strip().upper()
    posicao_assinatura = sql_str(pos_assinatura_raw if pos_assinatura_raw else "RODAPE")
    qtd_pagina = "1"  # Regra obrigatória da skill: sempre 1

    imp_hist_ficha = sql_bool(t.get("importa_historico_ficha_clinica"), False)
    imp_hist = sql_bool(t.get("importa_historico"), False)
    exp_hist = sql_bool(t.get("exporta_historico"), False)
    fatura_cid = sql_bool(t.get("fatura_cid"), False)
    sae = sql_bool(t.get("sae"), False)
    receituario = sql_bool(t.get("receituario"), False)
    ficha_alta = sql_bool(t.get("ficha_alta"), False)
    assinar_salvar = sql_bool(t.get("solicita_assinatura_ao_salvar"), False)
    mevo = sql_bool(t.get("integracao_mevo"), False)
    oci = sql_bool(t.get("atendimento_oci"), False)

    linhas: list[str] = [
        "DO $$",
        "DECLARE",
        "    v_template_id bigint;",
        "    v_pergunta_id bigint;",
        "BEGIN",
        "",
    ]

    if include_comments:
        linhas.extend([
            "    -- =========================================================================",
            f"    -- 1. CRIAÇÃO DO TEMPLATE: {nome_template_limpo}",
            "    -- =========================================================================",
        ])

    linhas.extend([
        "    INSERT INTO public.template_ficha_clinica (",
        "        nome, descricao, ativo, layout, orientacao,",
        "        posicao_assinatura, quantidade_pagina, importa_historico_ficha_clinica,",
        "        importa_historico, exporta_historico, fatura_cid, sae, receituario,",
        "        ficha_alta, solicita_assinatura_ao_salvar, integracao_mevo, atendimento_oci",
        "    ) VALUES (",
        f"        {nome}, {descricao}, {ativo}, {layout}, {orientacao},",
        f"        {posicao_assinatura}, {qtd_pagina}, {imp_hist_ficha},",
        f"        {imp_hist}, {exp_hist}, {fatura_cid}, {sae}, {receituario},",
        f"        {ficha_alta}, {assinar_salvar}, {mevo}, {oci}",
        "    ) RETURNING id INTO v_template_id;",
        "",
    ])

    for idx_p, p in enumerate(perguntas, start=1):
        if not isinstance(p, dict):
            raise ValueError(f"Pergunta na posição {idx_p} inválida: esperado um objeto JSON.")

        p_nome_limpo = limpar_ocr_texto(
            p.get("nome", ""),
            forcar_maiusculo=force_upper,
            aplicar_ocr=clean_ocr,
        )
        p_nome = sql_str(p_nome_limpo)
        p_titulo = sql_bool(p.get("titulo"), False)
        respostas = p.get("respostas", [])
        if respostas is None:
            respostas = []
        if not isinstance(respostas, list):
            raise ValueError(
                f"Erro na pergunta '{p_nome_limpo}': 'respostas' deve ser uma lista."
            )

        if include_comments:
            linhas.extend([
                "    -- -------------------------------------------------------------------------",
                f"    -- Pergunta {idx_p}: {p_nome_limpo} (titulo={p_titulo})",
                "    -- -------------------------------------------------------------------------",
            ])

        linhas.extend([
            "    INSERT INTO public.pergunta_template_ficha_clinica (",
            "        template_ficha_clinica_id, nome, titulo, ordenacao",
            "    ) VALUES (",
            f"        v_template_id, {p_nome}, {p_titulo}, {idx_p}",
            "    ) RETURNING id INTO v_pergunta_id;",
            "",
        ])

        if not respostas:
            continue

        # Validação preventiva de tipos contra os 11 valores válidos
        for r in respostas:
            if not isinstance(r, dict):
                raise ValueError(f"Resposta inválida na pergunta '{p_nome_limpo}'.")
            raw_tc = r.get("tipo_campo")
            tc = "" if raw_tc is None else str(raw_tc).strip().upper()
            if tc not in TIPOS_VALIDOS:
                raise ValueError(
                    f"Erro na pergunta '{p_nome_limpo}': tipo_campo inválido '{tc}'. "
                    f"Valores aceitos: {sorted(TIPOS_VALIDOS)}"
                )

        # PADRÃO 1: Pergunta com N linhas de TEXTO com label vazio -> generate_series
        if use_gen_series and eh_serie_texto_vazio(respostas, aplicar_ocr=clean_ocr):
            r = respostas[0]
            qtd = int(r.get("quantidade_linhas", 1) if r.get("quantidade_linhas") is not None else 1)
            obrig = sql_bool(_obter_obrigatorio(r), False)
            imp = sql_bool(r.get("importa_historico"), False)
            obs = sql_bool(r.get("observacao"), False)
            minimo = sql_num(r.get("minimo"), 0)

            linhas.extend([
                "    WITH dados AS (",
                "        SELECT ''::varchar AS label, gs AS ordem",
                f"        FROM generate_series(1, {qtd}) AS gs",
                "    )",
                "    INSERT INTO public.resposta_template_ficha_clinica (",
                "        label, tipo_campo, pergunta_template_ficha_clinica_id,",
                "        campo_obrigatorio, importa_historico, ordenacao, observacao, minimo",
                "    )",
                "    SELECT",
                f"        label, 'TEXTO', v_pergunta_id, {obrig}, {imp}, ordem, {obs}, {minimo}",
                "    FROM dados",
                "    ORDER BY ordem;",
                "",
            ])

        # PADRÃO 2: Lista homogênea (mesmo tipo_campo e mesmas flags) -> unnest(ARRAY[...])
        elif use_unnest_opt and eh_lista_homogenea(respostas, aplicar_ocr=clean_ocr):
            ref = respostas[0]
            tipo_unico = sql_str(str(ref.get("tipo_campo")).strip().upper())
            obrig = sql_bool(_obter_obrigatorio(ref), False)
            imp = sql_bool(ref.get("importa_historico"), False)
            obs = sql_bool(ref.get("observacao"), False)
            minimo = sql_num(ref.get("minimo"), 0)

            itens_array = ",\n            ".join(
                sql_str(
                    r.get("label", ""),
                    aplicar_ocr=clean_ocr,
                    forcar_maiusculo=force_upper,
                )
                for r in respostas
            )

            linhas.extend([
                "    WITH dados AS (",
                "        SELECT t.label, t.ordem",
                "        FROM unnest(ARRAY[",
                f"            {itens_array}",
                "        ]) WITH ORDINALITY AS t(label, ordem)",
                "    )",
                "    INSERT INTO public.resposta_template_ficha_clinica (",
                "        label, tipo_campo, pergunta_template_ficha_clinica_id,",
                "        campo_obrigatorio, importa_historico, ordenacao, observacao, minimo",
                "    )",
                "    SELECT",
                f"        label, {tipo_unico}, v_pergunta_id, {obrig}, {imp}, ordem, {obs}, {minimo}",
                "    FROM dados",
                "    ORDER BY ordem;",
                "",
            ])

        # PADRÃO 3: Campos heterogêneos na mesma pergunta ou com colunas polimórficas extras -> VALUES
        else:
            respostas_expandidas: list[dict[str, Any]] = []
            for r in respostas:
                qtd = int(
                    r.get("quantidade_linhas", 1)
                    if r.get("quantidade_linhas") is not None
                    else 1
                )
                for _ in range(max(1, qtd)):
                    respostas_expandidas.append(r)

            if not usa_colunas_extras(respostas_expandidas):
                linhas.extend([
                    "    INSERT INTO public.resposta_template_ficha_clinica (",
                    "        pergunta_template_ficha_clinica_id, label, tipo_campo,",
                    "        campo_obrigatorio, importa_historico, ordenacao, observacao, minimo",
                    "    ) VALUES",
                ])
                valores_sql: list[str] = []
                for idx_r, r in enumerate(respostas_expandidas, start=1):
                    valores_sql.append(
                        f"        (v_pergunta_id, {sql_str(r.get('label', ''), aplicar_ocr=clean_ocr, forcar_maiusculo=force_upper)}, "
                        f"{sql_str(str(r.get('tipo_campo')).strip().upper())}, "
                        f"{sql_bool(_obter_obrigatorio(r), False)}, "
                        f"{sql_bool(r.get('importa_historico'), False)}, "
                        f"{idx_r}, {sql_bool(r.get('observacao'), False)}, "
                        f"{sql_num(r.get('minimo'), 0)})"
                    )
                linhas.append(",\n".join(valores_sql) + ";")
                linhas.append("")
            else:
                linhas.extend([
                    "    INSERT INTO public.resposta_template_ficha_clinica (",
                    "        pergunta_template_ficha_clinica_id, label, tipo_campo,",
                    "        campo_obrigatorio, importa_historico, ordenacao, observacao, minimo,",
                    "        valor_numerico, valor_texto, valor_booleano, valor_data, valor_hora,",
                    "        cid_codigo, procedimento_codigo, exame_id, referencia,",
                    "        valor_data_atual, valor_hora_atual",
                    "    ) VALUES",
                ])
                valores_sql = []
                for idx_r, r in enumerate(respostas_expandidas, start=1):
                    valores_sql.append(
                        f"        (v_pergunta_id, {sql_str(r.get('label', ''), aplicar_ocr=clean_ocr, forcar_maiusculo=force_upper)}, "
                        f"{sql_str(str(r.get('tipo_campo')).strip().upper())}, "
                        f"{sql_bool(_obter_obrigatorio(r), False)}, "
                        f"{sql_bool(r.get('importa_historico'), False)}, "
                        f"{idx_r}, {sql_bool(r.get('observacao'), False)}, "
                        f"{sql_num(r.get('minimo'), 0)}, "
                        f"{sql_num(r.get('valor_numerico'))}, "
                        f"{sql_str(r.get('valor_texto'), aplicar_ocr=clean_ocr) if r.get('valor_texto') is not None else 'NULL'}, "
                        f"{sql_bool(r.get('valor_booleano')) if r.get('valor_booleano') is not None else 'NULL'}, "
                        f"{sql_str(r.get('valor_data'))}, {sql_str(r.get('valor_hora'))}, "
                        f"{sql_str(r.get('cid_codigo'))}, {sql_str(r.get('procedimento_codigo'))}, "
                        f"{sql_num(r.get('exame_id'))}, {sql_num(r.get('referencia'))}, "
                        f"{sql_bool(r.get('valor_data_atual')) if r.get('valor_data_atual') is not None else 'NULL'}, "
                        f"{sql_bool(r.get('valor_hora_atual')) if r.get('valor_hora_atual') is not None else 'NULL'})"
                    )
                linhas.append(",\n".join(valores_sql) + ";")
                linhas.append("")

    linhas.append("    RAISE NOTICE 'Template inserido com sucesso! ID gerado: %', v_template_id;")
    linhas.append("END $$;")

    return "\n".join(linhas)


# Alias de compatibilidade com gerar_sql-v2.py
converter_json_para_sql = generate_insert_sql


# =============================================================================
# Validação de Sintaxe e Realce de Sintaxe PostgreSQL
# =============================================================================

POSTGRES_KEYWORDS: tuple[str, ...] = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "FROM",
    "WHERE",
    "JOIN",
    "LEFT",
    "RIGHT",
    "INNER",
    "OUTER",
    "ON",
    "AND",
    "OR",
    "NOT",
    "NULL",
    "IS",
    "TRUE",
    "FALSE",
    "CASE",
    "WHEN",
    "THEN",
    "ELSE",
    "END",
    "AS",
    "INTO",
    "VALUES",
    "RETURNING",
    "DECLARE",
    "BEGIN",
    "DO",
    "WITH",
    "UNNEST",
    "GENERATE_SERIES",
    "ARRAY",
    "ORDINALITY",
    "ORDER BY",
    "GROUP BY",
    "ORDER",
    "GROUP",
    "BY",
    "RAISE",
    "NOTICE",
)

POSTGRES_FUNCTIONS: tuple[str, ...] = (
    "TO_CHAR",
    "BOOL_OR",
    "COALESCE",
    "MAX",
    "EXTRACT",
    "AGE",
    "REPLACE",
    "REGEXP_REPLACE",
    "CAST",
    "UPPER",
)

_STATEMENT_KEYWORDS = {
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "DO",
    "WITH",
    "CREATE",
    "ALTER",
    "DROP",
    "DECLARE",
    "BEGIN",
    "VALUES",
}

_VALID_START_KEYWORDS = _STATEMENT_KEYWORDS | {"SET", "EXPLAIN", "COMMENT"}

_KEYWORD_REGEX = re.compile(
    r"\$\$|\b(?:ORDER\s+BY|GROUP\s+BY|"
    + "|".join(re.escape(k) for k in POSTGRES_KEYWORDS if " " not in k)
    + r")\b",
    re.IGNORECASE,
)

_FUNCTION_REGEX = re.compile(
    r"\b(?:" + "|".join(re.escape(fn) for fn in POSTGRES_FUNCTIONS) + r")\b",
    re.IGNORECASE,
)

_NUMBER_REGEX = re.compile(r"\b\d+(?:\.\d+)?\b")
_STRING_OR_COMMENT_LINE_REGEX = re.compile(r"('(?:''|[^'])*')|(--.*$)")


def validate_postgres_syntax(sql: str) -> tuple[bool, str]:
    """
    Realiza validação sintática básica de PostgreSQL no script fornecido:
    - Verifica se o script não está vazio
    - Verifica balanceamento de aspas simples ('...') e aspas duplas ("...")
    - Verifica fechamento de comentários de bloco (/* ... */) e delimitadores $$
    - Verifica balanceamento de parênteses '(' e ')' (ignorando strings e comentários)
    - Verifica presença de palavras-chave válidas do PostgreSQL
    """
    if not isinstance(sql, str) or not sql.strip():
        return False, "Erro de sintaxe: O script SQL está vazio."

    paren_stack: list[int] = []
    dollar_quote_lines: list[int] = []
    stripped_chars: list[str] = []

    i = 0
    n = len(sql)
    line = 1

    while i < n:
        ch = sql[i]

        # Comentário de linha (-- ...)
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            stripped_chars.append(" ")
            continue

        # Comentário de bloco (/* ... */)
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            start_line = line
            i += 2
            closed = False
            while i < n:
                if sql[i] == "\n":
                    line += 1
                    stripped_chars.append("\n")
                if sql[i] == "*" and i + 1 < n and sql[i + 1] == "/":
                    i += 2
                    closed = True
                    break
                i += 1
            if not closed:
                return (
                    False,
                    f"Erro de sintaxe: Comentário de bloco '/*' iniciado na linha {start_line} não foi fechado.",
                )
            stripped_chars.append(" ")
            continue

        # String literal com aspas simples ('...')
        if ch == "'":
            start_line = line
            i += 1
            closed = False
            while i < n:
                if sql[i] == "\n":
                    line += 1
                    stripped_chars.append("\n")
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    closed = True
                    break
                i += 1
            if not closed:
                return (
                    False,
                    f"Erro de sintaxe: Aspas simples não balanceadas (abertas na linha {start_line}).",
                )
            stripped_chars.append(" 'STR' ")
            continue

        # Identificador com aspas duplas ("...")
        if ch == '"':
            start_line = line
            i += 1
            closed = False
            while i < n:
                if sql[i] == "\n":
                    line += 1
                    stripped_chars.append("\n")
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    closed = True
                    break
                i += 1
            if not closed:
                return (
                    False,
                    f"Erro de sintaxe: Aspas duplas não balanceadas (abertas na linha {start_line}).",
                )
            stripped_chars.append(" IDENT ")
            continue

        # Delimitador de bloco dollar-quoted ($$)
        if ch == "$" and i + 1 < n and sql[i + 1] == "$":
            dollar_quote_lines.append(line)
            stripped_chars.append(" $$ ")
            i += 2
            continue

        # Parênteses
        if ch == "(":
            paren_stack.append(line)
            stripped_chars.append("(")
            i += 1
            continue

        if ch == ")":
            if not paren_stack:
                return (
                    False,
                    f"Erro de sintaxe: Parêntese de fechamento ')' sem abertura correspondente na linha {line}.",
                )
            paren_stack.pop()
            stripped_chars.append(")")
            i += 1
            continue

        if ch == "\n":
            line += 1
            stripped_chars.append("\n")
            i += 1
            continue

        stripped_chars.append(ch)
        i += 1

    if paren_stack:
        open_line = paren_stack[-1]
        return (
            False,
            f"Erro de sintaxe: Parênteses não balanceados ('(' aberto na linha {open_line} não foi fechado).",
        )

    if len(dollar_quote_lines) % 2 != 0:
        open_line = dollar_quote_lines[-1]
        return (
            False,
            f"Erro de sintaxe: Delimitador de bloco '$$' não balanceado (linha {open_line}).",
        )

    cleaned_sql = "".join(stripped_chars)
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", cleaned_sql.upper())

    if not tokens:
        return (
            False,
            "Erro de sintaxe: Nenhuma instrução ou palavra-chave SQL encontrada.",
        )

    if not any(tok in _STATEMENT_KEYWORDS for tok in tokens):
        return (
            False,
            "Erro de sintaxe: Nenhuma palavra-chave principal do PostgreSQL encontrada (SELECT, INSERT, UPDATE, DELETE, DO, WITH).",
        )

    if tokens[0] not in _VALID_START_KEYWORDS:
        return (
            False,
            f"Erro de sintaxe: Palavra-chave inicial desconhecida ou inválida '{tokens[0]}'.",
        )

    if "INSERT" in tokens and "INTO" not in tokens:
        return (
            False,
            "Erro de sintaxe: Instrução INSERT sem a palavra-chave INTO.",
        )

    if "DO" in tokens and "BEGIN" in tokens and "END" not in tokens:
        return (
            False,
            "Erro de sintaxe: Bloco DO/BEGIN sem fechamento END.",
        )

    return (
        True,
        "Sintaxe OK: Parênteses, aspas e palavras-chave PostgreSQL validados com sucesso.",
    )


def apply_syntax_highlighting(text_widget: Any) -> None:
    """
    Configura e aplica tags de realce de sintaxe PostgreSQL em um widget Text/ScrolledText:
    - keywords: SELECT, INSERT, UPDATE, DELETE, FROM, WHERE, JOIN, ON, AND, OR, NOT, NULL,
      TRUE, FALSE, CASE, WHEN, THEN, ELSE, END, AS, INTO, VALUES, RETURNING, DECLARE,
      BEGIN, END, DO, $$, WITH, UNNEST, GENERATE_SERIES, ARRAY, ORDER BY, GROUP BY
    - functions: TO_CHAR, BOOL_OR, COALESCE, MAX, EXTRACT, AGE, REPLACE, REGEXP_REPLACE, CAST
    - strings: '...'
    - numbers: literais numéricos
    - comments: -- ...
    """
    text_widget.tag_configure("keyword", foreground="#1D4ED8")
    text_widget.tag_configure("keywords", foreground="#1D4ED8")
    text_widget.tag_configure("function", foreground="#7C3AED")
    text_widget.tag_configure("functions", foreground="#7C3AED")
    text_widget.tag_configure("string", foreground="#15803D")
    text_widget.tag_configure("strings", foreground="#15803D")
    text_widget.tag_configure("number", foreground="#B45309")
    text_widget.tag_configure("numbers", foreground="#B45309")
    text_widget.tag_configure("comment", foreground="#64748B")
    text_widget.tag_configure("comments", foreground="#64748B")

    all_tags = (
        "keyword",
        "keywords",
        "function",
        "functions",
        "string",
        "strings",
        "number",
        "numbers",
        "comment",
        "comments",
    )
    for tag in all_tags:
        text_widget.tag_remove(tag, "1.0", "end")

    content = text_widget.get("1.0", "end-1c")
    if not content:
        return

    for line_idx, line_text in enumerate(content.split("\n"), start=1):
        if not line_text:
            continue

        protected_spans: list[tuple[int, int]] = []
        for m in _STRING_OR_COMMENT_LINE_REGEX.finditer(line_text):
            s_idx, e_idx = m.start(), m.end()
            protected_spans.append((s_idx, e_idx))
            start_pos = f"{line_idx}.{s_idx}"
            end_pos = f"{line_idx}.{e_idx}"
            if m.group(1) is not None:
                text_widget.tag_add("string", start_pos, end_pos)
                text_widget.tag_add("strings", start_pos, end_pos)
            else:
                text_widget.tag_add("comment", start_pos, end_pos)
                text_widget.tag_add("comments", start_pos, end_pos)

        def _is_protected(start: int, end: int) -> bool:
            for p_start, p_end in protected_spans:
                if start < p_end and end > p_start:
                    return True
            return False

        for m in _KEYWORD_REGEX.finditer(line_text):
            if not _is_protected(m.start(), m.end()):
                start_pos = f"{line_idx}.{m.start()}"
                end_pos = f"{line_idx}.{m.end()}"
                text_widget.tag_add("keyword", start_pos, end_pos)
                text_widget.tag_add("keywords", start_pos, end_pos)

        for m in _FUNCTION_REGEX.finditer(line_text):
            if not _is_protected(m.start(), m.end()):
                start_pos = f"{line_idx}.{m.start()}"
                end_pos = f"{line_idx}.{m.end()}"
                text_widget.tag_add("function", start_pos, end_pos)
                text_widget.tag_add("functions", start_pos, end_pos)

        for m in _NUMBER_REGEX.finditer(line_text):
            if not _is_protected(m.start(), m.end()):
                start_pos = f"{line_idx}.{m.start()}"
                end_pos = f"{line_idx}.{m.end()}"
                text_widget.tag_add("number", start_pos, end_pos)
                text_widget.tag_add("numbers", start_pos, end_pos)

    text_widget.tag_raise("string")
    text_widget.tag_raise("strings")
    text_widget.tag_raise("comment")
    text_widget.tag_raise("comments")

