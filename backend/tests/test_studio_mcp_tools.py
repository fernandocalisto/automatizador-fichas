# -*- coding: utf-8 -*-
"""Testes abrangentes das ferramentas determinísticas do Studio e do servidor MCP stdio JSON-RPC 2.0."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore[no-redef]

from backend.app.db.schemas import ProjectCreate
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.jrxml.scaffolder import scaffold_salutem_jrxml
from backend.app.mcp_tools import (
    STUDIO_TOOL_DEFINITIONS,
    STUDIO_TOOL_HANDLERS,
    StudioMcpServer,
    dispatch_studio_tool,
    extract_pdf_geometry,
    get_all_mcp_tool_descriptors,
    get_all_sdk_tool_callables,
    get_mcp_tool_descriptors,
    get_sdk_tool_callables,
    render_preview_images,
    save_validated_json,
    validate_and_compile_jrxml,
)
from backend.app.mcp_tools.mcp_server import (
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    MCP_PROTOCOL_VERSION,
)
from backend.app.services.jasper_daemon import JasperDaemonError
from backend.app.services.workspace_service import ArtifactNotFoundError, WorkspaceService


def _make_pdf_bytes(page_count: int = 1) -> bytes:
    doc = fitz.open()
    for idx in range(page_count):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            fitz.Point(40, 60),
            f"FICHA CLINICA DE TESTE - PAGINA {idx + 1}",
            fontname="hebo",
            fontsize=12,
        )
        page.draw_rect(fitz.Rect(30, 210, 40, 220), color=(0, 0, 0), width=0.75)
        page.insert_text(fitz.Point(46, 218), "Hipertensao", fontname="helv", fontsize=9)
        page.draw_circle(fitz.Point(165, 215), 5.0, color=(0, 0, 0), width=0.75)
        page.insert_text(fitz.Point(175, 218), "Sim", fontname="helv", fontsize=9)
    raw = doc.tobytes()
    doc.close()
    return raw


def _sample_clinical_json() -> dict[str, Any]:
    return {
        "template": {
            "nome": "Avaliação Clínica de Enfermagem",
            "descricao": "Ficha para admissão hospitalar",
            "ativo": True,
            "layout": "ficha-clinica",
            "orientacao": "RETRATO",
            "posicao_assinatura": "RODAPE",
            "quantidade_pagina": 1,
            "importa_historico_ficha_clinica": False,
        },
        "perguntas": [
            {
                "nome": "Sinais Vitais e Triagem",
                "titulo": True,
                "respostas": [],
            },
            {
                "nome": "Pressão Arterial",
                "titulo": False,
                "respostas": [
                    {"label": "PA Sistólica", "tipo_campo": "TEXTO", "observacao": False},
                ],
            },
            {
                "nome": "Tabagista?",
                "titulo": False,
                "respostas": [
                    {"label": "Sim", "tipo_campo": "BOOLEANO_RADIO", "observacao": True},
                    {"label": "Não", "tipo_campo": "BOOLEANO_RADIO", "observacao": False},
                ],
            },
        ],
    }


class FakeJasperDaemon:
    """Daemon Jasper leve e rápido para testes unitários sem subir JVM."""

    def __init__(
        self,
        *,
        compile_ok: bool = True,
        compile_exception: Exception | None = None,
        export_ok: bool = True,
        pdf_pages: int = 1,
    ) -> None:
        self.compile_ok = compile_ok
        self.compile_exception = compile_exception
        self.export_ok = export_ok
        self.pdf_pages = pdf_pages
        self.compile_calls: list[tuple[str, str | None]] = []
        self.export_calls: list[dict[str, Any]] = []

    def compile(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        subreport_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        self.compile_calls.append((str(input_path), str(output_path) if output_path else None))
        if self.compile_exception is not None:
            raise self.compile_exception
        if not self.compile_ok:
            return {"ok": False, "status": "ERROR", "message": "Erro sintético de compilação JRXML"}
        if output_path is not None:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"FAKE_JASPER_COMPILED_BINARY")
        return {"ok": True, "status": "SUCCESS", "output": str(output_path or "")}

    def export_pdf(
        self,
        input_path: str | Path,
        output_path: str | Path | None = None,
        *,
        params: dict[str, Any] | None = None,
        mock_rows: list[dict[str, Any]] | None = None,
        subreport_dir: str | Path | None = None,
        db_url: str | None = None,
        db_user: str | None = None,
        db_pass: str | None = None,
    ) -> dict[str, Any]:
        self.export_calls.append(
            {
                "input_path": str(input_path),
                "output_path": str(output_path) if output_path else None,
                "params": dict(params or {}),
                "mock_rows": list(mock_rows) if mock_rows is not None else None,
                "subreport_dir": str(subreport_dir) if subreport_dir else None,
                "db_url": db_url,
            }
        )
        if not self.export_ok:
            return {"ok": False, "status": "ERROR", "message": "Falha sintética ao exportar PDF"}
        assert output_path is not None
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_make_pdf_bytes(page_count=self.pdf_pages))
        return {"ok": True, "status": "SUCCESS", "output": str(out), "pages": self.pdf_pages}


@pytest.fixture
def studio_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[WorkspaceService, str]:
    data_dir = tmp_path / "studio_data"
    monkeypatch.setenv("FICHA_STUDIO_DATA_DIR", str(data_dir))
    store = SQLiteStore(db_path=data_dir / "studio.db")
    ws = WorkspaceService(store=store, data_dir=data_dir)
    proj = ws.create_project(
        ProjectCreate(
            name="Avaliação Clínica Teste",
            entry_mode="pdf",
        ),
        pdf_bytes=_make_pdf_bytes(page_count=1),
    )
    return ws, proj.id


# =============================================================================
# 1. extract_pdf_geometry
# =============================================================================


def test_extract_pdf_geometry_by_path_and_by_project_id(
    studio_env: tuple[WorkspaceService, str],
    tmp_path: Path,
) -> None:
    ws, project_id = studio_env

    # Via project_id
    geo_proj = extract_pdf_geometry(project_id=project_id, workspace_service=ws)
    assert geo_proj["project_id"] == project_id
    assert geo_proj["page_count"] == 1
    assert geo_proj["orientation"] == "RETRATO"
    assert geo_proj["summary"]["checkbox_candidates"] == 1
    assert geo_proj["summary"]["radio_candidates"] == 1

    # Via pdf_path direto
    standalone_pdf = tmp_path / "avulso.pdf"
    standalone_pdf.write_bytes(_make_pdf_bytes(page_count=1))
    geo_path = extract_pdf_geometry(pdf_path=str(standalone_pdf))
    assert geo_path["page_count"] == 1
    assert "project_id" not in geo_path
    assert geo_path["summary"]["total_text_spans"] >= 3

    # Erro quando nenhum parâmetro é informado
    with pytest.raises(ValueError, match="pdf_path.*project_id"):
        extract_pdf_geometry()

    # Erro quando projeto não possui source.pdf
    empty_proj = ws.create_project(ProjectCreate(name="Sem PDF", entry_mode="pdf"))
    with pytest.raises(ArtifactNotFoundError):
        extract_pdf_geometry(project_id=empty_proj.id, workspace_service=ws)


# =============================================================================
# 2. save_validated_json
# =============================================================================


def test_save_validated_json_success_uppercase_and_sql_regen(
    studio_env: tuple[WorkspaceService, str],
) -> None:
    ws, project_id = studio_env
    payload = _sample_clinical_json()

    res = save_validated_json(
        project_id=project_id,
        json_content=payload,
        summary="Extração inicial validada",
        auto_regenerate_sql=True,
        apply_uppercase=True,
        workspace_service=ws,
    )

    assert res["ok"] is True
    assert res["project_id"] == project_id
    assert res["version_num"] == 1
    assert res["template_name"] == "AVALIAÇÃO CLÍNICA DE ENFERMAGEM"
    assert res["sections_count"] == 1
    assert res["questions_count"] == 2
    assert res["answers_count"] == 3
    assert res["warnings"] == []
    assert res["sql_insert_version"] == 1
    assert res["sql_select_version"] == 1

    latest_json = ws.get_latest_artifact(project_id, "json")
    assert latest_json.created_by == "agent"
    assert "AVALIAÇÃO CLÍNICA DE ENFERMAGEM" in latest_json.content

    # Salva segunda revisão com string JSON e aviso clínico não-bloqueante (sem regenerar SQL)
    warn_doc = _sample_clinical_json()
    warn_doc["template"]["layout"] = "layout-invalido"
    warn_doc["perguntas"][0]["respostas"] = [
        {"label": "Extra", "tipo_campo": "TEXTO"},
    ]
    res2 = save_validated_json(
        project_id=project_id,
        json_content=json.dumps(warn_doc, ensure_ascii=False),
        auto_regenerate_sql=False,
        workspace_service=ws,
    )
    assert res2["ok"] is True
    assert res2["version_num"] == 2
    assert res2["sql_insert_version"] is None
    assert res2["sql_select_version"] is None
    warning_codes = {w["code"] for w in res2["warnings"]}
    assert "TEMPLATE_LAYOUT_INVALID" in warning_codes
    assert "TITLE_WITH_ANSWERS" in warning_codes


def test_save_validated_json_rejects_invalid_json(
    studio_env: tuple[WorkspaceService, str],
) -> None:
    ws, project_id = studio_env

    with pytest.raises(ValueError):
        save_validated_json(project_id, "{json quebrado", workspace_service=ws)

    with pytest.raises(ValueError, match="template"):
        save_validated_json(project_id, {"perguntas": []}, workspace_service=ws)

    # Nenhuma revisão deve ter sido persistida
    assert ws.list_revisions(project_id, artifact_type="json") == []


# =============================================================================
# 3. validate_and_compile_jrxml
# =============================================================================


def test_validate_and_compile_jrxml_valid_and_stored_fallback(
    studio_env: tuple[WorkspaceService, str],
) -> None:
    ws, project_id = studio_env
    save_validated_json(project_id, _sample_clinical_json(), workspace_service=ws)
    latest_json = json.loads(ws.get_latest_artifact(project_id, "json").content)
    valid_jrxml = scaffold_salutem_jrxml(latest_json)
    daemon = FakeJasperDaemon(compile_ok=True)

    res = validate_and_compile_jrxml(
        project_id=project_id,
        jrxml_content=valid_jrxml,
        save_artifact=True,
        summary="JRXML Fase 4 validado",
        workspace_service=ws,
        jasper_daemon=daemon,
    )

    assert res["ok"] is True
    assert res["project_id"] == project_id
    assert res["compiled"] is True
    assert res["lint"]["is_valid"] is True
    assert res["lint"]["errors"] == []
    assert res["saved_version"] == 1
    assert res["daemon"]["status"] == "SUCCESS"
    assert len(daemon.compile_calls) == 1

    # Recarrega última revisão quando jrxml_content=None (não duplica revisão)
    res_stored = validate_and_compile_jrxml(
        project_id=project_id,
        jrxml_content=None,
        save_artifact=True,
        workspace_service=ws,
        jasper_daemon=daemon,
    )
    assert res_stored["ok"] is True
    assert res_stored["compiled"] is True
    assert res_stored["saved_version"] is None
    assert len(ws.list_revisions(project_id, artifact_type="jrxml")) == 1


def test_validate_and_compile_jrxml_lint_errors_malformed_and_daemon_failure(
    studio_env: tuple[WorkspaceService, str],
) -> None:
    ws, project_id = studio_env

    # 1. XML bem-formado com erros de lint Fase 4 (sem isBlankWhenNull e == true em printWhen)
    bad_lint_xml = """<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"
    name="ficha_erro_lint" pageWidth="595" pageHeight="842" columnWidth="555"
    leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20"
    uuid="11111111-2222-3333-4444-555555555555">
    <field name="sim" class="java.lang.Boolean"/>
    <field name="pa_sistolica" class="java.lang.String"/>
    <detail>
        <band height="40">
            <textField>
                <reportElement x="0" y="0" width="200" height="20" uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee">
                    <printWhenExpression><![CDATA[$F{sim} == true]]></printWhenExpression>
                </reportElement>
                <textFieldExpression><![CDATA["PA: " + $F{pa_sistolica}]]></textFieldExpression>
            </textField>
        </band>
    </detail>
</jasperReport>"""
    daemon = FakeJasperDaemon(compile_ok=True)
    res_lint = validate_and_compile_jrxml(
        project_id=project_id,
        jrxml_content=bad_lint_xml,
        save_artifact=True,
        workspace_service=ws,
        jasper_daemon=daemon,
    )
    assert res_lint["ok"] is False
    assert res_lint["compiled"] is True
    assert res_lint["lint"]["is_valid"] is False
    codes = {err["code"] for err in res_lint["lint"]["errors"]}
    assert "TEXTFIELD_MISSING_BLANK_WHEN_NULL" in codes
    assert "UNSAFE_PRINT_WHEN_BOOLEAN" in codes
    assert "UNSAFE_FIELD_CONCATENATION" in codes
    # XML era bem-formado -> revisão foi salva para iteração do agente
    assert res_lint["saved_version"] == 1

    # 2. XML mal-formado -> NÃO salva revisão e pula daemon
    res_malformed = validate_and_compile_jrxml(
        project_id=project_id,
        jrxml_content="<jasperReport><broken>",
        save_artifact=True,
        workspace_service=ws,
        jasper_daemon=daemon,
    )
    assert res_malformed["ok"] is False
    assert res_malformed["compiled"] is False
    assert res_malformed["saved_version"] is None
    assert res_malformed["daemon"]["skipped"] is True
    assert res_malformed["lint"]["errors"][0]["code"] == "XML_PARSE_ERROR"
    assert len(ws.list_revisions(project_id, artifact_type="jrxml")) == 1

    # 3. Falha no JasperDaemon (exceção JasperDaemonError)
    failing_daemon = FakeJasperDaemon(
        compile_exception=JasperDaemonError(
            "Erro de compilação Groovy/Java", error_type="JR_COMPILE_ERROR"
        )
    )
    save_validated_json(project_id, _sample_clinical_json(), workspace_service=ws)
    latest_json = json.loads(ws.get_latest_artifact(project_id, "json").content)
    valid_jrxml = scaffold_salutem_jrxml(latest_json)

    res_fail = validate_and_compile_jrxml(
        project_id=project_id,
        jrxml_content=valid_jrxml,
        save_artifact=False,
        workspace_service=ws,
        jasper_daemon=failing_daemon,
    )
    assert res_fail["ok"] is False
    assert res_fail["compiled"] is False
    assert res_fail["saved_version"] is None
    assert res_fail["daemon"]["error_type"] == "JR_COMPILE_ERROR"


# =============================================================================
# 4. render_preview_images
# =============================================================================


def test_render_preview_images_offline_single_and_multipage(
    studio_env: tuple[WorkspaceService, str],
) -> None:
    ws, project_id = studio_env
    save_validated_json(project_id, _sample_clinical_json(), workspace_service=ws)
    latest_json = json.loads(ws.get_latest_artifact(project_id, "json").content)
    valid_jrxml = scaffold_salutem_jrxml(latest_json)
    ws.save_artifact(project_id, "jrxml", valid_jrxml, created_by="agent")

    daemon = FakeJasperDaemon(compile_ok=True, export_ok=True, pdf_pages=1)
    res = render_preview_images(
        project_id=project_id,
        scenario="full",
        mode="offline",
        dpi=120,
        workspace_service=ws,
        jasper_daemon=daemon,
    )

    assert res["ok"] is True
    assert res["project_id"] == project_id
    assert res["scenario"] == "full"
    assert res["effective_mode"] == "offline"
    assert res["page_count"] == 1
    assert res["single_page_ok"] is True
    assert Path(res["pdf_path"]).is_file()
    assert len(res["png_paths"]) == 1
    assert Path(res["png_paths"][0]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert res["page_urls"] == [
        f"/api/projects/{project_id}/jasper/preview/pages/1?scenario=full"
    ]
    # 4 subreports offline mock foram compilados na primeira execução
    assert len(daemon.compile_calls) == 4
    assert len(daemon.export_calls) == 1
    assert daemon.export_calls[0]["mock_rows"] is not None

    # Segunda chamada com o mesmo daemon reutiliza subreports compilados (cache)
    res_stress = render_preview_images(
        project_id=project_id,
        scenario="stress",
        mode="auto",
        dpi=100,
        inline_jrxml=valid_jrxml,
        workspace_service=ws,
        jasper_daemon=daemon,
    )
    assert res_stress["ok"] is True
    assert res_stress["effective_mode"] == "offline"
    assert len(daemon.compile_calls) == 4  # Nenhuma recompilação extra dos mocks!

    # Cenário multi-página -> single_page_ok=False
    multi_daemon = FakeJasperDaemon(compile_ok=True, export_ok=True, pdf_pages=2)
    res_multi = render_preview_images(
        project_id=project_id,
        scenario="blank",
        mode="offline",
        dpi=96,
        workspace_service=ws,
        jasper_daemon=multi_daemon,
    )
    assert res_multi["page_count"] == 2
    assert res_multi["single_page_ok"] is False
    assert len(res_multi["png_paths"]) == 2
    assert len(res_multi["page_urls"]) == 2

    # Validação de parâmetros inválidos
    with pytest.raises(ValueError, match="Cenário inválido"):
        render_preview_images(project_id, scenario="invalido", workspace_service=ws, jasper_daemon=daemon)


# =============================================================================
# 5. Registro Unificado e Retrocompatibilidade
# =============================================================================


def test_unified_registry_contains_all_8_tools_and_preserves_legacy_api() -> None:
    all_names = [d["name"] for d in STUDIO_TOOL_DEFINITIONS]
    assert all_names == [
        "inspect_clinical_pdf",
        "render_pdf_preview_pages",
        "crop_pdf_feedback_region",
        "get_salutem_skill",
        "extract_pdf_geometry",
        "save_validated_json",
        "validate_and_compile_jrxml",
        "render_preview_images",
        "list_db_tables",
        "describe_db_table",
        "preview_db_select",
    ]
    assert set(STUDIO_TOOL_HANDLERS.keys()) == set(all_names)
    assert len(get_all_mcp_tool_descriptors()) == 11
    assert len(get_all_sdk_tool_callables()) == 11
    assert len(get_mcp_tool_descriptors(include_artifact_tools=True)) == 11
    assert len(get_sdk_tool_callables(include_artifact_tools=True)) == 11
    # Retrocompatibilidade com Fase 1
    assert len(get_mcp_tool_descriptors()) == 4
    assert len(get_sdk_tool_callables()) == 4

    for desc in STUDIO_TOOL_DEFINITIONS:
        schema = desc["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)

    with pytest.raises(KeyError):
        dispatch_studio_tool("ferramenta_inexistente", {})


# =============================================================================
# 6. Servidor MCP Stdio JSON-RPC 2.0 (`StudioMcpServer`)
# =============================================================================


def test_mcp_server_jsonrpc_protocol_and_tool_calls(
    studio_env: tuple[WorkspaceService, str],
) -> None:
    ws, project_id = studio_env
    daemon = FakeJasperDaemon(compile_ok=True, export_ok=True, pdf_pages=1)
    server = StudioMcpServer(workspace_service=ws, jasper_daemon=daemon)

    # 1. initialize
    init_resp = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init_resp is not None
    assert init_resp["id"] == 1
    assert init_resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert init_resp["result"]["capabilities"] == {"tools": {}}
    assert init_resp["result"]["serverInfo"]["name"] == "salutem-ficha-studio-mcp"

    # 2. notifications/initialized -> sem resposta
    notif_resp = server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notif_resp is None
    assert server.initialized is True

    # 3. ping
    ping_resp = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping_resp == {"jsonrpc": "2.0", "id": 2, "result": {}}

    # 4. tools/list retorna todas as 11 ferramentas (8 v1.0 + 3 DB READ ONLY v1.1)
    list_resp = server.handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert list_resp is not None
    tool_names = [t["name"] for t in list_resp["result"]["tools"]]
    assert len(tool_names) == 11
    assert "save_validated_json" in tool_names
    assert "validate_and_compile_jrxml" in tool_names
    assert "render_preview_images" in tool_names
    assert "list_db_tables" in tool_names
    assert "describe_db_table" in tool_names
    assert "preview_db_select" in tool_names

    # 5. tools/call -> extract_pdf_geometry (via project_id)
    geo_call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "extract_pdf_geometry", "arguments": {"project_id": project_id}},
        }
    )
    assert geo_call is not None
    assert geo_call["result"]["isError"] is False
    geo_payload = json.loads(geo_call["result"]["content"][0]["text"])
    assert geo_payload["page_count"] == 1
    assert geo_payload["project_id"] == project_id

    # 6. tools/call -> save_validated_json
    save_call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "save_validated_json",
                "arguments": {
                    "project_id": project_id,
                    "json_content": _sample_clinical_json(),
                },
            },
        }
    )
    assert save_call is not None
    assert save_call["result"]["isError"] is False
    save_payload = json.loads(save_call["result"]["content"][0]["text"])
    assert save_payload["ok"] is True
    assert save_payload["version_num"] == 1

    # 7. tools/call -> validate_and_compile_jrxml + render_preview_images
    latest_json = json.loads(ws.get_latest_artifact(project_id, "json").content)
    valid_jrxml = scaffold_salutem_jrxml(latest_json)

    compile_call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "validate_and_compile_jrxml",
                "arguments": {"project_id": project_id, "jrxml_content": valid_jrxml},
            },
        }
    )
    assert compile_call is not None
    assert compile_call["result"]["isError"] is False
    compile_payload = json.loads(compile_call["result"]["content"][0]["text"])
    assert compile_payload["ok"] is True
    assert compile_payload["compiled"] is True

    preview_call = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "render_preview_images",
                "arguments": {"project_id": project_id, "scenario": "full", "mode": "offline", "dpi": 100},
            },
        }
    )
    assert preview_call is not None
    assert preview_call["result"]["isError"] is False
    preview_payload = json.loads(preview_call["result"]["content"][0]["text"])
    assert preview_payload["ok"] is True
    assert preview_payload["single_page_ok"] is True

    # 8. tools/call erro -> isError=True (ferramenta desconhecida e JSON inválido)
    err_unknown = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "nao_existe", "arguments": {}},
        }
    )
    assert err_unknown is not None
    assert err_unknown["result"]["isError"] is True
    err_body = json.loads(err_unknown["result"]["content"][0]["text"])
    assert err_body["ok"] is False
    assert err_body["error_type"] == "KeyError"

    err_json = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "save_validated_json",
                "arguments": {"project_id": project_id, "json_content": "{invalido"},
            },
        }
    )
    assert err_json is not None
    assert err_json["result"]["isError"] is True

    # 9. Erros de protocolo JSON-RPC 2.0
    parse_err = json.loads(server.handle_raw_line("{not-json") or "{}")
    assert parse_err["error"]["code"] == JSONRPC_PARSE_ERROR

    invalid_req = server.handle_message({"jsonrpc": "1.0", "id": 10, "method": "ping"})
    assert invalid_req is not None
    assert invalid_req["error"]["code"] == JSONRPC_INVALID_REQUEST

    method_nf = server.handle_message({"jsonrpc": "2.0", "id": 11, "method": "unknown/method"})
    assert method_nf is not None
    assert method_nf["error"]["code"] == JSONRPC_METHOD_NOT_FOUND

    invalid_params = server.handle_message({"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {}})
    assert invalid_params is not None
    assert invalid_params["error"]["code"] == JSONRPC_INVALID_PARAMS


def test_mcp_server_stdio_loop_and_cli_module_execution() -> None:
    # Teste em memória com serve_stdio (StringIO)
    in_lines = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            "",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}),
        ]
    ) + "\n"
    stdin_buf = io.StringIO(in_lines)
    stdout_buf = io.StringIO()

    StudioMcpServer().serve_stdio(stdin=stdin_buf, stdout=stdout_buf)
    responses = [json.loads(line) for line in stdout_buf.getvalue().splitlines() if line.strip()]
    assert [r["id"] for r in responses] == [1, 2, 3]
    assert len(responses[2]["result"]["tools"]) == 11

    # Smoke test real via `python -m backend.app.mcp_tools.mcp_server`
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root / 'backend'}{os.pathsep}{repo_root}"
    proc = subprocess.run(
        [sys.executable, "-m", "backend.app.mcp_tools.mcp_server"],
        input=in_lines,
        text=True,
        capture_output=True,
        cwd=str(repo_root),
        env=env,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"
    cli_responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [r["id"] for r in cli_responses] == [1, 2, 3]
    assert cli_responses[0]["result"]["capabilities"] == {"tools": {}}
    assert len(cli_responses[2]["result"]["tools"]) == 11
