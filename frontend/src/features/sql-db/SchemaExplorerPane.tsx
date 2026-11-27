import { useCallback, useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Database,
  KeyRound,
  Link2,
  Plus,
  RefreshCw,
  Search,
  Table2,
  X,
} from "lucide-react";
import { Badge, Button, Input, Select } from "@/components/ui";
import type { TableSchemaDetail, TableSummary } from "@/types/studio";
import {
  describeProfileTable,
  listProfileSchemas,
  listProfileTables,
} from "./workbenchApi";

export interface SchemaExplorerPaneProps {
  profileId: string;
  onInsertSqlSnippet?: (snippet: string) => void;
  onClose?: () => void;
}

export function SchemaExplorerPane({
  profileId,
  onInsertSqlSnippet,
  onClose,
}: SchemaExplorerPaneProps) {
  const [schemas, setSchemas] = useState<string[]>(["public"]);
  const [selectedSchema, setSelectedSchema] = useState("public");
  const [search, setSearch] = useState("");
  const [tables, setTables] = useState<TableSummary[]>([]);
  const [loadingSchemas, setLoadingSchemas] = useState(false);
  const [loadingTables, setLoadingTables] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [expandedTable, setExpandedTable] = useState<string | null>(null);
  const [detailsByKey, setDetailsByKey] = useState<
    Record<string, TableSchemaDetail>
  >({});
  const [loadingDetailKey, setLoadingDetailKey] = useState<string | null>(null);

  const loadSchemas = useCallback(async () => {
    if (!profileId) return;
    setLoadingSchemas(true);
    setError(null);
    try {
      const list = await listProfileSchemas(profileId);
      const nextSchemas = list.length > 0 ? list : ["public"];
      setSchemas(nextSchemas);
      setSelectedSchema((prev) =>
        nextSchemas.includes(prev) ? prev : nextSchemas[0],
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingSchemas(false);
    }
  }, [profileId]);

  const loadTables = useCallback(
    async (schemaName: string, searchTerm: string) => {
      if (!profileId) return;
      setLoadingTables(true);
      setError(null);
      try {
        const list = await listProfileTables(profileId, {
          schema: schemaName,
          search: searchTerm.trim() || undefined,
          limit: 120,
        });
        setTables(list);
      } catch (err) {
        setTables([]);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoadingTables(false);
      }
    },
    [profileId],
  );

  useEffect(() => {
    setExpandedTable(null);
    setDetailsByKey({});
    if (!profileId) {
      setTables([]);
      return;
    }
    void loadSchemas();
  }, [profileId, loadSchemas]);

  useEffect(() => {
    if (!profileId || !selectedSchema) return;
    const timer = window.setTimeout(() => {
      void loadTables(selectedSchema, search);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [profileId, selectedSchema, search, loadTables]);

  const handleToggleTable = async (tableName: string) => {
    const key = `${selectedSchema}.${tableName}`;
    if (expandedTable === key) {
      setExpandedTable(null);
      return;
    }
    setExpandedTable(key);
    if (detailsByKey[key]) return;

    setLoadingDetailKey(key);
    try {
      const detail = await describeProfileTable(
        profileId,
        tableName,
        selectedSchema,
      );
      setDetailsByKey((prev) => ({ ...prev, [key]: detail }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingDetailKey((prev) => (prev === key ? null : prev));
    }
  };

  return (
    <aside
      aria-label="Schema Explorer PostgreSQL"
      className="flex h-full w-72 shrink-0 flex-col border-r border-border bg-surface text-xs"
    >
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <div className="flex items-center gap-1.5 font-semibold text-ink">
          <Database className="h-3.5 w-3.5 text-blueprint" />
          <span>Schema Explorer</span>
          <Badge tone="neutral" className="text-[10px]">
            RO
          </Badge>
        </div>

        <div className="flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="h-6 w-6"
            disabled={!profileId || loadingTables}
            onClick={() => void loadTables(selectedSchema, search)}
            title="Atualizar tabelas"
            aria-label="Atualizar tabelas do schema"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${loadingTables || loadingSchemas ? "animate-spin" : ""}`}
            />
          </Button>
          {onClose && (
            <Button
              size="icon"
              variant="ghost"
              className="h-6 w-6"
              onClick={onClose}
              title="Recolher Schema Explorer"
              aria-label="Recolher Schema Explorer"
            >
              <X className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      </div>

      {!profileId ? (
        <div className="p-3 text-ink-muted">
          Selecione um perfil PostgreSQL para explorar schemas, tabelas e
          colunas.
        </div>
      ) : (
        <>
          <div className="space-y-2 border-b border-border bg-surface-subtle/40 p-2.5">
            <Select
              aria-label="Schema PostgreSQL"
              value={selectedSchema}
              onChange={(e) => setSelectedSchema(e.target.value)}
              className="h-7 text-xs font-mono"
            >
              {schemas.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>

            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-2 h-3.5 w-3.5 text-ink-muted" />
              <Input
                aria-label="Filtrar tabelas"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar tabela ou view..."
                className="h-7 pl-7 text-xs"
              />
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="border-b border-danger/30 bg-danger-soft/70 px-2.5 py-2 text-[11px] text-danger"
            >
              {error}
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto divide-y divide-border/60">
            {loadingTables && tables.length === 0 ? (
              <div className="p-3 text-ink-muted">Carregando tabelas...</div>
            ) : tables.length === 0 ? (
              <div className="p-3 text-ink-muted">
                Nenhuma tabela encontrada em <code className="font-mono">{selectedSchema}</code>.
              </div>
            ) : (
              tables.map((tbl) => {
                const key = `${tbl.schema_name}.${tbl.table_name}`;
                const isExpanded = expandedTable === key;
                const detail = detailsByKey[key];
                const isLoadingDetail = loadingDetailKey === key;

                return (
                  <div key={key} className="bg-surface">
                    <div className="flex items-center gap-1 px-2 py-1.5 hover:bg-surface-subtle/60">
                      <button
                        type="button"
                        onClick={() => void handleToggleTable(tbl.table_name)}
                        className="flex min-w-0 flex-1 items-center gap-1.5 text-left cursor-pointer"
                      >
                        {isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
                        )}
                        <Table2 className="h-3.5 w-3.5 shrink-0 text-blueprint" />
                        <span className="truncate font-mono font-medium text-ink">
                          {tbl.table_name}
                        </span>
                      </button>

                      {tbl.estimated_rows !== null && (
                        <span
                          className="shrink-0 font-mono text-[10px] text-ink-muted tabular-nums"
                          title="Estimativa pg_class.reltuples"
                        >
                          ~{tbl.estimated_rows.toLocaleString("pt-BR")}
                        </span>
                      )}

                      {onInsertSqlSnippet && (
                        <button
                          type="button"
                          title={`Inserir SELECT * FROM ${key} LIMIT 50`}
                          aria-label={`Inserir SELECT para ${tbl.table_name}`}
                          onClick={() =>
                            onInsertSqlSnippet(
                              `SELECT *\nFROM ${tbl.schema_name}.${tbl.table_name}\nLIMIT 50`,
                            )
                          }
                          className="rounded p-0.5 text-ink-muted hover:bg-accent-soft hover:text-accent cursor-pointer"
                        >
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>

                    {isExpanded && (
                      <div className="border-t border-border/50 bg-surface-subtle/40 px-3 py-2">
                        {isLoadingDetail ? (
                          <p className="text-[11px] text-ink-muted">
                            Inspecionando colunas...
                          </p>
                        ) : detail ? (
                          <ul className="space-y-1">
                            {detail.columns.map((col) => {
                              const fk = detail.foreign_keys.find(
                                (item) => item.column_name === col.name,
                              );
                              return (
                                <li
                                  key={col.name}
                                  className="flex flex-col gap-0.5 rounded px-1.5 py-1 hover:bg-surface"
                                >
                                  <div className="flex items-center justify-between gap-1">
                                    <span className="flex min-w-0 items-center gap-1 font-mono text-[11px] text-ink">
                                      {col.is_primary_key && (
                                        <KeyRound
                                          className="h-3 w-3 shrink-0 text-warning"
                                          aria-label="Chave primária"
                                        />
                                      )}
                                      <span className="truncate font-medium">
                                        {col.name}
                                      </span>
                                    </span>
                                    <span
                                      className="shrink-0 font-mono text-[10px] text-ink-muted"
                                      title={col.java_class}
                                    >
                                      {col.udt_name}
                                    </span>
                                  </div>
                                  {fk && (
                                    <div className="flex items-center gap-1 pl-1 font-mono text-[10px] text-blueprint">
                                      <Link2 className="h-2.5 w-2.5 shrink-0" />
                                      <span className="truncate">
                                        {fk.foreign_table}.{fk.foreign_column}
                                      </span>
                                    </div>
                                  )}
                                </li>
                              );
                            })}
                          </ul>
                        ) : null}
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </>
      )}
    </aside>
  );
}
