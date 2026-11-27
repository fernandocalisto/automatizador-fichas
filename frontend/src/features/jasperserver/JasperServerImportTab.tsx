import { useEffect, useState } from "react";
import { AlertCircle, CloudDownload, Server } from "lucide-react";
import {
  Badge,
  Button,
  EmptyState,
  FieldLabel,
  Input,
  Select,
  Switch,
  useToast,
} from "@/components/ui";
import type {
  DbProfileRead,
  JasperServerProfileRead,
  JasperServerReportUnitDetail,
  JasperServerResourceItem,
  ProjectRead,
} from "@/types/studio";
import { JasperServerBrowser } from "./JasperServerBrowser";
import { jasperServerApi } from "./jasperServerApi";

export interface JasperServerImportTabProps {
  initialProfileId?: string;
  dbProfiles: DbProfileRead[];
  onProjectImported: (project: ProjectRead) => void;
  onCancel?: () => void;
}

export function JasperServerImportTab({
  initialProfileId,
  dbProfiles,
  onProjectImported,
  onCancel,
}: JasperServerImportTabProps) {
  const { pushToast } = useToast();

  const [profiles, setProfiles] = useState<JasperServerProfileRead[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(true);
  const [selectedProfileId, setSelectedProfileId] = useState(
    initialProfileId || "",
  );

  const [selectedResource, setSelectedResource] =
    useState<JasperServerResourceItem | null>(null);
  const [selectedDetail, setSelectedDetail] =
    useState<JasperServerReportUnitDetail | null>(null);

  const [projectName, setProjectName] = useState("");
  const [selectedDbProfileId, setSelectedDbProfileId] = useState("");
  const [syncSubreports, setSyncSubreports] = useState(true);
  const [importing, setImporting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadingProfiles(true);
    jasperServerApi
      .listProfiles()
      .then((list) => {
        if (!active) return;
        setProfiles(list);
        const preferred =
          (initialProfileId &&
            list.find((p) => p.id === initialProfileId)?.id) ||
          list[0]?.id ||
          "";
        setSelectedProfileId(preferred);
        const chosen = list.find((p) => p.id === preferred);
        if (chosen?.linked_db_profile_id) {
          setSelectedDbProfileId(chosen.linked_db_profile_id);
        }
      })
      .catch((err) => {
        if (!active) return;
        setErrorMsg(
          err instanceof Error
            ? err.message
            : "Falha ao carregar perfis do JasperReports Server.",
        );
      })
      .finally(() => {
        if (active) setLoadingProfiles(false);
      });
    return () => {
      active = false;
    };
  }, [initialProfileId]);

  const activeProfile =
    profiles.find((p) => p.id === selectedProfileId) || null;

  const handleProfileChange = (nextId: string) => {
    setSelectedProfileId(nextId);
    setSelectedResource(null);
    setSelectedDetail(null);
    setErrorMsg(null);
    const prof = profiles.find((p) => p.id === nextId);
    if (prof?.linked_db_profile_id) {
      setSelectedDbProfileId(prof.linked_db_profile_id);
    }
  };

  const handleSelectResource = (
    item: JasperServerResourceItem,
    detail: JasperServerReportUnitDetail | null,
  ) => {
    setSelectedResource(item);
    setSelectedDetail(detail);
    setErrorMsg(null);
    if (!projectName.trim() || projectName === selectedResource?.label) {
      setProjectName(detail?.label || item.label);
    }
  };

  const handleImport = async () => {
    if (!selectedProfileId || !selectedResource) {
      setErrorMsg("Selecione um perfil e uma Report Unit para importar.");
      return;
    }

    setImporting(true);
    setErrorMsg(null);
    try {
      const project = await jasperServerApi.importReport({
        profile_id: selectedProfileId,
        resource_uri: selectedResource.uri,
        project_name: projectName.trim() || undefined,
        db_profile_id: selectedDbProfileId || undefined,
        sync_subreports: syncSubreports,
      });
      pushToast({
        tone: "success",
        title: "Relatório importado do JasperServer",
        description: `${project.name} pronto no Jasper Studio.`,
      });
      onProjectImported(project);
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Falha ao importar relatório do JasperServer.",
      );
    } finally {
      setImporting(false);
    }
  };

  if (loadingProfiles) {
    return (
      <div className="py-8 text-center text-xs text-ink-muted">
        Carregando perfis do JasperReports Server...
      </div>
    );
  }

  if (profiles.length === 0) {
    return (
      <EmptyState
        icon={<Server className="h-5 w-5" />}
        title="Nenhum servidor JasperReports configurado"
        description="Cadastre um perfil na aba Configurações → JasperReports Server ou sincronize seus clientes antes de importar Report Units."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <FieldLabel htmlFor="js-import-profile">
            Servidor JasperReports *
          </FieldLabel>
          <Select
            id="js-import-profile"
            value={selectedProfileId}
            onChange={(e) => handleProfileChange(e.target.value)}
          >
            {profiles.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({p.environment}) — {p.base_url}
              </option>
            ))}
          </Select>
        </div>

        <div>
          <FieldLabel htmlFor="js-import-db">
            Banco PostgreSQL vinculado (opcional)
          </FieldLabel>
          <Select
            id="js-import-db"
            value={selectedDbProfileId}
            onChange={(e) => setSelectedDbProfileId(e.target.value)}
          >
            <option value="">Sem vínculo padrão</option>
            {dbProfiles.map((db) => (
              <option key={db.id} value={db.id}>
                {db.name} ({db.host}/{db.dbname || "—"})
              </option>
            ))}
          </Select>
        </div>
      </div>

      {activeProfile && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
          <Badge tone={activeProfile.environment === "PRD" ? "danger" : "blueprint"}>
            {activeProfile.environment}
          </Badge>
          {activeProfile.read_only && (
            <Badge tone="warning" dot>
              Somente leitura
            </Badge>
          )}
          <span className="font-mono text-[11px]">{activeProfile.base_url}</span>
        </div>
      )}

      {selectedProfileId && (
        <JasperServerBrowser
          profileId={selectedProfileId}
          initialFolderUri={activeProfile?.default_folder_uri || "/"}
          selectedUri={selectedResource?.uri}
          onSelectResource={handleSelectResource}
        />
      )}

      <div className="grid grid-cols-1 gap-3 border-t border-border pt-3 sm:grid-cols-2">
        <div>
          <FieldLabel htmlFor="js-import-name">Nome do projeto</FieldLabel>
          <Input
            id="js-import-name"
            placeholder="Usará o título da Report Unit se vazio"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
          />
        </div>

        <div className="flex items-end pb-1.5">
          <Switch
            id="js-import-sync-subreports"
            checked={syncSubreports}
            onChange={setSyncSubreports}
            label="Baixar e compilar subreports (_files e repo:/...)"
          />
        </div>
      </div>

      {selectedDetail?.datasource_uri && (
        <p className="text-[11px] text-ink-muted">
          DataSource da Report Unit:{" "}
          <code className="text-ink">{selectedDetail.datasource_uri}</code>
        </p>
      )}

      {errorMsg && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft/70 px-3 py-2 text-xs text-danger"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-1">
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={importing}>
            Cancelar
          </Button>
        )}
        <Button
          variant="primary"
          loading={importing}
          disabled={!selectedResource}
          onClick={() => void handleImport()}
          icon={<CloudDownload className="h-3.5 w-3.5" />}
        >
          Importar Report Unit
        </Button>
      </div>
    </div>
  );
}
