import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Building2,
  Clock,
  FileCode2,
  FileUp,
  FolderKanban,
  KeyRound,
  Search,
  Sparkles,
  Star,
  X,
} from "lucide-react";
import { Badge, Button, Card } from "@/components/ui";
import { clientsApi } from "@/features/clients/clientsApi";
import type { SettingsTabId } from "@/types/feature-props";
import type {
  ClientUnitRead,
  EntryMode,
  ProjectRead,
  StudioSection,
} from "@/types/studio";

export const FAVORITE_CLIENTS_STORAGE_KEY = "salutem:favorite-clients";
const GUIDE_DISMISSED_STORAGE_KEY = "salutem:home-guide-dismissed";

export interface HomeViewProps {
  projects: ProjectRead[];
  onSelectProject: (project: ProjectRead, nextSection?: StudioSection) => void;
  onNavigateSection: (
    section: StudioSection,
    settingsTab?: SettingsTabId,
  ) => void;
  onOpenCreateDialog: (mode: EntryMode) => void;
  onOpenClientById: (clientId: string) => void;
  onOpenCommandPalette: () => void;
}

function readFavoriteClientIds(): string[] {
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

function readGuideDismissed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(GUIDE_DISMISSED_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function formatRecentDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function getProjectOriginHint(project: ProjectRead): string | null {
  const provider =
    typeof project.source_origin?.provider === "string"
      ? project.source_origin.provider
      : null;
  if (provider === "jasperserver" || project.entry_mode === "jasperserver_import") {
    return "JasperServer";
  }
  if (provider === "sftp" || project.entry_mode === "sftp_import") {
    return "SFTP";
  }
  if (project.entry_mode === "pdf") {
    return "PDF";
  }
  if (project.entry_mode === "blank_report") {
    return "SQL + Jasper";
  }
  return null;
}

export function HomeView({
  projects,
  onSelectProject,
  onNavigateSection,
  onOpenCreateDialog,
  onOpenClientById,
  onOpenCommandPalette,
}: HomeViewProps) {
  const [clients, setClients] = useState<ClientUnitRead[]>([]);
  const [loadingClients, setLoadingClients] = useState(true);
  const [favoriteIds, setFavoriteIds] = useState<string[]>(() =>
    readFavoriteClientIds(),
  );
  const [guideDismissed, setGuideDismissed] = useState<boolean>(() =>
    readGuideDismissed(),
  );

  useEffect(() => {
    let active = true;
    setLoadingClients(true);
    setFavoriteIds(readFavoriteClientIds());
    clientsApi
      .listClients()
      .then((list) => {
        if (!active) return;
        setClients(Array.isArray(list) ? list : []);
      })
      .catch(() => {
        if (!active) return;
        setClients([]);
      })
      .finally(() => {
        if (active) setLoadingClients(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const favoriteClients = useMemo(() => {
    if (favoriteIds.length === 0 || clients.length === 0) return [];
    const byId = new Map(clients.map((c) => [c.id, c]));
    return favoriteIds
      .map((id) => byId.get(id))
      .filter((c): c is ClientUnitRead => Boolean(c));
  }, [clients, favoriteIds]);

  const recentProjects = useMemo(() => {
    return [...projects]
      .sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      )
      .slice(0, 6);
  }, [projects]);

  const handleDismissGuide = () => {
    setGuideDismissed(true);
    try {
      window.localStorage.setItem(GUIDE_DISMISSED_STORAGE_KEY, "1");
    } catch {
      // ignore storage errors
    }
  };

  return (
    <div className="h-full overflow-y-auto bg-canvas">
      <div className="mx-auto max-w-5xl space-y-8 px-5 py-8 sm:px-8">
        {/* Quick Start Banner when there are no clients yet */}
        {!loadingClients && clients.length === 0 && !guideDismissed && (
          <div className="relative rounded-xl border border-accent/30 bg-accent-soft/60 p-4 sm:p-5">
            <button
              type="button"
              onClick={handleDismissGuide}
              aria-label="Dispensar guia rápido de início"
              className="absolute right-3 top-3 rounded-md p-1 text-ink-muted hover:bg-surface/70 hover:text-ink cursor-pointer"
            >
              <X className="h-4 w-4" />
            </button>

            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between pr-6">
              <div className="space-y-1.5">
                <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent">
                  <Sparkles className="h-3.5 w-3.5" />
                  Guia Rápido de Início
                </div>
                <h2 className="text-sm font-semibold text-ink">
                  Comece conectando suas credenciais e sincronizando os clientes
                </h2>
                <p className="text-xs text-ink-secondary">
                  <strong>1. Configure Credenciais Padrão</strong> (PostgreSQL,
                  SFTP e JasperServer) →{" "}
                  <strong>2. Sincronize Clientes do Portal</strong> para abrir
                  relatórios em 2 cliques.
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    onNavigateSection("settings", "default_credentials")
                  }
                  icon={<KeyRound className="h-3.5 w-3.5" />}
                >
                  1. Credenciais Padrão
                </Button>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => onNavigateSection("clients")}
                  icon={<Building2 className="h-3.5 w-3.5" />}
                >
                  2. Sincronizar Clientes
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Top Hero + Quick Search */}
        <section className="space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="space-y-1">
              <h1 className="text-2xl font-semibold tracking-tight text-ink">
                O que você quer fazer agora?
              </h1>
              <p className="text-sm text-ink-muted">
                Escolha uma ação abaixo ou pesquise diretamente qualquer
                cliente, banco ou relatório.
              </p>
            </div>

            <button
              type="button"
              onClick={onOpenCommandPalette}
              className="inline-flex h-9 items-center justify-between gap-3 rounded-lg border border-border bg-surface px-3 text-xs text-ink-muted shadow-xs transition-colors hover:border-border-strong hover:text-ink cursor-pointer sm:w-72"
            >
              <span className="inline-flex items-center gap-2 truncate">
                <Search className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">Busca rápida...</span>
              </span>
              <kbd className="shrink-0 rounded border border-border bg-surface-subtle px-1.5 py-0.5 font-mono text-[10px] font-medium text-ink-secondary">
                Ctrl+K
              </kbd>
            </button>
          </div>

          {/* 3 Big Action Cards */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {/* Action 1: Edit Client Report */}
            <button
              type="button"
              onClick={() => onNavigateSection("clients")}
              className="group flex flex-col justify-between rounded-xl border-2 border-accent/30 bg-surface p-5 text-left shadow-xs transition-all hover:border-accent hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent cursor-pointer"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-soft text-accent">
                    <Building2 className="h-5 w-5" />
                  </span>
                  <Badge tone="accent">Mais usado</Badge>
                </div>
                <div className="space-y-1">
                  <h2 className="text-base font-semibold text-ink group-hover:text-accent transition-colors">
                    Editar Relatório de um Cliente
                  </h2>
                  <p className="text-xs leading-relaxed text-ink-muted">
                    Abra relatórios do JasperServer ou fichas SFTP de qualquer
                    cliente e ajuste com IA
                  </p>
                </div>
              </div>
              <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-accent">
                <span>Escolher cliente</span>
                <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </div>
            </button>

            {/* Action 2: New Clinical Form from PDF */}
            <button
              type="button"
              onClick={() => onOpenCreateDialog("pdf")}
              className="group flex flex-col justify-between rounded-xl border border-border bg-surface p-5 text-left shadow-xs transition-all hover:border-blueprint/60 hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent cursor-pointer"
            >
              <div className="space-y-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blueprint-soft text-blueprint">
                  <FileUp className="h-5 w-5" />
                </span>
                <div className="space-y-1">
                  <h2 className="text-base font-semibold text-ink group-hover:text-blueprint transition-colors">
                    Nova Ficha Clínica (de PDF)
                  </h2>
                  <p className="text-xs leading-relaxed text-ink-muted">
                    Envie um PDF ambulatorial para extrair perguntas, SQL e
                    layout
                  </p>
                </div>
              </div>
              <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-blueprint">
                <span>Enviar PDF</span>
                <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </div>
            </button>

            {/* Action 3: New Free Report */}
            <button
              type="button"
              onClick={() => onOpenCreateDialog("blank_report")}
              className="group flex flex-col justify-between rounded-xl border border-border bg-surface p-5 text-left shadow-xs transition-all hover:border-border-strong hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent cursor-pointer"
            >
              <div className="space-y-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-subtle text-ink-secondary">
                  <FileCode2 className="h-5 w-5" />
                </span>
                <div className="space-y-1">
                  <h2 className="text-base font-semibold text-ink">
                    Novo Relatório Livre (SQL + Jasper)
                  </h2>
                  <p className="text-xs leading-relaxed text-ink-muted">
                    Crie um relatório do zero conectado ao PostgreSQL
                  </p>
                </div>
              </div>
              <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-ink-secondary group-hover:text-ink">
                <span>Criar relatório</span>
                <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
              </div>
            </button>
          </div>
        </section>

        {/* Favorite Clients Section */}
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
              <Star className="h-4 w-4 fill-warning text-warning" />
              Clientes Favoritos
            </h2>
            {clients.length > 0 && (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => onNavigateSection("clients")}
              >
                Ver todos ({clients.length})
              </Button>
            )}
          </div>

          {loadingClients ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((idx) => (
                <Card key={idx} className="h-20 animate-pulse p-4">
                  <div className="h-3.5 w-2/3 rounded bg-surface-subtle" />
                  <div className="mt-2.5 h-3 w-1/2 rounded bg-surface-subtle" />
                </Card>
              ))}
            </div>
          ) : favoriteClients.length > 0 ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {favoriteClients.map((client) => {
                const hasAmb = client.systems.some(
                  (s) => s.system_type === "ambulatorial",
                );
                const hasHosp = client.systems.some(
                  (s) => s.system_type === "hospitalar",
                );
                const jasperCount = client.systems.filter(
                  (s) => s.jasperserver_profile_id,
                ).length;
                const sftpCount = client.systems.filter(
                  (s) => s.sftp_profile_id,
                ).length;

                return (
                  <button
                    key={client.id}
                    type="button"
                    onClick={() => onOpenClientById(client.id)}
                    className="group flex flex-col justify-between rounded-lg border border-border bg-surface p-3.5 text-left transition-all hover:border-accent/50 hover:shadow-sm cursor-pointer"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-ink group-hover:text-accent transition-colors">
                          {client.name}
                        </p>
                        <p className="mt-0.5 truncate font-mono text-[11px] text-ink-muted">
                          {client.unit_code}
                          {client.external_id ? ` · ID ${client.external_id}` : ""}
                        </p>
                      </div>
                      <Star className="h-3.5 w-3.5 shrink-0 fill-warning text-warning" />
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      {hasAmb && (
                        <Badge tone="accent" className="text-[10px] py-0">
                          Amb
                        </Badge>
                      )}
                      {hasHosp && (
                        <Badge tone="blueprint" className="text-[10px] py-0">
                          Hosp
                        </Badge>
                      )}
                      {jasperCount > 0 && (
                        <Badge tone="success" className="text-[10px] py-0">
                          JasperServer
                        </Badge>
                      )}
                      {sftpCount > 0 && (
                        <Badge tone="neutral" className="text-[10px] py-0">
                          SFTP
                        </Badge>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-start justify-between gap-3 rounded-lg border border-dashed border-border bg-surface/60 px-4 py-4 sm:flex-row sm:items-center">
              <p className="text-xs text-ink-muted">
                {clients.length > 0
                  ? "Clique na estrela ★ ao lado de qualquer cliente para fixá-lo aqui e abrir seus relatórios em 1 clique."
                  : "Sincronize ou cadastre seus clientes para marcar favoritos e acessar relatórios rapidamente."}
              </p>
              <Button
                variant="outline"
                size="xs"
                onClick={() => onNavigateSection("clients")}
                icon={<Building2 className="h-3.5 w-3.5" />}
              >
                Abrir Clientes
              </Button>
            </div>
          )}
        </section>

        {/* Recent Work Section */}
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
              <Clock className="h-4 w-4 text-ink-muted" />
              Trabalhos Recentes
            </h2>
            {projects.length > 0 && (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => onNavigateSection("projects")}
              >
                Meus Projetos ({projects.length})
              </Button>
            )}
          </div>

          {recentProjects.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border bg-surface/60 px-4 py-5 text-center">
              <FolderKanban className="mx-auto h-5 w-5 text-ink-muted" />
              <p className="mt-2 text-xs text-ink-muted">
                Nenhum trabalho recente ainda. Abra um relatório de um cliente
                ou crie uma nova ficha acima.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {recentProjects.map((project) => {
                const isFreeReport = project.project_kind === "free_report";
                const originHint = getProjectOriginHint(project);
                return (
                  <Card
                    key={project.id}
                    className="flex items-center justify-between gap-3 px-4 py-3 transition-colors hover:border-border-strong"
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="truncate text-sm font-medium text-ink">
                          {project.name}
                        </span>
                        <Badge
                          tone={isFreeReport ? "blueprint" : "accent"}
                          className="text-[10px] py-0"
                        >
                          {isFreeReport ? "Relatório" : "Ficha Clínica"}
                        </Badge>
                        {originHint && (
                          <Badge tone="neutral" className="text-[10px] py-0">
                            {originHint}
                          </Badge>
                        )}
                      </div>
                      <p className="truncate text-[11px] text-ink-muted">
                        Atualizado em {formatRecentDate(project.updated_at)}
                      </p>
                    </div>

                    <Button
                      variant="outline"
                      size="xs"
                      onClick={() => onSelectProject(project)}
                      className="shrink-0"
                    >
                      Continuar
                    </Button>
                  </Card>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
