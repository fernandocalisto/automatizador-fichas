# -*- coding: utf-8 -*-
"""
Gerador de dados clínicos fictícios para pré-visualização híbrida/offline de `.jrxml` Salutem
(`backend/app/jrxml/mock_data.py`).

Suporta os 3 cenários oficiais de homologação visual da Etapa 2:
- `"full"`: dados clínicos realistas, sinais vitais/datas/textos coerentes, exatamente 1 `True`
  por grupo `BOOLEANO_RADIO` (irmãos `False`), ~metade dos checkboxes `BOOLEANO` `True`, e
  campos `_obs` preenchidos somente quando o item pai está ativo.
- `"stress"`: strings clínicas acentuadas de 180–240 caracteres para teste de overflow/clipping,
  números elevados, todos os checkboxes `BOOLEANO` `True` (mantendo 1 `True` por grupo
  `BOOLEANO_RADIO`), e 100% dos `_obs` preenchidos.
- `"blank"`: `False` para todos os booleanos clínicos e `None` para textos, datas, números e
  observações clínicas, preservando os campos estruturais padrão da ficha Salutem.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Literal

try:
    from backend.app.core.sql_select import normalizar_slug, sufixo_tipo
    from backend.app.jrxml.scaffolder import STANDARD_SALUTEM_FIELDS
except ModuleNotFoundError:  # pragma: no cover
    from app.core.sql_select import normalizar_slug, sufixo_tipo  # type: ignore[no-redef]
    from app.jrxml.scaffolder import STANDARD_SALUTEM_FIELDS  # type: ignore[no-redef]

ScenarioType = Literal["full", "stress", "blank"]
VALID_SCENARIOS: tuple[str, ...] = ("full", "stress", "blank")

# PNG 1x1 transparente em Base64 (seguro caso assinatura seja exibida como String ou decodificada em <image>)
_TRANSPARENT_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

_INTEGER_JAVA_CLASSES: frozenset[str] = frozenset(
    {
        "java.lang.Long",
        "java.lang.Integer",
        "java.lang.Short",
        "java.lang.Byte",
        "java.math.BigInteger",
        "long",
        "int",
        "short",
    }
)

_FLOAT_JAVA_CLASSES: frozenset[str] = frozenset(
    {
        "java.lang.Double",
        "java.lang.Float",
        "java.math.BigDecimal",
        "java.lang.Number",
        "double",
        "float",
    }
)

_BOOLEAN_JAVA_CLASSES: frozenset[str] = frozenset(
    {
        "java.lang.Boolean",
        "boolean",
    }
)

_DATE_JAVA_CLASSES: frozenset[str] = frozenset(
    {
        "java.sql.Date",
        "java.util.Date",
        "java.sql.Timestamp",
        "java.sql.Time",
    }
)


def _local_tag_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_jrxml_declared_fields(jrxml_text: str) -> list[tuple[str, str]]:
    """
    Valida o XML `.jrxml` e extrai a lista ordenada `[(name, java_class), ...]`
    de todas as tags `<field>` declaradas no `<jasperReport>` raiz.
    """
    if not isinstance(jrxml_text, str) or not jrxml_text.strip():
        raise ValueError("Conteúdo JRXML vazio ou inválido.")

    cleaned = jrxml_text.lstrip("\ufeff").strip()
    try:
        root = ET.fromstring(cleaned)
    except ET.ParseError as exc:
        raise ValueError(f"Erro de sintaxe XML no JRXML: {exc}") from exc

    if _local_tag_name(root.tag) != "jasperReport":
        raise ValueError(
            f"Elemento raiz inválido '<{_local_tag_name(root.tag)}>': esperado '<jasperReport>'."
        )

    fields: list[tuple[str, str]] = []
    for child in root:
        if _local_tag_name(child.tag) == "field":
            fname = (child.attrib.get("name") or "").strip()
            fclass = (child.attrib.get("class") or "java.lang.String").strip()
            if fname:
                fields.append((fname, fclass))
    return fields


def _build_stress_clinical_string(field_name: str, label: str = "") -> str:
    """
    Gera string clínica acentuada determinística com comprimento estritamente entre 180 e 240 caracteres.
    """
    tag = (label or field_name or "campo_clinico").strip()[:36]
    core = (
        f"[{tag}] Avaliação clínica detalhada em cenário de estresse tipográfico: "
        "paciente lúcido, parâmetros hemodinâmicos monitorizados continuamente, "
        "perfusão periférica preservada, saturação estável e conduta terapêutica reavaliada pela equipe."
    )
    if len(core) < 185:
        filler = " Evolução clínica registrada sem intercorrências agudas adicionais no plantão."
        while len(core) < 185:
            core += filler
    if len(core) > 236:
        core = core[:235].rstrip() + "."
    return core


def _realistic_clinical_string(
    field_name: str,
    *,
    source_type: str | None = None,
    label: str = "",
    is_obs: bool = False,
    index: int = 0,
) -> str:
    """Retorna valor textual clínico realista e coerente para o cenário `'full'`."""
    if is_obs:
        obs_samples = (
            "Observação clínica complementar registrada sem intercorrências agudas.",
            "Achado avaliado pela equipe multiprofissional; mantida vigilância clínica.",
            "Orientado paciente e acompanhante quanto aos sinais de alerta e retorno.",
        )
        return obs_samples[index % len(obs_samples)]

    st = (source_type or "").strip().upper()
    slug = normalizar_slug(f"{field_name} {label}")

    if st == "HORA" or slug.endswith("_hora") or slug == "hora" or "horario" in slug:
        hours = ("08:15", "09:40", "11:20", "14:35", "16:10")
        return hours[index % len(hours)]

    if st == "DATA" or slug.endswith("_data") or slug.startswith("data_"):
        dates = ("25/11/2026", "24/11/2026", "20/11/2026", "15/10/2026")
        return dates[index % len(dates)]

    if st == "CID" or "cid" in slug:
        return "I10 - Hipertensão essencial (primária)"

    if st in ("PROCEDIMENTO", "PROCEDIMENTO_CID") or "procedimento" in slug:
        return "03.01.01.007-2 - Consulta médica em atenção especializada"

    if st == "EXAME" or "exame" in slug:
        return "Hemograma completo, ureia, creatinina e eletrólitos séricos dentro dos limites de referência."

    if st == "COMBOBOX":
        return "Adequado / Dentro dos parâmetros esperados"

    # Heurísticas de sinais vitais e antropometria em campos TEXTO
    tokens = set(slug.split("_"))
    if "pa" in tokens or "pressao" in slug:
        return "120/80 mmHg"
    if "fc" in tokens or "pulso" in tokens or "frequencia_cardiaca" in slug:
        return "78 bpm"
    if "fr" in tokens or "frequencia_respiratoria" in slug:
        return "16 irpm"
    if "spo2" in tokens or "sp02" in tokens or "saturacao" in slug:
        return "98%"
    if "temp" in tokens or "temperatura" in slug or "tax" in tokens:
        return "36,6 °C"
    if "peso" in tokens:
        return "72,5 kg"
    if "altura" in tokens or "estatura" in tokens:
        return "1,68 m"
    if "imc" in tokens:
        return "25,7 kg/m²"
    if "glicemia" in slug or "hgt" in tokens or "dextro" in tokens:
        return "96 mg/dL"
    if "dor" in tokens or "eva" in tokens:
        return "2/10 (leve)"
    if "alergia" in slug:
        return "Nega alergias medicamentosas conhecidas (dipirona/penicilina testadas)."
    if "medicamento" in slug or "med_uso" in slug:
        return "Losartana 50 mg VO 12/12h; Anlodipino 5 mg VO 1x/dia."

    clinical_phrases = (
        "Paciente lúcido, orientado em tempo e espaço, corado, hidratado, acianótico e eupneico em ar ambiente.",
        "Bom estado geral, hemodinamicamente estável, abdome plano, flácido e indolor à palpação superficial e profunda.",
        "Ausculta cardíaca com bulhas rítmicas normofonéticas em 2 tempos sem sopros; murmúrio vesicular presente bilateralmente.",
        "Evolução favorável no período de observação clínica, sem queixas álgicas agudas ou sinais flogísticos.",
    )
    return clinical_phrases[index % len(clinical_phrases)]


def _realistic_clinical_number(field_name: str, label: str = "", index: int = 0) -> float:
    """Retorna valor numérico clínico realista para o cenário `'full'`."""
    slug = normalizar_slug(f"{field_name} {label}")
    tokens = set(slug.split("_"))
    if "peso" in tokens:
        return 72.5
    if "altura" in tokens or "estatura" in tokens:
        return 1.68
    if "imc" in tokens:
        return 25.7
    if "temp" in tokens or "temperatura" in slug or "tax" in tokens:
        return 36.6
    if "spo2" in tokens or "sp02" in tokens or "saturacao" in slug:
        return 98.0
    if "fc" in tokens or "pulso" in tokens:
        return 78.0
    if "fr" in tokens:
        return 16.0
    if "glicemia" in slug or "hgt" in tokens:
        return 96.0
    defaults = (12.5, 36.5, 75.0, 110.0)
    return defaults[index % len(defaults)]


def _coerce_to_java_class(value: Any, java_class: str) -> Any:
    """Converte um valor Python para o tipo exato compatível com a classe Java declarada em `<field>`."""
    if value is None:
        return None

    jclass = (java_class or "java.lang.String").strip()

    if jclass in _BOOLEAN_JAVA_CLASSES:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "sim", "x", "t", "yes")
        return bool(value)

    if jclass in _INTEGER_JAVA_CLASSES:
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(float(str(value).strip()))
        except ValueError:
            return 10042

    if jclass in _FLOAT_JAVA_CLASSES:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip().replace(",", "."))
        except ValueError:
            return 36.5

    if jclass in _DATE_JAVA_CLASSES:
        s_val = str(value).strip()
        if len(s_val) >= 10 and s_val[4] == "-" and s_val[7] == "-":
            return s_val[:10]
        return "1985-04-12"

    # Default: java.lang.String e demais classes textuais
    return str(value)


def _build_standard_salutem_defaults(
    *,
    atendimento_id: int,
    descricao_ficha: str,
) -> dict[str, Any]:
    """
    Retorna valores padrão tipados para todos os campos estruturais do Salutem
    (`STANDARD_SALUTEM_FIELDS`: cabeçalho, paciente, profissional e atendimento).
    """
    return {
        "solicitante_cnes": "2078451",
        "solicitante": "HOSPITAL SALUTEM — AMBIENTE DE VALIDAÇÃO",
        "data_criacao": "Lorena, 25/11/2026 14:30",
        "pac_id": 50821,
        "pac_nome": "MARIA CLARA DE OLIVEIRA SANTOS",
        "pac_nasc": "1985-04-12",
        "pac_resp": "CARLOS EDUARDO DE OLIVEIRA SANTOS",
        "pac_mae": "ANA PAULA DE OLIVEIRA",
        "pac_idade_a": 41.0,
        "pac_idade_m": 7.0,
        "pac_idade_d": 13.0,
        "pac_sexo": "[F](X) [M](  )",
        "pac_raca": "PARDA",
        "pac_etnia": "NÃO SE APLICA",
        "pac_cns": "704801684920341",
        "pac_pront": 50821,
        "pac_cpf": "348.912.608-45",
        "pac_rg": "42.819.305-7",
        "pac_tel": "(12) 3152-4410",
        "pac_cel": "(12) 99741-8823",
        "pac_log": "AVENIDA DOUTOR PEIXOTO DE CASTRO, 1420  -  VILA ZÉLIA",
        "pac_compl": "APTO 302 BLOCO B",
        "pac_mun": "LORENA",
        "pac_idmun": 3527207,
        "pac_uf": "SP",
        "pac_cep": "12606-580",
        "codigo_cross": "CROSS-2026-009841",
        "assinatura": _TRANSPARENT_PNG_B64,
        "responsavel_assinatura": _TRANSPARENT_PNG_B64,
        "rg_reponsavel": "28.441.902-1",
        "solicitanteid": 309,
        "prof_nome": "DR. HENRIQUE ALMEIDA PRADO",
        "prof_cns": "700508912340118",
        "prof_org": "CRM-SP",
        "prof_crm": "168420",
        "prof_doc": "(X)CNS (  )CPF",
        "data_atendimento": "2026-11-25",
        "atendimento_id": int(atendimento_id),
        "descricao_ficha": descricao_ficha,
    }


def _extract_json_question_groups(
    json_data: dict[str, Any],
    *,
    column_naming: str = "label_only",
) -> list[dict[str, Any]]:
    """
    Reproduz exatamente a geração de aliases de `sql_select._build_question_plan()`,
    preservando o agrupamento por pergunta para impor a invariante de exclusividade
    dos grupos `BOOLEANO_RADIO` e o vínculo pai -> `_obs`.
    """
    perguntas = json_data.get("perguntas", [])
    if not isinstance(perguntas, list):
        return []

    aliases_usados: set[str] = set()
    groups: list[dict[str, Any]] = []

    for idx_p, p in enumerate(perguntas, start=1):
        if not isinstance(p, dict):
            continue
        p_nome = str(p.get("nome") or f"PERGUNTA_{idx_p}")
        respostas = p.get("respostas") or []
        if not isinstance(respostas, list):
            continue

        respostas_expandidas: list[dict[str, Any]] = []
        for r in respostas:
            if not isinstance(r, dict):
                continue
            qtd_raw = r.get("quantidade_linhas", 1)
            qtd = int(qtd_raw if qtd_raw is not None else 1)
            lbl_raw = str(r.get("label") or "").strip()
            if not lbl_raw and qtd > 1:
                for sub_i in range(1, qtd + 1):
                    novo_r = dict(r)
                    novo_r["_sub_idx"] = sub_i
                    respostas_expandidas.append(novo_r)
            else:
                respostas_expandidas.append(r)

        p_slug = normalizar_slug(p_nome)
        items: list[dict[str, Any]] = []

        for idx_r, r in enumerate(respostas_expandidas, start=1):
            lbl = str(r.get("label") or "").strip()
            raw_tipo = r.get("tipo_campo")
            tipo = str(raw_tipo if raw_tipo is not None else "TEXTO").strip().upper() or "TEXTO"

            if column_naming == "pergunta_label":
                if not lbl:
                    base_alias = f"{p_slug}_r{idx_r}"
                else:
                    lbl_slug = normalizar_slug(lbl)
                    base_alias = (
                        lbl_slug
                        if lbl_slug == p_slug or lbl_slug.startswith(f"{p_slug}_")
                        else f"{p_slug}_{lbl_slug}"
                    )
            elif column_naming == "label_sufixo":
                raw_base = f"p{idx_p}_r{idx_r}" if not lbl else normalizar_slug(lbl)
                suf = sufixo_tipo(tipo)
                base_alias = raw_base if raw_base.endswith(f"_{suf}") else f"{raw_base}_{suf}"
            else:
                base_alias = f"p{idx_p}_r{idx_r}" if not lbl else normalizar_slug(lbl)

            alias = base_alias
            if alias in aliases_usados:
                suf = sufixo_tipo(tipo)
                cand = (
                    f"{base_alias}_{suf}"
                    if not base_alias.endswith(f"_{suf}")
                    else f"{base_alias}_2"
                )
                if cand not in aliases_usados:
                    alias = cand
                else:
                    c = 2
                    while f"{cand}_{c}" in aliases_usados:
                        c += 1
                    alias = f"{cand}_{c}"
            aliases_usados.add(alias)

            tem_observacao = (
                (p.get("observacao") is True or r.get("observacao") is True)
                and tipo != "TEXTO"
            )
            alias_obs: str | None = None
            if tem_observacao:
                alias_obs_base = f"{base_alias}_obs"
                cand_obs = alias_obs_base
                c = 2
                while cand_obs in aliases_usados:
                    cand_obs = f"{alias_obs_base}_{c}"
                    c += 1
                aliases_usados.add(cand_obs)
                alias_obs = cand_obs

            items.append(
                {
                    "alias": alias,
                    "alias_obs": alias_obs,
                    "tipo": tipo,
                    "label": lbl,
                    "pergunta_nome": p_nome,
                }
            )

        groups.append({"idx_p": idx_p, "nome": p_nome, "items": items})

    return groups


def _select_best_question_groups(
    json_data: dict[str, Any],
    declared_names: set[str],
) -> list[dict[str, Any]]:
    """Seleciona a estratégia de `column_naming` mais aderente aos `<field>` declarados no `.jrxml`."""
    best_groups: list[dict[str, Any]] = []
    best_score = -1

    for naming in ("label_only", "pergunta_label", "label_sufixo"):
        candidate = _extract_json_question_groups(json_data, column_naming=naming)
        emitted: set[str] = set()
        for grp in candidate:
            for item in grp["items"]:
                emitted.add(item["alias"])
                if item["alias_obs"]:
                    emitted.add(item["alias_obs"])
        score = len(emitted & declared_names)
        if score > best_score:
            best_score = score
            best_groups = candidate

    return best_groups


def generate_fictitious_row(
    jrxml_text: str,
    json_data: dict[str, Any] | None = None,
    scenario: ScenarioType = "full",
    atendimento_id: int = 10042,
) -> dict[str, Any]:
    """
    Gera um registro clínico fictício (`dict[str, Any]`) sincronizado com os `<field>` do `.jrxml`
    e (quando disponível) com a semântica de grupos de perguntas do `json_data`.

    - Popula todos os campos padrão da ficha Salutem (`STANDARD_SALUTEM_FIELDS`) respeitando os tipos Java.
    - `"blank"`: `False` para booleanos clínicos; `None` para textos/números/datas/observações clínicas.
    - `"full"`: vitais/datas/textos realistas; apenas 1 `True` por grupo `BOOLEANO_RADIO` (irmãos `False`);
      ~metade dos checkboxes `BOOLEANO` `True`; `_obs` preenchido apenas quando o item pai está ativo.
    - `"stress"`: strings clínicas acentuadas de 180–240 caracteres, números grandes, todos os checkboxes
      `BOOLEANO` `True` (mantendo 1 `True` por grupo `BOOLEANO_RADIO`) e todos os `_obs` preenchidos.
    """
    if scenario not in ("full", "stress", "blank"):
        raise ValueError(
            f"Cenário inválido '{scenario}': esperado 'full', 'stress' ou 'blank'."
        )

    declared_fields = parse_jrxml_declared_fields(jrxml_text)
    declared_map: dict[str, str] = dict(declared_fields)
    declared_names = set(declared_map.keys())

    standard_class_map: dict[str, str] = {
        name: jclass for name, jclass, _ in STANDARD_SALUTEM_FIELDS
    }
    standard_names = set(standard_class_map.keys())

    descricao_ficha = "FICHA CLÍNICA DE VALIDAÇÃO SALUTEM"
    if isinstance(json_data, dict):
        tpl = json_data.get("template")
        if isinstance(tpl, dict) and str(tpl.get("nome") or "").strip():
            descricao_ficha = str(tpl["nome"]).strip().upper()

    std_defaults = _build_standard_salutem_defaults(
        atendimento_id=int(atendimento_id),
        descricao_ficha=descricao_ficha,
    )

    row: dict[str, Any] = {}
    for std_name, std_default_class in standard_class_map.items():
        target_class = declared_map.get(std_name, std_default_class)
        row[std_name] = _coerce_to_java_class(std_defaults[std_name], target_class)

    checkbox_idx = 0
    clinical_idx = 0
    populated_clinical: set[str] = set()

    # 1. População semântica guiada pelo JSON clínico (quando fornecido)
    if isinstance(json_data, dict) and isinstance(json_data.get("perguntas"), list):
        groups = _select_best_question_groups(json_data, declared_names)
        for grp in groups:
            items: list[dict[str, Any]] = grp["items"]
            radio_items = [it for it in items if it["tipo"] == "BOOLEANO_RADIO"]

            # Escolhe exatamente 1 vencedor no grupo BOOLEANO_RADIO (priorizando opção com _obs para exercitar layout)
            chosen_radio_alias: str | None = None
            if radio_items and scenario in ("full", "stress"):
                with_obs = [it for it in radio_items if it.get("alias_obs")]
                chosen_radio_alias = (
                    with_obs[0]["alias"] if with_obs else radio_items[0]["alias"]
                )

            for item in items:
                alias: str = item["alias"]
                alias_obs: str | None = item["alias_obs"]
                tipo: str = item["tipo"]
                lbl: str = item["label"]

                if alias in standard_names:
                    continue

                jclass = declared_map.get(
                    alias,
                    "java.lang.Boolean"
                    if tipo in ("BOOLEANO", "BOOLEANO_RADIO")
                    else ("java.lang.Double" if tipo == "NUMERICO" else "java.lang.String"),
                )

                is_active = False
                if tipo == "BOOLEANO_RADIO":
                    if scenario == "blank":
                        val: Any = False if jclass in _BOOLEAN_JAVA_CLASSES else None
                    else:
                        is_selected = alias == chosen_radio_alias
                        is_active = is_selected
                        if jclass in _BOOLEAN_JAVA_CLASSES:
                            val = is_selected
                        else:
                            val = (
                                _build_stress_clinical_string(alias, lbl)
                                if (scenario == "stress" and is_selected)
                                else ("X" if is_selected else "")
                            )
                elif tipo == "BOOLEANO":
                    if scenario == "blank":
                        val = False if jclass in _BOOLEAN_JAVA_CLASSES else None
                    elif scenario == "stress":
                        is_active = True
                        val = (
                            True
                            if jclass in _BOOLEAN_JAVA_CLASSES
                            else _build_stress_clinical_string(alias, lbl)
                        )
                    else:
                        is_checked = (checkbox_idx % 2) == 0
                        checkbox_idx += 1
                        is_active = is_checked
                        val = (
                            is_checked
                            if jclass in _BOOLEAN_JAVA_CLASSES
                            else ("X" if is_checked else "")
                        )
                elif tipo == "NUMERICO":
                    if scenario == "blank":
                        val = None
                    elif scenario == "stress":
                        is_active = True
                        raw_num = 98450.75 + (clinical_idx * 125.5)
                        val = _coerce_to_java_class(raw_num, jclass)
                    else:
                        is_active = True
                        raw_num = _realistic_clinical_number(alias, lbl, clinical_idx)
                        val = _coerce_to_java_class(raw_num, jclass)
                    clinical_idx += 1
                else:
                    # TEXTO, HORA, DATA, CID, EXAME, PROCEDIMENTO, PROCEDIMENTO_CID, COMBOBOX
                    if scenario == "blank":
                        val = None
                    elif scenario == "stress":
                        is_active = True
                        if jclass in _DATE_JAVA_CLASSES:
                            val = "1985-04-12"
                        elif jclass in (_INTEGER_JAVA_CLASSES | _FLOAT_JAVA_CLASSES):
                            val = _coerce_to_java_class(98450.75, jclass)
                        else:
                            val = _build_stress_clinical_string(alias, lbl)
                    else:
                        is_active = True
                        if jclass in _DATE_JAVA_CLASSES:
                            val = "2026-11-25"
                        elif jclass in (_INTEGER_JAVA_CLASSES | _FLOAT_JAVA_CLASSES):
                            val = _coerce_to_java_class(
                                _realistic_clinical_number(alias, lbl, clinical_idx),
                                jclass,
                            )
                        else:
                            val = _realistic_clinical_string(
                                alias,
                                source_type=tipo,
                                label=lbl,
                                is_obs=False,
                                index=clinical_idx,
                            )
                    clinical_idx += 1

                row[alias] = val if val is None else _coerce_to_java_class(val, jclass)
                populated_clinical.add(alias)

                if alias_obs and alias_obs not in standard_names:
                    obs_class = declared_map.get(alias_obs, "java.lang.String")
                    if scenario == "blank":
                        obs_val: Any = None
                    elif scenario == "stress":
                        obs_val = _build_stress_clinical_string(alias_obs, f"{lbl} obs")
                    else:
                        obs_val = (
                            _realistic_clinical_string(
                                alias_obs,
                                label=lbl,
                                is_obs=True,
                                index=clinical_idx,
                            )
                            if is_active
                            else None
                        )
                    row[alias_obs] = (
                        None if obs_val is None else _coerce_to_java_class(obs_val, obs_class)
                    )
                    populated_clinical.add(alias_obs)
                    clinical_idx += 1

    # 2. População heurística para quaisquer `<field>` declarados no `.jrxml` não cobertos acima
    obs_deferred: list[tuple[str, str]] = []
    for fname, fclass in declared_fields:
        if fname in standard_names or fname in populated_clinical:
            continue
        if fname.endswith("_obs") or "_obs_" in fname:
            obs_deferred.append((fname, fclass))
            continue

        if scenario == "blank":
            row[fname] = False if fclass in _BOOLEAN_JAVA_CLASSES else None
        elif scenario == "stress":
            if fclass in _BOOLEAN_JAVA_CLASSES:
                row[fname] = True
            elif fclass in _INTEGER_JAVA_CLASSES:
                row[fname] = 987654 + clinical_idx
            elif fclass in _FLOAT_JAVA_CLASSES:
                row[fname] = 98450.75 + (clinical_idx * 10.0)
            elif fclass in _DATE_JAVA_CLASSES:
                row[fname] = "1985-04-12"
            else:
                row[fname] = _build_stress_clinical_string(fname)
            clinical_idx += 1
        else:
            # scenario == "full" sem JSON
            if fclass in _BOOLEAN_JAVA_CLASSES:
                row[fname] = (checkbox_idx % 2) == 0
                checkbox_idx += 1
            elif fclass in _INTEGER_JAVA_CLASSES:
                row[fname] = int(_realistic_clinical_number(fname, index=clinical_idx))
                clinical_idx += 1
            elif fclass in _FLOAT_JAVA_CLASSES:
                row[fname] = _realistic_clinical_number(fname, index=clinical_idx)
                clinical_idx += 1
            elif fclass in _DATE_JAVA_CLASSES:
                row[fname] = "2026-11-25"
                clinical_idx += 1
            else:
                row[fname] = _realistic_clinical_string(
                    fname,
                    is_obs=False,
                    index=clinical_idx,
                )
                clinical_idx += 1

    for obs_name, obs_class in obs_deferred:
        if scenario == "blank":
            row[obs_name] = None
        elif scenario == "stress":
            row[obs_name] = _coerce_to_java_class(
                _build_stress_clinical_string(obs_name),
                obs_class,
            )
        else:
            base_candidate = obs_name.rsplit("_obs", 1)[0]
            parent_active = bool(row.get(base_candidate, True))
            if parent_active:
                row[obs_name] = _coerce_to_java_class(
                    _realistic_clinical_string(obs_name, is_obs=True, index=clinical_idx),
                    obs_class,
                )
            else:
                row[obs_name] = None
            clinical_idx += 1

    # Garante sincronia explícita de atendimento_id com o parâmetro recebido
    atend_class = declared_map.get("atendimento_id", "java.lang.Long")
    row["atendimento_id"] = _coerce_to_java_class(int(atendimento_id), atend_class)

    return row


__all__ = [
    "ScenarioType",
    "VALID_SCENARIOS",
    "generate_fictitious_row",
    "parse_jrxml_declared_fields",
]
