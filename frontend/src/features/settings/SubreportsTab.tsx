import { useRef, useState } from "react";
import {
  AlertCircle,
  FileArchive,
  RotateCcw,
  Trash2,
  Upload,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
  FieldLabel,
  Select,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { SubreportInfo, SubreportSource } from "@/types/studio";

export interface SubreportsTabProps {
  subreports: SubreportInfo[];
  loading: boolean;
  onRefresh: () => Promise<void>;
}

const BUILTIN_OVERRIDE_TARGETS = [
  "",
  "cabecalho_retrato.jasper",
  "cabecalho_paisagem.jasper",
  "dados_paciente.jasper",
  "rodape_retrato.jasper",
];

const SOURCE_META: Record<
  SubreportSource,
  { label: string; tone: "neutral" | "warning" | "blueprint" }
> = {
  builtin: { label: "Padrão embutido", tone: "neutral" },
  custom_override: { label: "Override customizado", tone: "warning" },
  custom_extra: { label: "Extra customizado", tone: "blueprint" },
};

function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function SubreportsTab({
  subreports,
  loading,
  onRefresh,
}: SubreportsTabProps) {
  const { pushToast } = useToast();

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [targetFilename, setTargetFilename] = useState("");
  const [uploading, setUploading] = useState(false);
  const [deletingName, setDeletingName] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleFileChange = (file: File | null) => {
    setUploadError(null);
    if (!file) {
      setSelectedFile(null);
      return;
    }
    if (!file.name.toLowerCase().endsWith(".jasper")) {
      setUploadError("Somente arquivos compilados .jasper são aceitos.");
      setSelectedFile(null);
      return;
    }
    setSelectedFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setUploadError("Selecione um arquivo .jasper antes de enviar.");
      return;
    }

    setUploading(true);
    setUploadError(null);
    try {
      const uploaded = await api.uploadSubreport(
        selectedFile,
        targetFilename || undefined,
      );
      pushToast({
        tone: "success",
        title: "Subreport .jasper salvo",
        description: `${uploaded.filename} ativo no diretório de runtime.`,
      });
      setSelectedFile(null);
      setTargetFilename("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      await onRefresh();
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "Falha ao enviar subreport.";
      setUploadError(msg);
      pushToast({
        tone: "error",
        title: "Erro no upload do subreport",
        description: msg,
      });
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteOrReset = async (item: SubreportInfo) => {
    setDeletingName(item.filename);
    try {
      await api.deleteSubreport(item.filename);
      pushToast({
        tone: "success",
        title:
          item.source === "custom_override"
            ? "Padrão restaurado"
            : "Subreport removido",
        description: item.filename,
      });
      await onRefresh();
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao remover subreport",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeletingName(null);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-ink">
          Subreports JasperReports (.jasper)
        </h2>
        <p className="text-xs text-ink-muted">
          Os 4 subreports padrão Salutem são embutidos no Studio. Você pode
          sobrescrevê-los com versões da unidade ou adicionar subreports extras.
        </p>
      </div>

      {/* Upload custom .jasper card */}
      <Card>
        <CardHeader>
          <CardTitle>Enviar subreport customizado (.jasper)</CardTitle>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3 md:items-end">
            <div>
              <FieldLabel htmlFor="subreport-file-input">
                Arquivo compilado (.jasper)
              </FieldLabel>
              <input
                ref={fileInputRef}
                id="subreport-file-input"
                type="file"
                accept=".jasper"
                aria-label="Selecionar arquivo .jasper"
                onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
                className="block w-full rounded-md border border-border bg-surface px-2 py-1 text-xs text-ink file:mr-2 file:rounded file:border-0 file:bg-surface-subtle file:px-2 file:py-1 file:text-xs file:font-medium file:text-ink cursor-pointer"
              />
            </div>

            <div>
              <FieldLabel htmlFor="subreport-override-select">
                Destino / Override (opcional)
              </FieldLabel>
              <Select
                id="subreport-override-select"
                value={targetFilename}
                onChange={(e) => setTargetFilename(e.target.value)}
              >
                <option value="">Usar nome original do arquivo</option>
                {BUILTIN_OVERRIDE_TARGETS.filter(Boolean).map((name) => (
                  <option key={name} value={name}>
                    Sobrescrever {name}
                  </option>
                ))}
              </Select>
            </div>

            <div className="flex justify-start md:justify-end">
              <Button
                variant="primary"
                size="sm"
                loading={uploading}
                disabled={!selectedFile || uploading}
                onClick={() => void handleUpload()}
                icon={<Upload className="h-3.5 w-3.5" />}
              >
                Enviar .jasper
              </Button>
            </div>
          </div>

          {uploadError && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{uploadError}</span>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Effective subreports list */}
      {loading && subreports.length === 0 ? (
        <Card className="p-6 text-center text-xs text-ink-muted">
          Carregando subreports...
        </Card>
      ) : subreports.length === 0 ? (
        <EmptyState
          icon={<FileArchive className="h-5 w-5" />}
          title="Nenhum subreport encontrado"
          description="Envie arquivos .jasper para compor o diretório $P{caminho_relatorio}."
        />
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-border bg-surface-subtle/70 text-[11px] text-ink-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Arquivo</th>
                  <th className="px-4 py-2.5 font-medium">Origem</th>
                  <th className="px-4 py-2.5 font-medium">Tamanho</th>
                  <th className="px-4 py-2.5 font-medium">SHA-256</th>
                  <th className="px-4 py-2.5 font-medium text-right">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {subreports.map((item) => {
                  const meta =
                    SOURCE_META[item.source] ?? SOURCE_META.builtin;
                  const canRemove = item.source !== "builtin";
                  const busy = deletingName === item.filename;

                  return (
                    <tr
                      key={item.filename}
                      className="hover:bg-surface-subtle/40"
                    >
                      <td className="px-4 py-2.5">
                        <div className="font-mono font-medium text-ink">
                          {item.filename}
                        </div>
                        {item.is_builtin_standard && (
                          <span className="text-[10px] text-ink-muted">
                            Subreport padrão Salutem
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2.5">
                        <Badge tone={meta.tone} dot>
                          {meta.label}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 font-mono text-ink-secondary tabular-nums">
                        {formatFileSize(item.size_bytes)}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-[11px] text-ink-muted">
                        {item.sha256 ? item.sha256.slice(0, 12) : "—"}
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        {canRemove ? (
                          <Button
                            variant="outline"
                            size="xs"
                            loading={busy}
                            disabled={deletingName !== null}
                            onClick={() => void handleDeleteOrReset(item)}
                            icon={
                              item.source === "custom_override" ? (
                                <RotateCcw className="h-3 w-3" />
                              ) : (
                                <Trash2 className="h-3 w-3" />
                              )
                            }
                          >
                            {item.source === "custom_override"
                              ? "Restaurar padrão"
                              : "Remover"}
                          </Button>
                        ) : (
                          <span className="text-[11px] text-ink-muted">
                            Embutido
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
