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

import re
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Literal

try:
    from backend.app.core.sql_select import normalizar_slug, sufixo_tipo
    from backend.app.jrxml.scaffolder import STANDARD_SALUTEM_FIELDS
except ModuleNotFoundError:  # pragma: no cover
    from app.core.sql_select import normalizar_slug, sufixo_tipo  # type: ignore[no-redef]
    from app.jrxml.scaffolder import STANDARD_SALUTEM_FIELDS  # type: ignore[no-redef]

ScenarioType = Literal["full", "stress", "blank"]
PreviewRewriteMode = Literal["offline", "db_hybrid"]
VALID_SCENARIOS: tuple[str, ...] = ("full", "stress", "blank")
VALID_PREVIEW_MODES: tuple[str, ...] = ("offline", "db_hybrid")

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


# -----------------------------------------------------------------------------
# Subreports Mock Offline & Reescrita Híbrida/Offline de JRXML (Etapa 2)
# -----------------------------------------------------------------------------

_SUBREPORT_BLOCK_RE = re.compile(r"(<subreport\b[^>]*>)(.*?)(</subreport>)", re.DOTALL)
_CONN_EXPR_RE = re.compile(r"<connectionExpression\b[^>]*>.*?</connectionExpression>", re.DOTALL)
_QUERY_STRING_RE = re.compile(r"<queryString\b[^>]*>.*?</queryString>", re.DOTALL)
_SIMPLE_SQL_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


def _safe_cdata(text: str) -> str:
    """Protege eventual sequência `]]>` dentro de blocos CDATA."""
    return text.replace("]]>", "]]]]><![CDATA[>")


def _xml_attr_escape(value: str) -> str:
    """Escapa caracteres especiais em valores de atributos XML."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _det_uuid(seed: str) -> str:
    """Gera UUID canônico determinístico (`8-4-4-4-12`) único por elemento de subreport mock."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"salutem.ficha.studio.mock.{seed}"))


def _build_header_mock_subreport(
    *,
    report_name: str,
    width: int,
    height: int,
    is_landscape: bool,
    unit_name: str,
) -> str:
    orientation_attr = ' orientation="Landscape"' if is_landscape else ""
    seed_prefix = f"{report_name}:{width}x{height}:{unit_name}"
    inner_w = width - 16
    esc_unit = _safe_cdata(unit_name.strip() or "HOSPITAL SALUTEM — AMBIENTE DE VALIDAÇÃO")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports '
            'http://jasperreports.sourceforge.net/xsd/jasperreport.xsd" '
            f'name="{_xml_attr_escape(report_name)}"{orientation_attr} '
            f'pageWidth="{width}" pageHeight="{height}" columnWidth="{width}" '
            'leftMargin="0" rightMargin="0" topMargin="0" bottomMargin="0" '
            'whenNoDataType="AllSectionsNoDetail" '
            f'uuid="{_det_uuid(seed_prefix + ":root")}">'
        ),
        '\t<parameter name="caminho_relatorio" class="java.lang.String"/>',
        "\t<title>",
        f'\t\t<band height="{height}" splitType="Stretch">',
        "\t\t\t<rectangle>",
        f'\t\t\t\t<reportElement x="0" y="0" width="{width}" height="{height}" uuid="{_det_uuid(seed_prefix + ":border")}"/>',
        "\t\t\t\t<graphicElement>",
        '\t\t\t\t\t<pen lineWidth="0.5" lineColor="#000000"/>',
        "\t\t\t\t</graphicElement>",
        "\t\t\t</rectangle>",
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="8" y="4" width="{inner_w}" height="22" uuid="{_det_uuid(seed_prefix + ":title")}"/>',
        '\t\t\t\t<textElement textAlignment="Center" verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="10" isBold="true"/>',
        "\t\t\t\t</textElement>",
        f"\t\t\t\t<text><![CDATA[{esc_unit}]]></text>",
        "\t\t\t</staticText>",
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="8" y="26" width="{inner_w}" height="15" uuid="{_det_uuid(seed_prefix + ":subtitle")}"/>',
        '\t\t\t\t<textElement textAlignment="Center" verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="8" isItalic="true"/>',
        "\t\t\t\t</textElement>",
        "\t\t\t\t<text><![CDATA[SISTEMA SALUTEM — PRÉ-VISUALIZAÇÃO OFFLINE (DADOS FICTÍCIOS)]]></text>",
        "\t\t\t</staticText>",
        "\t\t</band>",
        "\t</title>",
        "</jasperReport>",
    ]
    return "\n".join(lines) + "\n"


def _build_patient_mock_subreport(patient_info: dict[str, Any] | None = None) -> str:
    info = dict(patient_info or {})
    pac_nome = str(info.get("pac_nome") or info.get("nome") or "MARIA CLARA DE OLIVEIRA SANTOS")
    pac_pront = str(info.get("pac_pront") or info.get("prontuario") or "50821")
    atend_id = str(info.get("atendimento_id") or "10042")
    pac_nasc = str(info.get("pac_nasc") or info.get("nasc") or "12/04/1985 (41a)")
    pac_sexo = str(info.get("pac_sexo") or info.get("sexo") or "FEMININO")
    pac_cns = str(info.get("pac_cns") or info.get("cns") or "704801684920341")
    pac_mae = str(info.get("pac_mae") or info.get("mae") or "ANA PAULA DE OLIVEIRA")
    pac_cpf = str(info.get("pac_cpf") or info.get("cpf") or "348.912.608-45")
    pac_log = str(
        info.get("pac_log")
        or info.get("endereco")
        or "AV. DR. PEIXOTO DE CASTRO, 1420 - VILA ZÉLIA"
    )
    pac_mun = str(info.get("pac_mun") or info.get("municipio") or "LORENA")
    pac_uf = str(info.get("pac_uf") or info.get("uf") or "SP")

    row1 = _safe_cdata(f"PACIENTE: {pac_nome}   |   PRONTUÁRIO: {pac_pront}   |   ATEND.: {atend_id}")
    row2 = _safe_cdata(f"DATA NASC.: {pac_nasc}   |   SEXO: {pac_sexo}   |   CNS: {pac_cns}")
    row3 = _safe_cdata(f"NOME DA MÃE: {pac_mae}   |   CPF: {pac_cpf}")
    row4 = _safe_cdata(f"ENDEREÇO: {pac_log} — {pac_mun}/{pac_uf}")

    seed_prefix = f"dados_paciente:{pac_nome}:{atend_id}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports '
            'http://jasperreports.sourceforge.net/xsd/jasperreport.xsd" '
            'name="dados_paciente" pageWidth="555" pageHeight="77" columnWidth="555" '
            'leftMargin="0" rightMargin="0" topMargin="0" bottomMargin="0" '
            'whenNoDataType="AllSectionsNoDetail" '
            f'uuid="{_det_uuid(seed_prefix + ":root")}">'
        ),
        '\t<parameter name="atendimento_id" class="java.lang.Long"/>',
        "\t<title>",
        '\t\t<band height="77" splitType="Stretch">',
        "\t\t\t<rectangle>",
        f'\t\t\t\t<reportElement x="0" y="0" width="555" height="77" uuid="{_det_uuid(seed_prefix + ":border")}"/>',
        "\t\t\t\t<graphicElement>",
        '\t\t\t\t\t<pen lineWidth="0.5" lineColor="#000000"/>',
        "\t\t\t\t</graphicElement>",
        "\t\t\t</rectangle>",
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="6" y="2" width="543" height="18" uuid="{_det_uuid(seed_prefix + ":r1")}"/>',
        '\t\t\t\t<textElement verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="8" isBold="true"/>',
        "\t\t\t\t</textElement>",
        f"\t\t\t\t<text><![CDATA[{row1}]]></text>",
        "\t\t\t</staticText>",
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="6" y="20" width="543" height="18" uuid="{_det_uuid(seed_prefix + ":r2")}"/>',
        '\t\t\t\t<textElement verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="8"/>',
        "\t\t\t\t</textElement>",
        f"\t\t\t\t<text><![CDATA[{row2}]]></text>",
        "\t\t\t</staticText>",
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="6" y="38" width="543" height="18" uuid="{_det_uuid(seed_prefix + ":r3")}"/>',
        '\t\t\t\t<textElement verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="8"/>',
        "\t\t\t\t</textElement>",
        f"\t\t\t\t<text><![CDATA[{row3}]]></text>",
        "\t\t\t</staticText>",
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="6" y="56" width="543" height="19" uuid="{_det_uuid(seed_prefix + ":r4")}"/>',
        '\t\t\t\t<textElement verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="8"/>',
        "\t\t\t\t</textElement>",
        f"\t\t\t\t<text><![CDATA[{row4}]]></text>",
        "\t\t\t</staticText>",
        "\t\t</band>",
        "\t</title>",
        "</jasperReport>",
    ]
    return "\n".join(lines) + "\n"


def _build_footer_mock_subreport(unit_name: str) -> str:
    seed_prefix = f"rodape_retrato:{unit_name}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            '<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports '
            'http://jasperreports.sourceforge.net/xsd/jasperreport.xsd" '
            'name="rodape_retrato" pageWidth="555" pageHeight="17" columnWidth="555" '
            'leftMargin="0" rightMargin="0" topMargin="0" bottomMargin="0" '
            'whenNoDataType="AllSectionsNoDetail" '
            f'uuid="{_det_uuid(seed_prefix + ":root")}">'
        ),
        '\t<parameter name="caminho_relatorio" class="java.lang.String"/>',
        "\t<title>",
        '\t\t<band height="17" splitType="Stretch">',
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="0" y="0" width="385" height="17" uuid="{_det_uuid(seed_prefix + ":left")}"/>',
        "\t\t\t\t<box>",
        '\t\t\t\t\t<topPen lineWidth="0.5" lineStyle="Solid" lineColor="#000000"/>',
        "\t\t\t\t</box>",
        '\t\t\t\t<textElement textAlignment="Left" verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="7"/>',
        "\t\t\t\t</textElement>",
        "\t\t\t\t<text><![CDATA[Salutem Ficha Studio — Pré-visualização de Validação Visual (Sem Valor Legal)]]></text>",
        "\t\t\t</staticText>",
        "\t\t\t<staticText>",
        f'\t\t\t\t<reportElement x="385" y="0" width="170" height="17" uuid="{_det_uuid(seed_prefix + ":right")}"/>',
        "\t\t\t\t<box>",
        '\t\t\t\t\t<topPen lineWidth="0.5" lineStyle="Solid" lineColor="#000000"/>',
        "\t\t\t\t</box>",
        '\t\t\t\t<textElement textAlignment="Right" verticalAlignment="Middle">',
        '\t\t\t\t\t<font size="7" isItalic="true"/>',
        "\t\t\t\t</textElement>",
        "\t\t\t\t<text><![CDATA[Ambiente Homologação Offline]]></text>",
        "\t\t\t</staticText>",
        "\t\t</band>",
        "\t</title>",
        "</jasperReport>",
    ]
    return "\n".join(lines) + "\n"


def build_offline_mock_subreports_jrxml(
    unit_name: str = "HOSPITAL SALUTEM — AMBIENTE DE VALIDAÇÃO",
    patient_info: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Gera os 4 subreports padrão Salutem em `.jrxml` puro sem dependência de tabelas SQL,
    renderizando banners de hospital, paciente e rodapé em `<title><band height="...">`:
    - `cabecalho_retrato.jrxml` (`555x45`)
    - `cabecalho_paisagem.jrxml` (`800x45`, `orientation="Landscape"`)
    - `dados_paciente.jrxml` (`555x77`)
    - `rodape_retrato.jrxml` (`555x17`)
    """
    return {
        "cabecalho_retrato.jrxml": _build_header_mock_subreport(
            report_name="cabecalho_retrato",
            width=555,
            height=45,
            is_landscape=False,
            unit_name=unit_name,
        ),
        "cabecalho_paisagem.jrxml": _build_header_mock_subreport(
            report_name="cabecalho_paisagem",
            width=800,
            height=45,
            is_landscape=True,
            unit_name=unit_name,
        ),
        "dados_paciente.jrxml": _build_patient_mock_subreport(patient_info=patient_info),
        "rodape_retrato.jrxml": _build_footer_mock_subreport(unit_name=unit_name),
    }


def _sql_escape_literal(value: str) -> str:
    """Escapa aspas simples conforme padrão SQL ANSI/PostgreSQL (`'` -> `''`)."""
    return value.replace("'", "''")


def _format_pg_typed_literal(value: Any, java_class: str) -> str:
    """Formata um valor Python como literal PostgreSQL explicitamente tipado (`::boolean`, `::varchar`, etc.)."""
    jclass = (java_class or "java.lang.String").strip()

    if jclass in _BOOLEAN_JAVA_CLASSES:
        if value is None:
            return "NULL::boolean"
        return "true::boolean" if _coerce_to_java_class(value, jclass) else "false::boolean"

    if jclass in ("java.lang.Long", "long", "java.math.BigInteger"):
        if value is None:
            return "NULL::bigint"
        return f"{int(_coerce_to_java_class(value, jclass))}::bigint"

    if jclass in ("java.lang.Integer", "int"):
        if value is None:
            return "NULL::integer"
        return f"{int(_coerce_to_java_class(value, jclass))}::integer"

    if jclass in ("java.lang.Short", "short", "java.lang.Byte"):
        if value is None:
            return "NULL::smallint"
        return f"{int(_coerce_to_java_class(value, jclass))}::smallint"

    if jclass == "java.math.BigDecimal":
        if value is None:
            return "NULL::numeric"
        return f"{float(_coerce_to_java_class(value, jclass))}::numeric"

    if jclass in _FLOAT_JAVA_CLASSES:
        if value is None:
            return "NULL::double precision"
        return f"{float(_coerce_to_java_class(value, jclass))}::double precision"

    if jclass in ("java.sql.Date", "java.util.Date"):
        if value is None:
            return "NULL::date"
        coerced = _coerce_to_java_class(value, jclass)
        return f"'{_sql_escape_literal(str(coerced))}'::date"

    if jclass == "java.sql.Timestamp":
        if value is None:
            return "NULL::timestamp"
        return f"'{_sql_escape_literal(str(value).strip())}'::timestamp"

    if jclass == "java.sql.Time":
        if value is None:
            return "NULL::time"
        return f"'{_sql_escape_literal(str(value).strip())}'::time"

    if value is None:
        return "NULL::varchar"
    return f"'{_sql_escape_literal(str(value))}'::varchar"


def _format_pg_alias(field_name: str) -> str:
    if _SIMPLE_SQL_IDENT_RE.match(field_name):
        return field_name
    escaped = field_name.replace('"', '""')
    return f'"{escaped}"'


def _build_hybrid_select_sql(
    declared_fields: list[tuple[str, str]],
    mock_row: dict[str, Any],
) -> str:
    """Constrói `SELECT <literais PostgreSQL tipados>` na ordem exata dos `<field>` declarados."""
    if not declared_fields:
        return "SELECT 1::integer AS dummy_row"

    projections: list[str] = []
    for fname, fclass in declared_fields:
        if fname in mock_row:
            raw_val = mock_row[fname]
        else:
            raw_val = False if fclass in _BOOLEAN_JAVA_CLASSES else None
        lit = _format_pg_typed_literal(raw_val, fclass)
        alias = _format_pg_alias(fname)
        projections.append(f"    {lit} AS {alias}")

    return "SELECT\n" + ",\n".join(projections)


def prepare_preview_jrxml(
    jrxml_text: str,
    *,
    mode: PreviewRewriteMode,
    mock_row: dict[str, Any],
) -> str:
    """
    Gera uma cópia efêmera do `.jrxml` preparada para pré-visualização (sem jamais mutar o original):
    - `"offline"`: substitui `<connectionExpression>` dentro de cada `<subreport>` por
      `<dataSourceExpression><![CDATA[new net.sf.jasperreports.engine.JREmptyDataSource(1)]]></dataSourceExpression>`.
    - `"db_hybrid"`: mantém `<connectionExpression>` nos `<subreport>` (para que os `.jasper` reais
      consultem o PostgreSQL) e substitui `<queryString>` do relatório principal por um `SELECT` de
      literais PostgreSQL tipados para todos os `<field>` declarados na ordem exata.
    """
    if mode not in ("offline", "db_hybrid"):
        raise ValueError(
            f"Modo de reescrita inválido '{mode}': esperado 'offline' ou 'db_hybrid'."
        )

    declared_fields = parse_jrxml_declared_fields(jrxml_text)
    cleaned = jrxml_text.lstrip("\ufeff")

    if mode == "offline":
        empty_ds_tag = (
            "<dataSourceExpression>"
            "<![CDATA[new net.sf.jasperreports.engine.JREmptyDataSource(1)]]>"
            "</dataSourceExpression>"
        )

        def _rewrite_subreport(match: re.Match[str]) -> str:
            open_tag, inner, close_tag = match.group(1), match.group(2), match.group(3)
            new_inner = _CONN_EXPR_RE.sub(lambda _: empty_ds_tag, inner)
            return f"{open_tag}{new_inner}{close_tag}"

        rewritten = _SUBREPORT_BLOCK_RE.sub(_rewrite_subreport, cleaned)
        ET.fromstring(rewritten)
        return rewritten

    # mode == "db_hybrid"
    hybrid_sql = _build_hybrid_select_sql(declared_fields, mock_row)
    new_query_block = f"<queryString>\n\t\t<![CDATA[{_safe_cdata(hybrid_sql)}]]>\n\t</queryString>"

    if _QUERY_STRING_RE.search(cleaned):
        rewritten = _QUERY_STRING_RE.sub(lambda _: new_query_block, cleaned, count=1)
    else:
        insert_anchor = re.search(
            r"(^[ \t]*<(?:field|background|title|pageHeader|columnHeader|detail)\b)",
            cleaned,
            re.MULTILINE,
        )
        if insert_anchor:
            pos = insert_anchor.start()
            rewritten = f"{cleaned[:pos]}\t{new_query_block}\n{cleaned[pos:]}"
        else:
            rewritten = cleaned.replace("</jasperReport>", f"\t{new_query_block}\n</jasperReport>", 1)

    ET.fromstring(rewritten)
    return rewritten


__all__ = [
    "PreviewRewriteMode",
    "ScenarioType",
    "VALID_PREVIEW_MODES",
    "VALID_SCENARIOS",
    "build_offline_mock_subreports_jrxml",
    "generate_fictitious_row",
    "parse_jrxml_declared_fields",
    "prepare_preview_jrxml",
]
