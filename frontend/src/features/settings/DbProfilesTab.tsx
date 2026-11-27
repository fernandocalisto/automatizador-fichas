import { useEffect, useMemo, useState, type FormEvent } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Edit3,
  Lock,
  Play,
  Plus,
  Search,
  ShieldAlert,
  Star,
  Trash2,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  Dialog,
  EmptyState,
  FieldLabel,
  Input,
  Select,
  Switch,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import type {
  DbConnectionTestResult,
  DbProfileCreatePayload,
  DbProfileRead,
  DbProfileUpdatePayload,
  EnvironmentKind,
  SslMode,
} from "@/types/studio";

export interface DbProfilesTabProps {
  profiles: DbProfileRead[];
  loading: boolean;
  onRefresh: () => Promise<void>;
}

const SSL_MODES: SslMode[] = [
  "disable",
  "allow",
  "prefer",
  "require",
  "verify-ca",
  "verify-full",
];

type EnvFilter = "ALL" | EnvironmentKind;
const PAGE_SIZE = 25;

interface ProfileFormState {
  name: string;
  host: string;
  port: string;
  dbname: string;
  user: string;
  password: string;
  sslmode: SslMode;
  read_only: boolean;
  is_default: boolean;
}

const INITIAL_FORM: ProfileFormState = {
  name: "",
  host: "localhost",
  port: "5432",
  dbname: "salutem",
  user: "postgres",
  password: "",
  sslmode: "prefer",
  read_only: true,
  is_default: false,
};

export function DbProfilesTab({
  profiles,
  loading,
  onRefresh,
}: DbProfilesTabProps) {
  const { pushToast } = useToast();

  const [searchQuery, setSearchQuery] = useState("");
  const [envFilter, setEnvFilter] = useState<EnvFilter>("ALL");
  const [page, setPage] = useState(1);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<DbProfileRead | null>(
    null,
  );
  const [form, setForm] = useState<ProfileFormState>(INITIAL_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<DbProfileRead | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<
    Record<string, DbConnectionTestResult>
  >({});

  const envCounts = useMemo(() => {
    const counts = { ALL: profiles.length, PRD: 0, HML: 0, DEV: 0 };
    for (const p of profiles) {
      if (p.environment === "PRD") counts.PRD += 1;
      else if (p.environment === "HML") counts.HML += 1;
      else if (p.environment === "DEV") counts.DEV += 1;
    }
    return counts;
  }, [profiles]);

  const filteredProfiles = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return profiles.filter((p) => {
      if (envFilter !== "ALL" && p.environment !== envFilter) return false;
      if (!q) return true;
      const hay = `${p.name} ${p.host} ${p.dbname} ${p.user}`.toLowerCase();
      return hay.includes(q);
    });
  }, [profiles, searchQuery, envFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredProfiles.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paginatedProfiles = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE;
    return filteredProfiles.slice(start, start + PAGE_SIZE);
  }, [filteredProfiles, safePage]);

  useEffect(() => {
    setPage(1);
  }, [searchQuery, envFilter]);

  const openCreateModal = () => {
    setEditingProfile(null);
    setForm({
      ...INITIAL_FORM,
      is_default: profiles.length === 0,
    });
    setFormError(null);
    setModalOpen(true);
  };

  const openEditModal = (profile: DbProfileRead) => {
    setEditingProfile(profile);
    setForm({
      name: profile.name,
      host: profile.host,
      port: String(profile.port),
      dbname: profile.dbname,
      user: profile.user,
      password: "",
      sslmode: profile.sslmode,
      read_only: profile.read_only,
      is_default: profile.is_default,
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    const portNum = Number(form.port);
    if (!form.name.trim() || !form.host.trim() || !form.dbname.trim() || !form.user.trim()) {
      setFormError("Preencha nome, host, banco de dados e usuário.");
      return;
    }
    if (!Number.isInteger(portNum) || portNum < 1 || portNum > 65535) {
      setFormError("Informe uma porta TCP válida entre 1 e 65535.");
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      if (editingProfile) {
        const payload: DbProfileUpdatePayload = {
          name: form.name.trim(),
          host: form.host.trim(),
          port: portNum,
          dbname: form.dbname.trim(),
          user: form.user.trim(),
          sslmode: form.sslmode,
          read_only: form.read_only,
          is_default: form.is_default,
        };
        if (form.password.trim() !== "") {
          payload.password = form.password;
        }
        await api.updateDbProfile(editingProfile.id, payload);
        pushToast({
          tone: "success",
          title: "Perfil PostgreSQL atualizado",
          description: payload.name,
        });
      } else {
        const payload: DbProfileCreatePayload = {
          name: form.name.trim(),
          host: form.host.trim(),
          port: portNum,
          dbname: form.dbname.trim(),
          user: form.user.trim(),
          password: form.password !== "" ? form.password : undefined,
          sslmode: form.sslmode,
          read_only: form.read_only,
          is_default: form.is_default,
        };
        await api.createDbProfile(payload);
        pushToast({
          tone: "success",
          title: "Perfil PostgreSQL criado",
          description: payload.name,
        });
      }

      setModalOpen(false);
      await onRefresh();
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "Erro ao salvar perfil.",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.deleteDbProfile(deleteTarget.id);
      pushToast({
        tone: "success",
        title: "Perfil removido",
        description: deleteTarget.name,
      });
      setDeleteTarget(null);
      await onRefresh();
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao remover perfil",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeleting(false);
    }
  };

  const handleTestConnection = async (profile: DbProfileRead) => {
    setTestingId(profile.id);
    try {
      const result = await api.testDbProfile(profile.id);
      setTestResults((prev) => ({ ...prev, [profile.id]: result }));
      pushToast({
        tone: result.ok ? "success" : "error",
        title: result.ok
          ? `Conexão OK (${Math.round(result.latency_ms)} ms)`
          : "Falha na conexão PostgreSQL",
        description: result.ok
          ? result.server_version ?? result.message
          : result.error ?? result.message,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestResults((prev) => ({
        ...prev,
        [profile.id]: {
          profile_id: profile.id,
          ok: false,
          latency_ms: 0,
          server_version: null,
          current_database: null,
          current_user: null,
          read_only: profile.read_only,
          message: msg,
          error: msg,
        },
      }));
      pushToast({
        tone: "error",
        title: "Erro ao testar conexão",
        description: msg,
      });
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Perfis de Conexão PostgreSQL
          </h2>
          <p className="text-xs text-ink-muted">
            Credenciais armazenadas com segurança no cofre local. Senhas nunca
            são exibidas novamente após salvar.
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          onClick={openCreateModal}
          icon={<Plus className="h-3.5 w-3.5" />}
        >
          Novo perfil PostgreSQL
        </Button>
      </div>

      {/* Search & Environment Filter Bar */}
      {profiles.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-border bg-surface p-2.5">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Buscar banco por nome, host ou dbname..."
              aria-label="Buscar perfis PostgreSQL"
              className="h-8 w-full rounded-md border border-border bg-canvas pl-8 pr-7 text-xs text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                aria-label="Limpar busca PostgreSQL"
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-muted hover:text-ink cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          <div
            role="group"
            aria-label="Filtrar PostgreSQL por ambiente"
            className="flex flex-wrap items-center gap-1"
          >
            {(["ALL", "PRD", "HML", "DEV"] as const).map((env) => {
              const active = envFilter === env;
              const label = env === "ALL" ? "Todos" : env;
              return (
                <button
                  key={env}
                  type="button"
                  onClick={() => setEnvFilter(env)}
                  className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer ${
                    active
                      ? "bg-accent text-accent-ink"
                      : "bg-surface-subtle text-ink-secondary hover:bg-surface-subtle/80 hover:text-ink"
                  }`}
                >
                  <span>{label}</span>
                  <span
                    className={`font-mono text-[10px] ${
                      active ? "opacity-90" : "text-ink-muted"
                    }`}
                  >
                    {envCounts[env]}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {loading && profiles.length === 0 ? (
        <Card className="p-6 text-center text-xs text-ink-muted">
          Carregando perfis PostgreSQL...
        </Card>
      ) : profiles.length === 0 ? (
        <EmptyState
          icon={<Database className="h-5 w-5" />}
          title="Nenhum perfil PostgreSQL configurado"
          description="Adicione um perfil de homologação ou produção (com proteção Somente Leitura) para validar SQL INSERT em Dry-Run e inspecionar queries SELECT."
          action={
            <Button
              variant="primary"
              size="sm"
              onClick={openCreateModal}
              icon={<Plus className="h-3.5 w-3.5" />}
            >
              Cadastrar perfil
            </Button>
          }
        />
      ) : filteredProfiles.length === 0 ? (
        <Card className="p-6 text-center space-y-2">
          <p className="text-xs text-ink-muted">
            Nenhum perfil PostgreSQL encontrado para os filtros aplicados.
          </p>
          <Button
            variant="outline"
            size="xs"
            onClick={() => {
              setSearchQuery("");
              setEnvFilter("ALL");
            }}
          >
            Limpar filtros
          </Button>
        </Card>
      ) : (
        <div className="space-y-3">
          {paginatedProfiles.map((profile) => {
            const testResult = testResults[profile.id];
            const isTesting = testingId === profile.id;

            return (
              <Card key={profile.id}>
                <CardBody className="space-y-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-ink">
                          {profile.name}
                        </span>

                        {profile.environment && (
                          <Badge
                            tone={
                              profile.environment === "PRD"
                                ? "danger"
                                : profile.environment === "HML"
                                  ? "warning"
                                  : "neutral"
                            }
                          >
                            {profile.environment}
                          </Badge>
                        )}

                        {profile.is_default && (
                          <Badge tone="accent">
                            <Star className="h-3 w-3" />
                            Padrão
                          </Badge>
                        )}

                        {profile.read_only ? (
                          <Badge tone="warning" dot>
                            Somente leitura
                          </Badge>
                        ) : (
                          <Badge tone="blueprint">Escrita via Dry-Run</Badge>
                        )}

                        {profile.has_password && (
                          <Badge tone="success">
                            <Lock className="h-3 w-3" />
                            Senha protegida
                          </Badge>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-ink-secondary">
                        <span>
                          {profile.user}@{profile.host}:{profile.port}/
                          {profile.dbname}
                        </span>
                        <span className="text-ink-muted">
                          sslmode={profile.sslmode}
                        </span>
                      </div>
                    </div>

                    <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                      <Button
                        variant="outline"
                        size="xs"
                        loading={isTesting}
                        onClick={() => void handleTestConnection(profile)}
                        icon={<Play className="h-3 w-3" />}
                      >
                        Testar conexão
                      </Button>

                      <Button
                        variant="outline"
                        size="xs"
                        onClick={() => openEditModal(profile)}
                        icon={<Edit3 className="h-3 w-3" />}
                      >
                        Editar
                      </Button>

                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleteTarget(profile)}
                        aria-label={`Excluir perfil ${profile.name}`}
                        title="Excluir perfil"
                        className="text-ink-muted hover:bg-danger-soft hover:text-danger"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>

                  {profile.read_only && (
                    <div className="flex items-center gap-2 rounded-md border border-warning/30 bg-warning-soft/70 px-3 py-1.5 text-[11px] text-warning">
                      <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
                      <span>
                        Modo somente leitura ativo: execuções de COMMIT INSERT
                        estão bloqueadas neste perfil.
                      </span>
                    </div>
                  )}

                  {testResult && (
                    <div
                      role="status"
                      className={
                        testResult.ok
                          ? "flex flex-wrap items-center justify-between gap-2 rounded-md border border-success/30 bg-success-soft/70 px-3 py-2 text-xs text-success"
                          : "flex flex-wrap items-center justify-between gap-2 rounded-md border border-danger/30 bg-danger-soft/70 px-3 py-2 text-xs text-danger"
                      }
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        {testResult.ok ? (
                          <CheckCircle2 className="h-4 w-4 shrink-0" />
                        ) : (
                          <AlertCircle className="h-4 w-4 shrink-0" />
                        )}
                        <div className="min-w-0">
                          <span className="font-semibold">
                            {testResult.ok
                              ? "Conexão estabelecida"
                              : "Falha ao conectar"}
                          </span>
                          {testResult.server_version && (
                            <span className="ml-2 font-mono text-[11px] opacity-90">
                              {testResult.server_version}
                            </span>
                          )}
                          {!testResult.ok && (
                            <p className="text-[11px] break-words">
                              {testResult.error || testResult.message}
                            </p>
                          )}
                        </div>
                      </div>
                      <span className="font-mono text-xs font-semibold tabular-nums">
                        {Math.round(testResult.latency_ms)} ms
                      </span>
                    </div>
                  )}
                </CardBody>
              </Card>
            );
          })}

          {/* Pagination Footer */}
          {filteredProfiles.length > PAGE_SIZE && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-ink-muted">
              <span>
                Mostrando {(safePage - 1) * PAGE_SIZE + 1}–
                {Math.min(safePage * PAGE_SIZE, filteredProfiles.length)} de{" "}
                {filteredProfiles.length} perfis
              </span>
              <div className="flex items-center gap-1.5">
                <Button
                  variant="outline"
                  size="xs"
                  disabled={safePage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  icon={<ChevronLeft className="h-3.5 w-3.5" />}
                >
                  Anterior
                </Button>
                <span className="px-2 font-mono text-[11px] text-ink">
                  {safePage} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="xs"
                  disabled={safePage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  icon={<ChevronRight className="h-3.5 w-3.5" />}
                >
                  Próxima
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Create / Edit Profile Dialog */}
      <Dialog
        open={modalOpen}
        onClose={() => {
          if (!saving) setModalOpen(false);
        }}
        title={
          editingProfile
            ? `Editar perfil — ${editingProfile.name}`
            : "Novo perfil PostgreSQL"
        }
        description="Configure os parâmetros de conexão com o banco Salutem."
        size="md"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setModalOpen(false)}
              disabled={saving}
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              form="db-profile-form"
              variant="primary"
              loading={saving}
            >
              {editingProfile ? "Salvar alterações" : "Criar perfil"}
            </Button>
          </>
        }
      >
        <form id="db-profile-form" onSubmit={handleSave} className="space-y-3.5">
          <div>
            <FieldLabel htmlFor="pg-profile-name">Nome do perfil *</FieldLabel>
            <Input
              id="pg-profile-name"
              placeholder="Ex.: Homologação Salutem"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              required
            />
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <FieldLabel htmlFor="pg-profile-host">Host *</FieldLabel>
              <Input
                id="pg-profile-host"
                placeholder="10.0.0.10 ou localhost"
                value={form.host}
                onChange={(e) =>
                  setForm((f) => ({ ...f, host: e.target.value }))
                }
                required
              />
            </div>
            <div>
              <FieldLabel htmlFor="pg-profile-port">Porta *</FieldLabel>
              <Input
                id="pg-profile-port"
                type="number"
                min={1}
                max={65535}
                value={form.port}
                onChange={(e) =>
                  setForm((f) => ({ ...f, port: e.target.value }))
                }
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="pg-profile-dbname">
                Banco de dados (dbname) *
              </FieldLabel>
              <Input
                id="pg-profile-dbname"
                placeholder="salutem"
                value={form.dbname}
                onChange={(e) =>
                  setForm((f) => ({ ...f, dbname: e.target.value }))
                }
                required
              />
            </div>
            <div>
              <FieldLabel htmlFor="pg-profile-user">Usuário *</FieldLabel>
              <Input
                id="pg-profile-user"
                placeholder="postgres"
                value={form.user}
                onChange={(e) =>
                  setForm((f) => ({ ...f, user: e.target.value }))
                }
                required
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <FieldLabel htmlFor="pg-profile-password" className="mb-0">
                  Senha
                </FieldLabel>
                {editingProfile?.has_password && (
                  <Badge tone="success" className="text-[10px] py-0">
                    <Lock className="h-2.5 w-2.5" />
                    Senha protegida
                  </Badge>
                )}
              </div>
              <Input
                id="pg-profile-password"
                type="password"
                autoComplete="new-password"
                placeholder={
                  editingProfile?.has_password
                    ? "Deixe em branco para manter a senha atual"
                    : "Informe a senha do banco"
                }
                value={form.password}
                onChange={(e) =>
                  setForm((f) => ({ ...f, password: e.target.value }))
                }
              />
            </div>

            <div>
              <FieldLabel htmlFor="pg-profile-sslmode">SSL Mode</FieldLabel>
              <Select
                id="pg-profile-sslmode"
                value={form.sslmode}
                onChange={(e) =>
                  setForm((f) => ({ ...f, sslmode: e.target.value as SslMode }))
                }
              >
                {SSL_MODES.map((mode) => (
                  <option key={mode} value={mode}>
                    {mode}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-2.5 rounded-md border border-border bg-surface-subtle/50 p-3">
            <Switch
              id="pg-profile-readonly"
              checked={form.read_only}
              onChange={(checked) =>
                setForm((f) => ({ ...f, read_only: checked }))
              }
              label="Somente leitura (bloquear INSERT)"
            />

            {form.read_only ? (
              <div className="flex items-start gap-2 rounded border border-warning/30 bg-warning-soft/80 px-2.5 py-2 text-[11px] text-warning">
                <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Proteção ativa: apenas Dry-Run (rollback) e inspeção de SELECT
                  serão permitidos. Ideal para produção ou auditoria.
                </span>
              </div>
            ) : (
              <div className="flex items-start gap-2 rounded border border-blueprint/30 bg-blueprint-soft/70 px-2.5 py-2 text-[11px] text-blueprint">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Escrita habilitada: o perfil permitirá COMMIT INSERT após
                  validação obrigatória por token de Dry-Run.
                </span>
              </div>
            )}

            <div className="pt-1">
              <Switch
                id="pg-profile-default"
                checked={form.is_default}
                onChange={(checked) =>
                  setForm((f) => ({ ...f, is_default: checked }))
                }
                label="Definir como perfil padrão do Studio"
              />
            </div>
          </div>

          {formError && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{formError}</span>
            </div>
          )}
        </form>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={deleteTarget !== null}
        onClose={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        title="Excluir perfil PostgreSQL"
        description="A configuração de conexão e a senha salva no cofre serão apagadas permanentemente."
        size="sm"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setDeleteTarget(null)}
              disabled={deleting}
            >
              Cancelar
            </Button>
            <Button
              variant="danger"
              loading={deleting}
              onClick={() => void handleDelete()}
              icon={<Trash2 className="h-3.5 w-3.5" />}
            >
              Confirmar exclusão
            </Button>
          </>
        }
      >
        {deleteTarget && (
          <p className="text-xs text-ink-secondary">
            Deseja realmente remover o perfil{" "}
            <strong className="text-ink">{deleteTarget.name}</strong> (
            <span className="font-mono">
              {deleteTarget.host}:{deleteTarget.port}/{deleteTarget.dbname}
            </span>
            )?
          </p>
        )}
      </Dialog>
    </div>
  );
}
