import { useCallback, useEffect, useRef, useState } from "react";
import { SplitPane, useToast } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { JasperStudioViewProps } from "@/types/feature-props";
import type {
  ClinicalOrientation,
  DbProfileRead,
  JasperCompileResponse,
  JasperPreviewResponse,
  JrxmlLintReport,
  PreviewMode,
  ScenarioType,
} from "@/types/studio";
import { JrxmlEditorPane } from "./JrxmlEditorPane";
import { PdfPreviewCanvas } from "./PdfPreviewCanvas";
import { PreviewControlBar } from "./PreviewControlBar";
import type { RegionAnnotationSubmitPayload } from "./RegionAnnotationOverlay";
import {
  chatMessageToAnnotation,
  type VisualRegionAnnotation,
} from "./types";
import {
  detectJrxmlOrientation,
  extractDaemonError,
  triggerTextDownload,
} from "./utils";

const LIVE_RELOAD_DEBOUNCE_MS = 900;

export function JasperStudioView({
  project,
  onProjectUpdated,
  onOpenAgentChat,
  artifactSyncTick = 0,
}: JasperStudioViewProps) {
  const { pushToast } = useToast();
  const loadedVersionRef = useRef<number | null>(null);
  const initialLoadedRef = useRef(false);

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
  const [mode, setMode] = useState<PreviewMode>("auto");
  const [dbProfiles, setDbProfiles] = useState<DbProfileRead[]>([]);
  const [selectedDbProfileId, setSelectedDbProfileId] = useState("");
  const [atendimentoIdInput, setAtendimentoIdInput] = useState("");
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewResult, setPreviewResult] =
    useState<JasperPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [cacheBuster, setCacheBuster] = useState<number>(() => Date.now());

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

  const parseAtendimentoId = useCallback((raw: string): number | null => {
    const trimmed = raw.trim();
    if (!trimmed) return null;
    const parsed = Number(trimmed);
    return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
  }, []);

  const runPreview = useCallback(
    async (overrides?: {
      scenario?: ScenarioType;
      mode?: PreviewMode;
      dbProfileId?: string;
      atendimentoIdRaw?: string;
      inlineJrxml?: string;
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

      if (!targetXml.trim()) return;

      if (targetMode === "db_hybrid" && !targetProfileId) {
        setPreviewError(
          "Selecione um perfil PostgreSQL em Configurações ou na barra acima para usar o modo Banco Híbrido (CTE).",
        );
        return;
      }

      const reqSeq = ++previewReqSeqRef.current;
      setPreviewLoading(true);
      setPreviewError(null);

      try {
        const parsedAtend = parseAtendimentoId(targetAtendRaw);
        const res = await api.generatePreview(project.id, {
          scenario: targetScenario,
          mode: targetMode,
          db_profile_id:
            targetMode === "offline" ? null : targetProfileId || null,
          atendimento_id: parsedAtend,
          inline_jrxml: targetXml,
        });

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
      mode,
      parseAtendimentoId,
      project.id,
      pushToast,
      scenario,
      selectedDbProfileId,
    ],
  );

  // Carregamento inicial: JRXML + perfis PG + histórico de anotações visuais
  useEffect(() => {
    let cancelled = false;
    userEditedRef.current = false;
    setLoadingArtifact(true);
    setLintReport(null);
    setCompileResult(null);
    setCompileError(null);
    setPreviewResult(null);
    setPreviewError(null);
    setSelectedLine(null);

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
        const def = list.find((p) => p.is_default) ?? list[0];
        resolvedProfileId = def?.id ?? "";
        setSelectedDbProfileId(resolvedProfileId);
      } else {
        setDbProfiles([]);
        setSelectedDbProfileId("");
      }

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
        loadedVersionRef.current = rev.version_num;
        setHasJrxml(true);
        setJrxmlContent(rev.content);
        setSavedContent(rev.content);
        setVersionNum(rev.version_num);
        initialLoadedRef.current = true;
        setLoadingArtifact(false);

        void runPreview({
          scenario: "full",
          mode: "auto",
          dbProfileId: resolvedProfileId,
          inlineJrxml: rev.content,
          silent: true,
        });
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
        loadedVersionRef.current = rev.version_num;
        userEditedRef.current = false;
        jrxmlRef.current = rev.content;
        setHasJrxml(true);
        setJrxmlContent(rev.content);
        setSavedContent(rev.content);
        setVersionNum(rev.version_num);
        setCompileResult(null);
        setCompileError(null);
        setLintReport(null);

        void runPreview({ inlineJrxml: rev.content, silent: true });
      })
      .catch(() => {
        // Ignora erro transitório em refresh silencioso
      });

    return () => {
      cancelled = true;
    };
  }, [project.id, latestJrxmlVersion, artifactSyncTick, runPreview]);

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
  }, []);

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
        if (nextMode === "db_hybrid" && !selectedDbProfileId) {
          setPreviewError(
            "Selecione um perfil PostgreSQL para executar o preview em Banco Híbrido (CTE).",
          );
          return;
        }
        void runPreview({ mode: nextMode });
      }
    },
    [hasJrxml, runPreview, selectedDbProfileId],
  );

  const handleChangeDbProfileId = useCallback(
    (nextProfileId: string) => {
      setSelectedDbProfileId(nextProfileId);
      if (hasJrxml && mode === "db_hybrid" && nextProfileId) {
        void runPreview({ mode: "db_hybrid", dbProfileId: nextProfileId });
      }
    },
    [hasJrxml, mode, runPreview],
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

  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas">
      <SplitPane
        storageKey="salutem:split:jasper-studio"
        initialRatio={0.48}
        minRatio={0.28}
        maxRatio={0.72}
        left={
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
        }
        right={
          <div className="flex h-full min-h-0 flex-col bg-canvas">
            <PreviewControlBar
              projectId={project.id}
              projectSlug={project.slug}
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
            />

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
              onOpenAgentChat={
                onOpenAgentChat ? () => onOpenAgentChat("jrxml") : undefined
              }
            />
          </div>
        }
      />
    </div>
  );
}
