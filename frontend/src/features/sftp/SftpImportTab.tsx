import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AlertCircle, Download, Server, Sparkles } from "lucide-react";
import {
  Badge,
  Button,
  EmptyState,
  FieldLabel,
  Input,
  SearchableSelect,
  Switch,
  useToast,
} from "@/components/ui";
import type {
  DbProfileRead,
  ProjectRead,
  SftpProfileRead,
  SftpRemoteEntry,
} from "@/types/studio";
import { SftpBrowser } from "./SftpBrowser";
import { sftpApi } from "./sftpApi";

export interface SftpImportTabProps {
  initialProfileId?: string;
  dbProfiles: DbProfileRead[];
  onProjectImported: (project: ProjectRead) => void;
  onCancel?: () => void;
}

function inferProjectNameFromFilename(filename: string): string {
  return filename
    .replace(/\.(jrxml|jasper)$/i, "")
    .replace(/[_-]+/g, " ")
    .trim();
}

export function SftpImportTab({
  initialProfileId,
  dbProfiles,
  onProjectImported,
  onCancel,
}: SftpImportTabProps) {
  const { pushToast } = useToast();

  const [profiles, setProfiles] = useState<SftpProfileRead[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(true);
  const [selectedProfileId, setSelectedProfileId] = useState(
    initialProfileId ?? "",
  );
  const [selectedEntry, setSelectedEntry] = useState<SftpRemoteEntry | null>(
    null,
  );
  const [projectName, setProjectName] = useState("");
  const [dbProfileId, setDbProfileId] = useState("");
  const [syncSubreports, setSyncSubreports] = useState(true);
  const [importing, setImporting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoadingProfiles(true);
    sftpApi
      .listProfiles()
      .then((items) => {
        if (!active) return;
        const list = Array.isArray(items) ? items : [];
        setProfiles(list);
        const preferred =
          (initialProfileId && list.find((p) => p.id === initialProfileId)) ||
          list[0];
        if (preferred) {
          setSelectedProfileId(preferred.id);
          if (preferred.linked_db_profile_id) {
            setDbProfileId(preferred.linked_db_profile_id);
          }
        }
      })
      .catch((err) => {
        if (!active) return;
        setErrorMsg(
          err instanceof Error
            ? err.message
            : "Erro ao carregar perfis SFTP.",
        );
      })
      .finally(() => {
        if (active) setLoadingProfiles(false);
      });

    return () => {
      active = false;
    };
  }, [initialProfileId]);

  const activeProfile = useMemo(
    () => profiles.find((p) => p.id === selectedProfileId) ?? null,
    [profiles, selectedProfileId],
  );

  const profileOptions = useMemo(
    () =>
      profiles.map((p) => ({
        value: p.id,
        label: p.name,
        sublabel: `${p.username ? `${p.username}@` : ""}${p.host}:${p.port}`,
        badge: p.environment,
        keywords: p.remote_base_dir,
      })),
    [profiles],
  );

  const dbOptions = useMemo(
    () =>
      dbProfiles.map((db) => ({
        value: db.id,
        label: db.name,
        sublabel: `${db.host}:${db.port}/${db.dbname || "padrão"}`,
        badge: db.environment || undefined,
      })),
    [dbProfiles],
  );

  const handleProfileChange = (nextId: string) => {
    setSelectedProfileId(nextId);
    setSelectedEntry(null);
    setErrorMsg(null);
    const nextProf = profiles.find((p) => p.id === nextId);
    if (nextProf?.linked_db_profile_id) {
      setDbProfileId(nextProf.linked_db_profile_id);
    }
  };

  const handleSelectFile = (entry: SftpRemoteEntry) => {
    setSelectedEntry(entry);
    setErrorMsg(null);
    if (!projectName.trim()) {
      setProjectName(inferProjectNameFromFilename(entry.name));
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedProfileId) {
      setErrorMsg("Selecione um servidor SFTP.");
      return;
    }
    if (!selectedEntry) {
      setErrorMsg("Selecione um arquivo .jrxml ou .jasper no navegador SFTP.");
      return;
    }

    setImporting(true);
    setErrorMsg(null);
    try {
      const imported = await sftpApi.importReport({
        profile_id: selectedProfileId,
        remote_path: selectedEntry.path,
        project_name: projectName.trim() || undefined,
        db_profile_id: dbProfileId || undefined,
        sync_subreports: syncSubreports,
      });
      pushToast({
        tone: "success",
        title: "Relatório importado via SFTP",
        description:
          selectedEntry.kind === "jasper"
            ? `${imported.name} decompilado automaticamente para .jrxml.`
            : `${imported.name} pronto no Jasper Studio.`,
      });
      onProjectImported(imported);
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Falha ao importar relatório via SFTP.",
      );
    } finally {
      setImporting(false);
    }
  };

  if (loadingProfiles) {
    return (
      <div className="py-8 text-center text-xs text-ink-muted">
        Carregando servidores SFTP...
      </div>
    );
  }

  if (profiles.length === 0) {
    return (
      <EmptyState
        icon={<Server className="h-5 w-5" />}
        title="Nenhum servidor SFTP configurado"
        description="Cadastre ao menos um servidor SSH/SFTP em Configurações → Servidores SFTP para navegar e importar fichas diretamente do servidor Linux."
      />
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <FieldLabel htmlFor="sftp-import-profile">Servidor SFTP</FieldLabel>
          <SearchableSelect
            id="sftp-import-profile"
            ariaLabel="Servidor SFTP"
            value={selectedProfileId}
            onChange={handleProfileChange}
            options={profileOptions}
            placeholder="Selecionar servidor SFTP..."
            searchPlaceholder="Buscar por nome, host ou ambiente..."
            emptyLabel="Nenhum servidor SFTP encontrado."
          />
        </div>

        <div>
          <FieldLabel htmlFor="sftp-import-db">
            Banco PostgreSQL padrão (opcional)
          </FieldLabel>
          <SearchableSelect
            id="sftp-import-db"
            ariaLabel="Banco PostgreSQL padrão"
            value={dbProfileId}
            onChange={setDbProfileId}
            options={dbOptions}
            placeholder="Nenhum banco vinculado"
            searchPlaceholder="Buscar banco por nome ou host..."
            emptyLabel="Nenhum banco encontrado."
            allowClear
            clearLabel="Nenhum banco vinculado"
          />
        </div>
      </div>

      {activeProfile && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <FieldLabel className="mb-0">
              Navegar em {activeProfile.remote_base_dir}
            </FieldLabel>
            <div className="flex items-center gap-1.5">
              <Badge
                tone={
                  activeProfile.environment === "PRD"
                    ? "danger"
                    : activeProfile.environment === "HML"
                      ? "warning"
                      : "neutral"
                }
              >
                {activeProfile.environment}
              </Badge>
              {activeProfile.read_only && (
                <Badge tone="warning">Somente leitura</Badge>
              )}
            </div>
          </div>

          <SftpBrowser
            profileId={activeProfile.id}
            initialPath={activeProfile.remote_base_dir}
            selectedPath={selectedEntry?.path ?? null}
            onSelectFile={handleSelectFile}
          />
        </div>
      )}

      {selectedEntry && (
        <div className="rounded-md border border-border bg-surface-subtle/50 p-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span className="font-mono text-ink truncate">
              Selecionado: <strong>{selectedEntry.path}</strong>
            </span>
            <Badge tone={selectedEntry.kind === "jasper" ? "warning" : "accent"}>
              {selectedEntry.kind === "jasper"
                ? ".jasper (decompilação automática)"
                : ".jrxml"}
            </Badge>
          </div>

          {selectedEntry.kind === "jasper" && (
            <div className="flex items-start gap-2 rounded bg-warning-soft/60 px-2.5 py-2 text-xs text-warning">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Este arquivo está compilado (<code>.jasper</code>). O motor JVM
                do Studio irá decompilá-lo automaticamente para{" "}
                <code>.jrxml</code> editável ao importar.
              </span>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:items-end">
        <div>
          <FieldLabel htmlFor="sftp-import-name">Nome do projeto</FieldLabel>
          <Input
            id="sftp-import-name"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder="Ex.: Ficha de Evolução Ambulatorial"
          />
        </div>

        <div className="pb-1">
          <Switch
            id="sftp-sync-subreports"
            checked={syncSubreports}
            onChange={setSyncSubreports}
            label="Baixar subreports .jasper referenciados da mesma pasta"
          />
        </div>
      </div>

      {errorMsg && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
        {onCancel && (
          <Button variant="ghost" onClick={onCancel} disabled={importing}>
            Cancelar
          </Button>
        )}
        <Button
          type="submit"
          variant="primary"
          loading={importing}
          disabled={!selectedEntry || !selectedProfileId}
          icon={<Download className="h-3.5 w-3.5" />}
        >
          Importar via SFTP
        </Button>
      </div>
    </form>
  );
}
