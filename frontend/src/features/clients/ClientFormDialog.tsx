import { useEffect, useState, type FormEvent } from "react";
import { AlertCircle } from "lucide-react";
import {
  Button,
  Dialog,
  FieldLabel,
  Input,
  Select,
  Textarea,
  useToast,
} from "@/components/ui";
import type {
  ClientSystemRead,
  ClientSystemType,
  ClientUnitRead,
  EnvironmentKind,
} from "@/types/studio";
import { clientsApi } from "./clientsApi";

export interface ClientFormDialogProps {
  open: boolean;
  editingClient: ClientUnitRead | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}

export interface ClientSystemFormDialogProps {
  open: boolean;
  client: ClientUnitRead | null;
  editingSystem: ClientSystemRead | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}

function splitCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function ClientFormDialog({
  open,
  editingClient,
  onClose,
  onSaved,
}: ClientFormDialogProps) {
  const { pushToast } = useToast();

  const [name, setName] = useState("");
  const [unitCode, setUnitCode] = useState("");
  const [externalId, setExternalId] = useState("");
  const [hosting, setHosting] = useState("");
  const [licenseStatus, setLicenseStatus] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [integrationsText, setIntegrationsText] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    if (editingClient) {
      setName(editingClient.name);
      setUnitCode(editingClient.unit_code);
      setExternalId(editingClient.external_id ?? "");
      setHosting(editingClient.hosting);
      setLicenseStatus(editingClient.license_status);
      setTagsText(editingClient.tags.join(", "));
      setIntegrationsText(editingClient.integrations.join(", "));
      setNotes(editingClient.notes);
    } else {
      setName("");
      setUnitCode("");
      setExternalId("");
      setHosting("");
      setLicenseStatus("");
      setTagsText("");
      setIntegrationsText("");
      setNotes("");
    }
  }, [open, editingClient]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Informe o nome do cliente/unidade.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        unit_code: unitCode.trim() || undefined,
        external_id: externalId.trim() || null,
        hosting: hosting.trim(),
        license_status: licenseStatus.trim(),
        tags: splitCommaList(tagsText),
        integrations: splitCommaList(integrationsText),
        notes: notes.trim(),
      };

      if (editingClient) {
        await clientsApi.updateClient(editingClient.id, payload);
        pushToast({
          tone: "success",
          title: "Cliente atualizado",
          description: payload.name,
        });
      } else {
        await clientsApi.createClient(payload);
        pushToast({
          tone: "success",
          title: "Cliente cadastrado",
          description: payload.name,
        });
      }
      await onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar cliente.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!saving) onClose();
      }}
      title={
        editingClient ? `Editar cliente — ${editingClient.name}` : "Novo Cliente"
      }
      description="Cadastre os dados gerais da unidade. Você poderá vincular múltiplos sistemas (Ambulatorial, Hospitalar, HML/PRD) logo em seguida."
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancelar
          </Button>
          <Button
            type="submit"
            form="client-unit-form"
            variant="primary"
            loading={saving}
          >
            {editingClient ? "Salvar alterações" : "Cadastrar cliente"}
          </Button>
        </>
      }
    >
      <form id="client-unit-form" onSubmit={handleSubmit} className="space-y-3.5">
        <div>
          <FieldLabel htmlFor="client-name">Nome da unidade / cliente *</FieldLabel>
          <Input
            id="client-name"
            placeholder="Ex.: Unidade de Saúde Exemplo"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor="client-code">Código único (unit_code)</FieldLabel>
            <Input
              id="client-code"
              placeholder="Gerado automaticamente se vazio"
              value={unitCode}
              onChange={(e) => setUnitCode(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel htmlFor="client-ext-id">ID externo (portal)</FieldLabel>
            <Input
              id="client-ext-id"
              placeholder="Opcional"
              value={externalId}
              onChange={(e) => setExternalId(e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor="client-hosting">Hospedagem</FieldLabel>
            <Input
              id="client-hosting"
              placeholder="Cloud ou On-Premise"
              value={hosting}
              onChange={(e) => setHosting(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel htmlFor="client-license">Status da licença</FieldLabel>
            <Input
              id="client-license"
              placeholder="Ex.: Licença Ativa"
              value={licenseStatus}
              onChange={(e) => setLicenseStatus(e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor="client-tags">Tags (separadas por vírgula)</FieldLabel>
            <Input
              id="client-tags"
              placeholder="Ex.: prioridade, piloto"
              value={tagsText}
              onChange={(e) => setTagsText(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel htmlFor="client-integrations">
              Integrações (separadas por vírgula)
            </FieldLabel>
            <Input
              id="client-integrations"
              placeholder="Ex.: RNDS, e-SUS, Laboratório"
              value={integrationsText}
              onChange={(e) => setIntegrationsText(e.target.value)}
            />
          </div>
        </div>

        <div>
          <FieldLabel htmlFor="client-notes">Observações</FieldLabel>
          <Textarea
            id="client-notes"
            placeholder="Notas técnicas locais desta unidade..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
          >
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </form>
    </Dialog>
  );
}

export function ClientSystemFormDialog({
  open,
  client,
  editingSystem,
  onClose,
  onSaved,
}: ClientSystemFormDialogProps) {
  const { pushToast } = useToast();

  const [label, setLabel] = useState("");
  const [systemKey, setSystemKey] = useState("");
  const [systemType, setSystemType] = useState<ClientSystemType>("ambulatorial");
  const [environment, setEnvironment] = useState<EnvironmentKind>("PRD");
  const [systemUrl, setSystemUrl] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [dbProfileId, setDbProfileId] = useState("");
  const [sftpProfileId, setSftpProfileId] = useState("");
  const [jasperProfileId, setJasperProfileId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    if (editingSystem) {
      setLabel(editingSystem.label);
      setSystemKey(editingSystem.system_key);
      setSystemType(editingSystem.system_type);
      setEnvironment(editingSystem.environment);
      setSystemUrl(editingSystem.system_url);
      setVersionLabel(editingSystem.version_label);
      setDbProfileId(editingSystem.db_profile_id ?? "");
      setSftpProfileId(editingSystem.sftp_profile_id ?? "");
      setJasperProfileId(editingSystem.jasperserver_profile_id ?? "");
    } else {
      setLabel("");
      setSystemKey("");
      setSystemType("ambulatorial");
      setEnvironment("PRD");
      setSystemUrl("");
      setVersionLabel("");
      setDbProfileId("");
      setSftpProfileId("");
      setJasperProfileId("");
    }
  }, [open, editingSystem]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!client) return;
    if (!label.trim()) {
      setError("Informe o rótulo do sistema.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = {
        label: label.trim(),
        system_key: systemKey.trim() || undefined,
        system_type: systemType,
        environment,
        system_url: systemUrl.trim(),
        version_label: versionLabel.trim(),
        db_profile_id: dbProfileId.trim() || null,
        sftp_profile_id: sftpProfileId.trim() || null,
        jasperserver_profile_id: jasperProfileId.trim() || null,
      };

      if (editingSystem) {
        await clientsApi.updateClientSystem(client.id, editingSystem.id, payload);
        pushToast({
          tone: "success",
          title: "Sistema atualizado",
          description: `${client.name} — ${payload.label}`,
        });
      } else {
        await clientsApi.createClientSystem(client.id, payload);
        pushToast({
          tone: "success",
          title: "Sistema adicionado",
          description: `${client.name} — ${payload.label}`,
        });
      }
      await onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar sistema.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!saving) onClose();
      }}
      title={
        editingSystem
          ? `Editar sistema — ${editingSystem.label}`
          : `Adicionar sistema — ${client?.name ?? ""}`
      }
      description="Configure o tipo, ambiente, link web e vínculos opcionais de perfis PostgreSQL, SFTP e JasperServer."
      size="md"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            Cancelar
          </Button>
          <Button
            type="submit"
            form="client-system-form"
            variant="primary"
            loading={saving}
          >
            {editingSystem ? "Salvar sistema" : "Adicionar sistema"}
          </Button>
        </>
      }
    >
      <form id="client-system-form" onSubmit={handleSubmit} className="space-y-3.5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor="sys-label">Rótulo do sistema *</FieldLabel>
            <Input
              id="sys-label"
              placeholder="Ex.: Ambulatorial PRD"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              required
            />
          </div>
          <div>
            <FieldLabel htmlFor="sys-key">Chave técnica (opcional)</FieldLabel>
            <Input
              id="sys-key"
              placeholder="Ex.: ambulatorial_prd"
              value={systemKey}
              onChange={(e) => setSystemKey(e.target.value)}
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <FieldLabel htmlFor="sys-type">Tipo</FieldLabel>
            <Select
              id="sys-type"
              value={systemType}
              onChange={(e) => setSystemType(e.target.value as ClientSystemType)}
            >
              <option value="ambulatorial">Ambulatorial</option>
              <option value="hospitalar">Hospitalar</option>
              <option value="painel">Painel</option>
              <option value="compras">Compras</option>
              <option value="outro">Outro</option>
            </Select>
          </div>
          <div>
            <FieldLabel htmlFor="sys-env">Ambiente</FieldLabel>
            <Select
              id="sys-env"
              value={environment}
              onChange={(e) => setEnvironment(e.target.value as EnvironmentKind)}
            >
              <option value="PRD">PRD</option>
              <option value="HML">HML</option>
              <option value="DEV">DEV</option>
            </Select>
          </div>
          <div>
            <FieldLabel htmlFor="sys-version">Versão</FieldLabel>
            <Input
              id="sys-version"
              placeholder="Ex.: 4.14.0"
              value={versionLabel}
              onChange={(e) => setVersionLabel(e.target.value)}
            />
          </div>
        </div>

        <div>
          <FieldLabel htmlFor="sys-url">URL do sistema web</FieldLabel>
          <Input
            id="sys-url"
            placeholder="https://sistema.exemplo.local"
            value={systemUrl}
            onChange={(e) => setSystemUrl(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <FieldLabel htmlFor="sys-db-id">ID Perfil PostgreSQL</FieldLabel>
            <Input
              id="sys-db-id"
              placeholder="Opcional"
              value={dbProfileId}
              onChange={(e) => setDbProfileId(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel htmlFor="sys-sftp-id">ID Perfil SFTP</FieldLabel>
            <Input
              id="sys-sftp-id"
              placeholder="Opcional"
              value={sftpProfileId}
              onChange={(e) => setSftpProfileId(e.target.value)}
            />
          </div>
          <div>
            <FieldLabel htmlFor="sys-js-id">ID Perfil JasperServer</FieldLabel>
            <Input
              id="sys-js-id"
              placeholder="Opcional"
              value={jasperProfileId}
              onChange={(e) => setJasperProfileId(e.target.value)}
            />
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
          >
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </form>
    </Dialog>
  );
}
