import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Code2,
  Crosshair,
  FileText,
  Play,
  Sliders,
  Sparkles,
} from "lucide-react";
import { Button, EmptyState, SplitPane, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { JasperStudioViewProps } from "@/types/feature-props";
import type {
  ClinicalOrientation,
  DbProfileRead,
  JasperCompileResponse,
  JasperPreviewResponse,
  JrxmlLintReport,
  JrxmlParameterInfo,
  PreviewMode,
  ProjectKind,
  RepoResourcesStatus,
  ScenarioType,
} from "@/types/studio";
import { JrxmlEditorPane } from "./JrxmlEditorPane";
import { PdfPreviewCanvas } from "./PdfPreviewCanvas";
import {
  LayoutModeSwitcher,
  PreviewControlBar,
  RepoResourcesChip,
} from "./PreviewControlBar";
import type { RegionAnnotationSubmitPayload } from "./RegionAnnotationOverlay";
import { ReportParamsBar } from "./ReportParamsBar";
import {
  JASPER_LAYOUT_STORAGE_KEY,
  chatMessageToAnnotation,
  type JasperLayoutMode,
  type VisualRegionAnnotation,
} from "./types";
import {
  detectJrxmlOrientation,
  extractDaemonError,
  triggerTextDownload,
} from "./utils";

const LIVE_RELOAD_DEBOUNCE_MS = 900;
const REPORT_PARAMS_STORAGE_PREFIX = "salutem:report-params:";

const SYSTEM_PARAM_NAMES = new Set([
  "SUBREPORT_DIR",
  "caminho_relatorio",
  "JASPER_REPORT",
  "JASPER_REPORTS_CONTEXT",
  "IS_IGNORE_PAGINATION",
  "SORT_FIELDS",
  "FILTER",
]);

function inferInputKind(javaClass: string): JrxmlParameterInfo["input_kind"] {
  const short = javaClass.split(".").pop() ?? javaClass;
  if (["Long", "Integer", "Short", "Byte", "BigInteger"].includes(short)) {
    return "integer";
  }
  if (["Double", "Float", "BigDecimal", "Number"].includes(short)) {
    return "number";
  }
  if (short === "Boolean") return "boolean";
  if (javaClass === "java.sql.Date" || short === "LocalDate") return "date";
  if (
    ["Timestamp", "Date", "LocalDateTime", "OffsetDateTime"].includes(short)
  ) {
    return "datetime";
  }
  return "string";
}

function parseJrxmlParametersLocally(xml: string): JrxmlParameterInfo[] {
  if (!xml.trim()) return [];
  const results: JrxmlParameterInfo[] = [];
  const seen = new Set<string>();
  const withoutSubDatasets = xml.replace(
    /<subDataset\b[^>]*>[\s\S]*?<\/subDataset\s*>/g,
    "",
  );
  const paramRe =
    /<parameter\b([^>]*?)(?:\/>|>([\s\S]*?)<\/parameter\s*>)/g;
  let match: RegExpExecArray | null;
  while ((match = paramRe.exec(withoutSubDatasets)) !== null) {
    const attrs = match[1] ?? "";
    const body = match[2] ?? "";
    const nameMatch = /\bname\s*=\s*"([^"]+)"/.exec(attrs);
    if (!nameMatch) continue;
    const name = nameMatch[1].trim();
    if (!name || seen.has(name)) continue;
    seen.add(name);
    const classMatch = /\bclass\s*=\s*"([^"]+)"/.exec(attrs);
    const javaClass = classMatch?.[1]?.trim() || "java.lang.String";
    const defMatch =
      /<defaultValueExpression\b[^>]*>(?:<!\[CDATA\[([\s\S]*?)\]\]>|([\s\S]*?))<\/defaultValueExpression\s*>/.exec(
        body,
      );
    const defaultExpr = (defMatch?.[1] ?? defMatch?.[2] ?? "").trim() || null;
    const isSystem =
      SYSTEM_PARAM_NAMES.has(name) || name.toUpperCase().startsWith("REPORT_");
    results.push({
      name,
      java_class: javaClass,
      default_expression: defaultExpr,
      is_system: isSystem,
      input_kind: inferInputKind(javaClass),
    });
  }
  return results;
}

function getMissingRequiredParams(
  params: JrxmlParameterInfo[],
  values: Record<string, string>,
): JrxmlParameterInfo[] {
  return params.filter(
    (p) =>
      !p.is_system &&
      !p.default_expression &&
      !(values[p.name] ?? "").trim(),
  );
}

function loadStoredLayoutMode(): JasperLayoutMode | null {
  try {
    const raw = window.localStorage.getItem(JASPER_LAYOUT_STORAGE_KEY);
    if (raw === "visual" || raw === "split" || raw === "code") {
      return raw;
    }
  } catch {
    // Ignore storage read errors
  }
  return null;
}

function resolveInitialLayoutMode(projectKind?: ProjectKind): JasperLayoutMode {
  const stored = loadStoredLayoutMode();
  if (stored) return stored;
  return projectKind === "free_report" ? "visual" : "split";
}

function saveStoredLayoutMode(mode: JasperLayoutMode): void {
  try {
    window.localStorage.setItem(JASPER_LAYOUT_STORAGE_KEY, mode);
  } catch {
    // Ignore storage write errors
  }
}

function loadStoredReportParams(projectId: string): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(
      `${REPORT_PARAMS_STORAGE_PREFIX}${projectId}`,
    );
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof v === "string") out[k] = v;
        else if (v !== null && v !== undefined) out[k] = String(v);
      }
      return out;
    }
  } catch {
    // Ignore storage read errors
  }
  return {};
}

function saveStoredReportParams(
  projectId: string,
  values: Record<string, string>,
): void {
  try {
    window.localStorage.setItem(
      `${REPORT_PARAMS_STORAGE_PREFIX}${projectId}`,
      JSON.stringify(values),
    );
  } catch {
    // Ignore storage write errors
  }
}

export interface JasperStudioExtendedProps extends JasperStudioViewProps {
  headerExtraActions?: ReactNode;
}

export function JasperStudioView({
  project,
  onProjectUpdated,
  onOpenAgentChat,
  artifactSyncTick = 0,
  headerExtraActions,
}: JasperStudioExtendedProps) {
  const { pushToast } = useToast();
  const loadedVersionRef = useRef<number | null>(null);
  const initialLoadedRef = useRef(false);

  const isFreeReport = project.project_kind === "free_report";

  // Modo de visualização (Visual / Dividido / Só Código)
  const [layoutMode, setLayoutMode] = useState<JasperLayoutMode>(() =>
    resolveInitialLayoutMode(project.project_kind),
  );

  // Estado do artefato JRXML
  const [loadingArtifact, setLoadingArtifact] = useState(true);
  const [hasJrxml, setHasJrxml] = useState(false);
  const [jrxmlContent, setJrxmlContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [versionNum, setVersionNum] = useState<number | null>(null);

  // Operações do painel esquerdo
  const [scaffolding, setScaffolding] = useState(false);
  const [linting, setLinting] = useState(false);
  const [compiling, setCompiling] = useState(false);
  const [saving, setSaving] = useState(false);
  const [liveReload, setLiveReload] = useState(false);

  // Diagnósticos
  const [lintReport, setLintReport] = useState<JrxmlLintReport | null>(null);
  const [compileResult, setCompileResult] =
    useState<JasperCompileResponse | null>(null);
  const [compileError, setCompileError] = useState<string | null>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(true);
  const [selectedLine, setSelectedLine] = useState<number | null>(null);

  // Preview e cenários fictícios
  const [scenario, setScenario] = useState<ScenarioType>("full");
  const [mode, setMode] = useState<PreviewMode>(() =>
    isFreeReport && project.default_db_profile_id ? "db_live" : "auto",
  );
  const [dbProfiles, setDbProfiles] = useState<DbProfileRead[]>([]);
  const [selectedDbProfileId, setSelectedDbProfileId] = useState(
    project.default_db_profile_id ?? "",
  );
  const [atendimentoIdInput, setAtendimentoIdInput] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] =
    useState<JasperPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewDeferredForParams, setPreviewDeferredForParams] =
    useState(false);
  const [cacheBuster, setCacheBuster] = useState<number>(() => Date.now());

  // Recursos repo: (JasperReports Server)
  const [repoStatus, setRepoStatus] = useState<RepoResourcesStatus | null>(null);
  const [syncingRepo, setSyncingRepo] = useState(false);

  // Parâmetros $P{} do relatório (persistidos por projeto em localStorage)
  const [reportParameters, setReportParameters] = useState<
    JrxmlParameterInfo[]
  >([]);
  const [reportParamValues, setReportParamValues] = useState<
    Record<string, string>
  >(() => loadStoredReportParams(project.id));

  // Anotações visuais enviadas na sessão
  const [annotations, setAnnotations] = useState<VisualRegionAnnotation[]>([]);
  const [submittingAnnotation, setSubmittingAnnotation] = useState(false);

  // Refs para debounce e prevenção de race conditions
  const liveReloadTimerRef = useRef<number | null>(null);
  const userEditedRef = useRef(false);
  const previewReqSeqRef = useRef(0);
  const jrxmlRef = useRef(jrxmlContent);
  jrxmlRef.current = jrxmlContent;

  const dirty = hasJrxml && jrxmlContent !== savedContent;
  const orientation = detectJrxmlOrientation(jrxmlContent);

  const missingRequiredParams = useMemo(
    () => getMissingRequiredParams(reportParameters, reportParamValues),
    [reportParameters, reportParamValues],
  );

  const handleChangeLayoutMode = useCallback((nextMode: JasperLayoutMode) => {
    setLayoutMode(nextMode);
    saveStoredLayoutMode(nextMode);
  }, []);

  const fetchRepoResources = useCallback(async (projectId: string) => {
    if (typeof fetch !== "function") return;
    try {
      const resp = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/jasper/repo-resources`,
      );
      if (!resp.ok) return;
      const data = (await resp.json()) as RepoResourcesStatus;
      if (data && typeof data.total === "number") {
        setRepoStatus(data);
      }
    } catch {
      // Silencioso quando backend não suporta ou em testes sem mock de fetch
    }
  }, []);

  const handleSyncRepoResources = useCallback(async () => {
    if (typeof fetch !== "function") return;
    setSyncingRepo(true);
    try {
      const resp = await fetch(
        `/api/projects/${encodeURIComponent(project.id)}/jasper/sync-repo-resources`,
        { method: "POST" },
      );
      if (!resp.ok) {
        let message = `HTTP ${resp.status}`;
        try {
          const errPayload = (await resp.json()) as { detail?: string };
          if (typeof errPayload?.detail === "string") {
            message = errPayload.detail;
          }
        } catch {
          // Ignore parse error
        }
        throw new Error(message);
      }
      const data = (await resp.json()) as Partial<RepoResourcesStatus>;
      if (typeof data?.total === "number") {
        setRepoStatus(data as RepoResourcesStatus);
        pushToast({
          tone: (data.missing_count ?? 0) === 0 ? "success" : "warning",
          title:
            (data.missing_count ?? 0) === 0
              ? `Recursos repo: sincronizados (${data.resolved_count}/${data.total})`
              : `Sincronização parcial (${data.missing_count} pendente(s))`,
        });
      } else {
        await fetchRepoResources(project.id);
        pushToast({
          tone: "success",
          title: "Recursos repo: sincronizados",
        });
      }
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao sincronizar recursos repo:",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSyncingRepo(false);
    }
  }, [fetchRepoResources, project.id, pushToast]);

  const parseAtendimentoId = useCallback((raw: string): number | null => {
    const trimmed = raw.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, []);

  const buildFilledReportParams = useCallback(
    (values: Record<string, string>): Record<string, string> => {
      const filled: Record<string, string> = {};
      for (const [key, val] of Object.entries(values)) {
        const trimmed = val.trim();
        if (trimmed.length > 0) {
          filled[key] = trimmed;
        }
      }
      return filled;
    },
    [],
  );

  const runPreview = useCallback(
    async (overrides?: {
      scenario?: ScenarioType;
      mode?: PreviewMode;
      dbProfileId?: string;
      atendimentoIdRaw?: string;
      inlineJrxml?: string;
      reportParamsOverride?: Record<string, string>;
      silent?: boolean;
    }) => {
      const targetScenario = overrides?.scenario ?? scenario;
      const targetMode = overrides?.mode ?? mode;
      const targetProfileId =
        overrides?.dbProfileId !== undefined
          ? overrides.dbProfileId
          : selectedDbProfileId;
      const targetAtendRaw =
        overrides?.atendimentoIdRaw !== undefined
          ? overrides.atendimentoIdRaw
          : atendimentoIdInput;
      const targetXml = overrides?.inlineJrxml ?? jrxmlRef.current;
      const targetParamsMap = buildFilledReportParams(
        overrides?.reportParamsOverride ?? reportParamValues,
      );

      if (!targetXml.trim()) return;

      if (
        (targetMode === "db_hybrid" || targetMode === "db_live") &&
        !targetProfileId
      ) {
        setPreviewError(
          targetMode === "db_live"
            ? "Selecione um perfil PostgreSQL em Configurações ou na barra acima para usar o modo Live (Banco Real)."
            : "Selecione um perfil PostgreSQL em Configurações ou na barra acima para usar o modo Banco Híbrido (CTE).",
        );
        return;
      }

      const reqSeq = ++previewReqSeqRef.current;
      setPreviewDeferredForParams(false);
      setPreviewLoading(true);
      setPreviewError(null);

      try {
        const parsedAtend = parseAtendimentoId(targetAtendRaw);
        const previewPayload: Record<string, unknown> = {
          scenario: targetScenario,
          mode: targetMode,
          db_profile_id:
            targetMode === "offline" ? null : targetProfileId || null,
          atendimento_id: parsedAtend,
          inline_jrxml: targetXml,
        };
        if (
          targetMode === "db_live" ||
          Object.keys(targetParamsMap).length > 0
        ) {
          previewPayload.report_params = targetParamsMap;
        }
        const res = await api.generatePreview(
          project.id,
          previewPayload as Parameters<typeof api.generatePreview>[1],
        );

        if (reqSeq !== previewReqSeqRef.current) return;

        setPreviewResult(res);
        setCacheBuster(Date.now());
        if (res.lint) {
          setLintReport(res.lint);
        }
      } catch (err) {
        if (reqSeq !== previewReqSeqRef.current) return;
        const message =
          err instanceof Error ? err.message : "Falha ao gerar preview PDF.";
        setPreviewError(message);
        if (!overrides?.silent) {
          pushToast({
            tone: "error",
            title: "Erro ao gerar preview",
            description: message,
          });
        }
      } finally {
        if (reqSeq === previewReqSeqRef.current) {
          setPreviewLoading(false);
        }
      }
    },
    [
      atendimentoIdInput,
      buildFilledReportParams,
      mode,
      parseAtendimentoId,
      project.id,
      pushToast,
      reportParamValues,
      scenario,
      selectedDbProfileId,
    ],
  );

  // Carregamento inicial: JRXML + perfis PG + histórico de anotações visuais + repo:
  useEffect(() => {
    let cancelled = false;
    userEditedRef.current = false;
    setLayoutMode(resolveInitialLayoutMode(project.project_kind));
    setLoadingArtifact(true);
    setLintReport(null);
    setCompileResult(null);
    setCompileError(null);
    setPreviewResult(null);
    setPreviewError(null);
    setPreviewDeferredForParams(false);
    setRepoStatus(null);
    setSelectedLine(null);
    setReportParameters([]);
    const storedParams = loadStoredReportParams(project.id);
    setReportParamValues(storedParams);

    const loadInitial = async () => {
      const [artifactRes, profilesRes, chatRes] = await Promise.allSettled([
        api.getArtifact(project.id, "jrxml"),
        api.listDbProfiles(),
        api.listChat(project.id, "jrxml"),
      ]);

      if (cancelled) return;

      let resolvedProfileId = "";
      if (profilesRes.status === "fulfilled") {
        const list = profilesRes.value;
        setDbProfiles(list);
        const byProject = project.default_db_profile_id
          ? list.find((p) => p.id === project.default_db_profile_id)
          : undefined;
        const def = byProject ?? list.find((p) => p.is_default) ?? list[0];
        resolvedProfileId = def?.id ?? project.default_db_profile_id ?? "";
        setSelectedDbProfileId(resolvedProfileId);
      } else {
        setDbProfiles([]);
        resolvedProfileId = project.default_db_profile_id ?? "";
        setSelectedDbProfileId(resolvedProfileId);
      }

      const initialMode: PreviewMode =
        project.project_kind === "free_report" && project.default_db_profile_id
          ? "db_live"
          : "auto";
      setMode(initialMode);

      if (chatRes.status === "fulfilled") {
        const parsed = chatRes.value
          .map(chatMessageToAnnotation)
          .filter((item): item is VisualRegionAnnotation => item !== null);
        setAnnotations(parsed);
      } else {
        setAnnotations([]);
      }

      if (artifactRes.status === "fulfilled") {
        const rev = artifactRes.value;
        const localParams = parseJrxmlParametersLocally(rev.content);
        loadedVersionRef.current = rev.version_num;
        setHasJrxml(true);
        setJrxmlContent(rev.content);
        setSavedContent(rev.content);
        setVersionNum(rev.version_num);
        setReportParameters(localParams);
        initialLoadedRef.current = true;
        setLoadingArtifact(false);

        // Sincroniza parâmetros com o backend quando disponível (silencioso em fallback)
        if (typeof fetch === "function") {
          void fetch(
            `/api/projects/${encodeURIComponent(project.id)}/jasper/parameters`,
          )
            .then(async (resp) => {
              if (!resp.ok || cancelled) return;
              const data = (await resp.json()) as {
                parameters?: JrxmlParameterInfo[];
              };
              if (!cancelled && Array.isArray(data?.parameters)) {
                setReportParameters(data.parameters);
              }
            })
            .catch(() => {
              // Mantém parâmetros extraídos localmente
            });
        }

        // Busca status de recursos repo:
        void fetchRepoResources(project.id);

        // Option A Smart Initial Preview:
        // Para free_report com parâmetros obrigatórios ($P{} sem default e não preenchidos),
        // não dispara preview fadado a erro; exibe estado calmo pedindo preenchimento!
        const missingOnMount = getMissingRequiredParams(
          localParams,
          storedParams,
        );
        if (
          project.project_kind === "free_report" &&
          missingOnMount.length > 0
        ) {
          setPreviewDeferredForParams(true);
        } else {
          setPreviewDeferredForParams(false);
          void runPreview({
            scenario: "full",
            mode: initialMode,
            dbProfileId: resolvedProfileId,
            inlineJrxml: rev.content,
            reportParamsOverride: storedParams,
            silent: true,
          });
        }
      } else {
        const reason = artifactRes.reason;
        const isNotFound = reason instanceof ApiError && reason.status === 404;
        loadedVersionRef.current = null;
        setHasJrxml(false);
        setJrxmlContent("");
        setSavedContent("");
        setVersionNum(null);
        initialLoadedRef.current = true;
        setLoadingArtifact(false);

        if (!isNotFound && reason instanceof Error) {
          pushToast({
            tone: "error",
            title: "Falha ao carregar .jrxml",
            description: reason.message,
          });
        }
      }
    };

    initialLoadedRef.current = false;
    loadedVersionRef.current = null;
    void loadInitial();

    return () => {
      cancelled = true;
      if (liveReloadTimerRef.current !== null) {
        window.clearTimeout(liveReloadTimerRef.current);
        liveReloadTimerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  // Atualização automática do editor JRXML e do Preview quando o agente gerar uma nova revisão
  const latestJrxmlVersion = project.latest_artifacts?.jrxml ?? null;
  useEffect(() => {
    if (!initialLoadedRef.current) return;
    if (latestJrxmlVersion === null && artifactSyncTick === 0) return;
    if (
      latestJrxmlVersion !== null &&
      latestJrxmlVersion === loadedVersionRef.current
    ) {
      return;
    }

    let cancelled = false;
    api
      .getArtifact(project.id, "jrxml")
      .then((rev) => {
        if (cancelled) return;
        if (rev.version_num === loadedVersionRef.current) return;
        const updatedParams = parseJrxmlParametersLocally(rev.content);
        loadedVersionRef.current = rev.version_num;
        userEditedRef.current = false;
        jrxmlRef.current = rev.content;
        setHasJrxml(true);
        setJrxmlContent(rev.content);
        setSavedContent(rev.content);
        setVersionNum(rev.version_num);
        setReportParameters(updatedParams);
        setCompileResult(null);
        setCompileError(null);
        setLintReport(null);

        void fetchRepoResources(project.id);

        const missingNow = getMissingRequiredParams(
          updatedParams,
          reportParamValues,
        );
        if (isFreeReport && missingNow.length > 0 && !previewResult) {
          setPreviewDeferredForParams(true);
        } else {
          void runPreview({ inlineJrxml: rev.content, silent: true });
        }
      })
      .catch(() => {
        // Ignora erro transitório em refresh silencioso
      });

    return () => {
      cancelled = true;
    };
  }, [
    project.id,
    latestJrxmlVersion,
    artifactSyncTick,
    fetchRepoResources,
    isFreeReport,
    previewResult,
    reportParamValues,
    runPreview,
  ]);

  // Live-reload debounced (~900ms) após edições no editor
  useEffect(() => {
    if (!liveReload || !hasJrxml || !userEditedRef.current) return;

    if (liveReloadTimerRef.current !== null) {
      window.clearTimeout(liveReloadTimerRef.current);
    }

    liveReloadTimerRef.current = window.setTimeout(() => {
      liveReloadTimerRef.current = null;
      void runPreview({ inlineJrxml: jrxmlContent, silent: true });
    }, LIVE_RELOAD_DEBOUNCE_MS);

    return () => {
      if (liveReloadTimerRef.current !== null) {
        window.clearTimeout(liveReloadTimerRef.current);
        liveReloadTimerRef.current = null;
      }
    };
  }, [jrxmlContent, liveReload, hasJrxml, runPreview]);

  const handleChangeJrxml = useCallback((next: string) => {
    userEditedRef.current = true;
    setJrxmlContent(next);
    setReportParameters(parseJrxmlParametersLocally(next));
  }, []);

  const handleChangeReportParamValue = useCallback(
    (name: string, value: string) => {
      setReportParamValues((prev) => {
        const next = { ...prev, [name]: value };
        saveStoredReportParams(project.id, next);
        return next;
      });
    },
    [project.id],
  );

  const handleClearReportParams = useCallback(() => {
    setReportParamValues({});
    saveStoredReportParams(project.id, {});
  }, [project.id]);

  const handleScaffold = useCallback(
    async (targetOrientation: ClinicalOrientation) => {
      setScaffolding(true);
      try {
        const res = await api.scaffoldJrxml(project.id, {
          save_artifact: true,
          options: { orientacao: targetOrientation },
        });
        userEditedRef.current = false;
        setHasJrxml(true);
        setJrxmlContent(res.jrxml);
        setSavedContent(res.jrxml);
        const nextVersion =
          res.saved_revision?.version_num ?? (versionNum ?? 0) + 1;
        loadedVersionRef.current = nextVersion;
        setVersionNum(nextVersion);
        setLintReport(res.lint ?? null);
        setCompileResult(null);
        setCompileError(null);

        onProjectUpdated({
          ...project,
          latest_artifacts: {
            ...project.latest_artifacts,
            jrxml: nextVersion,
          },
        });

        pushToast({
          tone: "success",
          title: "Scaffold .jrxml gerado",
          description: `Orientação ${targetOrientation} salva como revisão v${nextVersion}.`,
        });

        void runPreview({ inlineJrxml: res.jrxml, silent: true });
      } catch (err) {
        pushToast({
          tone: "error",
          title: "Falha ao gerar scaffold .jrxml",
          description: err instanceof Error ? err.message : String(err),
        });
      } finally {
        setScaffolding(false);
      }
    },
    [onProjectUpdated, project, pushToast, runPreview, versionNum],
  );

  const handleLint = useCallback(async () => {
    if (!jrxmlContent.trim()) return;
    setLinting(true);
    try {
      const report = await api.lintJrxml(project.id, jrxmlContent);
      setLintReport(report);
      setDiagnosticsOpen(true);
      const errCount = report.errors?.length ?? 0;
      const warnCount = report.warnings?.length ?? 0;
      pushToast({
        tone: errCount > 0 ? "warning" : "success",
        title:
          errCount > 0
            ? `Linter encontrou ${errCount} erro(s)`
            : "Auditoria Fase 4 sem erros",
        description:
          warnCount > 0 ? `${warnCount} aviso(s) reportado(s).` : undefined,
      });
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Erro ao auditar JRXML",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLinting(false);
    }
  }, [jrxmlContent, project.id, pushToast]);

  const handleCompile = useCallback(async () => {
    if (!jrxmlContent.trim()) return;
    setCompiling(true);
    setCompileError(null);
    try {
      const res = await api.compileJasper(project.id, {
        inline_jrxml: jrxmlContent,
        run_linter: true,
      });
      setCompileResult(res);
      if (res.lint) {
        setLintReport(res.lint);
      }
      setDiagnosticsOpen(true);

      if (res.ok) {
        pushToast({
          tone: "success",
          title: "Compilação .jasper concluída",
          description: "Relatório compilado sem erros na JVM.",
        });
      } else {
        const daemonMsg =
          extractDaemonError(res.daemon) ||
          "Falha na compilação JasperReports.";
        setCompileError(daemonMsg);
        pushToast({
          tone: "error",
          title: "Erro ao compilar .jasper",
          description: daemonMsg,
        });
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setCompileResult(null);
      setCompileError(message);
      setDiagnosticsOpen(true);
      pushToast({
        tone: "error",
        title: "Falha na compilação JVM",
        description: message,
      });
    } finally {
      setCompiling(false);
    }
  }, [jrxmlContent, project.id, pushToast]);

  const handleSave = useCallback(async () => {
    if (!jrxmlContent.trim()) return;
    setSaving(true);
    try {
      const res = await api.saveArtifact(project.id, "jrxml", {
        content: jrxmlContent,
        summary: "Edição no Jasper Studio Light",
        created_by: "user",
      });
      userEditedRef.current = false;
      loadedVersionRef.current = res.artifact.version_num;
      setSavedContent(res.artifact.content);
      setVersionNum(res.artifact.version_num);

      onProjectUpdated({
        ...project,
        latest_artifacts: {
          ...project.latest_artifacts,
          jrxml: res.artifact.version_num,
        },
      });

      pushToast({
        tone: "success",
        title: `Revisão v${res.artifact.version_num} salva`,
      });

      void fetchRepoResources(project.id);

      if (liveReload) {
        if (liveReloadTimerRef.current !== null) {
          window.clearTimeout(liveReloadTimerRef.current);
          liveReloadTimerRef.current = null;
        }
        void runPreview({ inlineJrxml: res.artifact.content, silent: true });
      }
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao salvar revisão .jrxml",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSaving(false);
    }
  }, [
    fetchRepoResources,
    jrxmlContent,
    liveReload,
    onProjectUpdated,
    project,
    pushToast,
    runPreview,
  ]);

  const handleChangeScenario = useCallback(
    (nextScenario: ScenarioType) => {
      setScenario(nextScenario);
      if (hasJrxml) {
        void runPreview({ scenario: nextScenario });
      }
    },
    [hasJrxml, runPreview],
  );

  const handleChangeMode = useCallback(
    (nextMode: PreviewMode) => {
      setMode(nextMode);
      if (hasJrxml) {
        if (
          (nextMode === "db_hybrid" || nextMode === "db_live") &&
          !selectedDbProfileId
        ) {
          setPreviewError(
            nextMode === "db_live"
              ? "Selecione um perfil PostgreSQL para executar o preview em modo Live (Banco Real)."
              : "Selecione um perfil PostgreSQL para executar o preview em Banco Híbrido (CTE).",
          );
          return;
        }
        if (
          isFreeReport &&
          previewDeferredForParams &&
          missingRequiredParams.length > 0
        ) {
          return;
        }
        void runPreview({ mode: nextMode });
      }
    },
    [
      hasJrxml,
      isFreeReport,
      missingRequiredParams.length,
      previewDeferredForParams,
      runPreview,
      selectedDbProfileId,
    ],
  );

  const handleChangeDbProfileId = useCallback(
    (nextProfileId: string) => {
      setSelectedDbProfileId(nextProfileId);
      if (
        hasJrxml &&
        (mode === "db_hybrid" || mode === "db_live") &&
        nextProfileId
      ) {
        if (
          isFreeReport &&
          previewDeferredForParams &&
          missingRequiredParams.length > 0
        ) {
          return;
        }
        void runPreview({ mode, dbProfileId: nextProfileId });
      }
    },
    [
      hasJrxml,
      isFreeReport,
      missingRequiredParams.length,
      mode,
      previewDeferredForParams,
      runPreview,
    ],
  );

  const handleSubmitAnnotation = useCallback(
    async ({
      page,
      pdfRect,
      detailCoords,
      content,
    }: RegionAnnotationSubmitPayload) => {
      setSubmittingAnnotation(true);
      try {
        let savedMsg;
        let cropped = false;
        try {
          const cropRes = await api.submitVisualRegionFeedback(project.id, {
            page,
            pdf_rect: pdfRect,
            detail_coords: detailCoords,
            scenario,
            content,
            dpi: 200,
          });
          savedMsg = cropRes.message;
          cropped = Boolean(cropRes.crop_url);
        } catch (cropErr) {
          if (cropErr instanceof ApiError && cropErr.status !== 404) {
            throw cropErr;
          }
          savedMsg = await api.appendChat(project.id, {
            phase: "jrxml",
            role: "user",
            content,
            metadata: {
              type: "visual_region_feedback",
              page,
              pdf_rect: pdfRect,
              detail_coords: detailCoords,
              scenario,
            },
          });
        }

        const parsed = chatMessageToAnnotation(savedMsg) ?? {
          id: savedMsg.id ?? `local-${Date.now()}`,
          content,
          createdAt: savedMsg.created_at ?? new Date().toISOString(),
          page,
          scenario,
          pdfRect,
          detailCoords,
        };
        setAnnotations((prev) => [...prev, parsed]);

        pushToast({
          tone: "success",
          title: cropped
            ? "Ajuste visual com recorte PNG enviado ao agente"
            : "Ajuste visual enviado ao agente",
          description: `Página ${page} · detail(${detailCoords.x}, ${detailCoords.y})`,
        });
      } catch (err) {
        pushToast({
          tone: "error",
          title: "Falha ao enviar ajuste visual",
          description: err instanceof Error ? err.message : String(err),
        });
        throw err;
      } finally {
        setSubmittingAnnotation(false);
      }
    },
    [project.id, pushToast, scenario],
  );

  const handleDownloadJrxml = useCallback(() => {
    if (!jrxmlContent.trim()) return;
    triggerTextDownload(`${project.slug}.jrxml`, jrxmlContent);
  }, [jrxmlContent, project.slug]);

  const openJrxmlChat = useMemo(
    () => (onOpenAgentChat ? () => onOpenAgentChat("jrxml") : undefined),
    [onOpenAgentChat],
  );

  const showRequiredParamsEmptyState =
    isFreeReport &&
    hasJrxml &&
    previewDeferredForParams &&
    !previewResult &&
    !previewLoading;

  const editorPane = (
    <JrxmlEditorPane
      loading={loadingArtifact}
      hasJrxml={hasJrxml}
      jrxmlContent={jrxmlContent}
      versionNum={versionNum}
      dirty={dirty}
      scaffolding={scaffolding}
      linting={linting}
      compiling={compiling}
      saving={saving}
      liveReload={liveReload}
      onToggleLiveReload={setLiveReload}
      onChangeJrxml={handleChangeJrxml}
      onScaffold={handleScaffold}
      onLint={handleLint}
      onCompile={handleCompile}
      onSave={handleSave}
      lintReport={lintReport}
      compileResult={compileResult}
      compileError={compileError}
      diagnosticsOpen={diagnosticsOpen}
      onToggleDiagnostics={() => setDiagnosticsOpen((prev) => !prev)}
      selectedLine={selectedLine}
      onSelectLine={(line) => setSelectedLine(line)}
    />
  );

  const previewPane = (
    <div className="flex h-full min-h-0 flex-col bg-canvas">
      <PreviewControlBar
        projectId={project.id}
        projectSlug={project.slug}
        projectKind={project.project_kind}
        sourceOrigin={project.source_origin}
        hasJrxml={hasJrxml}
        scenario={scenario}
        onChangeScenario={handleChangeScenario}
        mode={mode}
        onChangeMode={handleChangeMode}
        dbProfiles={dbProfiles}
        selectedDbProfileId={selectedDbProfileId}
        onChangeDbProfileId={handleChangeDbProfileId}
        atendimentoIdInput={atendimentoIdInput}
        onChangeAtendimentoIdInput={setAtendimentoIdInput}
        previewLoading={previewLoading}
        previewResult={previewResult}
        previewError={previewError}
        cacheBuster={cacheBuster}
        onRefreshPreview={() => void runPreview()}
        onDownloadJrxml={handleDownloadJrxml}
        layoutMode={layoutMode}
        onChangeLayoutMode={handleChangeLayoutMode}
        repoStatus={repoStatus}
        syncingRepo={syncingRepo}
        onSyncRepoResources={() => void handleSyncRepoResources()}
        onOpenAgentChat={openJrxmlChat}
        headerExtraActions={headerExtraActions}
      />

      {layoutMode === "visual" && hasJrxml && (
        <div
          data-testid="visual-mode-tip-bar"
          className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-blueprint-soft/35 px-3 py-1.5 text-xs text-ink-secondary"
        >
          <div className="flex items-center gap-1.5">
            <Crosshair className="h-3.5 w-3.5 shrink-0 text-blueprint" />
            <span>
              Dica: clique em{" "}
              <strong className="text-ink">Selecionar área para ajuste</strong>{" "}
              no PDF para marcar exatamente onde quer alterar, ou peça direto à
              IA.
            </span>
          </div>
          <button
            type="button"
            onClick={() => handleChangeLayoutMode("split")}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-ink-muted hover:text-accent cursor-pointer"
          >
            <Code2 className="h-3 w-3" />
            Ver XML
          </button>
        </div>
      )}

      <ReportParamsBar
        parameters={reportParameters}
        values={reportParamValues}
        onChangeValue={handleChangeReportParamValue}
        onClearAll={handleClearReportParams}
        onApplyPreview={() => void runPreview()}
        previewLoading={previewLoading}
        defaultOpen={
          mode === "db_live" ||
          isFreeReport ||
          missingRequiredParams.length > 0
        }
        hasPreview={Boolean(previewResult)}
      />

      {showRequiredParamsEmptyState ? (
        <div
          data-testid="required-params-empty-state"
          className="flex min-h-0 flex-1 items-center justify-center bg-surface-subtle/60 p-6"
        >
          <EmptyState
            className="max-w-lg"
            icon={<Sliders className="h-5 w-5 text-blueprint" />}
            title={
              missingRequiredParams.length > 0
                ? "Preencha os parâmetros para gerar o preview"
                : "Parâmetros prontos para gerar o preview"
            }
            description={
              missingRequiredParams.length > 0
                ? `Este relatório precisa de parâmetros para gerar o preview (${missingRequiredParams.map((p) => p.name).join(", ")}). Preencha acima e clique em Gerar Preview.`
                : "Todos os parâmetros obrigatórios foram preenchidos. Clique em Gerar Preview para visualizar o PDF."
            }
            action={
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Play className="h-3.5 w-3.5" />}
                  onClick={() => void runPreview()}
                >
                  Gerar Preview
                </Button>
                {openJrxmlChat && (
                  <Button
                    variant="outline"
                    size="sm"
                    icon={<Sparkles className="h-3.5 w-3.5" />}
                    onClick={openJrxmlChat}
                  >
                    Pedir ajuste à IA
                  </Button>
                )}
              </div>
            }
          />
        </div>
      ) : layoutMode === "visual" && !loadingArtifact && !hasJrxml ? (
        <div className="flex min-h-0 flex-1 items-center justify-center bg-surface-subtle/60 p-6">
          <EmptyState
            className="max-w-lg"
            icon={<FileText className="h-5 w-5 text-accent" />}
            title="Nenhum arquivo .jrxml neste projeto ainda"
            description="Peça à IA para criar o relatório ou abra o modo Código para gerar um template inicial."
            action={
              <div className="flex flex-wrap items-center justify-center gap-2">
                {openJrxmlChat && (
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<Sparkles className="h-3.5 w-3.5" />}
                    onClick={openJrxmlChat}
                  >
                    Pedir ajuste à IA
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  icon={<Code2 className="h-3.5 w-3.5" />}
                  onClick={() => handleChangeLayoutMode("split")}
                >
                  Abrir editor XML
                </Button>
              </div>
            }
          />
        </div>
      ) : (
        <PdfPreviewCanvas
          projectId={project.id}
          hasJrxml={hasJrxml}
          scenario={scenario}
          orientation={orientation}
          previewResult={previewResult}
          previewLoading={previewLoading}
          cacheBuster={cacheBuster}
          annotations={annotations}
          submittingAnnotation={submittingAnnotation}
          onSubmitAnnotation={handleSubmitAnnotation}
          onGeneratePreview={() => void runPreview()}
          onOpenAgentChat={openJrxmlChat}
        />
      )}
    </div>
  );

  if (layoutMode === "visual") {
    return (
      <div
        data-testid="jasper-studio-visual-mode"
        className="flex h-full min-h-0 flex-col bg-canvas"
      >
        {previewPane}
      </div>
    );
  }

  if (layoutMode === "code") {
    return (
      <div
        data-testid="jasper-studio-code-mode"
        className="flex h-full min-h-0 flex-col bg-canvas"
      >
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border bg-surface px-3 py-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <LayoutModeSwitcher
              layoutMode={layoutMode}
              onChangeLayoutMode={handleChangeLayoutMode}
            />
            <RepoResourcesChip
              repoStatus={repoStatus}
              syncingRepo={syncingRepo}
              onSyncRepoResources={() => void handleSyncRepoResources()}
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {openJrxmlChat && (
              <Button
                variant="blueprint"
                size="xs"
                icon={<Sparkles className="h-3.5 w-3.5" />}
                onClick={openJrxmlChat}
              >
                Pedir ajuste à IA
              </Button>
            )}
            {headerExtraActions}
          </div>
        </div>
        <div className="min-h-0 flex-1">{editorPane}</div>
      </div>
    );
  }

  return (
    <div
      data-testid="jasper-studio-split-mode"
      className="flex h-full min-h-0 flex-col bg-canvas"
    >
      <SplitPane
        storageKey="salutem:split:jasper-studio"
        initialRatio={0.48}
        minRatio={0.28}
        maxRatio={0.72}
        left={editorPane}
        right={previewPane}
      />
    </div>
  );
}
