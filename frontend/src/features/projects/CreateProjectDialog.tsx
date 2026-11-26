import { useRef, useState, type DragEvent, type FormEvent } from "react";
import {
  AlertCircle,
  FileCode2,
  FileJson,
  FileText,
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
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { EntryMode, ProjectRead } from "@/types/studio";
import { formatBytes, HARNESS_OPTIONS } from "./projectMeta";

export interface CreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (project: ProjectRead) => void;
}

const ENTRY_TABS: { id: EntryMode; label: string; icon: React.ReactNode }[] = [
  { id: "pdf", label: "PDF Clínico", icon: <FileText className="h-3.5 w-3.5" /> },
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
];

export function CreateProjectDialog({
  open,
  onClose,
  onCreated,
}: CreateProjectDialogProps) {
  const { pushToast } = useToast();

  const [entryMode, setEntryMode] = useState<EntryMode>("pdf");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [preferredHarness, setPreferredHarness] = useState("agy");
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [initialJson, setInitialJson] = useState("");
  const [initialJrxml, setInitialJrxml] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const pdfInputRef = useRef<HTMLInputElement | null>(null);
  const jsonFileRef = useRef<HTMLInputElement | null>(null);
  const jrxmlFileRef = useRef<HTMLInputElement | null>(null);

  const resetForm = () => {
    setEntryMode("pdf");
    setName("");
    setDescription("");
    setPreferredHarness("agy");
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
      let created = await api.createProject({
        name: trimmedName,
        description: description.trim(),
        entry_mode: entryMode,
        preferred_harness: preferredHarness,
        initial_json: entryMode === "json" ? initialJson : undefined,
        initial_jrxml: entryMode === "jrxml" ? initialJrxml : undefined,
      });

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

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Novo projeto"
      description="Escolha o ponto de partida da ficha clínica Salutem e configure o workspace."
      size="lg"
      footer={
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
      }
    >
      <form
        id="create-project-form"
        onSubmit={handleSubmit}
        className="space-y-4"
      >
        <div>
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

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <FieldLabel htmlFor="project-name-input">
              Nome do projeto *
            </FieldLabel>
            <Input
              id="project-name-input"
              placeholder="Ex.: Ficha de Triagem Obstétrica"
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

        <div>
          <FieldLabel htmlFor="project-description-input">
            Descrição (opcional)
          </FieldLabel>
          <Input
            id="project-description-input"
            placeholder="Unidade, especialidade ou observações técnicas da ficha"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

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
                onChange={(e) => handlePdfSelect(e.target.files?.[0] ?? null)}
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
                      if (pdfInputRef.current) pdfInputRef.current.value = "";
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
                    Você também pode criar o projeto agora e anexar o PDF depois.
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
                    void handleLoadTextFile(e.target.files?.[0] ?? null, "json")
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
    </Dialog>
  );
}
