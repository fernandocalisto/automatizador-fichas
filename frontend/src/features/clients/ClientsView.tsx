import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  KeyRound,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  Input,
  Select,
  useToast,
} from "@/components/ui";
import type {
  ClientSystemRead,
  ClientSystemType,
  ClientUnitRead,
  EnvironmentKind,
} from "@/types/studio";
import { ClientCard } from "./ClientCard";
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
}

export function ClientsView({
  onCreateFreeReport,
  onOpenSftpImport,
  onOpenJasperImport,
  onOpenSettings,
}: ClientsViewProps) {
  const { pushToast } = useToast();

  const [clients, setClients] = useState<ClientUnitRead[]>([]);
  const [loading, setLoading] = useState(false);

  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | ClientSystemType>("all");
  const [envFilter, setEnvFilter] = useState<"all" | EnvironmentKind>("all");

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
    }
  }, [pushToast]);

  useEffect(() => {
    void loadClients();
  }, [loadClients]);

  const filteredClients = useMemo(() => {
    const q = query.trim().toLowerCase();
    return clients.filter((client) => {
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
        ...client.systems.map(
          (s) => `${s.label} ${s.system_url} ${s.version_label}`,
        ),
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [clients, query, typeFilter, envFilter]);

  const stats = useMemo(() => {
    let totalSystems = 0;
    let ambCount = 0;
    let hospCount = 0;
    let prdCount = 0;
    for (const c of clients) {
      totalSystems += c.systems.length;
      for (const s of c.systems) {
        if (s.system_type === "ambulatorial") ambCount += 1;
        if (s.system_type === "hospitalar") hospCount += 1;
        if (s.environment === "PRD") prdCount += 1;
      }
    }
    return {
      totalClients: clients.length,
      totalSystems,
      ambCount,
      hospCount,
      prdCount,
    };
  }, [clients]);

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

  return (
    <div className="flex h-full flex-col overflow-hidden bg-canvas">
      {/* Top Toolbar */}
      <div className="shrink-0 border-b border-border bg-surface px-5 py-3.5">
        <div className="mx-auto flex max-w-7xl flex-col gap-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <Building2 className="h-4.5 w-4.5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-base font-semibold tracking-tight text-ink">
                    Clientes & Sistemas
                  </h1>
                  <Badge tone="neutral" className="tabular-nums">
                    {filteredClients.length}
                    {filteredClients.length !== clients.length
                      ? ` / ${clients.length}`
                      : ""}
                  </Badge>
                </div>
                <p className="text-xs text-ink-muted">
                  Gerencie unidades multi-sistema (Ambulatorial, Hospitalar,
                  HML/PRD), links diretos e atalhos para SQL, SFTP e
                  JasperServer.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
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
          </div>

          {/* Search, Filters & Summary Stats */}
          <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative min-w-[220px] flex-1 sm:w-64 sm:flex-none">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Buscar por nome, código ou tag..."
                  aria-label="Buscar clientes por nome, código ou tag"
                  className="pl-8 pr-7"
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

              <Select
                aria-label="Filtrar por tipo de sistema"
                value={typeFilter}
                onChange={(e) =>
                  setTypeFilter(e.target.value as "all" | ClientSystemType)
                }
                className="w-40"
              >
                <option value="all">Todos os tipos</option>
                <option value="ambulatorial">Ambulatorial</option>
                <option value="hospitalar">Hospitalar</option>
                <option value="painel">Painel</option>
                <option value="compras">Compras</option>
                <option value="outro">Outro</option>
              </Select>

              <Select
                aria-label="Filtrar por ambiente"
                value={envFilter}
                onChange={(e) =>
                  setEnvFilter(e.target.value as "all" | EnvironmentKind)
                }
                className="w-36"
              >
                <option value="all">Todos ambientes</option>
                <option value="PRD">PRD</option>
                <option value="HML">HML</option>
                <option value="DEV">DEV</option>
              </Select>
            </div>

            {/* Summary KPIs */}
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <Badge tone="neutral" className="tabular-nums">
                {stats.totalClients} clientes
              </Badge>
              <Badge tone="neutral" className="tabular-nums">
                {stats.totalSystems} sistemas
              </Badge>
              <Badge tone="accent" className="tabular-nums">
                {stats.ambCount} Ambulatorial
              </Badge>
              <Badge tone="blueprint" className="tabular-nums">
                {stats.hospCount} Hospitalar
              </Badge>
              <Badge tone="danger" className="tabular-nums">
                {stats.prdCount} PRD
              </Badge>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="mx-auto max-w-7xl">
          {loading && clients.length === 0 ? (
            <div className="space-y-3">
              {[0, 1, 2].map((idx) => (
                <Card key={idx} className="p-4 animate-pulse">
                  <div className="h-4 w-1/3 rounded bg-surface-subtle" />
                  <div className="mt-2 h-3 w-1/2 rounded bg-surface-subtle" />
                </Card>
              ))}
            </div>
          ) : clients.length === 0 ? (
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title="Nenhum cliente cadastrado"
              description="Cadastre unidades manualmente ou sincronize diretamente da sua sessão autenticada no portal de gestão."
              action={
                <div className="flex flex-wrap items-center justify-center gap-2">
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
          ) : filteredClients.length === 0 ? (
            <EmptyState
              icon={<Search className="h-5 w-5" />}
              title="Nenhum cliente corresponde aos filtros"
              description="Ajuste a busca ou limpe os filtros de tipo e ambiente."
              action={
                <Button
                  variant="outline"
                  onClick={() => {
                    setQuery("");
                    setTypeFilter("all");
                    setEnvFilter("all");
                  }}
                >
                  Limpar filtros
                </Button>
              }
            />
          ) : (
            <div className="space-y-2.5">
              {filteredClients.map((client, idx) => (
                <ClientCard
                  key={client.id}
                  client={client}
                  defaultExpanded={idx === 0 || filteredClients.length <= 3}
                  onEditClient={(c) => {
                    setEditingClient(c);
                    setClientFormOpen(true);
                  }}
                  onDeleteClient={(c) => setDeleteClientTarget(c)}
                  onAddSystem={(c) => {
                    setEditingSystem(null);
                    setSystemFormClient(c);
                  }}
                  onEditSystem={(c, sys) => {
                    setEditingSystem(sys);
                    setSystemFormClient(c);
                  }}
                  onDeleteSystem={(c, sys) =>
                    setDeleteSystemTarget({ client: c, system: sys })
                  }
                  onCreateFreeReport={onCreateFreeReport}
                  onOpenSftpImport={onOpenSftpImport}
                  onOpenJasperImport={onOpenJasperImport}
                />
              ))}
            </div>
          )}
        </div>
      </div>

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
