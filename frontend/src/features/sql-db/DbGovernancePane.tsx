import { useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Database,
  FlaskConical,
  KeyRound,
  Lock,
  Play,
  PlugZap,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  TableProperties,
  Terminal,
  XCircle,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  Dialog,
  FieldLabel,
  Input,
  Select,
  Switch,
} from "@/components/ui";
import { cn } from "@/lib/cn";
import type {
  CommitInsertResult,
  DbConnectionTestResult,
  DbProfileRead,
  DryRunInsertResult,
  InspectSelectResult,
  ProjectRead,
  StudioSection,
} from "@/types/studio";

export type DryRunInvalidationReason = "sql_edited" | "profile_changed" | null;

export interface DbGovernancePaneProps {
  project: ProjectRead;
  profiles: DbProfileRead[];
  loadingProfiles: boolean;
  selectedProfileId: string;
  onSelectProfileId: (profileId: string) => void;
  onNavigateSection: (section: StudioSection) => void;

  testingConnection: boolean;
  connectionTestResult: DbConnectionTestResult | null;
  connectionTestError: string | null;
  onTestConnection: () => void;

  hasInsertSql: boolean;
  runningDryRun: boolean;
  dryRunResult: DryRunInsertResult | null;
  dryRunError: string | null;
  invalidationReason: DryRunInvalidationReason;
  onRunDryRun: () => void;

  committing: boolean;
  commitResult: CommitInsertResult | null;
  commitError: string | null;
  onConfirmCommit: () => Promise<boolean>;

  hasSelectSql: boolean;
  inspectingSelect: boolean;
  inspectResult: InspectSelectResult | null;
  inspectError: string | null;
  onInspectSelect: (opts: {
    sampleId?: number;
    lookupSampleId: boolean;
  }) => void;
}

function abbreviateHash(sha256: string): string {
  if (sha256.length <= 18) return sha256;
  return `${sha256.slice(0, 12)}…${sha256.slice(-6)}`;
}

function javaClassBadgeTone(
  javaClass: string,
): "accent" | "blueprint" | "neutral" | "warning" {
  if (javaClass.includes("Boolean")) return "accent";
  if (
    javaClass.includes("Double") ||
    javaClass.includes("Integer") ||
    javaClass.includes("Long") ||
    javaClass.includes("BigDecimal")
  ) {
    return "blueprint";
  }
  if (javaClass.includes("Date") || javaClass.includes("Timestamp")) {
    return "warning";
  }
  return "neutral";
}

export function DbGovernancePane({
  project,
  profiles,
  loadingProfiles,
  selectedProfileId,
  onSelectProfileId,
  onNavigateSection,
  testingConnection,
  connectionTestResult,
  connectionTestError,
  onTestConnection,
  hasInsertSql,
  runningDryRun,
  dryRunResult,
  dryRunError,
  invalidationReason,
  onRunDryRun,
  committing,
  commitResult,
  commitError,
  onConfirmCommit,
  hasSelectSql,
  inspectingSelect,
  inspectResult,
  inspectError,
  onInspectSelect,
}: DbGovernancePaneProps) {
  const [commitDialogOpen, setCommitDialogOpen] = useState(false);
  const [sampleIdInput, setSampleIdInput] = useState("");
  const [lookupSampleId, setLookupSampleId] = useState(false);
  const [columnFilter, setColumnFilter] = useState("");

  const selectedProfile = useMemo(
    () => profiles.find((p) => p.id === selectedProfileId) ?? null,
    [profiles, selectedProfileId],
  );

  const isReadOnlyProfile = selectedProfile?.read_only === true;
  const isDryRunValid = Boolean(dryRunResult?.ok && dryRunResult.dry_run_token);
  const canCommit =
    Boolean(selectedProfile) &&
    !isReadOnlyProfile &&
    isDryRunValid &&
    hasInsertSql &&
    !committing &&
    !runningDryRun;

  const filteredColumns = useMemo(() => {
    if (!inspectResult) return [];
    const term = columnFilter.trim().toLowerCase();
    if (!term) return inspectResult.columns;
    return inspectResult.columns.filter(
      (col) =>
        col.name.toLowerCase().includes(term) ||
        col.pg_type.toLowerCase().includes(term) ||
        col.java_class.toLowerCase().includes(term),
    );
  }, [inspectResult, columnFilter]);

  const handleRunInspect = () => {
    if (lookupSampleId) {
      onInspectSelect({ lookupSampleId: true });
      return;
    }
    const trimmed = sampleIdInput.trim();
    const parsed = trimmed ? Number.parseInt(trimmed, 10) : undefined;
    onInspectSelect({
      sampleId:
        parsed !== undefined && !Number.isNaN(parsed) ? parsed : undefined,
      lookupSampleId: false,
    });
  };

  const handleDialogConfirm = async () => {
    const ok = await onConfirmCommit();
    if (ok) {
      setCommitDialogOpen(false);
    }
  };

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto bg-canvas p-3.5">
      {/* 1. PostgreSQL Profile Selection */}
      <Card>
        <CardHeader className="py-2.5">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-accent" />
            <CardTitle>Perfil PostgreSQL</CardTitle>
          </div>
          <Button
            size="xs"
            variant="ghost"
            onClick={() => onNavigateSection("settings")}
            icon={<Settings className="h-3.5 w-3.5" />}
          >
            Configurações
          </Button>
        </CardHeader>

        <CardBody className="space-y-3 p-3.5">
          {loadingProfiles ? (
            <p className="text-xs text-ink-muted">
              Carregando perfis PostgreSQL...
            </p>
          ) : profiles.length === 0 ? (
            <div className="rounded-md border border-dashed border-warning/50 bg-warning-soft/60 p-3 text-xs">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <div className="space-y-2">
                  <p className="font-semibold text-ink">
                    Nenhum perfil PostgreSQL configurado
                  </p>
                  <p className="text-ink-secondary">
                    Cadastre uma conexão PostgreSQL nas Configurações para
                    executar Dry-Run, COMMIT de INSERT e inspeção do SELECT.
                  </p>
                  <Button
                    size="xs"
                    variant="primary"
                    onClick={() => onNavigateSection("settings")}
                    icon={<Settings className="h-3.5 w-3.5" />}
                  >
                    Configurar perfil PostgreSQL
                  </Button>
                </div>
              </div>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-[180px] flex-1">
                  <FieldLabel htmlFor="sql-db-profile-select">
                    Conexão alvo
                  </FieldLabel>
                  <Select
                    id="sql-db-profile-select"
                    value={selectedProfileId}
                    onChange={(e) => onSelectProfileId(e.target.value)}
                  >
                    {profiles.map((prof) => (
                      <option key={prof.id} value={prof.id}>
                        {prof.name}
                        {prof.read_only ? " (Somente Leitura)" : ""}
                        {prof.is_default ? " ★" : ""}
                      </option>
                    ))}
                  </Select>
                </div>

                <Button
                  size="sm"
                  variant="outline"
                  loading={testingConnection}
                  disabled={!selectedProfile}
                  onClick={onTestConnection}
                  icon={<PlugZap className="h-3.5 w-3.5 text-blueprint" />}
                >
                  Testar conexão
                </Button>
              </div>

              {selectedProfile && (
                <div className="flex flex-wrap items-center gap-1.5 rounded-md border border-border bg-surface-subtle/60 px-2.5 py-2 text-xs">
                  <span className="font-mono text-ink">
                    {selectedProfile.host}:{selectedProfile.port}/
                    {selectedProfile.dbname}
                  </span>
                  <span className="text-ink-muted">·</span>
                  <span className="font-mono text-ink-secondary">
                    usuário: {selectedProfile.user}
                  </span>
                  <Badge tone="neutral" className="text-[10px]">
                    ssl: {selectedProfile.sslmode}
                  </Badge>
                  {selectedProfile.read_only ? (
                    <Badge tone="danger" className="ml-auto font-semibold">
                      <Lock className="h-3 w-3" />
                      Somente Leitura
                    </Badge>
                  ) : (
                    <Badge tone="accent" className="ml-auto">
                      Leitura &amp; Escrita
                    </Badge>
                  )}
                </div>
              )}

              {isReadOnlyProfile && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-md border border-danger/35 bg-danger-soft/70 px-3 py-2 text-xs text-ink"
                >
                  <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
                  <span>
                    <strong>Trava Somente Leitura ativa:</strong> este perfil
                    bloqueia a execução definitiva (COMMIT) de scripts INSERT.
                    Dry-Run e inspeção SELECT continuam disponíveis.
                  </span>
                </div>
              )}

              {connectionTestResult && (
                <div
                  role="status"
                  className={cn(
                    "rounded-md border px-3 py-2 text-xs",
                    connectionTestResult.ok
                      ? "border-success/35 bg-success-soft/65 text-ink"
                      : "border-danger/35 bg-danger-soft/70 text-ink",
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5 font-semibold">
                      {connectionTestResult.ok ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-success" />
                      ) : (
                        <XCircle className="h-3.5 w-3.5 text-danger" />
                      )}
                      {connectionTestResult.ok
                        ? "Conexão validada"
                        : "Falha na conexão"}
                    </span>
                    <Badge tone="neutral" className="tabular-nums">
                      {connectionTestResult.latency_ms} ms
                    </Badge>
                  </div>
                  <p className="mt-1 text-ink-secondary">
                    {connectionTestResult.error || connectionTestResult.message}
                  </p>
                  {connectionTestResult.server_version && (
                    <p className="mt-0.5 font-mono text-[11px] text-ink-muted">
                      {connectionTestResult.server_version}
                    </p>
                  )}
                </div>
              )}

              {connectionTestError && (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-md border border-danger/35 bg-danger-soft/70 px-3 py-2 text-xs text-ink"
                >
                  <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" />
                  <span>{connectionTestError}</span>
                </div>
              )}
            </>
          )}
        </CardBody>
      </Card>

      {/* 2. Mandatory 2-Step Safe INSERT Execution */}
      <Card>
        <CardHeader className="py-2.5">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-accent" />
            <CardTitle>Execução Segura do INSERT (2 Etapas)</CardTitle>
          </div>
          {project.template_db_id !== null &&
            project.template_db_id !== undefined && (
              <Badge tone="success" dot className="tabular-nums">
                Template ID #{project.template_db_id}
              </Badge>
            )}
        </CardHeader>

        <CardBody className="space-y-3 p-3.5">
          {/* Step indicators */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div
              className={cn(
                "flex items-center gap-2 rounded-md border px-2.5 py-1.5",
                isDryRunValid
                  ? "border-success/40 bg-success-soft/60 text-success"
                  : "border-border bg-surface-subtle/50 text-ink-secondary",
              )}
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-current text-[11px] font-bold tabular-nums">
                1
              </span>
              <span className="font-medium">Dry-Run (ROLLBACK)</span>
            </div>
            <div
              className={cn(
                "flex items-center gap-2 rounded-md border px-2.5 py-1.5",
                commitResult?.committed
                  ? "border-success/40 bg-success-soft/60 text-success"
                  : canCommit
                    ? "border-accent/40 bg-accent-soft/60 text-accent"
                    : "border-border bg-surface-subtle/50 text-ink-muted",
              )}
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-current text-[11px] font-bold tabular-nums">
                2
              </span>
              <span className="font-medium">Confirmar COMMIT</span>
            </div>
          </div>

          {/* Step 1 Action */}
          <div className="space-y-2">
            <Button
              variant="blueprint"
              size="md"
              className="w-full"
              loading={runningDryRun}
              disabled={!selectedProfile || !hasInsertSql || committing}
              onClick={onRunDryRun}
              icon={<FlaskConical className="h-4 w-4" />}
            >
              Executar Dry-Run (BEGIN/ROLLBACK)
            </Button>

            {invalidationReason && !isDryRunValid && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-warning/45 bg-warning-soft/80 px-3 py-2 text-xs text-ink"
              >
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                <div>
                  <p className="font-semibold">
                    Token de Dry-Run invalidado — novo Dry-Run obrigatório
                  </p>
                  <p className="mt-0.5 text-ink-secondary">
                    {invalidationReason === "sql_edited"
                      ? "O SQL INSERT foi modificado após o último Dry-Run. Execute um novo Dry-Run para validar a versão atual antes do COMMIT."
                      : "O perfil PostgreSQL foi alterado após o último Dry-Run. Execute um novo Dry-Run no perfil selecionado antes do COMMIT."}
                  </p>
                </div>
              </div>
            )}

            {dryRunError && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-soft/75 px-3 py-2 text-xs text-ink"
              >
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">Dry-Run reprovado pelo PostgreSQL</p>
                  <p className="mt-0.5 break-words font-mono text-[11px] text-ink-secondary">
                    {dryRunError}
                  </p>
                </div>
              </div>
            )}

            {isDryRunValid && dryRunResult && (
              <div
                data-testid="dry-run-approved-card"
                className="space-y-2.5 rounded-md border border-success/45 bg-success-soft/55 p-3 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone="success" dot>
                      Dry-Run aprovado
                    </Badge>
                    {dryRunResult.rolled_back && (
                      <Badge tone="neutral">ROLLBACK confirmado</Badge>
                    )}
                  </div>
                  <Badge tone="neutral" className="tabular-nums">
                    {dryRunResult.latency_ms} ms
                  </Badge>
                </div>

                <div className="grid grid-cols-2 gap-2 rounded border border-border/70 bg-surface/90 p-2">
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-ink-muted">
                      Template ID simulado
                    </div>
                    <div className="mt-0.5 font-mono text-xs font-semibold text-ink tabular-nums">
                      {dryRunResult.simulated_template_id !== null
                        ? `#${dryRunResult.simulated_template_id}`
                        : "Não informado"}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-wider text-ink-muted">
                      Hash SQL (SHA-256)
                    </div>
                    <div
                      className="mt-0.5 flex items-center gap-1 font-mono text-xs text-ink"
                      title={dryRunResult.sql_sha256}
                    >
                      <KeyRound className="h-3 w-3 shrink-0 text-accent" />
                      <span>{abbreviateHash(dryRunResult.sql_sha256)}</span>
                    </div>
                  </div>
                </div>

                {dryRunResult.notices.length > 0 && (
                  <div className="rounded border border-border/70 bg-surface/90 p-2">
                    <div className="mb-1 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                      <Terminal className="h-3 w-3" />
                      Notices do PostgreSQL ({dryRunResult.notices.length})
                    </div>
                    <ul className="space-y-0.5 font-mono text-[11px] text-ink-secondary">
                      {dryRunResult.notices.map((notice, idx) => (
                        <li key={`${idx}-${notice}`} className="break-words">
                          {notice}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Step 2 Action */}
          <div className="space-y-1.5 border-t border-border pt-3">
            <Button
              variant="primary"
              size="md"
              className="w-full"
              loading={committing}
              disabled={!canCommit}
              onClick={() => setCommitDialogOpen(true)}
              icon={<Play className="h-4 w-4" />}
            >
              Confirmar e executar INSERT (COMMIT)
            </Button>

            {!canCommit && !committing && (
              <p className="text-[11px] text-ink-muted">
                {!selectedProfile
                  ? "Selecione um perfil PostgreSQL para habilitar a execução."
                  : isReadOnlyProfile
                    ? "Bloqueado: o perfil selecionado está configurado como Somente Leitura."
                    : !hasInsertSql
                      ? "Gere ou informe um script SQL INSERT antes de executar."
                      : "Bloqueado: execute um Dry-Run aprovado para o SQL e perfil atuais."}
              </p>
            )}

            {commitError && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-soft/75 px-3 py-2 text-xs text-ink"
              >
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">Falha ao confirmar COMMIT</p>
                  <p className="mt-0.5 break-words font-mono text-[11px] text-ink-secondary">
                    {commitError}
                  </p>
                </div>
              </div>
            )}

            {commitResult?.committed && (
              <div
                data-testid="commit-success-banner"
                role="status"
                className="space-y-2.5 rounded-md border border-success/50 bg-success-soft/80 p-3 text-xs"
              >
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-ink">
                      INSERT gravado no PostgreSQL com sucesso (COMMIT)
                    </p>
                    <p className="mt-0.5 text-ink-secondary">
                      {commitResult.message}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {commitResult.template_id !== null && (
                    <Badge tone="success" className="font-mono tabular-nums">
                      template_id: #{commitResult.template_id}
                    </Badge>
                  )}
                  <Badge tone="accent">
                    Gate 2: {commitResult.gate2_status}
                  </Badge>
                  <Badge tone="neutral" className="tabular-nums">
                    {commitResult.latency_ms} ms
                  </Badge>
                </div>

                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  onClick={() => onNavigateSection("jasper_studio")}
                  icon={<ArrowRight className="h-3.5 w-3.5" />}
                >
                  Avançar para Jasper Studio
                </Button>
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* 3. SELECT Inspection (LIMIT 0) */}
      <Card>
        <CardHeader className="py-2.5">
          <div className="flex items-center gap-2">
            <TableProperties className="h-4 w-4 text-blueprint" />
            <CardTitle>Inspecionar SELECT (LIMIT 0)</CardTitle>
          </div>
          {inspectResult && (
            <Badge tone="blueprint" className="tabular-nums">
              {inspectResult.columns.length}{" "}
              {inspectResult.columns.length === 1 ? "coluna" : "colunas"}
            </Badge>
          )}
        </CardHeader>

        <CardBody className="space-y-3 p-3.5">
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 sm:items-end">
            <div>
              <FieldLabel htmlFor="sql-inspect-sample-id">
                ID de atendimento (opcional)
              </FieldLabel>
              <Input
                id="sql-inspect-sample-id"
                type="number"
                min={0}
                value={sampleIdInput}
                disabled={lookupSampleId}
                onChange={(e) => setSampleIdInput(e.target.value)}
                placeholder={
                  lookupSampleId ? "Busca automática ativa" : "Ex.: 12345 (padrão 0)"
                }
              />
            </div>

            <div className="flex h-8 items-center">
              <Switch
                id="sql-inspect-lookup-sample"
                checked={lookupSampleId}
                onChange={setLookupSampleId}
                label="Buscar atendimento real recente"
              />
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            className="w-full"
            loading={inspectingSelect}
            disabled={!selectedProfile || !hasSelectSql}
            onClick={handleRunInspect}
            icon={<TableProperties className="h-3.5 w-3.5 text-blueprint" />}
          >
            Inspecionar colunas do SELECT (LIMIT 0)
          </Button>

          {inspectError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-soft/75 px-3 py-2 text-xs text-ink"
            >
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold">Erro ao inspecionar SELECT</p>
                <p className="mt-0.5 break-words font-mono text-[11px] text-ink-secondary">
                  {inspectError}
                </p>
              </div>
            </div>
          )}

          {inspectResult && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-surface-subtle/60 px-2.5 py-1.5 text-[11px]">
                <div className="flex flex-wrap items-center gap-2 text-ink-secondary">
                  <span className="font-semibold text-ink tabular-nums">
                    Total: {inspectResult.columns.length}{" "}
                    {inspectResult.columns.length === 1 ? "coluna" : "colunas"}
                  </span>
                  <span>·</span>
                  <span className="tabular-nums">
                    sample_id usado:{" "}
                    <strong className="font-mono text-ink">
                      {inspectResult.sample_id_used}
                    </strong>
                  </span>
                  <span>·</span>
                  <span className="tabular-nums">
                    {inspectResult.latency_ms} ms
                  </span>
                </div>
              </div>

              {inspectResult.columns.length > 6 && (
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-2 h-3.5 w-3.5 text-ink-muted" />
                  <Input
                    aria-label="Filtrar colunas do SELECT"
                    value={columnFilter}
                    onChange={(e) => setColumnFilter(e.target.value)}
                    placeholder="Filtrar por nome, tipo PG ou classe Java..."
                    className="h-7 pl-8 text-xs"
                  />
                </div>
              )}

              <div className="max-h-72 overflow-auto rounded-md border border-border">
                <table className="w-full border-collapse text-left text-xs">
                  <thead className="sticky top-0 border-b border-border bg-surface-subtle text-[11px] font-semibold text-ink-secondary">
                    <tr>
                      <th className="px-2.5 py-1.5">Coluna</th>
                      <th className="px-2.5 py-1.5">Tipo PG</th>
                      <th className="px-2.5 py-1.5 text-right">OID</th>
                      <th className="px-2.5 py-1.5">Classe Java</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/70 bg-surface">
                    {filteredColumns.length === 0 ? (
                      <tr>
                        <td
                          colSpan={4}
                          className="px-3 py-4 text-center text-ink-muted"
                        >
                          Nenhuma coluna corresponde ao filtro.
                        </td>
                      </tr>
                    ) : (
                      filteredColumns.map((col, idx) => (
                        <tr
                          key={`${col.name}-${idx}`}
                          className="hover:bg-surface-subtle/50"
                        >
                          <td className="px-2.5 py-1.5 font-mono font-medium text-ink">
                            {col.name}
                          </td>
                          <td className="px-2.5 py-1.5 font-mono text-ink-secondary">
                            {col.pg_type}
                          </td>
                          <td className="px-2.5 py-1.5 text-right font-mono text-ink-muted tabular-nums">
                            {col.type_oid ?? "—"}
                          </td>
                          <td className="px-2.5 py-1.5">
                            <Badge
                              tone={javaClassBadgeTone(col.java_class)}
                              className="font-mono text-[10px]"
                            >
                              {col.java_class}
                            </Badge>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Human Confirmation Dialog for COMMIT */}
      <Dialog
        open={commitDialogOpen}
        onClose={() => {
          if (!committing) setCommitDialogOpen(false);
        }}
        title="Confirmar e executar INSERT (COMMIT)"
        description="Revise os dados abaixo antes de gravar definitivamente o template da ficha clínica no PostgreSQL."
        size="md"
        footer={
          <>
            <Button
              variant="outline"
              disabled={committing}
              onClick={() => setCommitDialogOpen(false)}
            >
              Cancelar
            </Button>
            <Button
              variant="primary"
              loading={committing}
              disabled={!canCommit}
              onClick={handleDialogConfirm}
              icon={<Play className="h-3.5 w-3.5" />}
            >
              Confirmar COMMIT no PostgreSQL
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-xs">
          <div className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning-soft/75 p-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
            <p className="text-ink">
              Esta operação executará o script <strong>SQL INSERT</strong> com{" "}
              <strong>COMMIT</strong> definitivo no banco de destino, criando o
              template e suas perguntas/respostas e aprovando automaticamente o{" "}
              <strong>Gate 2</strong>.
            </p>
          </div>

          {selectedProfile && dryRunResult && (
            <dl className="grid grid-cols-1 gap-2 rounded-md border border-border bg-surface-subtle/50 p-3 sm:grid-cols-2">
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-ink-muted">
                  Perfil PostgreSQL
                </dt>
                <dd className="mt-0.5 font-semibold text-ink">
                  {selectedProfile.name}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-ink-muted">
                  Banco / Servidor
                </dt>
                <dd className="mt-0.5 font-mono text-ink">
                  {selectedProfile.host}:{selectedProfile.port}/
                  {selectedProfile.dbname}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-ink-muted">
                  Usuário
                </dt>
                <dd className="mt-0.5 font-mono text-ink">
                  {selectedProfile.user}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wider text-ink-muted">
                  Template ID simulado no Dry-Run
                </dt>
                <dd className="mt-0.5 font-mono font-semibold text-accent tabular-nums">
                  {dryRunResult.simulated_template_id !== null
                    ? `#${dryRunResult.simulated_template_id}`
                    : "Será atribuído pelo banco"}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-[10px] uppercase tracking-wider text-ink-muted">
                  Hash SHA-256 validado
                </dt>
                <dd className="mt-0.5 break-all font-mono text-[11px] text-ink-secondary">
                  {dryRunResult.sql_sha256}
                </dd>
              </div>
            </dl>
          )}

          {commitError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-soft/75 px-3 py-2 text-xs text-ink"
            >
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
              <div className="min-w-0 flex-1">
                <p className="font-semibold">Erro ao executar COMMIT</p>
                <p className="mt-0.5 break-words font-mono text-[11px] text-ink-secondary">
                  {commitError}
                </p>
              </div>
            </div>
          )}
        </div>
      </Dialog>
    </div>
  );
}
