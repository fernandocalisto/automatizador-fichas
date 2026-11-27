import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileDiff,
  Lock,
  ShieldAlert,
  UploadCloud,
} from "lucide-react";
import {
  Badge,
  Button,
  Dialog,
  FieldLabel,
  Input,
  SearchableSelect,
  Select,
  useToast,
  type SearchableSelectOption,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import type {
  ProjectRead,
  SftpDeployPreview,
  SftpDeployResult,
  SftpProfileRead,
  SftpPublishMode,
} from "@/types/studio";
import { sftpApi } from "./sftpApi";

export interface SftpDeployModalProps {
  open: boolean;
  onClose: () => void;
  project: ProjectRead;
  profiles?: SftpProfileRead[];
  onDeployed?: (result: SftpDeployResult) => void;
}

const PUBLISH_MODE_OPTIONS: Array<{
  value: SftpPublishMode;
  label: string;
  hint: string;
}> = [
  {
    value: "jrxml_only",
    label: "Só .jrxml (Padrão operacional)",
    hint: "Envia apenas o fonte .jrxml validado na JVM.",
  },
  {
    value: "both",
    label: "Ambos (.jrxml + .jasper)",
    hint: "Envia o fonte .jrxml e o binário .jasper compilado.",
  },
  {
    value: "jasper_only",
    label: "Só .jasper",
    hint: "Envia apenas o binário .jasper compilado.",
  },
];

function renderDiffLines(unifiedDiff: string) {
  if (!unifiedDiff.trim()) {
    return (
      <div className="px-3 py-4 text-xs text-ink-muted italic">
        Nenhuma diferença textual detectada em relação ao arquivo remoto atual.
      </div>
    );
  }
  const lines = unifiedDiff.split("\n");
  return (
    <pre className="max-h-72 overflow-auto bg-canvas p-2 font-mono text-[11px] leading-relaxed">
      {lines.map((line, idx) => {
        const toneClass = line.startsWith("+++") || line.startsWith("---")
          ? "text-ink-muted font-semibold"
          : line.startsWith("@@")
            ? "bg-blueprint-soft/50 text-blueprint font-semibold"
            : line.startsWith("+")
              ? "bg-success-soft/70 text-success"
              : line.startsWith("-")
                ? "bg-danger-soft/70 text-danger"
                : "text-ink-secondary";
        return (
          <div key={`${idx}-${line.slice(0, 12)}`} className={cn("px-2 whitespace-pre", toneClass)}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

export function SftpDeployModal({
  open,
  onClose,
  project,
  profiles: externalProfiles,
  onDeployed,
}: SftpDeployModalProps) {
  const { pushToast } = useToast();

  const [loadedProfiles, setLoadedProfiles] = useState<SftpProfileRead[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);

  const [profileId, setProfileId] = useState("");
  const [remoteDir, setRemoteDir] = useState("/");
  const [baseFilename, setBaseFilename] = useState(project.slug);
  const [publishMode, setPublishMode] = useState<SftpPublishMode>("jrxml_only");

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [preview, setPreview] = useState<SftpDeployPreview | null>(null);
  const [deployResult, setDeployResult] = useState<SftpDeployResult | null>(
    null,
  );
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const profiles = externalProfiles ?? loadedProfiles;

  // Initialize fields from project.source_origin when modal opens
  useEffect(() => {
    if (!open) return;

    const origin =
      project.source_origin && typeof project.source_origin === "object"
        ? project.source_origin
        : {};
    const isSftpOrigin = origin.provider === "sftp";

    setStep(1);
    setPreview(null);
    setDeployResult(null);
    setErrorMsg(null);
    setPublishMode("jrxml_only");
    setBaseFilename(
      isSftpOrigin && typeof origin.base_filename === "string" && origin.base_filename
        ? origin.base_filename
        : project.slug,
    );

    if (externalProfiles) {
      const originProfId =
        isSftpOrigin && typeof origin.profile_id === "string"
          ? origin.profile_id
          : "";
      const matched =
        externalProfiles.find((p) => p.id === originProfId) ??
        externalProfiles[0];
      setProfileId(matched?.id ?? "");
      setRemoteDir(
        isSftpOrigin && typeof origin.remote_dir === "string" && origin.remote_dir
          ? origin.remote_dir
          : matched?.remote_base_dir ?? "/",
      );
      return;
    }

    let active = true;
    setLoadingProfiles(true);
    sftpApi
      .listProfiles()
      .then((items) => {
        if (!active) return;
        const list = Array.isArray(items) ? items : [];
        setLoadedProfiles(list);
        const originProfId =
          isSftpOrigin && typeof origin.profile_id === "string"
            ? origin.profile_id
            : "";
        const matched = list.find((p) => p.id === originProfId) ?? list[0];
        setProfileId(matched?.id ?? "");
        setRemoteDir(
          isSftpOrigin && typeof origin.remote_dir === "string" && origin.remote_dir
            ? origin.remote_dir
            : matched?.remote_base_dir ?? "/",
        );
      })
      .catch((err) => {
        if (!active) return;
        setErrorMsg(
          err instanceof Error
            ? err.message
            : "Falha ao carregar perfis SFTP.",
        );
      })
      .finally(() => {
        if (active) setLoadingProfiles(false);
      });

    return () => {
      active = false;
    };
  }, [open, project, externalProfiles]);

  const selectedProfile = useMemo(
    () => profiles.find((p) => p.id === profileId) ?? null,
    [profiles, profileId],
  );
  const profileOptions = useMemo<SearchableSelectOption[]>(
    () =>
      profiles.map((p) => ({
        value: p.id,
        label: p.name,
        sublabel: `${p.host}:${p.port}${p.read_only ? " · Somente Leitura" : ""}`,
        badge: p.environment,
        keywords: `${p.name} ${p.host} ${p.port} ${p.environment} ${p.read_only ? "somente leitura" : ""}`,
      })),
    [profiles],
  );
  const isReadOnly = Boolean(selectedProfile?.read_only);

  const handleProfileChange = (nextId: string) => {
    setProfileId(nextId);
    setErrorMsg(null);
    const nextProf = profiles.find((p) => p.id === nextId);
    if (nextProf && (!remoteDir || remoteDir === "/")) {
      setRemoteDir(nextProf.remote_base_dir || "/");
    }
  };

  const handlePrepare = async () => {
    if (!profileId || isReadOnly) return;
    if (!remoteDir.trim() || !baseFilename.trim()) {
      setErrorMsg("Informe o diretório remoto e o nome base do arquivo.");
      return;
    }
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await sftpApi.prepareDeploy(project.id, {
        profile_id: profileId,
        remote_dir: remoteDir.trim(),
        base_filename: baseFilename.trim(),
        publish_mode: publishMode,
      });
      setPreview(res);
      setStep(2);
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Falha ao validar compilação ou gerar prévia de deploy.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const handleExecute = async () => {
    if (!preview || isReadOnly) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await sftpApi.executeDeploy(project.id, {
        deploy_token: preview.deploy_token,
      });
      setDeployResult(res);
      setStep(3);
      pushToast({
        tone: "success",
        title: "Publicado no SFTP com sucesso",
        description: res.message,
      });
      onDeployed?.(res);
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Falha ao publicar arquivo no servidor SFTP.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  const footer =
    step === 1 ? (
      <>
        <Button variant="ghost" onClick={onClose} disabled={submitting}>
          Cancelar
        </Button>
        <Button
          variant="primary"
          loading={submitting}
          disabled={!selectedProfile || isReadOnly || loadingProfiles}
          onClick={() => void handlePrepare()}
          icon={<FileDiff className="h-3.5 w-3.5" />}
        >
          Validar JVM e Gerar Diff
        </Button>
      </>
    ) : step === 2 ? (
      <>
        <Button
          variant="ghost"
          onClick={() => {
            setStep(1);
            setErrorMsg(null);
          }}
          disabled={submitting}
          icon={<ArrowLeft className="h-3.5 w-3.5" />}
        >
          Voltar
        </Button>
        <Button
          variant="primary"
          loading={submitting}
          disabled={isReadOnly || !preview}
          onClick={() => void handleExecute()}
          icon={<UploadCloud className="h-3.5 w-3.5" />}
        >
          Confirmar e Publicar no SFTP
        </Button>
      </>
    ) : (
      <Button variant="primary" onClick={onClose}>
        Concluir
      </Button>
    );

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!submitting) onClose();
      }}
      title="Publicar relatório no SFTP"
      description="Fluxo seguro em 2 etapas: validação de compilação na JVM, diff com o servidor remoto e backup automático .bak antes de sobrescrever."
      size="lg"
      footer={footer}
    >
      <div className="space-y-4">
        {/* Step Indicator */}
        <div className="flex items-center gap-2 text-xs">
          <Badge tone={step === 1 ? "accent" : "success"}>
            1. Destino & Validação JVM
          </Badge>
          <span className="text-ink-muted">→</span>
          <Badge tone={step === 2 ? "accent" : step === 3 ? "success" : "neutral"}>
            2. Diff & Confirmação (.bak)
          </Badge>
          {step === 3 && (
            <>
              <span className="text-ink-muted">→</span>
              <Badge tone="success">3. Publicado</Badge>
            </>
          )}
        </div>

        {/* Read-only hard warning */}
        {selectedProfile && isReadOnly && (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-md border border-danger/40 bg-danger-soft p-3 text-xs text-danger"
          >
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-1">
              <div className="flex items-center gap-2 font-semibold">
                <span>Publicação bloqueada neste servidor</span>
                <Badge tone="danger">
                  <Lock className="h-3 w-3" />
                  Somente Leitura ({selectedProfile.environment})
                </Badge>
              </div>
              <p>
                O perfil <strong>{selectedProfile.name}</strong> está protegido
                como Somente Leitura (HTTP 403 no backend). Escolha um servidor
                gravável ou ajuste a permissão em Configurações → Servidores
                SFTP.
              </p>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <FieldLabel htmlFor="sftp-deploy-profile">
                  Servidor SFTP de destino
                </FieldLabel>
                <SearchableSelect
                  id="sftp-deploy-profile"
                  ariaLabel="Servidor SFTP de destino"
                  value={profileId}
                  onChange={handleProfileChange}
                  options={profileOptions}
                  disabled={loadingProfiles || profiles.length === 0}
                  placeholder="Nenhum perfil SFTP cadastrado"
                  searchPlaceholder="Buscar servidor por nome, host ou ambiente..."
                  emptyLabel="Nenhum servidor SFTP encontrado."
                />
              </div>

              <div>
                <FieldLabel htmlFor="sftp-deploy-mode">
                  Modo de publicação
                </FieldLabel>
                <Select
                  id="sftp-deploy-mode"
                  value={publishMode}
                  onChange={(e) =>
                    setPublishMode(e.target.value as SftpPublishMode)
                  }
                >
                  {PUBLISH_MODE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <FieldLabel htmlFor="sftp-deploy-dir">
                  Diretório remoto (POSIX)
                </FieldLabel>
                <Input
                  id="sftp-deploy-dir"
                  value={remoteDir}
                  onChange={(e) => setRemoteDir(e.target.value)}
                  placeholder="/opt/salutem/relatorios"
                  className="font-mono text-xs"
                />
              </div>

              <div>
                <FieldLabel htmlFor="sftp-deploy-base">
                  Nome base do arquivo (sem extensão)
                </FieldLabel>
                <Input
                  id="sftp-deploy-base"
                  value={baseFilename}
                  onChange={(e) => setBaseFilename(e.target.value)}
                  placeholder="ficha_evolucao"
                  className="font-mono text-xs"
                />
              </div>
            </div>

            <p className="text-xs text-ink-muted">
              {
                PUBLISH_MODE_OPTIONS.find((o) => o.value === publishMode)?.hint
              }
            </p>
          </div>
        )}

        {step === 2 && preview && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-surface-subtle/50 px-3 py-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="success">
                  <CheckCircle2 className="h-3 w-3" />
                  Compilação JVM OK
                </Badge>
                <Badge tone="blueprint">{preview.publish_mode}</Badge>
                <span className="font-mono text-ink-secondary">
                  SHA-256 local: {preview.local_sha256.slice(0, 12)}
                </span>
              </div>
              {preview.remote_sha256 && (
                <span className="font-mono text-ink-muted">
                  Remoto: {preview.remote_sha256.slice(0, 12)}
                </span>
              )}
            </div>

            <div className="rounded-md border border-border bg-surface p-2.5 text-xs space-y-1">
              <div className="font-medium text-ink-secondary">
                Arquivos alvo no servidor:
              </div>
              <ul className="list-disc pl-5 font-mono text-ink">
                {preview.target_files.map((tf) => (
                  <li key={tf}>{tf}</li>
                ))}
              </ul>
            </div>

            {preview.remote_exists ? (
              <div className="flex items-start gap-2 rounded-md border border-warning/35 bg-warning-soft/70 p-2.5 text-xs text-warning">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  Arquivo remoto existente será preservado automaticamente em{" "}
                  <code>&lt;arquivo&gt;.bak.&lt;YYYYMMDD_HHMMSS&gt;</code> no
                  servidor e em <code>backups/</code> local antes de
                  sobrescrever.
                </span>
              </div>
            ) : (
              <div className="rounded-md border border-border bg-surface-subtle/50 p-2.5 text-xs text-ink-secondary">
                Novo arquivo: não existe versão anterior no diretório remoto.
              </div>
            )}

            <div className="overflow-hidden rounded-md border border-border">
              <div className="border-b border-border bg-surface-subtle px-3 py-1.5 text-xs font-medium text-ink-secondary">
                Prévia de Diff (remoto vs local)
              </div>
              {renderDiffLines(preview.unified_diff)}
            </div>
          </div>
        )}

        {step === 3 && deployResult && (
          <div className="space-y-3 rounded-md border border-success/30 bg-success-soft/40 p-4 text-xs">
            <div className="flex items-center gap-2 text-sm font-semibold text-success">
              <CheckCircle2 className="h-4 w-4" />
              <span>{deployResult.message}</span>
            </div>

            <div className="space-y-1">
              <div className="font-medium text-ink">Arquivos publicados:</div>
              <ul className="list-disc pl-5 font-mono text-ink-secondary">
                {deployResult.published_files.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </div>

            {deployResult.backup_files.length > 0 && (
              <div className="space-y-1">
                <div className="font-medium text-ink">
                  Backups remotos (.bak) criados:
                </div>
                <ul className="list-disc pl-5 font-mono text-ink-secondary">
                  {deployResult.backup_files.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </div>
            )}

            {deployResult.local_backup_path && (
              <div className="text-ink-muted">
                Cópia local salva em:{" "}
                <code className="font-mono text-ink">
                  {deployResult.local_backup_path}
                </code>
              </div>
            )}
          </div>
        )}

        {errorMsg && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
          >
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}
      </div>
    </Dialog>
  );
}
