import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import {
  Building2,
  CornerDownLeft,
  Database,
  FileCode2,
  FolderKanban,
  Layers,
  Loader2,
  Search,
  Server,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui";
import { clientsApi } from "@/features/clients/clientsApi";
import { jasperServerApi } from "@/features/jasperserver/jasperServerApi";
import { sftpApi } from "@/features/sftp/sftpApi";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { SettingsTabId } from "@/types/feature-props";
import type {
  ClientUnitRead,
  DbProfileRead,
  JasperServerProfileRead,
  ProjectRead,
  SftpProfileRead,
} from "@/types/studio";

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  projects: ProjectRead[];
  onSelectProject: (project: ProjectRead) => void;
  onSelectClient: (clientId: string) => void;
  onOpenSettingsTab: (tab: SettingsTabId) => void;
}

type CategoryId =
  | "clients"
  | "projects"
  | "db_profiles"
  | "sftp_profiles"
  | "jasperserver_profiles";

interface PaletteItem {
  id: string;
  category: CategoryId;
  title: string;
  subtitle?: string;
  badge?: string;
  badgeTone?: "neutral" | "accent" | "blueprint" | "success" | "warning" | "danger";
  icon: ReactNode;
  onSelect: () => void;
}

const CATEGORY_META: Record<CategoryId, { label: string }> = {
  clients: { label: "Clientes" },
  projects: { label: "Projetos" },
  db_profiles: { label: "Bancos PostgreSQL" },
  sftp_profiles: { label: "Servidores SFTP" },
  jasperserver_profiles: { label: "JasperReports Servers" },
};

const CATEGORY_ORDER: CategoryId[] = [
  "clients",
  "projects",
  "jasperserver_profiles",
  "sftp_profiles",
  "db_profiles",
];

function envBadgeTone(
  env?: string,
): "danger" | "warning" | "blueprint" | "neutral" {
  if (env === "PRD") return "danger";
  if (env === "HML") return "warning";
  if (env === "DEV") return "blueprint";
  return "neutral";
}

export function CommandPalette({
  open,
  onClose,
  projects,
  onSelectProject,
  onSelectClient,
  onOpenSettingsTab,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(false);

  const [clients, setClients] = useState<ClientUnitRead[]>([]);
  const [dbProfiles, setDbProfiles] = useState<DbProfileRead[]>([]);
  const [sftpProfiles, setSftpProfiles] = useState<SftpProfileRead[]>([]);
  const [jasperProfiles, setJasperProfiles] = useState<
    JasperServerProfileRead[]
  >([]);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    window.setTimeout(() => inputRef.current?.focus(), 0);

    let active = true;
    setLoading(true);
    Promise.allSettled([
      clientsApi.listClients(),
      api.listDbProfiles(),
      sftpApi.listProfiles(),
      jasperServerApi.listProfiles(),
    ])
      .then(([clientsRes, dbRes, sftpRes, jsRes]) => {
        if (!active) return;
        if (clientsRes.status === "fulfilled" && Array.isArray(clientsRes.value)) {
          setClients(clientsRes.value);
        }
        if (dbRes.status === "fulfilled" && Array.isArray(dbRes.value)) {
          setDbProfiles(dbRes.value);
        }
        if (sftpRes.status === "fulfilled" && Array.isArray(sftpRes.value)) {
          setSftpProfiles(sftpRes.value);
        }
        if (jsRes.status === "fulfilled" && Array.isArray(jsRes.value)) {
          setJasperProfiles(jsRes.value);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [open]);

  const sections = useMemo(() => {
    const q = query.trim().toLowerCase();
    const limitPerGroup = q ? 8 : 5;

    const matchedClients: PaletteItem[] = clients
      .filter((c) => {
        if (!q) return true;
        const hay = [
          c.name,
          c.unit_code,
          c.external_id ?? "",
          c.hosting,
          ...c.tags,
          ...c.systems.map((s) => `${s.label} ${s.system_url}`),
        ]
          .join(" ")
          .toLowerCase();
        return hay.includes(q);
      })
      .slice(0, limitPerGroup)
      .map((c) => ({
        id: `client:${c.id}`,
        category: "clients",
        title: c.name,
        subtitle: [
          c.unit_code,
          c.external_id ? `ID ${c.external_id}` : null,
          `${c.systems.length} ${c.systems.length === 1 ? "sistema" : "sistemas"}`,
        ]
          .filter(Boolean)
          .join(" · "),
        badge: c.hosting || undefined,
        badgeTone: "neutral",
        icon: <Building2 className="h-4 w-4 text-accent" />,
        onSelect: () => {
          onSelectClient(c.id);
          onClose();
        },
      }));

    const matchedProjects: PaletteItem[] = projects
      .filter((p) => {
        if (!q) return true;
        const hay = `${p.name} ${p.slug} ${p.description}`.toLowerCase();
        return hay.includes(q);
      })
      .slice(0, limitPerGroup)
      .map((p) => {
        const isFree = p.project_kind === "free_report";
        return {
          id: `project:${p.id}`,
          category: "projects",
          title: p.name,
          subtitle: p.slug,
          badge: isFree ? "Relatório" : "Ficha Clínica",
          badgeTone: isFree ? "blueprint" : "accent",
          icon: isFree ? (
            <FileCode2 className="h-4 w-4 text-blueprint" />
          ) : (
            <FolderKanban className="h-4 w-4 text-accent" />
          ),
          onSelect: () => {
            onSelectProject(p);
            onClose();
          },
        };
      });

    const matchedJasper: PaletteItem[] = jasperProfiles
      .filter((jp) => {
        if (!q) return true;
        const hay =
          `${jp.name} ${jp.base_url} ${jp.organization} ${jp.environment}`.toLowerCase();
        return hay.includes(q);
      })
      .slice(0, limitPerGroup)
      .map((jp) => ({
        id: `jasper:${jp.id}`,
        category: "jasperserver_profiles",
        title: jp.name,
        subtitle: jp.base_url,
        badge: jp.environment,
        badgeTone: envBadgeTone(jp.environment),
        icon: <Layers className="h-4 w-4 text-accent" />,
        onSelect: () => {
          onOpenSettingsTab("jasperserver_profiles");
          onClose();
        },
      }));

    const matchedSftp: PaletteItem[] = sftpProfiles
      .filter((sp) => {
        if (!q) return true;
        const hay =
          `${sp.name} ${sp.host} ${sp.username} ${sp.remote_base_dir} ${sp.environment}`.toLowerCase();
        return hay.includes(q);
      })
      .slice(0, limitPerGroup)
      .map((sp) => ({
        id: `sftp:${sp.id}`,
        category: "sftp_profiles",
        title: sp.name,
        subtitle: `${sp.username ? `${sp.username}@` : ""}${sp.host}:${sp.port}`,
        badge: sp.environment,
        badgeTone: envBadgeTone(sp.environment),
        icon: <Server className="h-4 w-4 text-ink-secondary" />,
        onSelect: () => {
          onOpenSettingsTab("sftp_profiles");
          onClose();
        },
      }));

    const matchedDb: PaletteItem[] = dbProfiles
      .filter((db) => {
        if (!q) return true;
        const hay =
          `${db.name} ${db.host} ${db.dbname} ${db.user} ${db.environment ?? ""}`.toLowerCase();
        return hay.includes(q);
      })
      .slice(0, limitPerGroup)
      .map((db) => ({
        id: `db:${db.id}`,
        category: "db_profiles",
        title: db.name,
        subtitle: `${db.host}:${db.port}/${db.dbname || "—"}`,
        badge: db.environment || "PG",
        badgeTone: envBadgeTone(db.environment),
        icon: <Database className="h-4 w-4 text-success" />,
        onSelect: () => {
          onOpenSettingsTab("db_profiles");
          onClose();
        },
      }));

    const byCategory: Record<CategoryId, PaletteItem[]> = {
      clients: matchedClients,
      projects: matchedProjects,
      jasperserver_profiles: matchedJasper,
      sftp_profiles: matchedSftp,
      db_profiles: matchedDb,
    };

    return CATEGORY_ORDER.map((cat) => ({
      id: cat,
      label: CATEGORY_META[cat].label,
      items: byCategory[cat],
    })).filter((section) => section.items.length > 0);
  }, [
    query,
    clients,
    projects,
    dbProfiles,
    sftpProfiles,
    jasperProfiles,
    onSelectClient,
    onSelectProject,
    onOpenSettingsTab,
    onClose,
  ]);

  const flatItems = useMemo(
    () => sections.flatMap((sec) => sec.items),
    [sections],
  );

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const activeEl = listRef.current?.querySelector<HTMLElement>(
      `[data-palette-index="${activeIndex}"]`,
    );
    activeEl?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, open]);

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (flatItems.length > 0) {
        setActiveIndex((idx) => (idx + 1) % flatItems.length);
      }
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (flatItems.length > 0) {
        setActiveIndex((idx) => (idx - 1 + flatItems.length) % flatItems.length);
      }
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const target = flatItems[activeIndex];
      if (target) {
        target.onSelect();
      }
    }
  };

  if (!open) return null;

  let runningIndex = 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 px-4 pt-[10vh] backdrop-blur-[1px]"
      role="dialog"
      aria-modal="true"
      aria-label="Busca global"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[76vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-border-strong bg-surface-elevated shadow-2xl">
        {/* Search Input */}
        <div className="flex items-center gap-2.5 border-b border-border bg-surface px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-ink-muted" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Buscar clientes, projetos, bancos PostgreSQL, SFTP ou JasperServer..."
            aria-label="Buscar clientes, projetos, bancos, SFTP ou JasperServer"
            className="w-full bg-transparent text-sm text-ink placeholder:text-ink-muted focus:outline-none"
          />
          {loading && (
            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-ink-muted" />
          )}
          {query && (
            <button
              type="button"
              onClick={() => setQuery("")}
              aria-label="Limpar busca"
              className="rounded p-1 text-ink-muted hover:bg-surface-subtle hover:text-ink cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Fechar busca global"
            className="rounded border border-border bg-surface-subtle px-1.5 py-0.5 font-mono text-[10px] text-ink-muted hover:text-ink cursor-pointer"
          >
            Esc
          </button>
        </div>

        {/* Results */}
        <div
          ref={listRef}
          role="listbox"
          aria-label="Resultados da busca"
          className="min-h-0 flex-1 overflow-y-auto p-2"
        >
          {flatItems.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <p className="text-sm font-medium text-ink">
                {loading
                  ? "Carregando catálogo..."
                  : "Nenhum resultado encontrado"}
              </p>
              {!loading && (
                <p className="mt-1 text-xs text-ink-muted">
                  Tente outro nome de cliente, código, host, banco ou relatório.
                </p>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {sections.map((section) => (
                <div key={section.id}>
                  <div className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-muted">
                    {section.label}
                  </div>
                  <div className="space-y-0.5">
                    {section.items.map((item) => {
                      const idx = runningIndex++;
                      const isActive = idx === activeIndex;
                      return (
                        <button
                          key={item.id}
                          type="button"
                          role="option"
                          aria-selected={isActive}
                          data-palette-index={idx}
                          onMouseEnter={() => setActiveIndex(idx)}
                          onClick={item.onSelect}
                          className={cn(
                            "flex w-full items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-left transition-colors cursor-pointer",
                            isActive
                              ? "bg-accent-soft/80 text-ink"
                              : "text-ink hover:bg-surface-subtle/80",
                          )}
                        >
                          <div className="flex min-w-0 items-center gap-2.5">
                            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface">
                              {item.icon}
                            </span>
                            <div className="min-w-0">
                              <p className="truncate text-xs font-semibold text-ink">
                                {item.title}
                              </p>
                              {item.subtitle && (
                                <p className="truncate font-mono text-[11px] text-ink-muted">
                                  {item.subtitle}
                                </p>
                              )}
                            </div>
                          </div>

                          <div className="flex shrink-0 items-center gap-2">
                            {item.badge && (
                              <Badge
                                tone={item.badgeTone ?? "neutral"}
                                className="text-[10px] py-0"
                              >
                                {item.badge}
                              </Badge>
                            )}
                            {isActive && (
                              <CornerDownLeft className="h-3.5 w-3.5 text-accent" />
                            )}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer keyboard hints */}
        <div className="flex items-center justify-between border-t border-border bg-surface-subtle/60 px-4 py-2 text-[11px] text-ink-muted">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="rounded border border-border bg-surface px-1 py-0.5 font-mono text-[10px]">
                ↑↓
              </kbd>{" "}
              navegar
            </span>
            <span>
              <kbd className="rounded border border-border bg-surface px-1 py-0.5 font-mono text-[10px]">
                Enter
              </kbd>{" "}
              abrir
            </span>
            <span>
              <kbd className="rounded border border-border bg-surface px-1 py-0.5 font-mono text-[10px]">
                Esc
              </kbd>{" "}
              fechar
            </span>
          </div>
          <span className="tabular-nums">
            {flatItems.length}{" "}
            {flatItems.length === 1 ? "item" : "itens"}
          </span>
        </div>
      </div>
    </div>
  );
}
