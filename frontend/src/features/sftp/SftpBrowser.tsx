import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowUp,
  ChevronRight,
  ExternalLink,
  File,
  FileCode2,
  FileCog,
  Folder,
  RefreshCw,
  Search,
  Sparkles,
  X,
} from "lucide-react";
import { Badge, Button, Input } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { SftpListResult, SftpRemoteEntry } from "@/types/studio";
import { sftpApi } from "./sftpApi";

export interface SftpBrowserProps {
  profileId: string;
  initialPath?: string;
  selectedPath?: string | null;
  selectableKinds?: Array<"jrxml" | "jasper">;
  onSelectFile?: (entry: SftpRemoteEntry) => void;
  onPathChange?: (currentPath: string) => void;
  fullHeight?: boolean;
  onQuickImport?: (entry: SftpRemoteEntry) => void;
  importingPath?: string | null;
  className?: string;
}

function getLastPathKey(profileId: string): string {
  return `salutem:sftp-last-folder:${profileId}`;
}

function readLastSftpPath(
  profileId: string,
  fallback?: string,
): string | undefined {
  if (typeof window === "undefined" || !profileId) return fallback;
  try {
    const saved = window.localStorage.getItem(getLastPathKey(profileId));
    return saved || fallback;
  } catch {
    return fallback;
  }
}

function writeLastSftpPath(profileId: string, path: string): void {
  if (typeof window === "undefined" || !profileId || !path) return;
  try {
    window.localStorage.setItem(getLastPathKey(profileId), path);
  } catch {
    // ignore storage errors
  }
}

function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function formatShortDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "2-digit",
    });
  } catch {
    return "";
  }
}

export function SftpBrowser({
  profileId,
  initialPath,
  selectedPath = null,
  selectableKinds = ["jrxml", "jasper"],
  onSelectFile,
  onPathChange,
  fullHeight = false,
  onQuickImport,
  importingPath = null,
  className,
}: SftpBrowserProps) {
  const [currentPath, setCurrentPath] = useState<string | undefined>(() =>
    readLastSftpPath(profileId, initialPath),
  );
  const [searchInput, setSearchInput] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [listing, setListing] = useState<SftpListResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    setCurrentPath(readLastSftpPath(profileId, initialPath));
    setSearchInput("");
    setAppliedSearch("");
  }, [profileId, initialPath]);

  const fetchDirectory = useCallback(
    async (targetPath?: string, searchTerm?: string) => {
      if (!profileId) return;
      setLoading(true);
      setErrorMsg(null);
      try {
        const res = await sftpApi.browse(profileId, {
          path: targetPath,
          search: searchTerm?.trim() || undefined,
        });
        setListing(res);
        setCurrentPath(res.current_path);
        writeLastSftpPath(profileId, res.current_path);
        onPathChange?.(res.current_path);
      } catch (err) {
        setErrorMsg(
          err instanceof Error
            ? err.message
            : "Falha ao listar diretório SFTP.",
        );
      } finally {
        setLoading(false);
      }
    },
    [profileId, onPathChange],
  );

  useEffect(() => {
    void fetchDirectory(
      readLastSftpPath(profileId, initialPath),
      appliedSearch,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profileId, appliedSearch]);

  const visibleEntries = useMemo(() => {
    const entries = listing?.entries ?? [];
    const q = searchInput.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((entry) => entry.name.toLowerCase().includes(q));
  }, [listing?.entries, searchInput]);

  const breadcrumbs = useMemo(() => {
    const path = listing?.current_path || currentPath || "/";
    if (path === "/") {
      return [{ label: "/", path: "/" }];
    }
    const parts = path.split("/").filter(Boolean);
    const items: Array<{ label: string; path: string }> = [
      { label: "/", path: "/" },
    ];
    let acc = "";
    for (const part of parts) {
      acc += `/${part}`;
      items.push({ label: part, path: acc });
    }
    return items;
  }, [listing?.current_path, currentPath]);

  const handleNavigate = (targetPath: string) => {
    void fetchDirectory(targetPath, appliedSearch);
  };

  const handleSearchSubmit = () => {
    setAppliedSearch(searchInput.trim());
  };

  const handleEntryClick = (entry: SftpRemoteEntry) => {
    if (entry.is_dir) {
      handleNavigate(entry.path);
      return;
    }
    if (
      (entry.kind === "jrxml" || entry.kind === "jasper") &&
      selectableKinds.includes(entry.kind)
    ) {
      onSelectFile?.(entry);
    }
  };

  return (
    <div
      className={cn(
        "flex flex-col rounded-md border border-border bg-surface overflow-hidden",
        fullHeight && "h-full min-h-0",
        className,
      )}
    >
      {/* Toolbar: Parent + Breadcrumbs + Search + Refresh */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-surface-subtle/60 px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto">
          <Button
            variant="ghost"
            size="xs"
            disabled={loading || !listing?.parent_path}
            onClick={() => {
              if (listing?.parent_path) handleNavigate(listing.parent_path);
            }}
            icon={<ArrowUp className="h-3.5 w-3.5" />}
            title="Pasta anterior"
          >
            Subir
          </Button>

          <nav
            aria-label="Caminho SFTP"
            className="flex items-center gap-0.5 text-xs font-mono text-ink-secondary"
          >
            {breadcrumbs.map((crumb, idx) => {
              const isLast = idx === breadcrumbs.length - 1;
              return (
                <span
                  key={crumb.path}
                  className="inline-flex items-center gap-0.5"
                >
                  {idx > 0 && (
                    <ChevronRight className="h-3 w-3 text-ink-muted shrink-0" />
                  )}
                  <button
                    type="button"
                    disabled={loading || isLast}
                    onClick={() => handleNavigate(crumb.path)}
                    className={cn(
                      "rounded px-1 py-0.5 transition-colors",
                      isLast
                        ? "font-semibold text-ink cursor-default"
                        : "hover:bg-surface hover:text-ink cursor-pointer",
                    )}
                  >
                    {crumb.label}
                  </button>
                </span>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-1.5">
          <div className="relative w-52">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
            <Input
              value={searchInput}
              onChange={(e) => {
                const nextVal = e.target.value;
                setSearchInput(nextVal);
                if (!nextVal.trim() && appliedSearch) {
                  setAppliedSearch("");
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  handleSearchSubmit();
                }
              }}
              placeholder="Filtrar arquivos..."
              aria-label="Filtrar arquivos SFTP"
              className="h-7 pl-7 pr-6 text-xs"
            />
            {searchInput && (
              <button
                type="button"
                aria-label="Limpar filtro SFTP"
                onClick={() => {
                  setSearchInput("");
                  setAppliedSearch("");
                }}
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <Button
            variant="outline"
            size="xs"
            onClick={handleSearchSubmit}
            disabled={loading}
          >
            Filtrar
          </Button>
          <Button
            variant="ghost"
            size="xs"
            loading={loading}
            onClick={() => void fetchDirectory(currentPath, appliedSearch)}
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            aria-label="Atualizar pasta SFTP"
          />
        </div>
      </div>

      {/* Error banner */}
      {errorMsg && (
        <div
          role="alert"
          className="flex shrink-0 items-center gap-2 border-b border-danger/20 bg-danger-soft px-3 py-2 text-xs text-danger"
        >
          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{errorMsg}</span>
        </div>
      )}

      {/* Entries List */}
      <div
        className={cn(
          "overflow-y-auto divide-y divide-border/60",
          fullHeight ? "min-h-0 flex-1" : "max-h-64 min-h-[160px]",
        )}
      >
        {loading && !listing ? (
          <div className="px-4 py-8 text-center text-xs text-ink-muted">
            Carregando diretório remoto...
          </div>
        ) : !listing || visibleEntries.length === 0 ? (
          <div className="px-4 py-8 text-center text-xs text-ink-muted">
            Nenhum item encontrado neste diretório.
          </div>
        ) : (
          visibleEntries.map((entry) => {
            const isImportable =
              !entry.is_dir &&
              (entry.kind === "jrxml" || entry.kind === "jasper") &&
              selectableKinds.includes(entry.kind);
            const isSelectable = entry.is_dir || isImportable;
            const isSelected = selectedPath === entry.path;
            const isImportingThis = importingPath === entry.path;

            return (
              <div
                key={entry.path}
                onDoubleClick={() => {
                  if (isImportable && onQuickImport && !importingPath) {
                    onQuickImport(entry);
                  }
                }}
                className={cn(
                  "flex w-full items-center justify-between gap-2 px-3 py-2 text-xs transition-colors",
                  isSelected
                    ? "bg-accent-soft/70 text-ink"
                    : isSelectable
                      ? "hover:bg-surface-subtle/70 text-ink"
                      : "opacity-55 text-ink-muted",
                )}
              >
                <button
                  type="button"
                  disabled={!isSelectable}
                  onClick={() => handleEntryClick(entry)}
                  className={cn(
                    "flex min-w-0 flex-1 items-center gap-2 text-left",
                    isSelectable ? "cursor-pointer" : "cursor-not-allowed",
                  )}
                >
                  {entry.is_dir ? (
                    <Folder className="h-4 w-4 shrink-0 text-warning" />
                  ) : entry.kind === "jrxml" ? (
                    <FileCode2 className="h-4 w-4 shrink-0 text-accent" />
                  ) : entry.kind === "jasper" ? (
                    <FileCog className="h-4 w-4 shrink-0 text-blueprint" />
                  ) : (
                    <File className="h-4 w-4 shrink-0 text-ink-muted" />
                  )}

                  <span className="truncate font-mono">{entry.name}</span>

                  {entry.kind === "jrxml" && (
                    <Badge tone="accent" className="text-[10px] py-0">
                      .jrxml
                    </Badge>
                  )}

                  {entry.kind === "jasper" && (
                    <>
                      <Badge tone="blueprint" className="text-[10px] py-0">
                        .jasper
                      </Badge>
                      <Badge
                        tone="warning"
                        className="text-[10px] py-0"
                        title="Será decompilado automaticamente para .jrxml pela JVM ao importar"
                      >
                        <Sparkles className="h-2.5 w-2.5" />
                        Decompila automático
                      </Badge>
                    </>
                  )}

                  {entry.has_paired_file && (
                    <Badge tone="neutral" className="text-[10px] py-0">
                      Par .jrxml/.jasper
                    </Badge>
                  )}
                </button>

                <div className="flex shrink-0 items-center gap-3 text-[11px] text-ink-muted tabular-nums">
                  {!entry.is_dir && (
                    <span>{formatFileSize(entry.size_bytes)}</span>
                  )}
                  {entry.modified_at && (
                    <span className="hidden sm:inline">
                      {formatShortDate(entry.modified_at)}
                    </span>
                  )}
                  {onQuickImport && isImportable && (
                    <Button
                      variant="primary"
                      size="xs"
                      loading={isImportingThis}
                      disabled={Boolean(importingPath)}
                      onClick={() => onQuickImport(entry)}
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
  );
}
