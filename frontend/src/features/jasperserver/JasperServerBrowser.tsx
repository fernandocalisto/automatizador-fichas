import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  AlertCircle,
  ArrowUp,
  ChevronRight,
  Database,
  ExternalLink,
  FileCode2,
  FileText,
  Folder,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Star,
  X,
} from "lucide-react";
import { Badge, Button, Card, Input } from "@/components/ui";
import { cn } from "@/lib/cn";
import type {
  JasperServerReportUnitDetail,
  JasperServerResourceItem,
} from "@/types/studio";
import { jasperServerApi } from "./jasperServerApi";

export interface JasperServerBrowserProps {
  profileId: string;
  initialFolderUri?: string;
  selectedUri?: string | null;
  onSelectResource?: (
    item: JasperServerResourceItem,
    detail: JasperServerReportUnitDetail | null,
  ) => void;
  selectableTypes?: Array<JasperServerResourceItem["resource_type"]>;
  filterTypes?: string[];
  fullHeight?: boolean;
  onQuickImport?: (item: JasperServerResourceItem) => void;
  importingUri?: string | null;
  className?: string;
}

const DEFAULT_SELECTABLE: Array<JasperServerResourceItem["resource_type"]> = [
  "reportUnit",
  "jrxml",
  "jasper",
];

function getLastFolderKey(profileId: string): string {
  return `salutem:js-last-folder:${profileId}`;
}

function getFavFoldersKey(profileId: string): string {
  return `salutem:js-fav-folders:${profileId}`;
}

function readLastFolder(profileId: string, fallback: string): string {
  if (typeof window === "undefined" || !profileId) return fallback || "/";
  try {
    const saved = window.localStorage.getItem(getLastFolderKey(profileId));
    return saved && saved.startsWith("/") ? saved : fallback || "/";
  } catch {
    return fallback || "/";
  }
}

function writeLastFolder(profileId: string, folderUri: string): void {
  if (typeof window === "undefined" || !profileId) return;
  try {
    window.localStorage.setItem(getLastFolderKey(profileId), folderUri);
  } catch {
    // ignore storage errors
  }
}

function readFavoriteFolders(profileId: string): string[] {
  if (typeof window === "undefined" || !profileId) return [];
  try {
    const raw = window.localStorage.getItem(getFavFoldersKey(profileId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((u): u is string => typeof u === "string")
      : [];
  } catch {
    return [];
  }
}

function writeFavoriteFolders(profileId: string, folders: string[]): void {
  if (typeof window === "undefined" || !profileId) return;
  try {
    window.localStorage.setItem(
      getFavFoldersKey(profileId),
      JSON.stringify(folders),
    );
  } catch {
    // ignore storage errors
  }
}

function getParentUri(uri: string): string | null {
  const cleaned = uri.replace(/\/+$/, "");
  if (!cleaned || cleaned === "/") return null;
  const idx = cleaned.lastIndexOf("/");
  if (idx <= 0) return "/";
  return cleaned.slice(0, idx);
}

function splitBreadcrumbs(uri: string): Array<{ label: string; uri: string }> {
  const cleaned = uri.replace(/\/+$/, "");
  if (!cleaned || cleaned === "/") {
    return [{ label: "/", uri: "/" }];
  }
  const segments = cleaned.split("/").filter(Boolean);
  const crumbs: Array<{ label: string; uri: string }> = [
    { label: "/", uri: "/" },
  ];
  let acc = "";
  for (const seg of segments) {
    acc += `/${seg}`;
    crumbs.push({ label: seg, uri: acc });
  }
  return crumbs;
}

function ResourceBadge({
  type,
}: {
  type: JasperServerResourceItem["resource_type"];
}) {
  switch (type) {
    case "reportUnit":
      return <Badge tone="accent">Report Unit</Badge>;
    case "jrxml":
      return <Badge tone="blueprint">.jrxml</Badge>;
    case "jasper":
      return <Badge tone="warning">.jasper</Badge>;
    case "datasource":
      return <Badge tone="success">DataSource</Badge>;
    case "folder":
      return <Badge tone="neutral">Pasta</Badge>;
    default:
      return <Badge tone="neutral">{type}</Badge>;
  }
}

function ResourceIcon({
  type,
}: {
  type: JasperServerResourceItem["resource_type"];
}) {
  switch (type) {
    case "folder":
      return <Folder className="h-4 w-4 shrink-0 text-warning" />;
    case "reportUnit":
      return <Layers className="h-4 w-4 shrink-0 text-accent" />;
    case "jrxml":
      return <FileCode2 className="h-4 w-4 shrink-0 text-blueprint" />;
    case "jasper":
      return <FileText className="h-4 w-4 shrink-0 text-warning" />;
    case "datasource":
      return <Database className="h-4 w-4 shrink-0 text-success" />;
    default:
      return <FileText className="h-4 w-4 shrink-0 text-ink-muted" />;
  }
}

export function JasperServerBrowser({
  profileId,
  initialFolderUri = "/",
  selectedUri,
  onSelectResource,
  selectableTypes = DEFAULT_SELECTABLE,
  filterTypes,
  fullHeight = false,
  onQuickImport,
  importingUri = null,
  className,
}: JasperServerBrowserProps) {
  const [currentFolder, setCurrentFolder] = useState(() =>
    readLastFolder(profileId, initialFolderUri || "/"),
  );
  const [favoriteFolders, setFavoriteFolders] = useState<string[]>(() =>
    readFavoriteFolders(profileId),
  );
  const [searchInput, setSearchInput] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [items, setItems] = useState<JasperServerResourceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [selectedItem, setSelectedItem] =
    useState<JasperServerResourceItem | null>(null);
  const [unitDetail, setUnitDetail] =
    useState<JasperServerReportUnitDetail | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [inspectError, setInspectError] = useState<string | null>(null);

  useEffect(() => {
    setCurrentFolder(readLastFolder(profileId, initialFolderUri || "/"));
    setFavoriteFolders(readFavoriteFolders(profileId));
    setSearchInput("");
    setActiveQuery("");
    setSelectedItem(null);
    setUnitDetail(null);
    setInspectError(null);
  }, [profileId, initialFolderUri]);

  const navigateToFolder = useCallback(
    (nextUri: string) => {
      const normalized = nextUri || "/";
      setCurrentFolder(normalized);
      writeLastFolder(profileId, normalized);
      setActiveQuery("");
      setSearchInput("");
    },
    [profileId],
  );

  const toggleFavoriteFolder = useCallback(
    (uri: string) => {
      setFavoriteFolders((prev) => {
        const exists = prev.includes(uri);
        const next = exists ? prev.filter((u) => u !== uri) : [...prev, uri];
        writeFavoriteFolders(profileId, next);
        return next;
      });
    },
    [profileId],
  );

  const loadResources = useCallback(
    async (folderUri: string, queryText: string) => {
      if (!profileId) return;
      setLoading(true);
      setErrorMsg(null);
      try {
        const list = await jasperServerApi.listResources(profileId, {
          folder_uri: folderUri,
          q: queryText.trim() || undefined,
          recursive: Boolean(queryText.trim()),
          types: filterTypes,
        });
        setItems(Array.isArray(list) ? list : []);
      } catch (err) {
        setErrorMsg(
          err instanceof Error
            ? err.message
            : "Falha ao listar recursos do JasperServer.",
        );
        setItems([]);
      } finally {
        setLoading(false);
      }
    },
    [profileId, filterTypes],
  );

  useEffect(() => {
    void loadResources(currentFolder, activeQuery);
  }, [loadResources, currentFolder, activeQuery]);

  const visibleItems = useMemo(() => {
    const q = searchInput.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) => {
      const hay = `${item.label} ${item.uri} ${item.description}`.toLowerCase();
      return hay.includes(q);
    });
  }, [items, searchInput]);

  const handleSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    setActiveQuery(searchInput.trim());
  };

  const handleItemClick = async (item: JasperServerResourceItem) => {
    if (item.resource_type === "folder") {
      navigateToFolder(item.uri);
      return;
    }

    if (!selectableTypes.includes(item.resource_type)) {
      return;
    }

    setSelectedItem(item);
    setUnitDetail(null);
    setInspectError(null);

    if (item.resource_type === "reportUnit") {
      setInspecting(true);
      try {
        const detail = await jasperServerApi.inspectReportUnit(
          profileId,
          item.uri,
        );
        setUnitDetail(detail);
        onSelectResource?.(item, detail);
      } catch (err) {
        setInspectError(
          err instanceof Error
            ? err.message
            : "Não foi possível inspecionar os detalhes da Report Unit.",
        );
        onSelectResource?.(item, null);
      } finally {
        setInspecting(false);
      }
    } else {
      onSelectResource?.(item, null);
    }
  };

  const parentUri = getParentUri(currentFolder);
  const breadcrumbs = splitBreadcrumbs(currentFolder);
  const activeSelectedUri = selectedUri ?? selectedItem?.uri ?? null;
  const isCurrentFavorite = favoriteFolders.includes(currentFolder);

  return (
    <div
      className={cn(
        fullHeight ? "flex h-full min-h-0 flex-col gap-2.5" : "space-y-3",
        className,
      )}
    >
      {/* Search & Folder Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="xs"
          disabled={!parentUri || loading}
          onClick={() => {
            if (parentUri) navigateToFolder(parentUri);
          }}
          icon={<ArrowUp className="h-3 w-3" />}
        >
          Subir
        </Button>

        <form
          onSubmit={handleSearchSubmit}
          className="flex min-w-[200px] flex-1 items-center gap-1.5"
        >
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
            <Input
              aria-label="Buscar recursos no JasperServer"
              placeholder="Filtrar pasta atual ou Enter para buscar em tudo..."
              value={searchInput}
              onChange={(e) => {
                const nextVal = e.target.value;
                setSearchInput(nextVal);
                if (!nextVal.trim() && activeQuery) {
                  setActiveQuery("");
                }
              }}
              className="h-8 pl-8 pr-7 text-xs"
            />
            {searchInput && (
              <button
                type="button"
                aria-label="Limpar filtro do JasperServer"
                onClick={() => {
                  setSearchInput("");
                  setActiveQuery("");
                }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink cursor-pointer"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <Button type="submit" variant="secondary" size="xs" disabled={loading}>
            Buscar
          </Button>
          {activeQuery && (
            <Button
              variant="ghost"
              size="xs"
              onClick={() => {
                setSearchInput("");
                setActiveQuery("");
              }}
            >
              Limpar
            </Button>
          )}
        </form>

        <Button
          variant="outline"
          size="xs"
          loading={loading}
          onClick={() => void loadResources(currentFolder, activeQuery)}
          icon={<RefreshCw className="h-3 w-3" />}
        >
          Atualizar
        </Button>
      </div>

      {/* Breadcrumbs + Pin Current Folder */}
      <div className="shrink-0 space-y-1.5">
        <div className="flex items-center gap-1.5 rounded-md border border-border bg-surface-subtle/60 px-2.5 py-1.5">
          <nav
            aria-label="Caminho do repositório JasperServer"
            className="flex min-w-0 flex-1 flex-wrap items-center gap-1 font-mono text-[11px] text-ink-secondary"
          >
            {breadcrumbs.map((crumb, idx) => (
              <span key={crumb.uri} className="inline-flex items-center gap-1">
                {idx > 0 && <ChevronRight className="h-3 w-3 text-ink-muted" />}
                <button
                  type="button"
                  onClick={() => navigateToFolder(crumb.uri)}
                  className="rounded px-1 py-0.5 hover:bg-surface hover:text-ink cursor-pointer"
                >
                  {crumb.label}
                </button>
              </span>
            ))}
          </nav>

          {activeQuery && (
            <Badge tone="blueprint" className="shrink-0 text-[10px] py-0">
              Busca servidor: {activeQuery}
            </Badge>
          )}

          <button
            type="button"
            onClick={() => toggleFavoriteFolder(currentFolder)}
            aria-label={
              isCurrentFavorite
                ? "Remover pasta dos favoritos"
                : "Fixar pasta atual nos favoritos"
            }
            title={
              isCurrentFavorite
                ? "Remover pasta dos favoritos"
                : "Fixar pasta atual nos favoritos"
            }
            className={cn(
              "inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors cursor-pointer",
              isCurrentFavorite
                ? "bg-warning-soft text-warning"
                : "text-ink-muted hover:bg-surface hover:text-ink",
            )}
          >
            <Star
              className={cn(
                "h-3 w-3",
                isCurrentFavorite && "fill-warning text-warning",
              )}
            />
            <span className="hidden sm:inline">
              {isCurrentFavorite ? "Fixada" : "Fixar pasta"}
            </span>
          </button>
        </div>

        {/* Pinned Favorite Folders */}
        {favoriteFolders.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className="text-[10px] font-medium uppercase tracking-wide text-ink-muted">
              Pastas fixadas:
            </span>
            {favoriteFolders.map((folderUri) => (
              <span
                key={folderUri}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10px] transition-colors",
                  currentFolder === folderUri
                    ? "border-accent/40 bg-accent-soft text-accent"
                    : "border-border bg-surface text-ink-secondary hover:border-border-strong",
                )}
              >
                <button
                  type="button"
                  onClick={() => navigateToFolder(folderUri)}
                  className="truncate max-w-[200px] cursor-pointer hover:underline"
                >
                  {folderUri}
                </button>
                <button
                  type="button"
                  aria-label={`Desafixar pasta ${folderUri}`}
                  onClick={() => toggleFavoriteFolder(folderUri)}
                  className="text-ink-muted hover:text-ink cursor-pointer"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </span>
            ))}
          </div>
        )}
      </div>

      {errorMsg && (
        <div
          role="alert"
          className="flex shrink-0 items-center gap-2 rounded-md border border-danger/30 bg-danger-soft/70 px-3 py-2 text-xs text-danger"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Split: Resource List + Inspection Panel */}
      <div
        className={cn(
          "grid grid-cols-1 gap-3 lg:grid-cols-12",
          fullHeight && "min-h-0 flex-1",
        )}
      >
        <div
          className={cn(
            fullHeight
              ? "flex min-h-0 flex-col lg:col-span-7 xl:col-span-8"
              : "lg:col-span-7",
          )}
        >
          <div
            className={cn(
              "overflow-y-auto rounded-md border border-border bg-surface divide-y divide-border",
              fullHeight ? "min-h-0 flex-1" : "max-h-72",
            )}
          >
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-10 text-xs text-ink-muted">
                <Loader2 className="h-4 w-4 animate-spin" />
                Carregando repositório...
              </div>
            ) : visibleItems.length === 0 ? (
              <div className="py-10 text-center text-xs text-ink-muted">
                {items.length > 0 && searchInput.trim()
                  ? "Nenhum item nesta pasta corresponde ao filtro local. Pressione Enter para buscar no servidor inteiro."
                  : "Nenhum recurso encontrado neste diretório."}
              </div>
            ) : (
              visibleItems.map((item) => {
                const isSelected = activeSelectedUri === item.uri;
                const isImportable = selectableTypes.includes(
                  item.resource_type,
                );
                const isClickable =
                  item.resource_type === "folder" || isImportable;
                const isImportingThis = importingUri === item.uri;

                return (
                  <div
                    key={item.uri}
                    onDoubleClick={() => {
                      if (isImportable && onQuickImport && !importingUri) {
                        onQuickImport(item);
                      }
                    }}
                    className={cn(
                      "group flex w-full items-center justify-between gap-2 px-3 py-2 text-xs transition-colors",
                      isClickable
                        ? "hover:bg-surface-subtle/70"
                        : "opacity-60",
                      isSelected && "bg-accent-soft/60",
                    )}
                  >
                    <button
                      type="button"
                      disabled={!isClickable}
                      onClick={() => void handleItemClick(item)}
                      className={cn(
                        "flex min-w-0 flex-1 items-center gap-2 text-left",
                        isClickable ? "cursor-pointer" : "cursor-default",
                      )}
                    >
                      <ResourceIcon type={item.resource_type} />
                      <div className="min-w-0">
                        <p className="truncate font-medium text-ink">
                          {item.label}
                        </p>
                        <p className="truncate font-mono text-[10px] text-ink-muted">
                          {item.uri}
                        </p>
                      </div>
                    </button>

                    <div className="flex shrink-0 items-center gap-2">
                      <ResourceBadge type={item.resource_type} />
                      {onQuickImport && isImportable && (
                        <Button
                          variant="primary"
                          size="xs"
                          loading={isImportingThis}
                          disabled={Boolean(importingUri)}
                          onClick={() => onQuickImport(item)}
                          icon={<ExternalLink className="h-3 w-3" />}
                        >
                          Abrir no Studio
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Report Unit Inspection Panel */}
        <div
          className={cn(
            fullHeight
              ? "flex min-h-0 flex-col lg:col-span-5 xl:col-span-4"
              : "lg:col-span-5",
          )}
        >
          <Card
            className={cn(
              "p-3",
              fullHeight ? "min-h-0 flex-1 overflow-y-auto" : "h-full",
            )}
          >
            <h4 className="text-xs font-semibold text-ink">
              Inspeção do Recurso
            </h4>
            {!selectedItem ? (
              <p className="mt-2 text-xs text-ink-muted">
                Selecione uma <strong>Report Unit</strong> ou arquivo{" "}
                <code>.jrxml</code> para visualizar DataSource, Input Controls
                e subreports anexos.
                {onQuickImport && (
                  <>
                    {" "}
                    Dê <strong>duplo clique</strong> ou clique em{" "}
                    <strong>Abrir no Studio</strong> para começar a editar.
                  </>
                )}
              </p>
            ) : inspecting ? (
              <div className="mt-4 flex items-center gap-2 text-xs text-ink-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Inspecionando Report Unit...
              </div>
            ) : (
              <div className="mt-2.5 space-y-2.5 text-xs">
                <div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-semibold text-ink">
                      {unitDetail?.label || selectedItem.label}
                    </span>
                    <ResourceBadge type={selectedItem.resource_type} />
                  </div>
                  <p className="mt-0.5 break-all font-mono text-[10px] text-ink-muted">
                    {selectedItem.uri}
                  </p>
                  {(unitDetail?.description || selectedItem.description) && (
                    <p className="mt-1 text-[11px] text-ink-secondary">
                      {unitDetail?.description || selectedItem.description}
                    </p>
                  )}
                </div>

                {onQuickImport &&
                  selectableTypes.includes(selectedItem.resource_type) && (
                    <Button
                      variant="primary"
                      size="sm"
                      loading={importingUri === selectedItem.uri}
                      disabled={Boolean(importingUri)}
                      onClick={() => onQuickImport(selectedItem)}
                      icon={<ExternalLink className="h-3.5 w-3.5" />}
                      className="w-full"
                    >
                      Abrir no Studio
                    </Button>
                  )}

                {inspectError && (
                  <div className="rounded border border-warning/30 bg-warning-soft/70 px-2 py-1.5 text-[11px] text-warning">
                    {inspectError}
                  </div>
                )}

                {unitDetail && (
                  <>
                    <div className="space-y-1 border-t border-border pt-2">
                      <div className="text-[11px]">
                        <span className="font-medium text-ink-secondary">
                          JRXML Principal:
                        </span>{" "}
                        <code className="break-all text-[10px] text-ink">
                          {unitDetail.main_jrxml_uri || "—"}
                        </code>
                      </div>
                      <div className="text-[11px]">
                        <span className="font-medium text-ink-secondary">
                          DataSource:
                        </span>{" "}
                        <code className="break-all text-[10px] text-ink">
                          {unitDetail.datasource_uri || "Não vinculado"}
                        </code>
                      </div>
                    </div>

                    <div className="border-t border-border pt-2">
                      <div className="flex items-center gap-1 text-[11px] font-medium text-ink-secondary">
                        <SlidersHorizontal className="h-3 w-3" />
                        Input Controls ({unitDetail.input_controls.length})
                      </div>
                      {unitDetail.input_controls.length === 0 ? (
                        <p className="mt-0.5 text-[11px] text-ink-muted">
                          Nenhum input control declarado.
                        </p>
                      ) : (
                        <ul className="mt-1 max-h-24 space-y-0.5 overflow-y-auto font-mono text-[10px] text-ink-secondary">
                          {unitDetail.input_controls.map((ic) => (
                            <li key={ic} className="truncate">
                              • {ic}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="border-t border-border pt-2">
                      <div className="text-[11px] font-medium text-ink-secondary">
                        Recursos Embutidos ({unitDetail.resources.length})
                      </div>
                      {unitDetail.resources.length === 0 ? (
                        <p className="mt-0.5 text-[11px] text-ink-muted">
                          Sem recursos em <code>_files</code> listados (subreports{" "}
                          <code>repo:/...</code> serão detectados no JRXML).
                        </p>
                      ) : (
                        <ul className="mt-1 max-h-28 space-y-1 overflow-y-auto text-[11px]">
                          {unitDetail.resources.map((res) => (
                            <li
                              key={res.uri}
                              className="flex items-center justify-between gap-2 font-mono text-[10px]"
                            >
                              <span className="truncate text-ink">
                                {res.name}
                              </span>
                              <Badge tone="neutral" className="text-[10px]">
                                {res.type}
                              </Badge>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  </>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
