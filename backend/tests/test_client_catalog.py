# -*- coding: utf-8 -*-
"""Comprehensive unit and FastAPI tests for Clients Hub & Local Portal Sync (Block 4)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from keyring.errors import KeyringError

from backend.app.api.clients import router as clients_router
from backend.app.api.credentials import router as credentials_router
from backend.app.db.sqlite_store import SQLiteStore
from backend.app.services import secret_vault as secret_vault_module
from backend.app.services.client_catalog_service import (
    ClientCatalogService,
    ClientSystemCreate,
    ClientSystemUpdate,
    ClientUnitCreate,
    ClientUnitUpdate,
    UnitCatalogProvider,
    infer_environment,
    infer_system_type,
)
from backend.app.services.default_credentials_service import (
    DefaultCredentialsService,
    DefaultCredentialUpdate,
)
from backend.app.services.postgres_service import DbProfileUpdate, PostgresService
from backend.app.services.secret_vault import SecretVaultService


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Create isolated SQLite DB, AES-256-GCM fallback vault, services, and FastAPI TestClient."""

    def _fail_keyring(*_args: Any, **_kwargs: Any) -> Any:
        raise KeyringError("headless test keyring disabled")

    monkeypatch.setattr(secret_vault_module.keyring, "set_password", _fail_keyring)
    monkeypatch.setattr(secret_vault_module.keyring, "get_password", _fail_keyring)
    monkeypatch.setattr(secret_vault_module.keyring, "delete_password", _fail_keyring)
    monkeypatch.setenv("FICHA_STUDIO_VAULT_KEY", "test-master-key-for-clients-hub-99887766")

    db_path = tmp_path / "studio_test.db"
    vault_path = tmp_path / ".vault.json"

    store = SQLiteStore(db_path=db_path)
    store.init_db()
    vault = SecretVaultService(vault_path=vault_path)
    defaults_svc = DefaultCredentialsService(store=store, vault=vault)
    pg_svc = PostgresService(
        store=store,
        vault=vault,
        default_credentials_service=defaults_svc,
    )
    catalog_svc = ClientCatalogService(
        store=store,
        vault=vault,
        postgres_service=pg_svc,
        default_credentials_service=defaults_svc,
    )

    app = FastAPI()
    app.state.store = store
    app.state.secret_vault = vault
    app.state.default_credentials_service = defaults_svc
    app.state.postgres_service = pg_svc
    app.state.client_catalog_service = catalog_svc
    app.include_router(clients_router)
    app.include_router(credentials_router)

    return {
        "db_path": db_path,
        "vault_path": vault_path,
        "store": store,
        "vault": vault,
        "defaults": defaults_svc,
        "postgres": pg_svc,
        "catalog": catalog_svc,
        "client": TestClient(app),
    }


def _read_all_sqlite_text(db_path: Path) -> str:
    """Dump all rows across all tables in SQLite to verify zero plaintext secrets are persisted."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        chunks: list[str] = []
        for tbl in tables:
            rows = conn.execute(f"SELECT * FROM {tbl}").fetchall()
            chunks.append(repr(rows))
        return "\n".join(chunks)
    finally:
        conn.close()


# =============================================================================
# 1. Inference & Provider Protocol Tests
# =============================================================================


def test_inference_helpers() -> None:
    assert infer_system_type("Salutem Ambulatorial") == "ambulatorial"
    assert infer_system_type("Hospitalar PRD") == "hospitalar"
    assert infer_system_type("Painel de Chamadas") == "painel"
    assert infer_system_type("Portal de Compras") == "compras"
    assert infer_system_type("Monitoramento Zabbix") == "outro"

    assert infer_environment("Ambulatorial Homologação") == "HML"
    assert infer_environment("BD HML Hospitalar") == "HML"
    assert infer_environment("Ambiente Teste") == "HML"
    assert infer_environment("Servidor DEV") == "DEV"
    assert infer_environment("Ambulatorial Produção") == "PRD"
    assert infer_environment("Hospitalar") == "PRD"


def test_providers_implement_protocol(isolated_env: dict[str, Any]) -> None:
    svc: ClientCatalogService = isolated_env["catalog"]
    for provider in svc._providers.values():
        assert isinstance(provider, UnitCatalogProvider)


# =============================================================================
# 2. Manual Multi-System CRUD Tests
# =============================================================================


def test_manual_client_and_multisystem_crud(isolated_env: dict[str, Any]) -> None:
    svc: ClientCatalogService = isolated_env["catalog"]

    unit = svc.create_client(
        ClientUnitCreate(
            external_id="401",
            unit_code="UNIT-ALPHA",
            name="Unidade Alpha Exemplo",
            hosting="Cloud",
            license_status="Licença Ativa",
            notes="Cliente sintético de teste",
            tags=["prioridade", "regiao-sul"],
            integrations=["RNDS", "e-SUS"],
        )
    )
    assert unit.unit_code == "UNIT-ALPHA"
    assert unit.name == "Unidade Alpha Exemplo"
    assert unit.tags == ["prioridade", "regiao-sul"]
    assert unit.integrations == ["RNDS", "e-SUS"]
    assert unit.systems == []

    sys_amb = svc.upsert_system(
        unit.id,
        ClientSystemCreate(
            system_key="ambulatorial_prd",
            label="Ambulatorial PRD",
            system_type="ambulatorial",
            environment="PRD",
            system_url="https://amb.alpha.example.local",
            version_label="4.12.3",
        ),
    )
    sys_hosp = svc.upsert_system(
        unit.id,
        ClientSystemCreate(
            system_key="hospitalar_hml",
            label="Hospitalar Homologação",
            system_type="hospitalar",
            environment="HML",
            system_url="https://hosp-hml.alpha.example.local",
            version_label="3.9.0",
        ),
    )

    loaded = svc.get_client(unit.id)
    assert len(loaded.systems) == 2

    # Filters
    assert len(svc.list_clients(search="alpha")) == 1
    assert len(svc.list_clients(search="regiao-sul")) == 1
    assert len(svc.list_clients(system_type="hospitalar")) == 1
    assert len(svc.list_clients(system_type="compras")) == 0
    assert len(svc.list_clients(environment="HML")) == 1
    assert len(svc.list_clients(environment="DEV")) == 0

    # Update client & system
    updated_unit = svc.update_client(
        unit.id,
        ClientUnitUpdate(hosting="On-Premise", notes="Atualizado"),
    )
    assert updated_unit.hosting == "On-Premise"
    assert updated_unit.notes == "Atualizado"

    updated_sys = svc.update_system(
        unit.id,
        sys_amb.id,
        ClientSystemUpdate(version_label="4.13.0"),
    )
    assert updated_sys.version_label == "4.13.0"

    # Delete one system, then delete whole client (cascade)
    assert svc.delete_system(unit.id, sys_hosp.id) is True
    assert len(svc.get_client(unit.id).systems) == 1
    assert svc.delete_client(unit.id) is True
    assert svc.list_clients() == []


# =============================================================================
# 3. Portal HTML Parser Tests (Synthetic `.management-client-card`)
# =============================================================================


SYNTHETIC_PORTAL_HTML = """
<!doctype html>
<html>
<body>
  <div class="management-client-card" data-gestao-card-title="Unidade Beta Exemplo">
    <div class="card-header">
      <span class="badge">ID: 77</span>
      <span class="badge">Cloud</span>
      <span class="badge">Licença Ativa</span>
      <span class="tag">saude-publica</span>
    </div>
    <div class="versions">
      <h4>Versões do Sistema:</h4>
      <ul>
        <li>Ambulatorial: 4.14.2</li>
        <li>Hospitalar: 3.11.0</li>
      </ul>
    </div>
    <div class="tech-access">
      <h4>Acessos Técnicos</h4>
      <div class="section-dns">
        <strong>DNS:</strong>
        <ul>
          <li>Ambulatorial: <a href="https://amb.beta.example.local">https://amb.beta.example.local</a></li>
          <li>Hospitalar: <a href="https://hosp.beta.example.local">https://hosp.beta.example.local</a></li>
          <li>Ambulatorial Homologação: <a href="https://amb-hml.beta.example.local">https://amb-hml.beta.example.local</a></li>
        </ul>
      </div>
      <div class="section-bd">
        <strong>BD:</strong>
        <ul>
          <li>BD Ambulatorial: 10.20.30.10:5432</li>
          <li>BD Hospitalar: 10.20.30.11:5432/hosp_beta</li>
          <li>BD Homologação Ambulatorial: 10.20.30.12:5433</li>
        </ul>
      </div>
      <div class="section-ssh">
        <strong>SSH:</strong>
        <ul>
          <li data-password="SshSyntheticSecret#1">SSH Ambulatorial: appuser@10.20.30.10:22</li>
          <li>SSH Homologação Ambulatorial: appuser@10.20.30.12:2222 senha=HmlSyntheticSecret#2</li>
        </ul>
      </div>
      <div class="section-jasper">
        <strong>Jasper:</strong>
        <ul>
          <li>Jasper Hospitalar: <a href="https://jasper.beta.example.local/jasperserver">https://jasper.beta.example.local/jasperserver</a></li>
        </ul>
      </div>
      <div class="section-integrations">
        <strong>Integrações:</strong>
        <p>RNDS, Laboratorio Regional, CNS</p>
      </div>
    </div>
  </div>
</body>
</html>
"""


def test_portal_html_parser_correlates_multisystem_and_redacts_preview(
    isolated_env: dict[str, Any],
) -> None:
    svc: ClientCatalogService = isolated_env["catalog"]

    preview = svc.preview_sync(SYNTHETIC_PORTAL_HTML, source_format="auto")
    assert preview.ok is True
    assert preview.total_parsed == 1
    assert preview.to_create == 1
    assert preview.to_update == 0
    assert preview.unchanged == 0

    # SECURITY: preview response must NEVER echo plaintext SSH passwords!
    preview_json = json.dumps(preview.model_dump(mode="json"))
    assert "SshSyntheticSecret#1" not in preview_json
    assert "HmlSyntheticSecret#2" not in preview_json

    unit_dict = preview.normalized_units[0]
    assert unit_dict["name"] == "Unidade Beta Exemplo"
    assert unit_dict["external_id"] == "77"
    assert unit_dict["hosting"] == "Cloud"
    assert unit_dict["license_status"] == "Licença Ativa"
    assert set(unit_dict["integrations"]) == {"RNDS", "Laboratorio Regional", "CNS"}

    systems = {s["system_key"]: s for s in unit_dict["systems"]}
    assert "ambulatorial_prd" in systems
    assert "hospitalar_prd" in systems
    assert "ambulatorial_hml" in systems

    amb_prd = systems["ambulatorial_prd"]
    assert amb_prd["environment"] == "PRD"
    assert amb_prd["system_url"] == "https://amb.beta.example.local"
    assert amb_prd["version_label"] == "4.14.2"
    assert amb_prd["postgres"]["host"] == "10.20.30.10"
    assert amb_prd["postgres"]["port"] == 5432
    assert amb_prd["sftp"]["host"] == "10.20.30.10"
    assert amb_prd["sftp"]["user"] == "appuser"
    assert amb_prd["metadata"]["has_ssh_password_in_source"] is True

    hosp_prd = systems["hospitalar_prd"]
    assert hosp_prd["environment"] == "PRD"
    assert hosp_prd["version_label"] == "3.11.0"
    assert hosp_prd["postgres"]["host"] == "10.20.30.11"
    assert hosp_prd["postgres"]["dbname"] == "hosp_beta"
    assert hosp_prd["jasperserver"]["base_url"] == "https://jasper.beta.example.local/jasperserver"

    amb_hml = systems["ambulatorial_hml"]
    assert amb_hml["environment"] == "HML"
    assert amb_hml["postgres"]["host"] == "10.20.30.12"
    assert amb_hml["postgres"]["port"] == 5433
    assert amb_hml["sftp"]["port"] == 2222


# =============================================================================
# 4. Portal JSON Parser Tests
# =============================================================================


def test_portal_json_parser_handles_nested_management_data(
    isolated_env: dict[str, Any],
) -> None:
    svc: ClientCatalogService = isolated_env["catalog"]

    raw_portal_json = {
        "clients": [
            {
                "id": 901,
                "sigla": "GAMMA",
                "nome": "Unidade Gamma Exemplo",
                "hospedagem": "On-Premise",
                "licenca": "Ativa",
                "versoes": {"Ambulatorial": "4.15.0", "Painel": "2.1.0"},
                "acessos_tecnicos": {
                    "dns": [
                        {"nome": "Ambulatorial", "url": "https://amb.gamma.example.local"},
                        {"nome": "Painel Chamadas", "url": "https://painel.gamma.example.local"},
                    ],
                    "bancos": [
                        {"nome": "BD Ambulatorial", "host": "10.30.0.5", "porta": 5432},
                    ],
                    "ssh": [
                        {"nome": "SSH Ambulatorial", "host": "10.30.0.5", "porta": 22, "usuario": "ops_demo"},
                    ],
                    "jasper": [
                        {"nome": "Jasper", "url": "https://jasper.gamma.example.local/jasperserver"},
                    ],
                    "integracoes": ["TISS", "RNDS"],
                },
            }
        ]
    }

    preview = svc.preview_sync(raw_portal_json, source_format="auto")
    assert preview.total_parsed == 1
    assert preview.to_create == 1
    unit = preview.normalized_units[0]
    assert unit["unit_code"] == "GAMMA"
    assert unit["hosting"] == "On-Premise"
    assert len(unit["systems"]) == 2
    types = {s["system_type"] for s in unit["systems"]}
    assert types == {"ambulatorial", "painel"}


# =============================================================================
# 5. Apply Sync Idempotency, PRD Read-Only, SSH Passwords Vault-Only & Preservation
# =============================================================================


def test_sync_apply_idempotency_prd_readonly_and_ssh_password_security(
    isolated_env: dict[str, Any],
) -> None:
    svc: ClientCatalogService = isolated_env["catalog"]
    defaults: DefaultCredentialsService = isolated_env["defaults"]
    pg_svc: PostgresService = isolated_env["postgres"]
    vault: SecretVaultService = isolated_env["vault"]
    db_path: Path = isolated_env["db_path"]

    # Configure local default DB names & SFTP remote dir
    defaults.update_default(
        "postgres",
        DefaultCredentialUpdate(
            username="default_pg_user",
            password="DefaultPgPassword#99",
            default_dbname_ambulatorial="salutem_amb_default",
            default_dbname_hospitalar="salutem_hosp_default",
        ),
    )
    defaults.update_default(
        "sftp",
        DefaultCredentialUpdate(
            username="default_ssh_user",
            default_remote_base_dir="/opt/reports/forms",
        ),
    )

    # First apply with import_ssh_passwords=False (default safe mode)
    catalog, _ = svc.parse_payload(SYNTHETIC_PORTAL_HTML, source_format="portal_html")
    res1 = svc.apply_sync(catalog.units, import_ssh_passwords=False)
    assert res1.ok is True
    assert res1.created_units == 1
    assert res1.updated_units == 0
    assert res1.created_systems == 3
    assert res1.created_profiles == {"postgres": 3, "sftp": 2, "jasperserver": 1}

    # Verify PRD profiles are ALWAYS read_only=True, default credential_mode, and linked_db_profile_id set
    units = svc.list_clients()
    assert len(units) == 1
    systems = {s.system_key: s for s in units[0].systems}

    amb_prd_pg = pg_svc.get_profile(systems["ambulatorial_prd"].db_profile_id or "")
    assert amb_prd_pg.environment == "PRD"
    assert amb_prd_pg.read_only is True
    assert amb_prd_pg.credential_mode == "default"
    assert amb_prd_pg.dbname == "salutem_amb_default"

    amb_hml_pg = pg_svc.get_profile(systems["ambulatorial_hml"].db_profile_id or "")
    assert amb_hml_pg.environment == "HML"
    assert amb_hml_pg.read_only is False

    # Inspect sftp_profiles and jasperserver_profiles directly in SQLite
    with isolated_env["store"].connection() as conn:
        sftp_prd = conn.execute(
            "SELECT * FROM sftp_profiles WHERE id = ?",
            (systems["ambulatorial_prd"].sftp_profile_id,),
        ).fetchone()
        assert sftp_prd["credential_mode"] == "default"
        assert int(sftp_prd["read_only"]) == 1
        assert sftp_prd["remote_base_dir"] == "/opt/reports/forms"
        assert sftp_prd["linked_db_profile_id"] == systems["ambulatorial_prd"].db_profile_id
        # No password imported into vault when import_ssh_passwords=False
        assert vault.get_secret(f"sftp_password:{sftp_prd['id']}") is None

        js_hosp = conn.execute(
            "SELECT * FROM jasperserver_profiles WHERE id = ?",
            (systems["hospitalar_prd"].jasperserver_profile_id,),
        ).fetchone()
        assert js_hosp["credential_mode"] == "default"
        assert int(js_hosp["read_only"]) == 1
        assert js_hosp["linked_db_profile_id"] == systems["hospitalar_prd"].db_profile_id

    # Second preview of identical payload MUST report unchanged
    preview2 = svc.preview_sync(SYNTHETIC_PORTAL_HTML, source_format="portal_html")
    assert preview2.to_create == 0
    assert preview2.to_update == 0
    assert preview2.unchanged == 1

    # User customizes dbname and sets custom PG credentials on amb_prd_pg
    pg_svc.update_profile(
        amb_prd_pg.id,
        DbProfileUpdate(
            dbname="custom_user_dbname",
            credential_mode="custom",
            user="custom_pg_user",
            password="CustomPgUserSecret#1",
        ),
    )

    # Re-sync with import_ssh_passwords=True
    res2 = svc.apply_sync(catalog.units, import_ssh_passwords=True)
    assert res2.created_units == 0
    assert res2.updated_units == 1
    assert res2.created_systems == 0
    assert res2.updated_systems == 3
    assert res2.created_profiles == {"postgres": 0, "sftp": 0, "jasperserver": 0}

    # Verify custom PG dbname and custom password were PRESERVED
    reloaded_pg = pg_svc.get_profile(amb_prd_pg.id)
    assert reloaded_pg.dbname == "custom_user_dbname"
    assert reloaded_pg.credential_mode == "custom"
    assert reloaded_pg.user == "custom_pg_user"
    assert vault.get_secret(f"db_profile:{amb_prd_pg.id}") == "CustomPgUserSecret#1"

    # Verify SSH password was stored ONLY in SecretVault (upgraded from default -> custom)
    sftp_prd_id = systems["ambulatorial_prd"].sftp_profile_id
    assert vault.get_secret(f"sftp_password:{sftp_prd_id}") == "SshSyntheticSecret#1"

    # Now user rotates SFTP custom password manually; a subsequent re-sync MUST NOT overwrite it!
    vault.set_secret(f"sftp_password:{sftp_prd_id}", "UserRotatedSshSecret#777")
    svc.apply_sync(catalog.units, import_ssh_passwords=True)
    assert vault.get_secret(f"sftp_password:{sftp_prd_id}") == "UserRotatedSshSecret#777"

    # CRITICAL SECURITY CHECK: zero plaintext passwords anywhere in SQLite file!
    sqlite_dump = _read_all_sqlite_text(db_path)
    for secret in (
        "DefaultPgPassword#99",
        "CustomPgUserSecret#1",
        "SshSyntheticSecret#1",
        "HmlSyntheticSecret#2",
        "UserRotatedSshSecret#777",
    ):
        assert secret not in sqlite_dump


# =============================================================================
# 6. FastAPI Router End-to-End Tests & Portal Config Security
# =============================================================================


def test_clients_api_endpoints_and_portal_config(isolated_env: dict[str, Any]) -> None:
    client: TestClient = isolated_env["client"]

    # Default portal URL MUST be empty string and snippet must contain no hardcoded domains
    r_snip = client.get("/api/clients/sync/snippet")
    assert r_snip.status_code == 200
    snip_data = r_snip.json()
    assert snip_data["management_portal_url"] == ""
    assert "/api/management/data" in snip_data["console_snippet"]
    assert ".management-client-card" in snip_data["console_snippet"]
    assert snip_data["bookmarklet"].startswith("javascript:")
    assert "http://" not in snip_data["console_snippet"]
    assert "https://" not in snip_data["console_snippet"]

    # Reject invalid URL scheme
    r_bad = client.put("/api/clients/sync/config", json={"management_portal_url": "ftp://invalid.local"})
    assert r_bad.status_code == 400

    # Save valid local portal URL
    r_cfg = client.put(
        "/api/clients/sync/config",
        json={"management_portal_url": "https://portal.exemplo.local/gestao"},
    )
    assert r_cfg.status_code == 200
    assert r_cfg.json()["management_portal_url"] == "https://portal.exemplo.local/gestao"
    assert client.get("/api/clients/sync/snippet").json()["management_portal_url"] == "https://portal.exemplo.local/gestao"

    # Preview normalized_json via HTTP
    normalized_payload = {
        "units": [
            {
                "unit_code": "DELTA-01",
                "name": "Unidade Delta Exemplo",
                "hosting": "Cloud",
                "license_status": "Ativa",
                "tags": ["piloto"],
                "systems": [
                    {
                        "system_key": "ambulatorial_prd",
                        "label": "Ambulatorial PRD",
                        "system_type": "ambulatorial",
                        "environment": "PRD",
                        "system_url": "https://delta.example.local",
                        "version_label": "4.16.0",
                        "postgres": {"host": "10.50.0.10", "port": 5432},
                    }
                ],
            }
        ]
    }
    r_prev = client.post(
        "/api/clients/sync/preview",
        json={"raw_payload": normalized_payload, "source_format": "normalized_json"},
    )
    assert r_prev.status_code == 200
    prev_body = r_prev.json()
    assert prev_body["to_create"] == 1
    assert prev_body["items"][0]["action"] == "create"

    # Apply via HTTP
    r_apply = client.post(
        "/api/clients/sync/apply",
        json={"units": normalized_payload["units"], "import_ssh_passwords": False},
    )
    assert r_apply.status_code == 200
    apply_body = r_apply.json()
    assert apply_body["created_units"] == 1
    assert apply_body["created_systems"] == 1
    assert apply_body["created_profiles"]["postgres"] == 1

    # List, Get, Patch, Add System, Delete System, Delete Client via HTTP
    r_list = client.get("/api/clients", params={"search": "Delta", "environment": "PRD"})
    assert r_list.status_code == 200
    units = r_list.json()
    assert len(units) == 1
    unit_id = units[0]["id"]

    r_get = client.get(f"/api/clients/{unit_id}")
    assert r_get.status_code == 200
    assert r_get.json()["unit_code"] == "DELTA-01"

    r_patch = client.patch(f"/api/clients/{unit_id}", json={"notes": "Observação local"})
    assert r_patch.status_code == 200
    assert r_patch.json()["notes"] == "Observação local"

    r_add_sys = client.post(
        f"/api/clients/{unit_id}/systems",
        json={
            "label": "Hospitalar HML",
            "system_type": "hospitalar",
            "environment": "HML",
            "system_url": "https://delta-hosp-hml.example.local",
        },
    )
    assert r_add_sys.status_code == 201
    sys_id = r_add_sys.json()["id"]

    r_patch_sys = client.patch(
        f"/api/clients/{unit_id}/systems/{sys_id}",
        json={"version_label": "3.12.1"},
    )
    assert r_patch_sys.status_code == 200
    assert r_patch_sys.json()["version_label"] == "3.12.1"

    r_del_sys = client.delete(f"/api/clients/{unit_id}/systems/{sys_id}")
    assert r_del_sys.status_code == 200

    r_del_unit = client.delete(f"/api/clients/{unit_id}")
    assert r_del_unit.status_code == 200
    assert client.get(f"/api/clients/{unit_id}").status_code == 404
