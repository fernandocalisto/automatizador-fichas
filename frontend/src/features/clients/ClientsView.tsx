import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Cloud,
  Database,
  Edit3,
  ExternalLink,
  FilePlus2,
  FolderDown,
  HardDrive,
  KeyRound,
  Layers,
  Link2,
  Plus,
  RefreshCw,
  Search,
  Server,
  Shield,
  Star,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Dialog,
  EmptyState,
  Input,
  useToast,
} from "@/components/ui";
import type { BadgeTone } from "@/components/ui";
import { FAVORITE_CLIENTS_STORAGE_KEY } from "@/features/home";
import { JasperServerBrowser } from "@/features/jasperserver/JasperServerBrowser";
import { jasperServerApi } from "@/features/jasperserver/jasperServerApi";
import { SftpBrowser } from "@/features/sftp/SftpBrowser";
import { sftpApi } from "@/features/sftp/sftpApi";
import { cn } from "@/lib/cn";
import type {
  ClientSystemRead,
  ClientSystemType,
  ClientUnitRead,
  EnvironmentKind,
  JasperServerResourceItem,
  ProjectRead,
  SftpRemoteEntry,
} from "@/types/studio";
import { ENVIRONMENT_META, SYSTEM_TYPE_META } from "./ClientCard";
import { ClientFormDialog, ClientSystemFormDialog } from "./ClientFormDialog";
import { ClientSyncDialog } from "./ClientSyncDialog";
import { clientsApi } from "./clientsApi";

export interface ClientsViewProps {
  onCreateFreeReport?: (opts: {
    clientSystemId: string;
    dbProfileId?: string | null;
    defaultName: string;
  }) => void;
  onOpenSftpImport?: (
    sftpProfileId: string,
    dbProfileId?: string | null,
  ) => void;
  onOpenJasperImport?: (
    jasperProfileId: string,
    dbProfileId?: string | null,
  ) => void;
  onOpenSettings?: () => void;
  onProjectImported?: (project: ProjectRead) => void;
  initialSelectedClientId?: string | null;
}

type DetailTabId = "jasperserver" | "sftp" | "systems";

function readFavorites(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(FAVORITE_CLIENTS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}

function writeFavorites(ids: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      FAVORITE_CLIENTS_STORAGE_KEY,
      JSON.stringify(ids),
    );
  } catch {
    // ignore storage errors
  }
}

function isSafeExternalUrl(url: string): boolean {
  const trimmed = url.trim();
  return trimmed.startsWith("http://") || trimmed.startsWith("https://");
}

function getLicenseTone(status: string): BadgeTone {
  const lower = status.toLowerCase();
  if (lower.includes("ativ")) return "success";
  if (lower.includes("susp") || lower.includes("bloq") || lower.includes("venc"))
    return "danger";
  if (lower.includes("trial") || lower.includes("pend")) return "warning";
  return "neutral";
}

function inferProjectNameFromFilename(filename: string): string {
  return filename
    .replace(/\.(jrxml|jasper)$/i, "")
    .replace(/[_-]+/g, " ")
    .trim();
}

function defaultTabForClient(client: ClientUnitRead): DetailTabId {
  if (client.systems.some((s) => Boolean(s.jasperserver_profile_id))) {
    return "jasperserver";
  }
  if (client.systems.some((s) => Boolean(s.sftp_profile_id))) {
    return "sftp";
  }
  return "systems";
}

function formatSystemLinkLabel(
  sys: ClientSystemRead,
  allWebSystems: ClientSystemRead[],
): string {
  const typeLabel =
    SYSTEM_TYPE_META[sys.system_type]?.label ?? sys.label ?? "Sistema";
  const sameTypeCount = allWebSystems.filter(
    (s) => s.system_type === sys.system_type,
  ).length;
  if (sameTypeCount > 1) {
    return `Abrir ${typeLabel} (${sys.environment})`;
  }
  return `Abrir ${typeLabel}`;
}

export function ClientsView({
  onCreateFreeReport,
  onOpenSftpImport,
  onOpenJasperImport,
  onOpenSettings,
  onProjectImported,
  initialSelectedClientId = null,
}: ClientsViewProps) {
  const { pushToast } = useToast();

  const [clients, setClients] = useState<ClientUnitRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  // Left-pane filters
  const [query, setQuery] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [typeFilter, setTypeFilter] = useState<"all" | ClientSystemType>("all");
  const [envFilter, setEnvFilter] = useState<"all" | EnvironmentKind>("all");
  const [favoriteIds, setFavoriteIds] = useState<string[]>(() =>
    readFavorites(),
  );

  // Selection & Detail tabs
  const [selectedClientId, setSelectedClientId] = useState<string | null>(
    initialSelectedClientId,
  );
  const [activeTab, setActiveTab] = useState<DetailTabId>("jasperserver");
  const [selectedJasperSystemId, setSelectedJasperSystemId] = useState<
    string | null
  >(null);
  const [selectedSftpSystemId, setSelectedSftpSystemId] = useState<
    string | null
  >(null);

  // Quick-import loading states
  const [importingJasperUri, setImportingJasperUri] = useState<string | null>(
    null,
  );
  const [importingSftpPath, setImportingSftpPath] = useState<string | null>(
    null,
  );

  // Dialogs
  const [syncOpen, setSyncOpen] = useState(false);
  const [clientFormOpen, setClientFormOpen] = useState(false);
  const [editingClient, setEditingClient] = useState<ClientUnitRead | null>(
    null,
  );
  const [systemFormClient, setSystemFormClient] =
    useState<ClientUnitRead | null>(null);
  const [editingSystem, setEditingSystem] = useState<ClientSystemRead | null>(
    null,
  );
  const [deleteClientTarget, setDeleteClientTarget] =
    useState<ClientUnitRead | null>(null);
  const [deleteSystemTarget, setDeleteSystemTarget] = useState<{
    client: ClientUnitRead;
    system: ClientSystemRead;
  } | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadClients = useCallback(async () => {
    setLoading(true);
    try {
      const list = await clientsApi.listClients();
      setClients(Array.isArray(list) ? list : []);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao carregar clientes",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
      setHasLoaded(true);
    }
  }, [pushToast]);

  useEffect(() => {
    void loadClients();
  }, [loadClients]);

  // Honor initialSelectedClientId when jumping from HomeView or CommandPalette
  useEffect(() => {
    if (initialSelectedClientId) {
      setSelectedClientId(initialSelectedClientId);
    }
  }, [initialSelectedClientId]);

  const favoriteSet = useMemo(() => new Set(favoriteIds), [favoriteIds]);

  const toggleFavorite = useCallback((clientId: string) => {
    setFavoriteIds((prev) => {
      const next = prev.includes(clientId)
        ? prev.filter((id) => id !== clientId)
        : [...prev, clientId];
      writeFavorites(next);
      return next;
    });
  }, []);

  const filteredClients = useMemo(() => {
    const q = query.trim().toLowerCase();
    return clients.filter((client) => {
      if (favoritesOnly && !favoriteSet.has(client.id)) {
        return false;
      }
      if (
        typeFilter !== "all" &&
        !client.systems.some((s) => s.system_type === typeFilter)
      ) {
        return false;
      }
      if (
        envFilter !== "all" &&
        !client.systems.some((s) => s.environment === envFilter)
      ) {
        return false;
      }
      if (!q) return true;
      const haystack = [
        client.name,
        client.unit_code,
        client.external_id ?? "",
        client.hosting,
        ...client.tags,
        ...client.integrations,
        ...client.systems.map((s) => {
          const meta = s.metadata ?? {};
          return [
            s.label,
            s.system_url,
            s.version_label,
            typeof meta.pg_host === "string" ? meta.pg_host : "",
            typeof meta.sftp_host === "string" ? meta.sftp_host : "",
            typeof meta.jasper_url === "string" ? meta.jasper_url : "",
          ].join(" ");
        }),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [clients, query, favoritesOnly, favoriteSet, typeFilter, envFilter]);

  // Keep a valid client selected once the catalog has loaded
  useEffect(() => {
    if (!hasLoaded) return;
    if (clients.length === 0) {
      setSelectedClientId(null);
      return;
    }
    if (selectedClientId && clients.some((c) => c.id === selectedClientId)) {
      return;
    }
    const preferred =
      (initialSelectedClientId &&
        clients.find((c) => c.id === initialSelectedClientId)) ??
      filteredClients[0] ??
      clients[0];
    if (preferred) {
      setSelectedClientId(preferred.id);
    }
  }, [hasLoaded, clients, filteredClients, selectedClientId, initialSelectedClientId]);

  const selectedClient = useMemo(
    () => clients.find((c) => c.id === selectedClientId) ?? null,
    [clients, selectedClientId],
  );

  // Deduplicated JasperServer & SFTP systems for selected client
  const jasperSystems = useMemo(() => {
    if (!selectedClient) return [];
    const seen = new Set<string>();
    return selectedClient.systems.filter((s) => {
      if (!s.jasperserver_profile_id) return false;
      if (seen.has(s.jasperserver_profile_id)) return false;
      seen.add(s.jasperserver_profile_id);
      return true;
    });
  }, [selectedClient]);

  const sftpSystems = useMemo(() => {
    if (!selectedClient) return [];
    const seen = new Set<string>();
    return selectedClient.systems.filter((s) => {
      if (!s.sftp_profile_id) return false;
      if (seen.has(s.sftp_profile_id)) return false;
      seen.add(s.sftp_profile_id);
      return true;
    });
  }, [selectedClient]);

  // Reset detail tab & active sub-profiles when switching selected client
  useEffect(() => {
    if (!selectedClient) return;
    setActiveTab(defaultTabForClient(selectedClient));
    const firstJs = selectedClient.systems.find((s) =>
      Boolean(s.jasperserver_profile_id),
    );
    const firstSftp = selectedClient.systems.find((s) =>
      Boolean(s.sftp_profile_id),
    );
    setSelectedJasperSystemId(firstJs?.id ?? null);
    setSelectedSftpSystemId(firstSftp?.id ?? null);
    setImportingJasperUri(null);
    setImportingSftpPath(null);
  }, [selectedClient?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const activeJasperSystem = useMemo(() => {
    if (jasperSystems.length === 0) return null;
    return (
      jasperSystems.find((s) => s.id === selectedJasperSystemId) ??
      jasperSystems[0]
    );
  }, [jasperSystems, selectedJasperSystemId]);

  const activeSftpSystem = useMemo(() => {
    if (sftpSystems.length === 0) return null;
    return (
      sftpSystems.find((s) => s.id === selectedSftpSystemId) ?? sftpSystems[0]
    );
  }, [sftpSystems, selectedSftpSystemId]);

  const handleQuickImportJasper = async (item: JasperServerResourceItem) => {
    if (!activeJasperSystem?.jasperserver_profile_id) return;
    setImportingJasperUri(item.uri);
    try {
      const project = await jasperServerApi.importReport({
        profile_id: activeJasperSystem.jasperserver_profile_id,
        resource_uri: item.uri,
        project_name: item.label || undefined,
        db_profile_id: activeJasperSystem.db_profile_id || undefined,
        sync_subreports: true,
      });
      pushToast({
        tone: "success",
        title: "Relatório aberto no Studio",
        description: `${project.name} pronto para edição e preview.`,
      });
      onProjectImported?.(project);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao abrir relatório do JasperServer",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setImportingJasperUri(null);
    }
  };

  const handleQuickImportSftp = async (entry: SftpRemoteEntry) => {
    if (!activeSftpSystem?.sftp_profile_id) return;
    setImportingSftpPath(entry.path);
    try {
      const project = await sftpApi.importReport({
        profile_id: activeSftpSystem.sftp_profile_id,
        remote_path: entry.path,
        project_name: inferProjectNameFromFilename(entry.name) || undefined,
        db_profile_id: activeSftpSystem.db_profile_id || undefined,
        sync_subreports: true,
      });
      pushToast({
        tone: "success",
        title: "Ficha aberta no Studio",
        description:
          entry.kind === "jasper"
            ? `${project.name} decompilado automaticamente para .jrxml.`
            : `${project.name} pronto para edição.`,
      });
      onProjectImported?.(project);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao abrir arquivo via SFTP",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setImportingSftpPath(null);
    }
  };

  const handleConfirmDeleteClient = async () => {
    if (!deleteClientTarget) return;
    setDeleting(true);
    try {
      await clientsApi.deleteClient(deleteClientTarget.id);
      pushToast({
        tone: "success",
        title: "Cliente removido",
        description: deleteClientTarget.name,
      });
      setDeleteClientTarget(null);
      await loadClients();
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Erro ao remover cliente",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeleting(false);
    }
  };

  const handleConfirmDeleteSystem = async () => {
    if (!deleteSystemTarget) return;
    setDeleting(true);
    try {
      await clientsApi.deleteClientSystem(
        deleteSystemTarget.client.id,
        deleteSystemTarget.system.id,
      );
      pushToast({
        tone: "success",
        title: "Sistema removido",
        description: deleteSystemTarget.system.label,
      });
      setDeleteSystemTarget(null);
      await loadClients();
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Erro ao remover sistema",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeleting(false);
    }
  };

  const resetAllFilters = () => {
    setQuery("");
    setFavoritesOnly(false);
    setTypeFilter("all");
    setEnvFilter("all");
  };

  const isAllPillActive =
    !favoritesOnly && typeFilter === "all" && envFilter === "all";

  const webSystems = useMemo(() => {
    if (!selectedClient) return [];
    return selectedClient.systems.filter((s) =>
      isSafeExternalUrl(s.system_url),
    );
  }, [selectedClient]);

  const isSelectedCloud = selectedClient
    ? selectedClient.hosting.toLowerCase().includes("cloud") ||
      selectedClient.hosting.toLowerCase().includes("nuvem") ||
      selectedClient.hosting.toLowerCase().includes("saas")
    : false;

  return (
    <div className="flex h-full overflow-hidden bg-canvas">
      {/* LEFT PANE: Client Master List */}
      <aside className="flex w-80 xl:w-96 shrink-0 flex-col overflow-hidden border-r border-border bg-surface">
        {/* Left Header */}
        <div className="shrink-0 space-y-2.5 border-b border-border p-3.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <Building2 className="h-4 w-4 shrink-0 text-accent" />
              <h1 className="truncate text-sm font-semibold text-ink">
                Clientes
              </h1>
              <Badge tone="neutral" className="tabular-nums text-[10px] py-0">
                {filteredClients.length}
                {filteredClients.length !== clients.length
                  ? `/${clients.length}`
                  : ""}
              </Badge>
            </div>

            <div className="flex shrink-0 items-center gap-1.5">
              <Button
                variant="outline"
                size="xs"
                onClick={() => setSyncOpen(true)}
                icon={<RefreshCw className="h-3 w-3" />}
                title="Sincronizar clientes do portal"
              >
                Sincronizar
              </Button>
              <Button
                variant="primary"
                size="xs"
                onClick={() => {
                  setEditingClient(null);
                  setClientFormOpen(true);
                }}
                icon={<Plus className="h-3 w-3" />}
              >
                Novo
              </Button>
            </div>
          </div>

          {/* Search Input */}
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por nome, ID, host ou tag..."
              aria-label="Buscar clientes"
              className="h-8 pl-8 pr-7 text-xs"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Limpar busca"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink cursor-pointer"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {/* Compact Filter Pills */}
          <div
            role="group"
            aria-label="Filtros de clientes"
            className="flex flex-wrap items-center gap-1"
          >
            <button
              type="button"
              onClick={resetAllFilters}
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                isAllPillActive
                  ? "border-accent/40 bg-accent-soft text-accent"
                  : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
              )}
            >
              Todos
            </button>

            <button
              type="button"
              aria-pressed={favoritesOnly}
              onClick={() => setFavoritesOnly((prev) => !prev)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                favoritesOnly
                  ? "border-warning/40 bg-warning-soft text-warning"
                  : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
              )}
            >
              <Star
                className={cn(
                  "h-2.5 w-2.5",
                  favoritesOnly && "fill-warning text-warning",
                )}
              />
              Favoritos
              {favoriteIds.length > 0 && (
                <span className="tabular-nums opacity-80">
                  ({favoriteIds.length})
                </span>
              )}
            </button>

            <button
              type="button"
              aria-pressed={typeFilter === "ambulatorial"}
              onClick={() =>
                setTypeFilter((prev) =>
                  prev === "ambulatorial" ? "all" : "ambulatorial",
                )
              }
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                typeFilter === "ambulatorial"
                  ? "border-accent/40 bg-accent-soft text-accent"
                  : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
              )}
            >
              Ambulatorial
            </button>

            <button
              type="button"
              aria-pressed={typeFilter === "hospitalar"}
              onClick={() =>
                setTypeFilter((prev) =>
                  prev === "hospitalar" ? "all" : "hospitalar",
                )
              }
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                typeFilter === "hospitalar"
                  ? "border-blueprint/40 bg-blueprint-soft text-blueprint"
                  : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
              )}
            >
              Hospitalar
            </button>

            <button
              type="button"
              aria-pressed={envFilter === "PRD"}
              onClick={() =>
                setEnvFilter((prev) => (prev === "PRD" ? "all" : "PRD"))
              }
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                envFilter === "PRD"
                  ? "border-danger/40 bg-danger-soft text-danger"
                  : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
              )}
            >
              PRD
            </button>

            <button
              type="button"
              aria-pressed={envFilter === "HML"}
              onClick={() =>
                setEnvFilter((prev) => (prev === "HML" ? "all" : "HML"))
              }
              className={cn(
                "rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors cursor-pointer",
                envFilter === "HML"
                  ? "border-warning/40 bg-warning-soft text-warning"
                  : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
              )}
            >
              HML
            </button>
          </div>
        </div>

        {/* Scrollable Client List */}
        <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-border/50">
          {loading && clients.length === 0 ? (
            <div className="space-y-2 p-3">
              {[0, 1, 2, 3].map((idx) => (
                <div
                  key={idx}
                  className="h-14 animate-pulse rounded-md bg-surface-subtle"
                />
              ))}
            </div>
          ) : clients.length === 0 ? (
            <div className="p-6 text-center text-xs text-ink-muted">
              Nenhum cliente cadastrado ainda.
            </div>
          ) : filteredClients.length === 0 ? (
            <div className="space-y-2 p-6 text-center text-xs text-ink-muted">
              <p>Nenhum cliente corresponde aos filtros.</p>
              <Button variant="outline" size="xs" onClick={resetAllFilters}>
                Limpar filtros
              </Button>
            </div>
          ) : (
            filteredClients.map((client) => {
              const isSelected = client.id === selectedClientId;
              const isFav = favoriteSet.has(client.id);
              const hasAmb = client.systems.some(
                (s) => s.system_type === "ambulatorial",
              );
              const hasHosp = client.systems.some(
                (s) => s.system_type === "hospitalar",
              );

              return (
                <div
                  key={client.id}
                  className={cn(
                    "flex items-center gap-1.5 border-l-2 px-2.5 py-2.5 transition-colors",
                    isSelected
                      ? "border-l-accent bg-accent-soft/60"
                      : "border-l-transparent hover:bg-surface-subtle/60",
                  )}
                >
                  <button
                    type="button"
                    aria-label={
                      isFav
                        ? `Remover ${client.name} dos favoritos`
                        : `Marcar ${client.name} como favorito`
                    }
                    aria-pressed={isFav}
                    title={
                      isFav
                        ? "Remover dos favoritos"
                        : "Marcar como favorito"
                    }
                    onClick={() => toggleFavorite(client.id)}
                    className="shrink-0 rounded p-1 text-ink-muted hover:bg-surface hover:text-warning cursor-pointer"
                  >
                    <Star
                      className={cn(
                        "h-3.5 w-3.5",
                        isFav && "fill-warning text-warning",
                      )}
                    />
                  </button>

                  <button
                    type="button"
                    onClick={() => setSelectedClientId(client.id)}
                    aria-current={isSelected ? "true" : undefined}
                    className="min-w-0 flex-1 text-left cursor-pointer"
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="truncate text-xs font-semibold text-ink">
                        {client.name}
                      </span>
                      <span className="shrink-0 text-[10px] text-ink-muted tabular-nums">
                        {client.systems.length} sist.
                      </span>
                    </div>

                    <div className="mt-1 flex items-center justify-between gap-1.5">
                      <span className="truncate font-mono text-[10px] text-ink-muted">
                        {client.unit_code}
                        {client.external_id ? ` · #${client.external_id}` : ""}
                      </span>

                      <div className="flex shrink-0 items-center gap-1">
                        {hasAmb && (
                          <span className="rounded bg-accent-soft px-1.5 py-0 text-[10px] font-medium text-accent">
                            Amb
                          </span>
                        )}
                        {hasHosp && (
                          <span className="rounded bg-blueprint-soft px-1.5 py-0 text-[10px] font-medium text-blueprint">
                            Hosp
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* RIGHT PANE: Selected Client Detail + Full-Height Inline Explorers */}
      <section className="flex min-w-0 flex-1 flex-col overflow-hidden bg-canvas">
        {clients.length === 0 && !loading ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="Nenhum cliente cadastrado"
              description="Cadastre unidades manualmente ou sincronize diretamente da sua sessão autenticada no portal de gestão."
              action={
                <div className="flex flex-wrap items-center justify-center gap-2">
                  {onOpenSettings && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={onOpenSettings}
                      icon={<KeyRound className="h-3.5 w-3.5" />}
                    >
                      Credenciais Padrão
                    </Button>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSyncOpen(true)}
                    icon={<RefreshCw className="h-3.5 w-3.5" />}
                  >
                    Sincronizar do Portal
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      setEditingClient(null);
                      setClientFormOpen(true);
                    }}
                    icon={<Plus className="h-3.5 w-3.5" />}
                  >
                    Novo Cliente
                  </Button>
                </div>
              }
            />
          </div>
        ) : !selectedClient ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="Selecione um cliente"
              description="Escolha um cliente na lista à esquerda para explorar seus relatórios do JasperServer, fichas SFTP e conexões."
            />
          </div>
        ) : (
          <>
            {/* Client Detail Header */}
            <div className="shrink-0 border-b border-border bg-surface px-5 pt-3.5">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 space-y-1.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="truncate text-base font-semibold tracking-tight text-ink">
                      {selectedClient.name}
                    </h2>

                    <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                      {selectedClient.unit_code}
                    </span>

                    {selectedClient.external_id && (
                      <Badge tone="neutral" className="tabular-nums text-[10px] py-0">
                        ID: {selectedClient.external_id}
                      </Badge>
                    )}

                    {selectedClient.hosting && (
                      <Badge
                        tone={isSelectedCloud ? "blueprint" : "neutral"}
                        className="text-[10px] py-0"
                      >
                        {isSelectedCloud ? (
                          <Cloud className="h-3 w-3" />
                        ) : (
                          <HardDrive className="h-3 w-3" />
                        )}
                        {selectedClient.hosting}
                      </Badge>
                    )}

                    {selectedClient.license_status && (
                      <Badge
                        tone={getLicenseTone(selectedClient.license_status)}
                        dot
                        className="text-[10px] py-0"
                      >
                        {selectedClient.license_status}
                      </Badge>
                    )}
                  </div>

                  {/* Direct clickable web links */}
                  {webSystems.length > 0 && (
                    <div className="flex flex-wrap items-center gap-1.5">
                      {webSystems.map((sys) => (
                        <a
                          key={sys.id}
                          href={sys.system_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 rounded-md border border-accent/25 bg-accent-soft/50 px-2 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft transition-colors"
                        >
                          <span>{formatSystemLinkLabel(sys, webSystems)}</span>
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ))}
                    </div>
                  )}
                </div>

                {/* Right Header Actions */}
                <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                  {onOpenSettings && (
                    <Button
                      variant="outline"
                      size="xs"
                      onClick={onOpenSettings}
                      icon={<KeyRound className="h-3 w-3" />}
                    >
                      Credenciais Padrão
                    </Button>
                  )}

                  <Button
                    variant="outline"
                    size="xs"
                    onClick={() => {
                      setEditingClient(selectedClient);
                      setClientFormOpen(true);
                    }}
                    icon={<Edit3 className="h-3 w-3" />}
                  >
                    Editar
                  </Button>

                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => setDeleteClientTarget(selectedClient)}
                    aria-label={`Excluir cliente ${selectedClient.name}`}
                    title="Excluir cliente"
                    className="h-7 w-7 text-ink-muted hover:bg-danger-soft hover:text-danger"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>

              {/* 3 Internal Detail Tabs */}
              <div
                role="tablist"
                aria-label="Seções do cliente"
                className="mt-3 flex items-center gap-1 overflow-x-auto"
              >
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "jasperserver"}
                  onClick={() => setActiveTab("jasperserver")}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
                    activeTab === "jasperserver"
                      ? "border-accent text-accent"
                      : "border-transparent text-ink-secondary hover:text-ink",
                  )}
                >
                  <Layers className="h-3.5 w-3.5" />
                  <span>Relatórios (JasperServer)</span>
                  <Badge
                    tone={jasperSystems.length > 0 ? "accent" : "neutral"}
                    className="text-[10px] py-0 px-1.5 tabular-nums"
                  >
                    {jasperSystems.length}
                  </Badge>
                </button>

                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "sftp"}
                  onClick={() => setActiveTab("sftp")}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
                    activeTab === "sftp"
                      ? "border-accent text-accent"
                      : "border-transparent text-ink-secondary hover:text-ink",
                  )}
                >
                  <Server className="h-3.5 w-3.5" />
                  <span>Fichas (SFTP)</span>
                  <Badge
                    tone={sftpSystems.length > 0 ? "blueprint" : "neutral"}
                    className="text-[10px] py-0 px-1.5 tabular-nums"
                  >
                    {sftpSystems.length}
                  </Badge>
                </button>

                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "systems"}
                  onClick={() => setActiveTab("systems")}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-xs font-medium transition-colors cursor-pointer",
                    activeTab === "systems"
                      ? "border-accent text-accent"
                      : "border-transparent text-ink-secondary hover:text-ink",
                  )}
                >
                  <Database className="h-3.5 w-3.5" />
                  <span>Conexões & Sistemas</span>
                  <Badge
                    tone="neutral"
                    className="text-[10px] py-0 px-1.5 tabular-nums"
                  >
                    {selectedClient.systems.length}
                  </Badge>
                </button>
              </div>
            </div>

            {/* TAB 1: Inline Full-Height JasperServer Explorer */}
            {activeTab === "jasperserver" && (
              <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-4">
                {jasperSystems.length === 0 ? (
                  <div className="flex flex-1 items-center justify-center">
                    <EmptyState
                      icon={<Layers className="h-5 w-5" />}
                      title="Nenhum JasperReports Server vinculado"
                      description="Este cliente ainda não possui um servidor JasperReports configurado nos seus sistemas."
                      action={
                        <div className="flex flex-wrap items-center justify-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setActiveTab("systems")}
                          >
                            Ver Conexões & Sistemas
                          </Button>
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => {
                              setEditingSystem(null);
                              setSystemFormClient(selectedClient);
                            }}
                            icon={<Plus className="h-3.5 w-3.5" />}
                          >
                            Adicionar sistema
                          </Button>
                        </div>
                      }
                    />
                  </div>
                ) : activeJasperSystem ? (
                  <>
                    {/* Multi-JasperServer selector + info bar */}
                    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        {jasperSystems.length > 1 ? (
                          <div className="flex flex-wrap items-center gap-1">
                            {jasperSystems.map((sys) => {
                              const active = sys.id === activeJasperSystem.id;
                              return (
                                <button
                                  key={sys.id}
                                  type="button"
                                  onClick={() =>
                                    setSelectedJasperSystemId(sys.id)
                                  }
                                  className={cn(
                                    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
                                    active
                                      ? "border-accent/40 bg-accent-soft text-accent"
                                      : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
                                  )}
                                >
                                  <span>{sys.label}</span>
                                  <span className="text-[10px] opacity-80">
                                    {sys.environment}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 text-xs">
                            <span className="font-semibold text-ink">
                              {activeJasperSystem.label}
                            </span>
                            <Badge
                              tone={
                                ENVIRONMENT_META[activeJasperSystem.environment]
                                  ?.tone ?? "neutral"
                              }
                              dot
                              className="text-[10px] py-0"
                            >
                              {activeJasperSystem.environment}
                            </Badge>
                          </div>
                        )}

                        {typeof activeJasperSystem.metadata?.jasper_url ===
                          "string" &&
                          activeJasperSystem.metadata.jasper_url && (
                            <span className="hidden md:inline font-mono text-[11px] text-ink-muted truncate max-w-[340px]">
                              {activeJasperSystem.metadata.jasper_url}
                            </span>
                          )}
                      </div>

                      {onOpenJasperImport && (
                        <Button
                          variant="ghost"
                          size="xs"
                          onClick={() =>
                            onOpenJasperImport(
                              activeJasperSystem.jasperserver_profile_id!,
                              activeJasperSystem.db_profile_id,
                            )
                          }
                          icon={<FolderDown className="h-3 w-3" />}
                        >
                          Importação avançada
                        </Button>
                      )}
                    </div>

                    <div className="min-h-0 flex-1 overflow-hidden">
                      <JasperServerBrowser
                        profileId={activeJasperSystem.jasperserver_profile_id!}
                        fullHeight
                        onQuickImport={handleQuickImportJasper}
                        importingUri={importingJasperUri}
                      />
                    </div>
                  </>
                ) : null}
              </div>
            )}

            {/* TAB 2: Inline Full-Height SFTP Explorer */}
            {activeTab === "sftp" && (
              <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-4">
                {sftpSystems.length === 0 ? (
                  <div className="flex flex-1 items-center justify-center">
                    <EmptyState
                      icon={<Server className="h-5 w-5" />}
                      title="Nenhum servidor SFTP vinculado"
                      description="Este cliente ainda não possui um servidor SFTP configurado nos seus sistemas."
                      action={
                        <div className="flex flex-wrap items-center justify-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setActiveTab("systems")}
                          >
                            Ver Conexões & Sistemas
                          </Button>
                          <Button
                            variant="primary"
                            size="sm"
                            onClick={() => {
                              setEditingSystem(null);
                              setSystemFormClient(selectedClient);
                            }}
                            icon={<Plus className="h-3.5 w-3.5" />}
                          >
                            Adicionar sistema
                          </Button>
                        </div>
                      }
                    />
                  </div>
                ) : activeSftpSystem ? (
                  <>
                    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        {sftpSystems.length > 1 ? (
                          <div className="flex flex-wrap items-center gap-1">
                            {sftpSystems.map((sys) => {
                              const active = sys.id === activeSftpSystem.id;
                              return (
                                <button
                                  key={sys.id}
                                  type="button"
                                  onClick={() =>
                                    setSelectedSftpSystemId(sys.id)
                                  }
                                  className={cn(
                                    "inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
                                    active
                                      ? "border-accent/40 bg-accent-soft text-accent"
                                      : "border-border bg-surface-subtle/60 text-ink-secondary hover:text-ink",
                                  )}
                                >
                                  <span>{sys.label}</span>
                                  <span className="text-[10px] opacity-80">
                                    {sys.environment}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 text-xs">
                            <span className="font-semibold text-ink">
                              {activeSftpSystem.label}
                            </span>
                            <Badge
                              tone={
                                ENVIRONMENT_META[activeSftpSystem.environment]
                                  ?.tone ?? "neutral"
                              }
                              dot
                              className="text-[10px] py-0"
                            >
                              {activeSftpSystem.environment}
                            </Badge>
                          </div>
                        )}

                        {typeof activeSftpSystem.metadata?.sftp_host ===
                          "string" &&
                          activeSftpSystem.metadata.sftp_host && (
                            <span className="hidden md:inline font-mono text-[11px] text-ink-muted">
                              {typeof activeSftpSystem.metadata.sftp_user ===
                                "string" && activeSftpSystem.metadata.sftp_user
                                ? `${activeSftpSystem.metadata.sftp_user}@`
                                : ""}
                              {activeSftpSystem.metadata.sftp_host}
                            </span>
                          )}
                      </div>

                      {onOpenSftpImport && (
                        <Button
                          variant="ghost"
                          size="xs"
                          onClick={() =>
                            onOpenSftpImport(
                              activeSftpSystem.sftp_profile_id!,
                              activeSftpSystem.db_profile_id,
                            )
                          }
                          icon={<Server className="h-3 w-3" />}
                        >
                          Importação avançada
                        </Button>
                      )}
                    </div>

                    <div className="min-h-0 flex-1 overflow-hidden">
                      <SftpBrowser
                        profileId={activeSftpSystem.sftp_profile_id!}
                        fullHeight
                        onQuickImport={handleQuickImportSftp}
                        importingPath={importingSftpPath}
                      />
                    </div>
                  </>
                ) : null}
              </div>
            )}

            {/* TAB 3: Connections & Systems */}
            {activeTab === "systems" && (
              <div className="min-h-0 flex-1 overflow-y-auto p-5">
                <div className="mx-auto max-w-4xl space-y-4">
                  {/* Notes, Tags & Add System Bar */}
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1.5">
                      {selectedClient.notes && (
                        <p className="text-xs text-ink-secondary">
                          {selectedClient.notes}
                        </p>
                      )}
                      {(selectedClient.tags.length > 0 ||
                        selectedClient.integrations.length > 0) && (
                        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                          {selectedClient.tags.map((tag) => (
                            <span
                              key={`tag-${tag}`}
                              className="inline-flex items-center gap-1 rounded border border-border bg-surface px-1.5 py-0.5 text-ink-secondary"
                            >
                              <Tag className="h-2.5 w-2.5 text-ink-muted" />
                              {tag}
                            </span>
                          ))}
                          {selectedClient.integrations.map((integ) => (
                            <span
                              key={`integ-${integ}`}
                              className="inline-flex items-center gap-1 rounded border border-accent/20 bg-accent-soft/50 px-1.5 py-0.5 text-accent"
                            >
                              <Link2 className="h-2.5 w-2.5" />
                              {integ}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <Button
                      variant="primary"
                      size="xs"
                      onClick={() => {
                        setEditingSystem(null);
                        setSystemFormClient(selectedClient);
                      }}
                      icon={<Plus className="h-3.5 w-3.5" />}
                    >
                      Adicionar sistema
                    </Button>
                  </div>

                  {/* Systems Cards */}
                  {selectedClient.systems.length === 0 ? (
                    <EmptyState
                      icon={<Database className="h-5 w-5" />}
                      title="Nenhum sistema cadastrado"
                      description="Adicione um sistema Ambulatorial ou Hospitalar com vínculos de PostgreSQL, SFTP ou JasperServer."
                      action={
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => {
                            setEditingSystem(null);
                            setSystemFormClient(selectedClient);
                          }}
                          icon={<Plus className="h-3.5 w-3.5" />}
                        >
                          Adicionar sistema
                        </Button>
                      }
                    />
                  ) : (
                    <div className="space-y-3">
                      {selectedClient.systems.map((sys) => {
                        const typeMeta =
                          SYSTEM_TYPE_META[sys.system_type] ??
                          SYSTEM_TYPE_META.outro;
                        const envMeta =
                          ENVIRONMENT_META[sys.environment] ??
                          ENVIRONMENT_META.PRD;
                        const hasValidUrl = isSafeExternalUrl(sys.system_url);

                        const meta = sys.metadata ?? {};
                        const pgHost =
                          typeof meta.pg_host === "string" ? meta.pg_host : "";
                        const pgPort =
                          typeof meta.pg_port === "number" ||
                          typeof meta.pg_port === "string"
                            ? String(meta.pg_port)
                            : "";
                        const pgDb =
                          typeof meta.pg_dbname === "string"
                            ? meta.pg_dbname
                            : "";
                        const sftpHost =
                          typeof meta.sftp_host === "string"
                            ? meta.sftp_host
                            : "";
                        const sftpPort =
                          typeof meta.sftp_port === "number" ||
                          typeof meta.sftp_port === "string"
                            ? String(meta.sftp_port)
                            : "";
                        const sftpUser =
                          typeof meta.sftp_user === "string"
                            ? meta.sftp_user
                            : "";
                        const jasperUrl =
                          typeof meta.jasper_url === "string"
                            ? meta.jasper_url
                            : "";

                        const pgSummary = pgHost
                          ? `${pgHost}${pgPort ? `:${pgPort}` : ""}${pgDb ? `/${pgDb}` : ""}`
                          : "";
                        const sftpSummary = sftpHost
                          ? `${sftpUser ? `${sftpUser}@` : ""}${sftpHost}${sftpPort ? `:${sftpPort}` : ""}`
                          : "";

                        return (
                          <Card key={sys.id}>
                            <CardBody className="space-y-3">
                              <div className="flex flex-col gap-2.5 sm:flex-row sm:items-start sm:justify-between">
                                <div className="min-w-0 space-y-1.5">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <span className="text-sm font-semibold text-ink">
                                      {sys.label}
                                    </span>
                                    <Badge tone={typeMeta.tone}>
                                      {typeMeta.label}
                                    </Badge>
                                    <Badge tone={envMeta.tone} dot>
                                      {envMeta.label}
                                    </Badge>
                                    {sys.environment === "PRD" && (
                                      <Badge
                                        tone="warning"
                                        title="Perfis de produção nascem somente leitura por padrão"
                                      >
                                        <Shield className="h-2.5 w-2.5" />
                                        RO
                                      </Badge>
                                    )}
                                    {sys.version_label && (
                                      <span className="rounded border border-border bg-surface-subtle px-1.5 py-0.5 font-mono text-[10px] text-ink-secondary">
                                        v{sys.version_label.replace(/^v/i, "")}
                                      </span>
                                    )}
                                    {hasValidUrl && (
                                      <a
                                        href={sys.system_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="inline-flex items-center gap-1 rounded border border-accent/30 bg-accent-soft/60 px-2 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft transition-colors"
                                      >
                                        <ExternalLink className="h-3 w-3" />
                                        Abrir Sistema
                                      </a>
                                    )}
                                  </div>

                                  {/* Connection chips */}
                                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                                    <Badge
                                      tone={
                                        sys.db_profile_id
                                          ? "success"
                                          : "neutral"
                                      }
                                      className="text-[10px] py-0"
                                      title={pgSummary || undefined}
                                    >
                                      <Database className="h-2.5 w-2.5" />
                                      {sys.db_profile_id
                                        ? pgSummary
                                          ? `PG: ${pgSummary}`
                                          : "PG vinculado"
                                        : "Sem PG"}
                                    </Badge>

                                    <Badge
                                      tone={
                                        sys.sftp_profile_id
                                          ? "success"
                                          : "neutral"
                                      }
                                      className="text-[10px] py-0"
                                      title={sftpSummary || undefined}
                                    >
                                      <Server className="h-2.5 w-2.5" />
                                      {sys.sftp_profile_id
                                        ? sftpSummary
                                          ? `SFTP: ${sftpSummary}`
                                          : "SFTP vinculado"
                                        : "Sem SFTP"}
                                    </Badge>

                                    {sys.jasperserver_profile_id &&
                                    isSafeExternalUrl(jasperUrl) ? (
                                      <a
                                        href={jasperUrl}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        title={jasperUrl}
                                        className="inline-flex items-center gap-1 rounded-full border border-success/30 bg-success-soft px-2 py-0 text-[10px] font-medium text-success hover:underline"
                                      >
                                        <FolderDown className="h-2.5 w-2.5" />
                                        Jasper:{" "}
                                        {jasperUrl.replace(/^https?:\/\//i, "")}
                                      </a>
                                    ) : (
                                      <Badge
                                        tone={
                                          sys.jasperserver_profile_id
                                            ? "success"
                                            : "neutral"
                                        }
                                        className="text-[10px] py-0"
                                      >
                                        <FolderDown className="h-2.5 w-2.5" />
                                        {sys.jasperserver_profile_id
                                          ? "Jasper vinculado"
                                          : "Sem Jasper"}
                                      </Badge>
                                    )}
                                  </div>
                                </div>

                                <div className="flex shrink-0 items-center gap-1">
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() => {
                                      setEditingSystem(sys);
                                      setSystemFormClient(selectedClient);
                                    }}
                                    aria-label={`Editar sistema ${sys.label}`}
                                    title="Editar sistema"
                                    className="h-7 w-7"
                                  >
                                    <Edit3 className="h-3.5 w-3.5" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    onClick={() =>
                                      setDeleteSystemTarget({
                                        client: selectedClient,
                                        system: sys,
                                      })
                                    }
                                    aria-label={`Excluir sistema ${sys.label}`}
                                    title="Excluir sistema"
                                    className="h-7 w-7 text-ink-muted hover:bg-danger-soft hover:text-danger"
                                  >
                                    <Trash2 className="h-3.5 w-3.5" />
                                  </Button>
                                </div>
                              </div>

                              {/* 1-click System Actions */}
                              <div className="flex flex-wrap items-center gap-2 border-t border-border/70 pt-2.5">
                                {onCreateFreeReport && (
                                  <Button
                                    variant="primary"
                                    size="xs"
                                    onClick={() =>
                                      onCreateFreeReport({
                                        clientSystemId: sys.id,
                                        dbProfileId: sys.db_profile_id,
                                        defaultName: `${selectedClient.name} — ${sys.label}`,
                                      })
                                    }
                                    icon={<FilePlus2 className="h-3 w-3" />}
                                  >
                                    Novo Relatório Livre neste Banco
                                  </Button>
                                )}

                                {sys.jasperserver_profile_id && (
                                  <Button
                                    variant="outline"
                                    size="xs"
                                    onClick={() => {
                                      setSelectedJasperSystemId(sys.id);
                                      setActiveTab("jasperserver");
                                    }}
                                    icon={<Layers className="h-3 w-3" />}
                                  >
                                    Explorar JasperServer
                                  </Button>
                                )}

                                {sys.sftp_profile_id && (
                                  <Button
                                    variant="outline"
                                    size="xs"
                                    onClick={() => {
                                      setSelectedSftpSystemId(sys.id);
                                      setActiveTab("sftp");
                                    }}
                                    icon={<Server className="h-3 w-3" />}
                                  >
                                    Explorar SFTP
                                  </Button>
                                )}
                              </div>
                            </CardBody>
                          </Card>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* Sync Dialog */}
      <ClientSyncDialog
        open={syncOpen}
        onClose={() => setSyncOpen(false)}
        onSynced={loadClients}
      />

      {/* Client Create / Edit Dialog */}
      <ClientFormDialog
        open={clientFormOpen}
        editingClient={editingClient}
        onClose={() => setClientFormOpen(false)}
        onSaved={loadClients}
      />

      {/* System Create / Edit Dialog */}
      <ClientSystemFormDialog
        open={systemFormClient !== null}
        client={systemFormClient}
        editingSystem={editingSystem}
        onClose={() => {
          setSystemFormClient(null);
          setEditingSystem(null);
        }}
        onSaved={loadClients}
      />

      {/* Delete Client Confirmation */}
      <Dialog
        open={deleteClientTarget !== null}
        onClose={() => {
          if (!deleting) setDeleteClientTarget(null);
        }}
        title="Excluir cliente"
        description="Remove o cliente e seus vínculos de sistemas no catálogo local (os perfis de conexão já criados permanecem intactos)."
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setDeleteClientTarget(null)}
              disabled={deleting}
            >
              Cancelar
            </Button>
            <Button
              variant="danger"
              loading={deleting}
              onClick={() => void handleConfirmDeleteClient()}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            >
              Confirmar exclusão
            </Button>
          </>
        }
      >
        {deleteClientTarget && (
          <p className="text-xs text-ink-secondary">
            Deseja remover{" "}
            <strong className="text-ink">{deleteClientTarget.name}</strong> (
            <span className="font-mono">{deleteClientTarget.unit_code}</span>)?
          </p>
        )}
      </Dialog>

      {/* Delete System Confirmation */}
      <Dialog
        open={deleteSystemTarget !== null}
        onClose={() => {
          if (!deleting) setDeleteSystemTarget(null);
        }}
        title="Excluir sistema do cliente"
        description="Remove apenas o vínculo deste sistema no cadastro do cliente."
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setDeleteSystemTarget(null)}
              disabled={deleting}
            >
              Cancelar
            </Button>
            <Button
              variant="danger"
              loading={deleting}
              onClick={() => void handleConfirmDeleteSystem()}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            >
              Confirmar exclusão
            </Button>
          </>
        }
      >
        {deleteSystemTarget && (
          <p className="text-xs text-ink-secondary">
            Remover o sistema{" "}
            <strong className="text-ink">
              {deleteSystemTarget.system.label}
            </strong>{" "}
            de{" "}
            <strong className="text-ink">
              {deleteSystemTarget.client.name}
            </strong>
            ?
          </p>
        )}
      </Dialog>
    </div>
  );
}
