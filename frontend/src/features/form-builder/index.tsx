import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import {
  AlertTriangle,
  ArrowRight,
  FileJson,
  FilePlus2,
  Loader2,
  Save,
  Upload,
} from "lucide-react";
import {
  Badge,
  Button,
  EmptyState,
  SplitPane,
  Switch,
  useToast,
} from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { FormBuilderViewProps } from "@/types/feature-props";
import type {
  ClinicalFormJson,
  ClinicalQuestion,
  ClinicalTemplateMeta,
  ClinicalWarningItem,
  ProjectRead,
} from "@/types/studio";
import {
  applyUppercaseClinicalForm,
  createBlankClinicalForm,
  formatClinicalFormJson,
  normalizeWarnings,
  parseClinicalFormJson,
  renumberClinicalForm,
} from "./model";
import { QuestionsList } from "./QuestionsList";
import { RightInspectorPane } from "./RightInspectorPane";
import { TemplateMetaPanel } from "./TemplateMetaPanel";
import { WarningsBanner } from "./WarningsBanner";

export function FormBuilderView({
  project,
  onProjectUpdated,
  onNavigateSection,
  artifactSyncTick = 0,
}: FormBuilderViewProps) {
  const { pushToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const loadedVersionRef = useRef<number | null>(null);
  const initialLoadedRef = useRef(false);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [formModel, setFormModel] = useState<ClinicalFormJson | null>(null);
  const [jsonText, setJsonText] = useState<string>("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [versionNum, setVersionNum] = useState<number | null>(null);

  const [warnings, setWarnings] = useState<ClinicalWarningItem[]>([]);
  const [schemaWarnings, setSchemaWarnings] = useState<ClinicalWarningItem[]>([]);
  const [loadingWarnings, setLoadingWarnings] = useState(false);
  const lastSchemaWarnSigRef = useRef<string>("");

  const reportSchemaWarnings = useCallback(
    (nextWarnings: ClinicalWarningItem[], notifyToast: boolean) => {
      setSchemaWarnings(nextWarnings);
      const sig = nextWarnings
        .map((w) => `${w.code ?? ""}:${w.path ?? ""}`)
        .join("|");
      if (notifyToast && nextWarnings.length > 0 && sig !== lastSchemaWarnSigRef.current) {
        pushToast({
          tone: "warning",
          title: "Estrutura JSON Salutem incompatível",
          description: `${nextWarnings.length} campo(s) esperado(s) ausente(s): ${nextWarnings[0].message}`,
        });
      }
      lastSchemaWarnSigRef.current = sig;
    },
    [pushToast],
  );

  const [autoRegenerateSql, setAutoRegenerateSql] = useState(true);
  const [applyUppercase, setApplyUppercase] = useState(true);
  const [saving, setSaving] = useState(false);

  const fetchWarnings = useCallback(async (projectId: string) => {
    setLoadingWarnings(true);
    try {
      const res = await api.getJsonWarnings(projectId);
      setWarnings(normalizeWarnings(res.warnings));
    } catch {
      setWarnings([]);
    } finally {
      setLoadingWarnings(false);
    }
  }, []);

  const loadProjectJson = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    setIsDirty(false);
    setJsonError(null);
    setWarnings([]);
    setSchemaWarnings([]);
    lastSchemaWarnSigRef.current = "";

    try {
      const artifact = await api.getArtifact(project.id, "json");
      const raw = artifact.content ?? "";
      loadedVersionRef.current = artifact.version_num;
      setVersionNum(artifact.version_num);
      setJsonText(raw);

      const parsed = parseClinicalFormJson(raw);
      if (parsed.data) {
        setFormModel(renumberClinicalForm(parsed.data));
        setJsonError(null);
        reportSchemaWarnings(parsed.schemaWarnings, true);
      } else {
        setFormModel(null);
        setJsonError(parsed.error);
        reportSchemaWarnings([], false);
      }

      void fetchWarnings(project.id);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        loadedVersionRef.current = null;
        setFormModel(null);
        setJsonText("");
        setVersionNum(null);
        setWarnings([]);
      } else {
        setLoadError(
          err instanceof Error
            ? err.message
            : "Erro ao carregar o artefato JSON do projeto.",
        );
      }
    } finally {
      initialLoadedRef.current = true;
      setLoading(false);
    }
  }, [project.id, fetchWarnings, reportSchemaWarnings]);

  useEffect(() => {
    initialLoadedRef.current = false;
    loadedVersionRef.current = null;
    void loadProjectJson();
  }, [loadProjectJson]);

  // Atualização automática quando o agente ou outra tela gerar uma nova revisão JSON
  const latestJsonVersion = project.latest_artifacts?.json ?? null;
  useEffect(() => {
    if (!initialLoadedRef.current) return;
    if (latestJsonVersion === null && artifactSyncTick === 0) return;
    if (latestJsonVersion !== null && latestJsonVersion === loadedVersionRef.current) {
      return;
    }

    let cancelled = false;
    api
      .getArtifact(project.id, "json")
      .then((artifact) => {
        if (cancelled) return;
        if (artifact.version_num === loadedVersionRef.current) return;
        const raw = artifact.content ?? "";
        loadedVersionRef.current = artifact.version_num;
        setVersionNum(artifact.version_num);
        setJsonText(raw);
        setIsDirty(false);
        const parsed = parseClinicalFormJson(raw);
        if (parsed.data) {
          setFormModel(renumberClinicalForm(parsed.data));
          setJsonError(null);
          reportSchemaWarnings(parsed.schemaWarnings, false);
        } else {
          setFormModel(null);
          setJsonError(parsed.error);
          reportSchemaWarnings([], false);
        }
        void fetchWarnings(project.id);
      })
      .catch(() => {
        // Ignora erro transitório em refresh silencioso
      });

    return () => {
      cancelled = true;
    };
  }, [
    project.id,
    latestJsonVersion,
    artifactSyncTick,
    fetchWarnings,
    reportSchemaWarnings,
  ]);

  const applyModelUpdate = useCallback((next: ClinicalFormJson) => {
    const normalized = renumberClinicalForm(next);
    setFormModel(normalized);
    setJsonText(formatClinicalFormJson(normalized));
    setJsonError(null);
    setIsDirty(true);
  }, []);

  const handleTemplateChange = useCallback(
    (nextTemplate: ClinicalTemplateMeta) => {
      if (!formModel) return;
      applyModelUpdate({
        ...formModel,
        template: nextTemplate,
      });
    },
    [formModel, applyModelUpdate],
  );

  const handleQuestionsChange = useCallback(
    (nextPerguntas: ClinicalQuestion[]) => {
      if (!formModel) return;
      applyModelUpdate({
        ...formModel,
        perguntas: nextPerguntas,
      });
    },
    [formModel, applyModelUpdate],
  );

  const handleJsonTextChange = useCallback(
    (nextText: string) => {
      setJsonText(nextText);
      setIsDirty(true);

      const parsed = parseClinicalFormJson(nextText);
      if (parsed.data) {
        setFormModel(parsed.data);
        setJsonError(null);
        reportSchemaWarnings(parsed.schemaWarnings, true);
      } else {
        setJsonError(parsed.error);
        reportSchemaWarnings([], false);
      }
    },
    [reportSchemaWarnings],
  );

  const handleFormatJson = useCallback(() => {
    const parsed = parseClinicalFormJson(jsonText);
    if (parsed.data) {
      const normalized = renumberClinicalForm(parsed.data);
      setFormModel(normalized);
      setJsonText(formatClinicalFormJson(normalized));
      setJsonError(null);
    } else {
      setJsonError(parsed.error);
    }
  }, [jsonText]);

  const handleApplyUppercaseLocal = useCallback(() => {
    const parsed = parseClinicalFormJson(jsonText);
    if (!parsed.data) {
      setJsonError(parsed.error);
      return;
    }
    const upper = applyUppercaseClinicalForm(parsed.data);
    setFormModel(upper);
    setJsonText(formatClinicalFormJson(upper));
    setJsonError(null);
    setIsDirty(true);
    pushToast({
      tone: "info",
      title: "UPPERCASE aplicado localmente",
      description: "Salve a revisão para persistir as alterações.",
    });
  }, [jsonText, pushToast]);

  const handleCreateBlank = useCallback(() => {
    const blank = createBlankClinicalForm(project.name);
    applyModelUpdate(blank);
    setWarnings([]);
    reportSchemaWarnings([], false);
    pushToast({
      tone: "info",
      title: "Ficha em branco criada",
      description: "Edite os campos e clique em Salvar revisão.",
    });
  }, [project.name, applyModelUpdate, pushToast, reportSchemaWarnings]);

  const handleTriggerFileImport = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;

    try {
      const text = await file.text();
      const parsed = parseClinicalFormJson(text);
      if (!parsed.data) {
        pushToast({
          tone: "error",
          title: "Arquivo JSON inválido",
          description: parsed.error ?? "Verifique a estrutura Salutem.",
        });
        return;
      }
      applyModelUpdate(parsed.data);
      reportSchemaWarnings(parsed.schemaWarnings, false);
      if (parsed.schemaWarnings.length > 0) {
        pushToast({
          tone: "warning",
          title: `Arquivo "${file.name}" importado com avisos de esquema`,
          description: parsed.schemaWarnings[0].message,
        });
      } else {
        pushToast({
          tone: "success",
          title: `Arquivo "${file.name}" importado`,
          description: "Revise os campos e salve a revisão no projeto.",
        });
      }
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao ler arquivo .json",
        description: err instanceof Error ? err.message : String(err),
      });
    }
  };

  const handleSaveRevision = async () => {
    const parsed = parseClinicalFormJson(jsonText);
    if (!parsed.data) {
      setJsonError(parsed.error);
      pushToast({
        tone: "error",
        title: "Corrija o JSON antes de salvar",
        description: parsed.error ?? undefined,
      });
      return;
    }

    const prepared = applyUppercase
      ? applyUppercaseClinicalForm(parsed.data)
      : renumberClinicalForm(parsed.data);
    const payloadContent = formatClinicalFormJson(prepared);

    setSaving(true);
    try {
      const response = await api.saveArtifact(project.id, "json", {
        content: payloadContent,
        summary: "Edição via Form Builder Visual",
        created_by: "user",
        auto_regenerate_sql: autoRegenerateSql,
        apply_uppercase: applyUppercase,
      });

      const savedContent = response.artifact.content || payloadContent;
      setJsonText(savedContent);
      const savedParsed = parseClinicalFormJson(savedContent);
      if (savedParsed.data) {
        setFormModel(renumberClinicalForm(savedParsed.data));
      } else {
        setFormModel(prepared);
      }
      setJsonError(null);
      setIsDirty(false);
      loadedVersionRef.current = response.artifact.version_num;
      setVersionNum(response.artifact.version_num);

      const nextArtifacts: Record<string, number> = {
        ...project.latest_artifacts,
        json: response.artifact.version_num,
      };
      if (response.generated_sql_insert) {
        nextArtifacts.sql_insert = response.generated_sql_insert.version_num;
      }
      if (response.generated_sql_select) {
        nextArtifacts.sql_select = response.generated_sql_select.version_num;
      }

      const updatedProject: ProjectRead = {
        ...project,
        latest_artifacts: nextArtifacts,
        updated_at: response.artifact.created_at || project.updated_at,
      };
      onProjectUpdated(updatedProject);

      const sqlRegenerated = Boolean(
        response.generated_sql_insert || response.generated_sql_select,
      );
      pushToast({
        tone: "success",
        title: `Revisão JSON v${response.artifact.version_num} salva`,
        description: sqlRegenerated
          ? "Scripts SQL INSERT e SELECT regenerados automaticamente."
          : "Artefato JSON atualizado no histórico de revisões.",
      });

      void fetchWarnings(project.id);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao salvar revisão JSON",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const hasContent = formModel !== null || jsonText.trim().length > 0;

  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas">
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        aria-label="Importar arquivo JSON"
        className="hidden"
        onChange={(e) => void handleFileSelected(e)}
      />

      {/* Top Action Bar */}
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2 min-w-0">
          <FileJson className="h-4 w-4 shrink-0 text-accent" />
          <h2 className="text-sm font-semibold text-ink truncate">
            Form Builder — {project.name}
          </h2>
          {versionNum !== null ? (
            <Badge tone="blueprint" className="font-mono tabular-nums">
              JSON v{versionNum}
            </Badge>
          ) : hasContent ? (
            <Badge tone="neutral">Rascunho local</Badge>
          ) : null}

          {isDirty && (
            <Badge tone="warning" dot>
              Alterações não salvas
            </Badge>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {hasContent && (
            <>
              <Switch
                id="fb-auto-sql"
                checked={autoRegenerateSql}
                onChange={setAutoRegenerateSql}
                label="Regenerar SQL ao salvar"
              />
              <Switch
                id="fb-uppercase"
                checked={applyUppercase}
                onChange={setApplyUppercase}
                label="Aplicar UPPERCASE"
              />
              <Button
                variant="outline"
                size="sm"
                icon={<Upload className="h-3.5 w-3.5" />}
                onClick={handleTriggerFileImport}
              >
                Importar .json
              </Button>
              <Button
                variant="primary"
                size="sm"
                loading={saving}
                disabled={Boolean(jsonError)}
                icon={<Save className="h-3.5 w-3.5" />}
                onClick={() => void handleSaveRevision()}
              >
                Salvar revisão
              </Button>
            </>
          )}

          <Button
            variant="blueprint"
            size="sm"
            icon={<ArrowRight className="h-3.5 w-3.5" />}
            onClick={() => onNavigateSection("sql_db")}
          >
            Avançar para SQL &amp; Banco
          </Button>
        </div>
      </header>

      {/* Clinical Warnings Collapsible Banner */}
      {hasContent && (
        <WarningsBanner warnings={warnings} loading={loadingWarnings} />
      )}

      {/* Schema Mismatch Validation Banner */}
      {hasContent && schemaWarnings.length > 0 && (
        <div
          data-testid="json-schema-warning-banner"
          role="alert"
          className="border-b border-warning/40 bg-warning-soft/80 px-4 py-2 text-xs text-ink"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <div className="min-w-0 flex-1 space-y-1">
              <p className="font-semibold text-warning">
                Aviso de estrutura JSON Salutem ({schemaWarnings.length}{" "}
                {schemaWarnings.length === 1 ? "inconsistência" : "inconsistências"})
              </p>
              <ul className="space-y-0.5 text-ink-secondary">
                {schemaWarnings.slice(0, 5).map((item, idx) => (
                  <li key={`${item.code ?? "schema"}-${item.path ?? idx}-${idx}`}>
                    {item.path && (
                      <code className="mr-1.5 rounded bg-warning/15 px-1 py-0.5 font-mono text-[10px] text-warning">
                        {item.path}
                      </code>
                    )}
                    <span>{item.message}</span>
                  </li>
                ))}
                {schemaWarnings.length > 5 && (
                  <li className="text-[11px] text-ink-muted">
                    +{schemaWarnings.length - 5} outro(s) aviso(s) de estrutura.
                  </li>
                )}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Main Body */}
      {loading ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-ink-muted">
          <Loader2 className="h-4 w-4 animate-spin text-accent" />
          <span>Carregando JSON da ficha clínica...</span>
        </div>
      ) : loadError ? (
        <div className="p-6">
          <EmptyState
            title="Não foi possível carregar o JSON"
            description={loadError}
            action={
              <Button variant="primary" onClick={() => void loadProjectJson()}>
                Tentar novamente
              </Button>
            }
          />
        </div>
      ) : !hasContent ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState
            icon={<FileJson className="h-5 w-5 text-accent" />}
            title="Nenhuma estrutura JSON criada para este projeto"
            description="Crie uma ficha clínica Salutem em branco para montar visualmente ou importe um arquivo .json já extraído."
            action={
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Button
                  variant="primary"
                  size="md"
                  icon={<FilePlus2 className="h-4 w-4" />}
                  onClick={handleCreateBlank}
                >
                  Criar ficha em branco
                </Button>
                <Button
                  variant="outline"
                  size="md"
                  icon={<Upload className="h-4 w-4" />}
                  onClick={handleTriggerFileImport}
                >
                  Importar arquivo .json
                </Button>
              </div>
            }
            className="max-w-xl w-full"
          />
        </div>
      ) : (
        <div className="min-h-0 flex-1">
          <SplitPane
            storageKey="salutem-form-builder-split"
            initialRatio={0.56}
            minRatio={0.3}
            maxRatio={0.75}
            left={
              <div className="h-full overflow-y-auto p-4 space-y-4">
                {formModel ? (
                  <>
                    <TemplateMetaPanel
                      template={formModel.template}
                      onChange={handleTemplateChange}
                    />
                    <QuestionsList
                      perguntas={formModel.perguntas}
                      onChange={handleQuestionsChange}
                    />
                  </>
                ) : (
                  <EmptyState
                    title="JSON aguardando correção"
                    description="Corrija a estrutura JSON no editor ao lado para reativar a visualização do Form Builder."
                  />
                )}
              </div>
            }
            right={
              <RightInspectorPane
                projectId={project.id}
                hasPdf={project.has_pdf}
                jsonText={jsonText}
                jsonError={jsonError}
                onJsonTextChange={handleJsonTextChange}
                onFormatJson={handleFormatJson}
                onApplyUppercaseLocal={handleApplyUppercaseLocal}
              />
            }
          />
        </div>
      )}
    </div>
  );
}
