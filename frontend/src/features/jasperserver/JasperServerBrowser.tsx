import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  AlertCircle,
  ArrowUp,
  ChevronRight,
  Database,
  FileCode2,
  FileText,
  Folder,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  SlidersHorizontal,
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
  className?: string;
}

const DEFAULT_SELECTABLE: Array<JasperServerResourceItem["resource_type"]> = [
  "reportUnit",
  "jrxml",
  "jasper",
];

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
  className,
}: JasperServerBrowserProps) {
  const [currentFolder, setCurrentFolder] = useState(initialFolderUri || "/");
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
    setCurrentFolder(initialFolderUri || "/");
    setSearchInput("");
    setActiveQuery("");
    setSelectedItem(null);
    setUnitDetail(null);
    setInspectError(null);
  }, [profileId, initialFolderUri]);

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
        setItems(list);
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

  const handleSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    setActiveQuery(searchInput.trim());
  };

  const handleItemClick = async (item: JasperServerResourceItem) => {
    if (item.resource_type === "folder") {
      setCurrentFolder(item.uri);
      setActiveQuery("");
      setSearchInput("");
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

  return (
    <div className={cn("space-y-3", className)}>
      {/* Search & Folder Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="xs"
          disabled={!parentUri || loading}
          onClick={() => {
            if (parentUri) {
              setCurrentFolder(parentUri);
              setActiveQuery("");
              setSearchInput("");
            }
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
              placeholder="Buscar Report Units ou arquivos na pasta..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="h-8 pl-8 text-xs"
            />
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

      {/* Breadcrumbs */}
      <nav
        aria-label="Caminho do repositório JasperServer"
        className="flex flex-wrap items-center gap-1 rounded-md border border-border bg-surface-subtle/60 px-2.5 py-1.5 font-mono text-[11px] text-ink-secondary"
      >
        {breadcrumbs.map((crumb, idx) => (
          <span key={crumb.uri} className="inline-flex items-center gap-1">
            {idx > 0 && <ChevronRight className="h-3 w-3 text-ink-muted" />}
            <button
              type="button"
              onClick={() => {
                setCurrentFolder(crumb.uri);
                setActiveQuery("");
                setSearchInput("");
              }}
              className="rounded px-1 py-0.5 hover:bg-surface hover:text-ink cursor-pointer"
            >
              {crumb.label}
            </button>
          </span>
        ))}
        {activeQuery && (
          <Badge tone="blueprint" className="ml-auto text-[10px]">
            Busca: {activeQuery}
          </Badge>
        )}
      </nav>

      {errorMsg && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft/70 px-3 py-2 text-xs text-danger"
        >
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Split: Resource List + Inspection Panel */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        <div className="lg:col-span-7">
          <div className="max-h-72 overflow-y-auto rounded-md border border-border bg-surface divide-y divide-border">
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-8 text-xs text-ink-muted">
                <Loader2 className="h-4 w-4 animate-spin" />
                Carregando repositório...
              </div>
            ) : items.length === 0 ? (
              <div className="py-8 text-center text-xs text-ink-muted">
                Nenhum recurso encontrado neste diretório.
              </div>
            ) : (
              items.map((item) => {
                const isSelected = activeSelectedUri === item.uri;
                const isClickable =
                  item.resource_type === "folder" ||
                  selectableTypes.includes(item.resource_type);

                return (
                  <button
                    key={item.uri}
                    type="button"
                    disabled={!isClickable}
                    onClick={() => void handleItemClick(item)}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs transition-colors",
                      isClickable
                        ? "cursor-pointer hover:bg-surface-subtle/70"
                        : "cursor-default opacity-60",
                      isSelected && "bg-accent-soft/60",
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-2">
                      <ResourceIcon type={item.resource_type} />
                      <div className="min-w-0">
                        <p className="truncate font-medium text-ink">
                          {item.label}
                        </p>
                        <p className="truncate font-mono text-[10px] text-ink-muted">
                          {item.uri}
                        </p>
                      </div>
                    </div>
                    <ResourceBadge type={item.resource_type} />
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Report Unit Inspection Panel */}
        <div className="lg:col-span-5">
          <Card className="h-full p-3">
            <h4 className="text-xs font-semibold text-ink">
              Inspeção do Recurso
            </h4>
            {!selectedItem ? (
              <p className="mt-2 text-xs text-ink-muted">
                Selecione uma <strong>Report Unit</strong> ou arquivo{" "}
                <code>.jrxml</code> para visualizar DataSource, Input Controls
                e subreports anexos.
              </p>
            ) : inspecting ? (
              <div className="mt-4 flex items-center gap-2 text-xs text-ink-muted">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Inspecionando Report Unit...
              </div>
            ) : (
              <div className="mt-2.5 space-y-2.5 text-xs">
                <div>
                  <div className="flex items-center gap-1.5">
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
                        <ul className="mt-1 max-h-20 space-y-0.5 overflow-y-auto font-mono text-[10px] text-ink-secondary">
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
                        <ul className="mt-1 max-h-24 space-y-1 overflow-y-auto text-[11px]">
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
