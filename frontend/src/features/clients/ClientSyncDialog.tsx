import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Code2,
  Copy,
  ExternalLink,
  FileUp,
  Lock,
  RefreshCw,
  Shield,
  Terminal,
} from "lucide-react";
import {
  Badge,
  Button,
  Dialog,
  FieldLabel,
  Input,
  Select,
  Switch,
  Textarea,
  useToast,
} from "@/components/ui";
import type { ClientSyncPreviewResponse } from "@/types/studio";
import {
  clientsApi,
  type ClientSyncSnippetResponse,
  type ClientSyncSourceFormat,
} from "./clientsApi";

export interface ClientSyncDialogProps {
  open: boolean;
  onClose: () => void;
  onSynced: () => Promise<void> | void;
}

export function ClientSyncDialog({
  open,
  onClose,
  onSynced,
}: ClientSyncDialogProps) {
  const { pushToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [step, setStep] = useState<1 | 2>(1);
  const [snippetData, setSnippetData] =
    useState<ClientSyncSnippetResponse | null>(null);
  const [loadingSnippet, setLoadingSnippet] = useState(false);

  const [portalUrl, setPortalUrl] = useState("");
  const [savingUrl, setSavingUrl] = useState(false);
  const [collectorTab, setCollectorTab] = useState<"console" | "bookmarklet">(
    "console",
  );
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  const [rawInput, setRawInput] = useState("");
  const [sourceFormat, setSourceFormat] =
    useState<ClientSyncSourceFormat>("auto");
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null);
  const [importSshPasswords, setImportSshPasswords] = useState(false);

  const [previewing, setPreviewing] = useState(false);
  const [preview, setPreview] = useState<ClientSyncPreviewResponse | null>(
    null,
  );
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep(1);
    setError(null);
    setPreview(null);
    setRawInput("");
    setUploadedFileName(null);
    setSourceFormat("auto");
    setImportSshPasswords(false);

    let cancelled = false;
    setLoadingSnippet(true);
    clientsApi
      .getSyncSnippet()
      .then((res) => {
        if (cancelled) return;
        setSnippetData(res);
        setPortalUrl(res.management_portal_url || "");
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error
            ? err.message
            : "Falha ao carregar instruções de sincronização.",
        );
      })
      .finally(() => {
        if (!cancelled) setLoadingSnippet(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open]);

  const handleSavePortalUrl = async () => {
    setSavingUrl(true);
    setError(null);
    try {
      const res = await clientsApi.saveSyncConfig(portalUrl.trim());
      setPortalUrl(res.management_portal_url);
      pushToast({
        tone: "success",
        title: "URL do portal salva localmente",
        description: res.management_portal_url || "URL limpa.",
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Erro ao salvar URL do portal.",
      );
    } finally {
      setSavingUrl(false);
    }
  };

  const handleCopyText = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedKey(key);
      setTimeout(() => setCopiedKey(null), 1800);
      pushToast({
        tone: "success",
        title: "Copiado para a área de transferência",
      });
    } catch {
      pushToast({
        tone: "warning",
        title: "Não foi possível copiar automaticamente",
        description: "Selecione o conteúdo manualmente para copiar.",
      });
    }
  };

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setRawInput(text);
      setUploadedFileName(file.name);
      if (file.name.toLowerCase().endsWith(".html") || file.name.toLowerCase().endsWith(".htm")) {
        setSourceFormat("portal_html");
      } else {
        setSourceFormat("auto");
      }
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Erro ao ler arquivo selecionado.",
      );
    }
  };

  const handlePreview = async () => {
    if (!rawInput.trim()) {
      setError(
        "Cole o JSON/HTML capturado do portal ou selecione um arquivo .json/.html.",
      );
      return;
    }

    setPreviewing(true);
    setError(null);
    try {
      const res = await clientsApi.previewClientSync({
        raw_payload: rawInput,
        source_format: sourceFormat,
      });
      setPreview(res);
      setStep(2);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Não foi possível interpretar os dados enviados.",
      );
    } finally {
      setPreviewing(false);
    }
  };

  const handleConfirmApply = async () => {
    if (!preview) return;
    setApplying(true);
    setError(null);
    try {
      const res = await clientsApi.applyClientSync({
        raw_payload: rawInput,
        source_format: sourceFormat,
        import_ssh_passwords: importSshPasswords,
      });
      pushToast({
        tone: "success",
        title: "Sincronização concluída",
        description: `${res.created_units} novo(s), ${res.updated_units} atualizado(s), ${res.created_systems} sistema(s) criados.`,
      });
      await onSynced();
      onClose();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Erro ao aplicar sincronização de clientes.",
      );
    } finally {
      setApplying(false);
    }
  };

  const canOpenPortal =
    portalUrl.trim().startsWith("http://") ||
    portalUrl.trim().startsWith("https://");

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!previewing && !applying) onClose();
      }}
      title={
        step === 1
          ? "Sincronizar Clientes do Portal (Etapa 1 de 2)"
          : "Prévia da Sincronização — Diff (Etapa 2 de 2)"
      }
      description={
        step === 1
          ? "Use sua sessão já autenticada no navegador para exportar o JSON ou HTML do portal e importar localmente sem embutir URLs ou credenciais no código."
          : "Revise os clientes novos, atualizados e inalterados antes de gravar no banco local."
      }
      size="xl"
      footer={
        step === 1 ? (
          <>
            <Button variant="ghost" onClick={onClose} disabled={previewing}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={previewing}
              onClick={() => void handlePreview()}
              icon={<RefreshCw className="h-3.5 w-3.5" />}
            >
              Analisar e Pré-visualizar
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="outline"
              onClick={() => setStep(1)}
              disabled={applying}
              icon={<ArrowLeft className="h-3.5 w-3.5" />}
            >
              Voltar
            </Button>
            <Button
              variant="primary"
              loading={applying}
              onClick={() => void handleConfirmApply()}
              icon={<CheckCircle2 className="h-3.5 w-3.5" />}
            >
              Confirmar Sincronização
            </Button>
          </>
        )
      }
    >
      {step === 1 ? (
        <div className="space-y-4">
          {/* Local Portal URL Config */}
          <div className="rounded-md border border-border bg-surface-subtle/40 p-3.5 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-accent" />
                <span className="text-xs font-semibold text-ink">
                  URL Local do Portal de Gestão
                </span>
              </div>
              <Badge tone="neutral" className="text-[10px]">
                Salva apenas no SQLite local
              </Badge>
            </div>

            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                id="sync-portal-url"
                aria-label="URL do portal de gestão"
                placeholder="https://portal.exemplo.local"
                value={portalUrl}
                onChange={(e) => setPortalUrl(e.target.value)}
                className="flex-1"
              />
              <Button
                variant="outline"
                size="sm"
                loading={savingUrl}
                onClick={() => void handleSavePortalUrl()}
              >
                Salvar URL local
              </Button>
              {canOpenPortal && (
                <a
                  href={portalUrl.trim()}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-border bg-surface px-3 text-xs font-medium text-ink hover:bg-surface-subtle transition-colors"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Abrir Portal
                </a>
              )}
            </div>
          </div>

          {/* Collector Snippet & Bookmarklet */}
          <div className="rounded-md border border-border bg-surface p-3.5 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                <Button
                  variant={collectorTab === "console" ? "secondary" : "ghost"}
                  size="xs"
                  onClick={() => setCollectorTab("console")}
                  icon={<Terminal className="h-3 w-3" />}
                >
                  Snippet de Console
                </Button>
                <Button
                  variant={
                    collectorTab === "bookmarklet" ? "secondary" : "ghost"
                  }
                  size="xs"
                  onClick={() => setCollectorTab("bookmarklet")}
                  icon={<Code2 className="h-3 w-3" />}
                >
                  Bookmarklet
                </Button>
              </div>

              <Button
                variant="outline"
                size="xs"
                disabled={!snippetData}
                onClick={() => {
                  if (!snippetData) return;
                  const target =
                    collectorTab === "console"
                      ? snippetData.console_snippet
                      : snippetData.bookmarklet;
                  void handleCopyText(collectorTab, target);
                }}
                icon={
                  copiedKey === collectorTab ? (
                    <Check className="h-3 w-3 text-success" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )
                }
              >
                {copiedKey === collectorTab
                  ? "Copiado"
                  : collectorTab === "console"
                    ? "Copiar snippet"
                    : "Copiar bookmarklet"}
              </Button>
            </div>

            {loadingSnippet ? (
              <p className="text-xs text-ink-muted">
                Carregando coletor local...
              </p>
            ) : snippetData ? (
              <>
                <pre className="max-h-36 overflow-auto rounded border border-border bg-surface-subtle p-2.5 font-mono text-[11px] text-ink-secondary whitespace-pre-wrap break-all">
                  {collectorTab === "console"
                    ? snippetData.console_snippet
                    : snippetData.bookmarklet}
                </pre>
                <ul className="space-y-0.5 text-[11px] text-ink-muted">
                  {snippetData.instructions.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </div>

          {/* Paste or Upload Payload */}
          <div className="space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <FieldLabel htmlFor="sync-raw-payload" className="mb-0">
                Colar JSON / HTML capturado ou importar arquivo
              </FieldLabel>

              <div className="flex flex-wrap items-center gap-2">
                <Select
                  aria-label="Formato de entrada"
                  value={sourceFormat}
                  onChange={(e) =>
                    setSourceFormat(e.target.value as ClientSyncSourceFormat)
                  }
                  className="w-44 h-7 text-xs"
                >
                  <option value="auto">Auto-detectar formato</option>
                  <option value="portal_json">JSON do Portal</option>
                  <option value="portal_html">HTML (.management-client-card)</option>
                  <option value="normalized_json">JSON Normalizado</option>
                </Select>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json,.html,.htm,application/json,text/html"
                  aria-label="Enviar arquivo JSON ou HTML"
                  className="hidden"
                  onChange={(e) => void handleFileChange(e)}
                />
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => fileInputRef.current?.click()}
                  icon={<FileUp className="h-3 w-3" />}
                >
                  Enviar .json / .html
                </Button>
              </div>
            </div>

            {uploadedFileName && (
              <div className="text-[11px] text-accent">
                Arquivo carregado: <span className="font-mono">{uploadedFileName}</span>
              </div>
            )}

            <Textarea
              id="sync-raw-payload"
              rows={7}
              className="font-mono text-xs"
              placeholder='Cole aqui o JSON retornado pelo coletor ou o HTML salvo com cards ".management-client-card"...'
              value={rawInput}
              onChange={(e) => setRawInput(e.target.value)}
            />
          </div>

          {/* SSH Password Vault Toggle */}
          <div className="rounded-md border border-border bg-surface-subtle/50 p-3 space-y-1.5">
            <Switch
              id="sync-import-ssh-passwords"
              checked={importSshPasswords}
              onChange={setImportSshPasswords}
              label="Importar senhas SSH no cofre local"
            />
            <p className="flex items-start gap-1.5 text-[11px] text-ink-muted">
              <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />
              <span>
                Desligado por padrão: perfis SFTP herdam suas Credenciais Padrão.
                Quando ativado, senhas SSH presentes no arquivo são gravadas
                exclusivamente no cofre criptografado local (nunca no SQLite),
                sem sobrescrever senhas customizadas já existentes.
              </span>
            </p>
          </div>

          {error && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>
      ) : preview ? (
        <div className="space-y-4">
          {/* Diff KPIs */}
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <div className="rounded-md border border-border bg-surface-subtle/60 p-3">
              <div className="text-[11px] text-ink-muted">Total analisados</div>
              <div className="mt-0.5 text-lg font-semibold text-ink tabular-nums">
                {preview.total_parsed}
              </div>
            </div>
            <div className="rounded-md border border-success/30 bg-success-soft/60 p-3">
              <div className="text-[11px] text-success">Novos</div>
              <div className="mt-0.5 text-lg font-semibold text-success tabular-nums">
                {preview.to_create}
              </div>
            </div>
            <div className="rounded-md border border-blueprint/30 bg-blueprint-soft/60 p-3">
              <div className="text-[11px] text-blueprint">Atualizados</div>
              <div className="mt-0.5 text-lg font-semibold text-blueprint tabular-nums">
                {preview.to_update}
              </div>
            </div>
            <div className="rounded-md border border-border bg-surface-subtle/40 p-3">
              <div className="text-[11px] text-ink-muted">Inalterados</div>
              <div className="mt-0.5 text-lg font-semibold text-ink-secondary tabular-nums">
                {preview.unchanged}
              </div>
            </div>
          </div>

          {preview.warnings.length > 0 && (
            <div className="rounded-md border border-warning/30 bg-warning-soft/70 p-3 space-y-1 text-xs text-warning">
              <div className="flex items-center gap-1.5 font-semibold">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>Avisos ({preview.warnings.length})</span>
              </div>
              <ul className="list-disc pl-5 space-y-0.5 text-[11px]">
                {preview.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Diff Table */}
          <div className="max-h-72 overflow-auto rounded-md border border-border">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 border-b border-border bg-surface-subtle text-[11px] font-semibold text-ink-secondary">
                <tr>
                  <th className="px-3 py-2">Ação</th>
                  <th className="px-3 py-2">Cliente</th>
                  <th className="px-3 py-2">Sistemas</th>
                  <th className="px-3 py-2">Alterações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-surface">
                {preview.items.map((item) => (
                  <tr key={`${item.unit_code}-${item.name}`}>
                    <td className="px-3 py-2 align-top">
                      {item.action === "create" ? (
                        <Badge tone="success">Novo</Badge>
                      ) : item.action === "update" ? (
                        <Badge tone="blueprint">Atualizar</Badge>
                      ) : (
                        <Badge tone="neutral">Inalterado</Badge>
                      )}
                    </td>
                    <td className="px-3 py-2 align-top">
                      <div className="font-semibold text-ink">{item.name}</div>
                      <div className="font-mono text-[10px] text-ink-muted">
                        {item.unit_code}
                      </div>
                    </td>
                    <td className="px-3 py-2 align-top tabular-nums text-ink-secondary">
                      {item.systems_count}
                    </td>
                    <td className="px-3 py-2 align-top text-[11px] text-ink-secondary">
                      {item.changes.length === 0 ? (
                        <span className="italic text-ink-muted">
                          Sem alterações
                        </span>
                      ) : (
                        <ul className="space-y-0.5">
                          {item.changes.map((chg, idx) => (
                            <li key={idx}>{chg}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {error && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>
      ) : null}
    </Dialog>
  );
}
