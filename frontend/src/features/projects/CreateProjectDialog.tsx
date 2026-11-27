import {
  useEffect,
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from "react";
import {
  AlertCircle,
  CloudDownload,
  FileCode2,
  FileJson,
  FileText,
  Server,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import {
  Button,
  Dialog,
  FieldLabel,
  Input,
  Select,
  Tabs,
  Textarea,
  useToast,
} from "@/components/ui";
import { JasperServerImportTab } from "@/features/jasperserver";
import { SftpImportTab } from "@/features/sftp";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { DbProfileRead, EntryMode, ProjectRead } from "@/types/studio";
import { formatBytes, HARNESS_OPTIONS } from "./projectMeta";

export interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (project: ProjectRead) => void;
  initialEntryMode?: EntryMode;
  initialName?: string;
  initialDbProfileId?: string | null;
  initialClientSystemId?: string | null;
  initialSftpProfileId?: string;
  initialJasperProfileId?: string;
}

const ENTRY_TABS: { id: EntryMode; label: string; icon: React.ReactNode }[] = [
  { id: "pdf", label: "PDF Clínico", icon: <FileText className="h-3.5 w-3.5" /> },
  {
    id: "blank_report",
    label: "Relatório Livre",
    icon: <Sparkles className="h-3.5 w-3.5" />,
  },
  {
    id: "json",
    label: "Importar JSON",
    icon: <FileJson className="h-3.5 w-3.5" />,
  },
  {
    id: "jrxml",
    label: "Importar JRXML",
    icon: <FileCode2 className="h-3.5 w-3.5" />,
  },
  {
    id: "sftp_import",
    label: "Importar SFTP",
    icon: <Server className="h-3.5 w-3.5" />,
  },
  {
    id: "jasperserver_import",
    label: "JasperServer",
    icon: <CloudDownload className="h-3.5 w-3.5" />,
  },
];

export function CreateProjectDialog({
  open,
  onClose,
  onCreated,
  initialEntryMode,
  initialName,
  initialDbProfileId,
  initialClientSystemId,
  initialSftpProfileId,
  initialJasperProfileId,
}: CreateProjectDialogProps) {
  const { pushToast } = useToast();

  const [entryMode, setEntryMode] = useState<EntryMode>(
    initialEntryMode ?? "pdf",
  );
  const [name, setName] = useState(initialName ?? "");
  const [description, setDescription] = useState("");
  const [preferredHarness, setPreferredHarness] = useState("agy");
  const [defaultDbProfileId, setDefaultDbProfileId] = useState(
    initialDbProfileId ?? "",
  );
  const [dbProfiles, setDbProfiles] = useState<DbProfileRead[]>([]);
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [initialJson, setInitialJson] = useState("");
  const [initialJrxml, setInitialJrxml] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const pdfInputRef = useRef<HTMLInputElement | null>(null);
  const jsonFileRef = useRef<HTMLInputElement | null>(null);
  const jrxmlFileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setEntryMode(initialEntryMode ?? "pdf");
    setName(initialName ?? "");
    setDefaultDbProfileId(initialDbProfileId ?? "");
    setErrorMsg(null);

    let active = true;
    api
      .listDbProfiles()
      .then((list) => {
        if (active && Array.isArray(list)) {
          setDbProfiles(list);
        }
      })
      .catch(() => {
        if (active) setDbProfiles([]);
      });
    return () => {
      active = false;
    };
  }, [open, initialEntryMode, initialName, initialDbProfileId]);

  const resetForm = () => {
    setEntryMode("pdf");
    setName("");
    setDescription("");
    setPreferredHarness("agy");
    setDefaultDbProfileId("");
    setPdfFile(null);
    setDragActive(false);
    setInitialJson("");
    setInitialJrxml("");
    setErrorMsg(null);
  };

  const handleClose = () => {
    if (submitting) return;
    resetForm();
    onClose();
  };

  const handlePdfSelect = (file: File | null) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setErrorMsg("Selecione um arquivo com extensão .pdf.");
      return;
    }
    setErrorMsg(null);
    setPdfFile(file);
    if (!name.trim()) {
      const inferred = file.name.replace(/\.pdf$/i, "").replace(/[_-]+/g, " ");
      setName(inferred);
    }
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0] ?? null;
    handlePdfSelect(file);
  };

  const handleLoadTextFile = async (
    file: File | null,
    target: "json" | "jrxml",
  ) => {
    if (!file) return;
    try {
      const content = await file.text();
      setErrorMsg(null);
      if (target === "json") {
        setInitialJson(content);
      } else {
        setInitialJrxml(content);
      }
      if (!name.trim()) {
        const inferred = file.name
          .replace(/\.(json|jrxml)$/i, "")
          .replace(/[_-]+/g, " ");
        setName(inferred);
      }
    } catch {
      setErrorMsg("Não foi possível ler o arquivo selecionado.");
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      setErrorMsg("Informe o nome do projeto.");
      return;
    }

    if (entryMode === "json") {
      if (!initialJson.trim()) {
        setErrorMsg("Cole ou carregue o conteúdo JSON clínico.");
        return;
      }
      try {
        JSON.parse(initialJson);
      } catch {
        setErrorMsg("O JSON informado é inválido. Verifique a sintaxe.");
        return;
      }
    }

    if (entryMode === "jrxml") {
      if (!initialJrxml.trim()) {
        setErrorMsg("Cole ou carregue o conteúdo XML do arquivo .jrxml.");
        return;
      }
    }

    setSubmitting(true);
    setErrorMsg(null);
    try {
      const payload: Parameters<typeof api.createProject>[0] = {
        name: trimmedName,
        description: description.trim(),
        entry_mode: entryMode,
        preferred_harness: preferredHarness,
        initial_json: entryMode === "json" ? initialJson : undefined,
        initial_jrxml: entryMode === "jrxml" ? initialJrxml : undefined,
      };
      if (entryMode === "blank_report") {
        payload.project_kind = "free_report";
      }
      if (defaultDbProfileId) {
        payload.default_db_profile_id = defaultDbProfileId;
      }
      if (initialClientSystemId) {
        payload.client_system_id = initialClientSystemId;
      }

      let created = await api.createProject(payload);

      if (entryMode === "pdf" && pdfFile) {
        created = await api.uploadProjectPdf(created.id, pdfFile);
      }

      pushToast({
        tone: "success",
        title: "Projeto criado com sucesso",
        description:
          entryMode === "pdf" && pdfFile
            ? `${created.name} pronto com source.pdf anexado.`
            : `${created.name} criado no modo ${entryMode.toUpperCase()}.`,
      });
      resetForm();
      onCreated(created);
    } catch (err) {
      setErrorMsg(
        err instanceof Error ? err.message : "Erro ao criar o projeto.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const isRemoteImportTab =
    entryMode === "sftp_import" || entryMode === "jasperserver_import";

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Novo projeto"
      description="Crie uma ficha clínica Salutem, um relatório livre SQL/Jasper ou importe diretamente via SFTP / JasperReports Server."
      size={isRemoteImportTab ? "xl" : "lg"}
      footer={
        isRemoteImportTab ? undefined : (
          <>
            <Button variant="ghost" onClick={handleClose} disabled={submitting}>
              Cancelar
            </Button>
            <Button
              type="submit"
              form="create-project-form"
              variant="primary"
              loading={submitting}
            >
              Criar projeto
            </Button>
          </>
        )
      }
    >
      <div className="space-y-4">
        <div className="overflow-x-auto">
          <FieldLabel>Modo de entrada</FieldLabel>
          <Tabs
            options={ENTRY_TABS}
            value={entryMode}
            onChange={(next) => {
              setEntryMode(next);
              setErrorMsg(null);
            }}
            className="w-full justify-start"
          />
        </div>

        {entryMode === "sftp_import" && (
          <SftpImportTab
            initialProfileId={initialSftpProfileId}
            dbProfiles={dbProfiles}
            onProjectImported={(project) => {
              resetForm();
              onCreated(project);
            }}
            onCancel={handleClose}
          />
        )}

        {entryMode === "jasperserver_import" && (
          <JasperServerImportTab
            initialProfileId={initialJasperProfileId}
            dbProfiles={dbProfiles}
            onProjectImported={(project) => {
              resetForm();
              onCreated(project);
            }}
            onCancel={handleClose}
          />
        )}

        {!isRemoteImportTab && (
          <form
            id="create-project-form"
            onSubmit={handleSubmit}
            className="space-y-4"
          >
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <FieldLabel htmlFor="project-name-input">
                  Nome do projeto *
                </FieldLabel>
                <Input
                  id="project-name-input"
                  placeholder={
                    entryMode === "blank_report"
                      ? "Ex.: Relatório de Produtividade Hospitalar"
                      : "Ex.: Ficha de Triagem Obstétrica"
                  }
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoFocus
                  required
                />
              </div>

              <div>
                <FieldLabel htmlFor="project-harness-select">
                  Harness de IA preferido
                </FieldLabel>
                <Select
                  id="project-harness-select"
                  value={preferredHarness}
                  onChange={(e) => setPreferredHarness(e.target.value)}
                >
                  {HARNESS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <FieldLabel htmlFor="project-description-input">
                  Descrição (opcional)
                </FieldLabel>
                <Input
                  id="project-description-input"
                  placeholder="Unidade, especialidade ou observações técnicas"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>

              {(entryMode === "blank_report" || entryMode === "jrxml") && (
                <div>
                  <FieldLabel htmlFor="project-db-profile-select">
                    Perfil PostgreSQL padrão (opcional)
                  </FieldLabel>
                  <Select
                    id="project-db-profile-select"
                    value={defaultDbProfileId}
                    onChange={(e) => setDefaultDbProfileId(e.target.value)}
                  >
                    <option value="">Usar perfil padrão do Studio</option>
                    {dbProfiles.map((prof) => (
                      <option key={prof.id} value={prof.id}>
                        {prof.name} ({prof.host}:{prof.port})
                      </option>
                    ))}
                  </Select>
                </div>
              )}
            </div>

            {entryMode === "blank_report" && (
              <div className="rounded-lg border border-accent/25 bg-accent-soft/40 p-3 text-xs text-ink-secondary">
                <p className="font-semibold text-ink">
                  Modo Relatório Livre / Manutenção (Ambulatorial ou Hospitalar)
                </p>
                <p className="mt-1">
                  Abre diretamente no <strong>Jasper Studio</strong> e{" "}
                  <strong>SQL Workbench</strong> (sem Form Builder nem{" "}
                  <code>INSERT</code> de ficha clínica), com acesso read-only ao
                  schema do banco e preview Live com parâmetros{" "}
                  <code>$P&#123;...&#125;</code>.
                </p>
              </div>
            )}

            {entryMode === "pdf" && (
              <div>
                <FieldLabel>Arquivo PDF de referência (source.pdf)</FieldLabel>
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragActive(true);
                  }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={handleDrop}
                  className={cn(
                    "flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-4 py-6 text-center transition-colors",
                    dragActive
                      ? "border-accent bg-accent-soft/60"
                      : "border-border-strong bg-surface-subtle/50 hover:border-accent/60",
                  )}
                >
                  <input
                    ref={pdfInputRef}
                    type="file"
                    accept=".pdf,application/pdf"
                    aria-label="Selecionar arquivo PDF"
                    className="hidden"
                    onChange={(e) =>
                      handlePdfSelect(e.target.files?.[0] ?? null)
                    }
                  />

                  {pdfFile ? (
                    <div className="flex w-full max-w-md items-center justify-between gap-3 rounded-md border border-border bg-surface px-3 py-2 text-left">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <FileText className="h-5 w-5 shrink-0 text-blueprint" />
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-ink">
                            {pdfFile.name}
                          </p>
                          <p className="text-[11px] text-ink-muted tabular-nums">
                            {formatBytes(pdfFile.size)}
                          </p>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setPdfFile(null);
                          if (pdfInputRef.current)
                            pdfInputRef.current.value = "";
                        }}
                        aria-label="Remover PDF selecionado"
                        className="rounded p-1 text-ink-muted hover:bg-surface-subtle hover:text-danger cursor-pointer"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                  ) : (
                    <>
                      <Upload className="mb-2 h-6 w-6 text-ink-muted" />
                      <p className="text-xs font-medium text-ink">
                        Arraste o PDF clínico aqui ou selecione um arquivo
                      </p>
                      <p className="mt-0.5 text-[11px] text-ink-muted">
                        Você também pode criar o projeto agora e anexar o PDF
                        depois.
                      </p>
                      <Button
                        variant="outline"
                        size="xs"
                        className="mt-3"
                        onClick={() => pdfInputRef.current?.click()}
                      >
                        Escolher arquivo .pdf
                      </Button>
                    </>
                  )}
                </div>
              </div>
            )}

            {entryMode === "json" && (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <FieldLabel htmlFor="project-initial-json" className="mb-0">
                    JSON clínico inicial *
                  </FieldLabel>
                  <div>
                    <input
                      ref={jsonFileRef}
                      type="file"
                      accept=".json,application/json"
                      aria-label="Carregar arquivo JSON"
                      className="hidden"
                      onChange={(e) =>
                        void handleLoadTextFile(
                          e.target.files?.[0] ?? null,
                          "json",
                        )
                      }
                    />
                    <Button
                      variant="outline"
                      size="xs"
                      icon={<Upload className="h-3 w-3" />}
                      onClick={() => jsonFileRef.current?.click()}
                    >
                      Carregar .json
                    </Button>
                  </div>
                </div>
                <Textarea
                  id="project-initial-json"
                  rows={8}
                  className="font-mono text-xs leading-relaxed"
                  placeholder='{"template": {"nome": "FICHA EXEMPLO"}, "perguntas": []}'
                  value={initialJson}
                  onChange={(e) => setInitialJson(e.target.value)}
                />
              </div>
            )}

            {entryMode === "jrxml" && (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <FieldLabel htmlFor="project-initial-jrxml" className="mb-0">
                    Conteúdo JRXML inicial *
                  </FieldLabel>
                  <div>
                    <input
                      ref={jrxmlFileRef}
                      type="file"
                      accept=".jrxml,.xml,application/xml,text/xml"
                      aria-label="Carregar arquivo JRXML"
                      className="hidden"
                      onChange={(e) =>
                        void handleLoadTextFile(
                          e.target.files?.[0] ?? null,
                          "jrxml",
                        )
                      }
                    />
                    <Button
                      variant="outline"
                      size="xs"
                      icon={<Upload className="h-3 w-3" />}
                      onClick={() => jrxmlFileRef.current?.click()}
                    >
                      Carregar .jrxml
                    </Button>
                  </div>
                </div>
                <Textarea
                  id="project-initial-jrxml"
                  rows={8}
                  className="font-mono text-xs leading-relaxed"
                  placeholder='<?xml version="1.0" encoding="UTF-8"?><jasperReport ...>'
                  value={initialJrxml}
                  onChange={(e) => setInitialJrxml(e.target.value)}
                />
              </div>
            )}

            {errorMsg && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
              >
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{errorMsg}</span>
              </div>
            )}
          </form>
        )}
      </div>
    </Dialog>
  );
}
