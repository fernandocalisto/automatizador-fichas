import { useCallback, useEffect, useState } from "react";
import { SplitPane, useToast } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { SqlDbViewProps } from "@/types/feature-props";
import type {
  ArtifactRevisionRead,
  CommitInsertResult,
  DbConnectionTestResult,
  DbProfileRead,
  DryRunInsertResult,
  InspectSelectResult,
  SqlValidateResponse,
} from "@/types/studio";
import {
  DbGovernancePane,
  type DryRunInvalidationReason,
} from "./DbGovernancePane";
import { SqlEditorPane, type SqlTabId } from "./SqlEditorPane";
import {
  DEFAULT_SQL_SELECT_OPTIONS,
  type SqlSelectRegenerateOptions,
} from "./SqlRegenerateControls";

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
}: SqlDbViewProps) {
  const { pushToast } = useToast();

  // Artifacts & drafts
  const [loadingArtifacts, setLoadingArtifacts] = useState(true);
  const [activeTab, setActiveTab] = useState<SqlTabId>("sql_insert");
  const [insertArtifact, setInsertArtifact] =
    useState<ArtifactRevisionRead | null>(null);
  const [selectArtifact, setSelectArtifact] =
    useState<ArtifactRevisionRead | null>(null);
  const [insertDraft, setInsertDraft] = useState("");
  const [selectDraft, setSelectDraft] = useState("");

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
    setConnectionTestResult(null);
    setConnectionTestError(null);

    Promise.all([
      fetchArtifactOrNull(project.id, "sql_insert"),
      fetchArtifactOrNull(project.id, "sql_select"),
    ])
      .then(([ins, sel]) => {
        if (cancelled) return;
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
        if (!cancelled) setLoadingArtifacts(false);
      });

    api
      .listDbProfiles()
      .then((list) => {
        if (cancelled) return;
        setProfiles(list);
        const preferred = list.find((p) => p.is_default) ?? list[0] ?? null;
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
    },
    [dryRunState],
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

      setInsertArtifact(res.sql_insert);
      setSelectArtifact(res.sql_select);
      setInsertDraft(res.sql_insert.content);
      setSelectDraft(res.sql_select.content);
      setValidationByTab({ sql_insert: null, sql_select: null });
      setInspectResult(null);
      setInspectError(null);

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
  }, [project.id, selectOptions, dryRunState, pushToast]);

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
        setInsertArtifact(res.artifact);
        setInsertDraft(res.artifact.content);
      } else {
        setSelectArtifact(res.artifact);
        setSelectDraft(res.artifact.content);
      }
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
  }, [activeTab, insertDraft, selectDraft, project.id, pushToast]);

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

  return (
    <div className="h-full w-full overflow-hidden">
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
  );
}
