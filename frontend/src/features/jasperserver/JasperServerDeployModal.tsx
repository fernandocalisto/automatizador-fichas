import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  CloudUpload,
  FileDiff,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import {
  Badge,
  Button,
  Dialog,
  FieldLabel,
  Input,
  SearchableSelect,
  Select,
  Tabs,
  useToast,
  type SearchableSelectOption,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import type {
  JasperServerDeployPreview,
  JasperServerDeployResult,
  JasperServerProfileRead,
  JasperServerResourceItem,
  ProjectRead,
} from "@/types/studio";
import { jasperServerApi } from "./jasperServerApi";

export interface JasperServerDeployModalProps {
  open: boolean;
  onClose: () => void;
  project: ProjectRead;
  profiles?: JasperServerProfileRead[];
  onDeployed?: (result: JasperServerDeployResult) => void;
}

type DeployMode = "update" | "create";

function readOriginString(
  origin: Record<string, unknown> | undefined,
  key: string,
): string {
  const val = origin?.[key];
  return typeof val === "string" ? val : "";
}

function UnifiedDiffBox({ diff }: { diff: string }) {
  const lines = diff ? diff.split(/\r?\n/) : [];
  if (lines.length === 0) {
    return (
      <div className="rounded-md border border-border bg-surface-subtle/50 p-3 font-mono text-xs text-ink-muted">
        Nenhuma diferença textual detectada entre o JRXML local e o remoto.
      </div>
    );
  }

  return (
    <pre className="max-h-64 overflow-auto rounded-md border border-border bg-surface-subtle/60 p-3 font-mono text-[11px] leading-relaxed">
      {lines.map((line, idx) => {
        let cls = "text-ink-secondary";
        if (line.startsWith("+") && !line.startsWith("+++")) {
          cls = "bg-success-soft/70 text-success";
        } else if (line.startsWith("-") && !line.startsWith("---")) {
          cls = "bg-danger-soft/70 text-danger";
        } else if (line.startsWith("@@")) {
          cls = "text-blueprint font-semibold";
        }
        return (
          <div key={idx} className={cn("px-1 whitespace-pre", cls)}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

export function JasperServerDeployModal({
  open,
  onClose,
  project,
  profiles: externalProfiles,
  onDeployed,
}: JasperServerDeployModalProps) {
  const { pushToast } = useToast();

  const [profiles, setProfiles] = useState<JasperServerProfileRead[]>(
    externalProfiles ?? [],
  );
  const [loadingProfiles, setLoadingProfiles] = useState(false);

  const [profileId, setProfileId] = useState("");
  const [mode, setMode] = useState<DeployMode>("update");
  const [targetUri, setTargetUri] = useState("");
  const [mainJrxmlUri, setMainJrxmlUri] = useState("");
  const [label, setLabel] = useState("");
  const [datasourceUri, setDatasourceUri] = useState("");
  const [datasources, setDatasources] = useState<JasperServerResourceItem[]>(
    [],
  );
  const [loadingDatasources, setLoadingDatasources] = useState(false);

  const [preview, setPreview] = useState<JasperServerDeployPreview | null>(
    null,
  );
  const [deployResult, setDeployResult] =
    useState<JasperServerDeployResult | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Sync external profiles or fetch on open
  useEffect(() => {
    if (!open) return;
    setPreview(null);
    setDeployResult(null);
    setErrorMsg(null);

    const origin = project.source_origin;
    const isJsOrigin = readOriginString(origin, "provider") === "jasperserver";
    const originProfileId = isJsOrigin
      ? readOriginString(origin, "profile_id")
      : "";
    const originResourceUri = isJsOrigin
      ? readOriginString(origin, "resource_uri")
      : "";
    const originMainJrxml = isJsOrigin
      ? readOriginString(origin, "main_jrxml_uri")
      : "";
    const originDatasource = isJsOrigin
      ? readOriginString(origin, "datasource_uri")
      : "";

    setMode(originResourceUri ? "update" : "create");
    setTargetUri(originResourceUri || `/reports/${project.slug}`);
    setMainJrxmlUri(originMainJrxml);
    setLabel(project.name);
    setDatasourceUri(originDatasource);

    if (externalProfiles) {
      setProfiles(externalProfiles);
      const chosen =
        (originProfileId &&
          externalProfiles.find((p) => p.id === originProfileId)?.id) ||
        externalProfiles[0]?.id ||
        "";
      setProfileId(chosen);
      return;
    }

    let active = true;
    setLoadingProfiles(true);
    jasperServerApi
      .listProfiles()
      .then((list) => {
        if (!active) return;
        setProfiles(list);
        const chosen =
          (originProfileId && list.find((p) => p.id === originProfileId)?.id) ||
          list[0]?.id ||
          "";
        setProfileId(chosen);
      })
      .catch((err) => {
        if (!active) return;
        setErrorMsg(
          err instanceof Error
            ? err.message
            : "Erro ao carregar perfis JasperServer.",
        );
      })
      .finally(() => {
        if (active) setLoadingProfiles(false);
      });
    return () => {
      active = false;
    };
  }, [open, project, externalProfiles]);

  const activeProfile = profiles.find((p) => p.id === profileId) || null;
  const profileOptions = useMemo<SearchableSelectOption[]>(
    () =>
      profiles.map((p) => ({
        value: p.id,
        label: p.name,
        sublabel: p.base_url,
        badge: p.read_only ? `${p.environment} · RO` : p.environment,
        keywords: `${p.name} ${p.base_url} ${p.environment} ${p.read_only ? "somente leitura" : ""}`,
      })),
    [profiles],
  );
  const isReadOnly = Boolean(activeProfile?.read_only);

  const loadDatasources = async (pid: string) => {
    if (!pid) return;
    setLoadingDatasources(true);
    try {
      const items = await jasperServerApi.listResources(pid, {
        folder_uri: "/",
        recursive: true,
        types: ["jdbcDataSource", "jndiJdbcDataSource", "dataSource"],
      });
      setDatasources(items.filter((i) => i.resource_type === "datasource"));
    } catch {
      setDatasources([]);
    } finally {
      setLoadingDatasources(false);
    }
  };

  useEffect(() => {
    if (open && mode === "create" && profileId) {
      void loadDatasources(profileId);
    }
  }, [open, mode, profileId]);

  const handlePrepare = async () => {
    if (!profileId || !targetUri.trim()) {
      setErrorMsg("Informe o perfil JasperServer e a URI de destino.");
      return;
    }
    if (isReadOnly) {
      setErrorMsg(
        "Deploy bloqueado: este perfil está configurado como Somente Leitura (read_only).",
      );
      return;
    }

    setPreparing(true);
    setErrorMsg(null);
    try {
      const res = await jasperServerApi.prepareDeploy(project.id, {
        profile_id: profileId,
        mode,
        target_uri: targetUri.trim(),
        main_jrxml_uri:
          mode === "update" && mainJrxmlUri.trim()
            ? mainJrxmlUri.trim()
            : undefined,
        label: label.trim() || undefined,
        datasource_uri:
          mode === "create" && datasourceUri.trim()
            ? datasourceUri.trim()
            : undefined,
      });
      setPreview(res);
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Falha ao pré-validar deploy no JasperServer.",
      );
    } finally {
      setPreparing(false);
    }
  };

  const handleExecute = async () => {
    if (!preview?.deploy_token) return;
    setExecuting(true);
    setErrorMsg(null);
    try {
      const result = await jasperServerApi.executeDeploy(project.id, {
        deploy_token: preview.deploy_token,
      });
      setDeployResult(result);
      pushToast({
        tone: "success",
        title: "Publicado no JasperReports Server",
        description: result.message,
      });
      onDeployed?.(result);
    } catch (err) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : "Falha ao executar deploy no JasperServer.",
      );
    } finally {
      setExecuting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!preparing && !executing) onClose();
      }}
      title="Publicar no JasperReports Server"
      description="Fluxo seguro em 2 etapas: compilação obrigatória na JVM, diff remoto e backup local automático."
      size="xl"
      footer={
        deployResult ? (
          <Button variant="primary" onClick={onClose}>
            Concluir
          </Button>
        ) : preview ? (
          <>
            <Button
              variant="ghost"
              disabled={executing}
              onClick={() => {
                setPreview(null);
                setErrorMsg(null);
              }}
            >
              Voltar
            </Button>
            <Button
              variant="primary"
              loading={executing}
              onClick={() => void handleExecute()}
              icon={<CloudUpload className="h-3.5 w-3.5" />}
            >
              Confirmar publicação
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose} disabled={preparing}>
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={preparing}
              disabled={!profileId || !targetUri.trim() || isReadOnly}
              onClick={() => void handlePrepare()}
              icon={<FileDiff className="h-3.5 w-3.5" />}
            >
              Pré-validar e gerar diff
            </Button>
          </>
        )
      }
    >
      {deployResult ? (
        <div className="space-y-3">
          <div className="flex items-start gap-2.5 rounded-md border border-success/30 bg-success-soft/70 p-3 text-xs text-success">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-1">
              <p className="font-semibold">{deployResult.message}</p>
              <p className="font-mono text-[11px]">
                Destino: {deployResult.target_uri}
              </p>
              <p className="font-mono text-[11px]">
                JRXML: {deployResult.main_jrxml_uri}
              </p>
              {deployResult.local_backup_path && (
                <p className="font-mono text-[11px]">
                  Backup local: {deployResult.local_backup_path}
                </p>
              )}
            </div>
          </div>
        </div>
      ) : preview ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="success">
              <CheckCircle2 className="h-3 w-3" />
              Compilação JVM OK
            </Badge>
            <Badge tone="blueprint">
              {preview.mode === "update"
                ? "Atualizar Report Unit"
                : "Criar Nova Report Unit"}
            </Badge>
            {preview.remote_exists ? (
              <Badge tone="warning">Substituirá JRXML remoto (backup local será salvo)</Badge>
            ) : (
              <Badge tone="accent">Novo recurso no repositório</Badge>
            )}
          </div>

          <div className="grid grid-cols-1 gap-2 rounded-md border border-border bg-surface-subtle/50 p-3 font-mono text-[11px] sm:grid-cols-2">
            <div>
              <span className="text-ink-muted">Target URI:</span>{" "}
              <span className="text-ink">{preview.target_uri}</span>
            </div>
            <div>
              <span className="text-ink-muted">Main JRXML:</span>{" "}
              <span className="text-ink">{preview.main_jrxml_uri}</span>
            </div>
            <div>
              <span className="text-ink-muted">Local SHA-256:</span>{" "}
              <span className="text-ink">
                {preview.local_sha256.slice(0, 16)}…
              </span>
            </div>
            <div>
              <span className="text-ink-muted">Remote SHA-256:</span>{" "}
              <span className="text-ink">
                {preview.remote_sha256
                  ? `${preview.remote_sha256.slice(0, 16)}…`
                  : "—"}
              </span>
            </div>
          </div>

          <div>
            <FieldLabel>Diff unificado (Remoto → Local)</FieldLabel>
            <UnifiedDiffBox diff={preview.unified_diff} />
          </div>

          {errorMsg && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft/70 px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <FieldLabel>Modo de publicação</FieldLabel>
            <Tabs
              options={[
                { id: "update", label: "Atualizar Report Unit existente" },
                { id: "create", label: "Criar nova Report Unit" },
              ]}
              value={mode}
              onChange={(next) => {
                setMode(next as DeployMode);
                setErrorMsg(null);
              }}
            />
          </div>

          <div>
            <FieldLabel htmlFor="js-deploy-profile">
              Perfil JasperReports Server *
            </FieldLabel>
            <SearchableSelect
              id="js-deploy-profile"
              ariaLabel="Perfil JasperReports Server"
              value={profileId}
              disabled={loadingProfiles || profiles.length === 0}
              onChange={(nextId) => {
                setProfileId(nextId);
                setErrorMsg(null);
              }}
              options={profileOptions}
              placeholder="Nenhum perfil cadastrado"
              searchPlaceholder="Buscar perfil por nome, URL ou ambiente..."
              emptyLabel="Nenhum perfil JasperServer encontrado."
            />
          </div>

          {isReadOnly && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning-soft/80 px-3 py-2.5 text-xs text-warning"
            >
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <p className="font-semibold">
                  Perfil em modo Somente Leitura (read_only)
                </p>
                <p className="mt-0.5 text-[11px]">
                  Publicações estão bloqueadas para este servidor (especialmente
                  em ambientes PRD). Selecione um perfil de homologação ou
                  desative o bloqueio em Configurações se realmente desejar
                  publicar.
                </p>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="js-deploy-target-uri">
                URI da Report Unit *
              </FieldLabel>
              <Input
                id="js-deploy-target-uri"
                placeholder="/reports/hospitalar/meu_relatorio"
                value={targetUri}
                onChange={(e) => setTargetUri(e.target.value)}
              />
            </div>

            {mode === "update" ? (
              <div>
                <FieldLabel htmlFor="js-deploy-main-jrxml">
                  URI do main_jrxml (opcional)
                </FieldLabel>
                <Input
                  id="js-deploy-main-jrxml"
                  placeholder="Auto-resolvido via _files/main_jrxml"
                  value={mainJrxmlUri}
                  onChange={(e) => setMainJrxmlUri(e.target.value)}
                />
              </div>
            ) : (
              <div>
                <FieldLabel htmlFor="js-deploy-label">
                  Rótulo (Label) da Report Unit
                </FieldLabel>
                <Input
                  id="js-deploy-label"
                  placeholder="Nome exibido no JasperServer"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                />
              </div>
            )}
          </div>

          {mode === "create" && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <FieldLabel htmlFor="js-deploy-datasource">
                  DataSource do servidor (opcional)
                </FieldLabel>
                <Button
                  variant="ghost"
                  size="xs"
                  loading={loadingDatasources}
                  onClick={() => void loadDatasources(profileId)}
                  icon={<RefreshCw className="h-3 w-3" />}
                >
                  Recarregar DataSources
                </Button>
              </div>

              {datasources.length > 0 ? (
                <Select
                  id="js-deploy-datasource"
                  value={datasourceUri}
                  onChange={(e) => setDatasourceUri(e.target.value)}
                >
                  <option value="">Selecionar DataSource...</option>
                  {datasources.map((ds) => (
                    <option key={ds.uri} value={ds.uri}>
                      {ds.label} ({ds.uri})
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  id="js-deploy-datasource"
                  placeholder="/datasources/salutem_postgres"
                  value={datasourceUri}
                  onChange={(e) => setDatasourceUri(e.target.value)}
                />
              )}
            </div>
          )}

          {errorMsg && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft/70 px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}
        </div>
      )}
    </Dialog>
  );
}
