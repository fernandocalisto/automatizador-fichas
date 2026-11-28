import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpFromLine,
  Database,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  PlugZap,
  Save,
  ShieldCheck,
} from "lucide-react";
import {
  Badge,
  Button,
  CodeEditor,
  SearchableSelect,
  SplitPane,
  useToast,
  type SearchableSelectOption,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { SqlDbViewProps } from "@/types/feature-props";
import type {
  ArtifactRevisionRead,
  CommitInsertResult,
  DbConnectionTestResult,
  DbProfileRead,
  DryRunInsertResult,
  InspectSelectResult,
  SelectPreviewResult,
  SqlValidateResponse,
} from "@/types/studio";
import {
  DbGovernancePane,
  type DryRunInvalidationReason,
} from "./DbGovernancePane";
import { SchemaExplorerPane } from "./SchemaExplorerPane";
import { SelectPreviewGrid } from "./SelectPreviewGrid";
import { SqlEditorPane, type SqlTabId } from "./SqlEditorPane";
import {
  DEFAULT_SQL_SELECT_OPTIONS,
  type SqlSelectRegenerateOptions,
} from "./SqlRegenerateControls";
import { previewProfileSelect, syncProjectQuery } from "./workbenchApi";

interface DryRunState {
  result: DryRunInsertResult;
  sqlSnapshot: string;
  profileId: string;
}

function getErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err);
}

async function fetchArtifactOrNull(
  projectId: string,
  type: "sql_insert" | "sql_select",
): Promise<ArtifactRevisionRead | null> {
  try {
    return await api.getArtifact(projectId, type);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      return null;
    }
    throw err;
  }
}

export function SqlDbView({
  project,
  onProjectUpdated,
  onNavigateSection,
  artifactSyncTick = 0,
}: SqlDbViewProps) {
  const { pushToast } = useToast();
  const isFreeReport = project.project_kind === "free_report";
  const loadedInsertVerRef = useRef<number | null>(null);
  const loadedSelectVerRef = useRef<number | null>(null);
  const initialLoadedRef = useRef(false);

  // Artifacts & drafts
  const [loadingArtifacts, setLoadingArtifacts] = useState(true);
  const [activeTab, setActiveTab] = useState<SqlTabId>(
    isFreeReport ? "sql_select" : "sql_insert",
  );
  const [insertArtifact, setInsertArtifact] =
    useState<ArtifactRevisionRead | null>(null);
  const [selectArtifact, setSelectArtifact] =
    useState<ArtifactRevisionRead | null>(null);
  const [insertDraft, setInsertDraft] = useState("");
  const [selectDraft, setSelectDraft] = useState("");

  // SQL Workbench (free_report & optional Schema Explorer)
  const [schemaExplorerOpen, setSchemaExplorerOpen] = useState(isFreeReport);
  const [runningPreviewSelect, setRunningPreviewSelect] = useState(false);
  const [previewSelectResult, setPreviewSelectResult] =
    useState<SelectPreviewResult | null>(null);
  const [previewSelectError, setPreviewSelectError] = useState<string | null>(
    null,
  );
  const [syncingQuery, setSyncingQuery] = useState(false);

  // Regeneration options
  const [selectOptions, setSelectOptions] =
    useState<SqlSelectRegenerateOptions>(DEFAULT_SQL_SELECT_OPTIONS);
  const [regenerating, setRegenerating] = useState(false);

  // Syntax validation & save
  const [validating, setValidating] = useState(false);
  const [validationByTab, setValidationByTab] = useState<
    Record<SqlTabId, SqlValidateResponse | null>
  >({
    sql_insert: null,
    sql_select: null,
  });
  const [saving, setSaving] = useState(false);

  // PostgreSQL profiles & test
  const [profiles, setProfiles] = useState<DbProfileRead[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(true);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionTestResult, setConnectionTestResult] =
    useState<DbConnectionTestResult | null>(null);
  const [connectionTestError, setConnectionTestError] = useState<string | null>(
    null,
  );

  // 2-step Dry-Run -> Commit state
  const [runningDryRun, setRunningDryRun] = useState(false);
  const [dryRunState, setDryRunState] = useState<DryRunState | null>(null);
  const [dryRunError, setDryRunError] = useState<string | null>(null);
  const [invalidationReason, setInvalidationReason] =
    useState<DryRunInvalidationReason>(null);

  const [committing, setCommitting] = useState(false);
  const [commitResult, setCommitResult] = useState<CommitInsertResult | null>(
    null,
  );
  const [commitError, setCommitError] = useState<string | null>(null);

  // SELECT inspection
  const [inspectingSelect, setInspectingSelect] = useState(false);
  const [inspectResult, setInspectResult] =
    useState<InspectSelectResult | null>(null);
  const [inspectError, setInspectError] = useState<string | null>(null);

  // Load SQL artifacts & PostgreSQL profiles when project changes
  useEffect(() => {
    let cancelled = false;

    setLoadingArtifacts(true);
    setLoadingProfiles(true);
    setValidationByTab({ sql_insert: null, sql_select: null });
    setDryRunState(null);
    setDryRunError(null);
    setInvalidationReason(null);
    setCommitResult(null);
    setCommitError(null);
    setInspectResult(null);
    setInspectError(null);
    setPreviewSelectResult(null);
    setPreviewSelectError(null);
    setConnectionTestResult(null);
    setConnectionTestError(null);
    if (project.project_kind === "free_report") {
      setActiveTab("sql_select");
    }

    Promise.all([
      fetchArtifactOrNull(project.id, "sql_insert"),
      fetchArtifactOrNull(project.id, "sql_select"),
    ])
      .then(([ins, sel]) => {
        if (cancelled) return;
        loadedInsertVerRef.current = ins?.version_num ?? null;
        loadedSelectVerRef.current = sel?.version_num ?? null;
        setInsertArtifact(ins);
        setSelectArtifact(sel);
        setInsertDraft(ins?.content ?? "");
        setSelectDraft(sel?.content ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        pushToast({
          tone: "error",
          title: "Falha ao carregar scripts SQL",
          description: getErrorMessage(err),
        });
      })
      .finally(() => {
        if (!cancelled) {
          initialLoadedRef.current = true;
          setLoadingArtifacts(false);
        }
      });

    api
      .listDbProfiles()
      .then((list) => {
        if (cancelled) return;
        setProfiles(list);
        const byProject = project.default_db_profile_id
          ? list.find((p) => p.id === project.default_db_profile_id)
          : null;
        const preferred =
          byProject ?? list.find((p) => p.is_default) ?? list[0] ?? null;
        setSelectedProfileId(preferred?.id ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        setProfiles([]);
        setSelectedProfileId("");
        pushToast({
          tone: "error",
          title: "Falha ao carregar perfis PostgreSQL",
          description: getErrorMessage(err),
        });
      })
      .finally(() => {
        if (!cancelled) setLoadingProfiles(false);
      });

    return () => {
      cancelled = true;
    };
  }, [project.id, pushToast]);

  // Recarrega scripts SQL automaticamente quando o agente ou JSON regenerar novas versões
  const latestSqlInsertVer = project.latest_artifacts?.sql_insert ?? null;
  const latestSqlSelectVer = project.latest_artifacts?.sql_select ?? null;
  useEffect(() => {
    if (!initialLoadedRef.current) return;
    const insertOutdated =
      latestSqlInsertVer !== null &&
      latestSqlInsertVer !== loadedInsertVerRef.current;
    const selectOutdated =
      latestSqlSelectVer !== null &&
      latestSqlSelectVer !== loadedSelectVerRef.current;
    if (!insertOutdated && !selectOutdated && artifactSyncTick === 0) return;

    let cancelled = false;
    Promise.all([
      fetchArtifactOrNull(project.id, "sql_insert"),
      fetchArtifactOrNull(project.id, "sql_select"),
    ])
      .then(([ins, sel]) => {
        if (cancelled) return;
        if (ins && ins.version_num !== loadedInsertVerRef.current) {
          loadedInsertVerRef.current = ins.version_num;
          setInsertArtifact(ins);
          setInsertDraft(ins.content ?? "");
          setValidationByTab((prev) => ({ ...prev, sql_insert: null }));
          setDryRunState(null);
          setInvalidationReason("sql_edited");
        }
        if (sel && sel.version_num !== loadedSelectVerRef.current) {
          loadedSelectVerRef.current = sel.version_num;
          setSelectArtifact(sel);
          setSelectDraft(sel.content ?? "");
          setValidationByTab((prev) => ({ ...prev, sql_select: null }));
          setInspectResult(null);
        }
      })
      .catch(() => {
        // Ignora erro transitório em refresh silencioso
      });

    return () => {
      cancelled = true;
    };
  }, [project.id, latestSqlInsertVer, latestSqlSelectVer, artifactSyncTick]);

  // Strict tamper-check: Dry-Run token is valid ONLY for exact SQL & profile snapshot
  const activeDryRunResult =
    dryRunState &&
    dryRunState.sqlSnapshot === insertDraft &&
    dryRunState.profileId === selectedProfileId
      ? dryRunState.result
      : null;

  const handleInsertChange = useCallback(
    (next: string) => {
      setInsertDraft(next);
      setValidationByTab((prev) => ({ ...prev, sql_insert: null }));
      if (dryRunState && next !== dryRunState.sqlSnapshot) {
        setDryRunState(null);
        setInvalidationReason("sql_edited");
        setCommitError(null);
      }
    },
    [dryRunState],
  );

  const handleSelectChange = useCallback((next: string) => {
    setSelectDraft(next);
    setValidationByTab((prev) => ({ ...prev, sql_select: null }));
  }, []);

  const handleSelectProfileId = useCallback(
    (nextProfileId: string) => {
      setSelectedProfileId(nextProfileId);
      setConnectionTestResult(null);
      setConnectionTestError(null);
      setCommitError(null);
      if (dryRunState && nextProfileId !== dryRunState.profileId) {
        setDryRunState(null);
        setInvalidationReason("profile_changed");
      }
      // Persiste a seleção no projeto para que F5 mantenha o banco escolhido
      void api
        .updateProject(project.id, {
          default_db_profile_id: nextProfileId || null,
        })
        .then((updated) => {
          if (updated && updated.id) {
            onProjectUpdated(updated);
          }
        })
        .catch(() => {
          // Falha transitória de persistência não bloqueia a operação local
        });
    },
    [dryRunState, onProjectUpdated, project.id],
  );

  const dbProfileOptions = useMemo<SearchableSelectOption[]>(
    () =>
      profiles.map((prof) => ({
        value: prof.id,
        label: prof.name,
        sublabel: `${prof.host}/${prof.dbname || "postgres"}`,
        badge:
          prof.environment ??
          (prof.read_only ? "RO" : prof.is_default ? "Padrão" : undefined),
        keywords: `${prof.name} ${prof.host} ${prof.dbname} ${prof.environment ?? ""} ${prof.read_only ? "somente leitura" : ""}`,
      })),
    [profiles],
  );

  const handleRegenerateSql = useCallback(async () => {
    setRegenerating(true);
    try {
      const res = await api.regenerateSql(project.id, {
        select_options: {
          boolean_style: selectOptions.boolean_style,
          column_naming: selectOptions.column_naming,
          param_syntax: selectOptions.param_syntax,
          include_obs: selectOptions.include_obs,
        },
        created_by: "user",
        summary: "Regenerado a partir do JSON na tela SQL & Banco",
      });

      loadedInsertVerRef.current = res.sql_insert.version_num;
      loadedSelectVerRef.current = res.sql_select.version_num;
      setInsertArtifact(res.sql_insert);
      setSelectArtifact(res.sql_select);
      setInsertDraft(res.sql_insert.content);
      setSelectDraft(res.sql_select.content);
      setValidationByTab({ sql_insert: null, sql_select: null });
      setInspectResult(null);
      setInspectError(null);
      onProjectUpdated({
        ...project,
        latest_artifacts: {
          ...project.latest_artifacts,
          sql_insert: res.sql_insert.version_num,
          sql_select: res.sql_select.version_num,
        },
      });

      if (dryRunState && res.sql_insert.content !== dryRunState.sqlSnapshot) {
        setDryRunState(null);
        setInvalidationReason("sql_edited");
      }

      pushToast({
        tone: "success",
        title: "Scripts SQL regenerados",
        description: `INSERT v${res.sql_insert.version_num} e SELECT v${res.sql_select.version_num} atualizados.`,
      });
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Erro ao regenerar SQL",
        description: getErrorMessage(err),
      });
    } finally {
      setRegenerating(false);
    }
  }, [project, selectOptions, dryRunState, onProjectUpdated, pushToast]);

  const handleValidateSql = useCallback(async () => {
    const sqlText = activeTab === "sql_insert" ? insertDraft : selectDraft;
    if (!sqlText.trim()) return;
    setValidating(true);
    try {
      const res = await api.validateSql(project.id, {
        sql: sqlText,
        artifact_type: activeTab,
      });
      setValidationByTab((prev) => ({ ...prev, [activeTab]: res }));
    } catch (err) {
      setValidationByTab((prev) => ({
        ...prev,
        [activeTab]: {
          valid: false,
          message: getErrorMessage(err),
          artifact_type: activeTab,
          unknown_field_types: [],
        },
      }));
    } finally {
      setValidating(false);
    }
  }, [activeTab, insertDraft, selectDraft, project.id]);

  const handleSaveRevision = useCallback(async () => {
    const sqlText = activeTab === "sql_insert" ? insertDraft : selectDraft;
    if (!sqlText.trim()) return;
    setSaving(true);
    try {
      const res = await api.saveArtifact(project.id, activeTab, {
        content: sqlText,
        created_by: "user",
        summary:
          activeTab === "sql_insert"
            ? "Edição manual do SQL INSERT"
            : "Edição manual do SQL SELECT Jasper",
      });
      if (activeTab === "sql_insert") {
        loadedInsertVerRef.current = res.artifact.version_num;
        setInsertArtifact(res.artifact);
        setInsertDraft(res.artifact.content);
      } else {
        loadedSelectVerRef.current = res.artifact.version_num;
        setSelectArtifact(res.artifact);
        setSelectDraft(res.artifact.content);
      }
      onProjectUpdated({
        ...project,
        latest_artifacts: {
          ...project.latest_artifacts,
          [activeTab]: res.artifact.version_num,
        },
      });
      pushToast({
        tone: "success",
        title: `Revisão v${res.artifact.version_num} salva`,
      });
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao salvar revisão SQL",
        description: getErrorMessage(err),
      });
    } finally {
      setSaving(false);
    }
  }, [activeTab, insertDraft, selectDraft, project, onProjectUpdated, pushToast]);

  const handleRevertCurrent = useCallback(() => {
    if (activeTab === "sql_insert" && insertArtifact) {
      handleInsertChange(insertArtifact.content);
    } else if (activeTab === "sql_select" && selectArtifact) {
      handleSelectChange(selectArtifact.content);
    }
  }, [
    activeTab,
    insertArtifact,
    selectArtifact,
    handleInsertChange,
    handleSelectChange,
  ]);

  const handleCopySql = useCallback(
    async (text: string) => {
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(text);
        }
        pushToast({
          tone: "info",
          title: "SQL copiado para a área de transferência",
        });
      } catch (err) {
        pushToast({
          tone: "error",
          title: "Não foi possível copiar",
          description: getErrorMessage(err),
        });
      }
    },
    [pushToast],
  );

  const handleTestConnection = useCallback(async () => {
    if (!selectedProfileId) return;
    setTestingConnection(true);
    setConnectionTestError(null);
    try {
      const res = await api.testDbProfile(selectedProfileId);
      setConnectionTestResult(res);
    } catch (err) {
      setConnectionTestResult(null);
      setConnectionTestError(getErrorMessage(err));
    } finally {
      setTestingConnection(false);
    }
  }, [selectedProfileId]);

  const handleRunDryRun = useCallback(async () => {
    if (!selectedProfileId || !insertDraft.trim()) return;
    setRunningDryRun(true);
    setDryRunError(null);
    setCommitError(null);
    try {
      const res = await api.dryRunInsert(project.id, {
        profile_id: selectedProfileId,
        sql_text: insertDraft,
      });
      if (res.ok && res.dry_run_token) {
        setDryRunState({
          result: res,
          sqlSnapshot: insertDraft,
          profileId: selectedProfileId,
        });
        setInvalidationReason(null);
        pushToast({
          tone: "success",
          title: "Dry-Run aprovado (ROLLBACK concluído)",
          description:
            res.simulated_template_id !== null
              ? `Template ID simulado: #${res.simulated_template_id}`
              : res.message,
        });
      } else {
        setDryRunState(null);
        setDryRunError(res.message || "Dry-Run não retornou token válido.");
      }
    } catch (err) {
      setDryRunState(null);
      setDryRunError(getErrorMessage(err));
    } finally {
      setRunningDryRun(false);
    }
  }, [project.id, selectedProfileId, insertDraft, pushToast]);

  const handleConfirmCommit = useCallback(async (): Promise<boolean> => {
    const profile = profiles.find((p) => p.id === selectedProfileId);
    if (!profile || profile.read_only || !activeDryRunResult) {
      return false;
    }

    setCommitting(true);
    setCommitError(null);
    try {
      const res = await api.commitInsert(project.id, {
        profile_id: selectedProfileId,
        dry_run_token: activeDryRunResult.dry_run_token,
        sql_text: insertDraft,
      });

      setCommitResult(res);
      setDryRunState(null);
      setInvalidationReason(null);

      try {
        const refreshedProject = await api.getProject(project.id);
        onProjectUpdated(refreshedProject);
      } catch {
        // Keep commit success state even if project refresh fails transiently
      }

      pushToast({
        tone: "success",
        title: "INSERT confirmado no PostgreSQL",
        description:
          res.template_id !== null
            ? `Template ID #${res.template_id} gravado com sucesso.`
            : res.message,
      });
      return true;
    } catch (err) {
      setCommitError(getErrorMessage(err));
      return false;
    } finally {
      setCommitting(false);
    }
  }, [
    profiles,
    selectedProfileId,
    activeDryRunResult,
    project.id,
    insertDraft,
    onProjectUpdated,
    pushToast,
  ]);

  const handleInspectSelect = useCallback(
    async (opts: { sampleId?: number; lookupSampleId: boolean }) => {
      if (!selectedProfileId || !selectDraft.trim()) return;
      setInspectingSelect(true);
      setInspectError(null);
      try {
        const payload: {
          profile_id: string;
          sql_select: string;
          sample_id?: number;
          lookup_sample_id: boolean;
        } = {
          profile_id: selectedProfileId,
          sql_select: selectDraft,
          lookup_sample_id: opts.lookupSampleId,
        };
        if (!opts.lookupSampleId && opts.sampleId !== undefined) {
          payload.sample_id = opts.sampleId;
        }
        const res = await api.inspectSelect(project.id, payload);
        setInspectResult(res);
      } catch (err) {
        setInspectResult(null);
        setInspectError(getErrorMessage(err));
      } finally {
        setInspectingSelect(false);
      }
    },
    [project.id, selectedProfileId, selectDraft],
  );

  const handleRunPreviewSelect = useCallback(async () => {
    if (!selectedProfileId || !selectDraft.trim()) return;
    setRunningPreviewSelect(true);
    setPreviewSelectError(null);
    try {
      const res = await previewProfileSelect(selectedProfileId, {
        sql_select: selectDraft,
        limit: 50,
      });
      setPreviewSelectResult(res);
    } catch (err) {
      setPreviewSelectResult(null);
      setPreviewSelectError(getErrorMessage(err));
    } finally {
      setRunningPreviewSelect(false);
    }
  }, [selectedProfileId, selectDraft]);

  const handleSyncQuery = useCallback(
    async (direction: "jrxml_to_sql" | "sql_to_jrxml") => {
      setSyncingQuery(true);
      try {
        const res = await syncProjectQuery(project.id, {
          direction,
          sql_select: direction === "sql_to_jrxml" ? selectDraft : undefined,
          save_artifact: true,
        });
        if (direction === "jrxml_to_sql") {
          setSelectDraft(res.sql_select);
          if (res.saved_revision) {
            loadedSelectVerRef.current = res.saved_revision.version_num;
            setSelectArtifact(res.saved_revision);
            onProjectUpdated({
              ...project,
              latest_artifacts: {
                ...project.latest_artifacts,
                sql_select: res.saved_revision.version_num,
              },
            });
          }
          pushToast({
            tone: "success",
            title: "Query extraída do JRXML",
            description: "Tag <queryString> carregada no SQL Workbench.",
          });
        } else {
          if (res.saved_revision) {
            onProjectUpdated({
              ...project,
              latest_artifacts: {
                ...project.latest_artifacts,
                jrxml: res.saved_revision.version_num,
              },
            });
          }
          pushToast({
            tone: "success",
            title: "Query aplicada no JRXML",
            description: res.saved_revision
              ? `Revisão JRXML v${res.saved_revision.version_num} salva.`
              : "Tag <queryString> atualizada.",
          });
        }
      } catch (err) {
        pushToast({
          tone: "error",
          title:
            direction === "jrxml_to_sql"
              ? "Falha ao extrair query do JRXML"
              : "Falha ao aplicar query no JRXML",
          description: getErrorMessage(err),
        });
      } finally {
        setSyncingQuery(false);
      }
    },
    [onProjectUpdated, project, pushToast, selectDraft],
  );

  const handleInsertSnippet = useCallback((snippet: string) => {
    setSelectDraft((prev) => (prev.trim() ? `${prev.trimEnd()}\n\n${snippet}` : snippet));
  }, []);

  if (isFreeReport) {
    const selectDirty =
      selectArtifact !== null
        ? selectDraft !== selectArtifact.content
        : selectDraft.trim().length > 0;

    return (
      <div
        data-testid="free-report-sql-workbench"
        className="flex h-full w-full flex-col overflow-hidden bg-canvas"
      >
        {/* Top Workbench Toolbar */}
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-surface px-2.5 py-1.5">
          <div className="flex min-w-0 items-center gap-1.5">
            <Button
              size="xs"
              variant={schemaExplorerOpen ? "secondary" : "outline"}
              onClick={() => setSchemaExplorerOpen((prev) => !prev)}
              title="Alternar painel Schema Explorer"
              className="shrink-0 whitespace-nowrap"
              icon={
                schemaExplorerOpen ? (
                  <PanelLeftClose className="h-3.5 w-3.5" />
                ) : (
                  <PanelLeftOpen className="h-3.5 w-3.5" />
                )
              }
            >
              Schema
            </Button>

            <div className="flex items-center gap-1.5">
              <Database className="h-3.5 w-3.5 shrink-0 text-blueprint" />
              <SearchableSelect
                ariaLabel="Perfil PostgreSQL do Workbench"
                value={selectedProfileId}
                onChange={handleSelectProfileId}
                options={dbProfileOptions}
                placeholder={
                  profiles.length === 0
                    ? "Nenhum perfil cadastrado"
                    : "Selecionar banco PostgreSQL..."
                }
                searchPlaceholder="Buscar por nome, host, banco ou ambiente..."
                emptyLabel="Nenhum perfil encontrado."
                disabled={loadingProfiles || profiles.length === 0}
                size="sm"
                className="w-48 xl:w-56"
              />
              <Button
                size="xs"
                variant="outline"
                loading={testingConnection}
                disabled={!selectedProfileId}
                onClick={handleTestConnection}
                className="shrink-0 whitespace-nowrap"
                icon={<PlugZap className="h-3.5 w-3.5 text-blueprint" />}
              >
                Testar
              </Button>
            </div>

            {connectionTestResult && (
              <Badge
                tone={connectionTestResult.ok ? "success" : "danger"}
                dot
                className="shrink-0"
              >
                {connectionTestResult.ok
                  ? `OK · ${connectionTestResult.latency_ms} ms`
                  : "Falha"}
              </Badge>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <Button
              size="xs"
              variant="outline"
              loading={syncingQuery}
              onClick={() => void handleSyncQuery("jrxml_to_sql")}
              title="Extrair query <queryString> do JRXML"
              className="whitespace-nowrap"
              icon={<ArrowDownToLine className="h-3.5 w-3.5" />}
            >
              Extrair JRXML
            </Button>

            <Button
              size="xs"
              variant="outline"
              loading={syncingQuery}
              disabled={!selectDraft.trim()}
              onClick={() => void handleSyncQuery("sql_to_jrxml")}
              title="Aplicar query na tag <queryString> do JRXML"
              className="whitespace-nowrap"
              icon={<ArrowUpFromLine className="h-3.5 w-3.5" />}
            >
              Aplicar JRXML
            </Button>

            <Button
              size="xs"
              variant="outline"
              loading={validating}
              disabled={!selectDraft.trim()}
              onClick={handleValidateSql}
              title="Validar sintaxe SQL"
              className="whitespace-nowrap"
              icon={<ShieldCheck className="h-3.5 w-3.5 text-blueprint" />}
            >
              Validar
            </Button>

            <Button
              size="xs"
              variant={selectDirty ? "primary" : "outline"}
              loading={saving}
              disabled={!selectDraft.trim() || !selectDirty}
              onClick={handleSaveRevision}
              title="Salvar revisão SQL"
              className="whitespace-nowrap"
              icon={<Save className="h-3.5 w-3.5" />}
            >
              Salvar
            </Button>

            <Button
              size="xs"
              variant="blueprint"
              loading={runningPreviewSelect}
              disabled={!selectedProfileId || !selectDraft.trim()}
              onClick={() => void handleRunPreviewSelect()}
              title="Executar Preview SQL (READ ONLY · LIMIT 50)"
              className="whitespace-nowrap"
              icon={<Play className="h-3.5 w-3.5" />}
            >
              Preview (LIMIT 50)
            </Button>

            <Button
              size="xs"
              variant="ghost"
              onClick={() => onNavigateSection("jasper_studio")}
              className="shrink-0 whitespace-nowrap"
              icon={<ArrowRight className="h-3.5 w-3.5" />}
            >
              Jasper Studio
            </Button>
          </div>
        </div>

        {/* Main Area: Collapsible Schema Explorer + SQL Editor & Preview Grid */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {schemaExplorerOpen && (
            <SchemaExplorerPane
              profileId={selectedProfileId}
              onInsertSqlSnippet={handleInsertSnippet}
              onClose={() => setSchemaExplorerOpen(false)}
            />
          )}

          <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
            <div className="min-h-0 flex-1 border-b border-border bg-surface">
              {loadingArtifacts ? (
                <div className="flex h-full items-center justify-center text-xs text-ink-muted">
                  Carregando SQL SELECT do relatório...
                </div>
              ) : (
                <CodeEditor
                  language="sql"
                  value={selectDraft}
                  onChange={handleSelectChange}
                  ariaLabel="Editor SQL SELECT Workbench"
                />
              )}
            </div>

            <div className="max-h-[45%] shrink-0 overflow-y-auto bg-canvas p-3">
              {validationByTab.sql_select && (
                <div
                  role="status"
                  className="mb-2 rounded-md border border-border bg-surface px-3 py-1.5 text-xs"
                >
                  <strong>
                    {validationByTab.sql_select.valid
                      ? "Sintaxe válida:"
                      : "Erro de sintaxe:"}
                  </strong>{" "}
                  {validationByTab.sql_select.message}
                </div>
              )}

              <SelectPreviewGrid
                result={previewSelectResult}
                error={previewSelectError}
                loading={runningPreviewSelect}
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full overflow-hidden">
      {schemaExplorerOpen && (
        <SchemaExplorerPane
          profileId={selectedProfileId}
          onInsertSqlSnippet={handleInsertSnippet}
          onClose={() => setSchemaExplorerOpen(false)}
        />
      )}
      <div className="min-w-0 flex-1 overflow-hidden">
        <SplitPane
          storageKey="salutem-sql-db-split"
          initialRatio={0.56}
          minRatio={0.32}
          maxRatio={0.74}
          left={
            <SqlEditorPane
              projectSlug={project.slug}
              loading={loadingArtifacts}
              activeTab={activeTab}
              onTabChange={setActiveTab}
              insertArtifact={insertArtifact}
              selectArtifact={selectArtifact}
              insertDraft={insertDraft}
              selectDraft={selectDraft}
              onInsertChange={handleInsertChange}
              onSelectChange={handleSelectChange}
              selectOptions={selectOptions}
              onSelectOptionsChange={setSelectOptions}
              regenerating={regenerating}
              onRegenerateSql={handleRegenerateSql}
              validating={validating}
              validationResult={validationByTab[activeTab]}
              onValidateSql={handleValidateSql}
              saving={saving}
              onSaveRevision={handleSaveRevision}
              onRevertCurrent={handleRevertCurrent}
              onCopySql={handleCopySql}
            />
          }
          right={
            <DbGovernancePane
              project={project}
              profiles={profiles}
              loadingProfiles={loadingProfiles}
              selectedProfileId={selectedProfileId}
              onSelectProfileId={handleSelectProfileId}
              onNavigateSection={onNavigateSection}
              testingConnection={testingConnection}
              connectionTestResult={connectionTestResult}
              connectionTestError={connectionTestError}
              onTestConnection={handleTestConnection}
              hasInsertSql={insertDraft.trim().length > 0}
              runningDryRun={runningDryRun}
              dryRunResult={activeDryRunResult}
              dryRunError={dryRunError}
              invalidationReason={invalidationReason}
              onRunDryRun={handleRunDryRun}
              committing={committing}
              commitResult={commitResult}
              commitError={commitError}
              onConfirmCommit={handleConfirmCommit}
              hasSelectSql={selectDraft.trim().length > 0}
              inspectingSelect={inspectingSelect}
              inspectResult={inspectResult}
              inspectError={inspectError}
              onInspectSelect={handleInspectSelect}
            />
          }
        />
      </div>
    </div>
  );
}
