import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Edit3,
  KeyRound,
  Lock,
  Play,
  Plus,
  Server,
  ShieldAlert,
  Trash2,
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
import { jasperServerApi } from "@/features/jasperserver/jasperServerApi";
import type {
  CredentialMode,
  DbProfileRead,
  EnvironmentKind,
  JasperServerProfileCreatePayload,
  JasperServerProfileRead,
  JasperServerProfileUpdatePayload,
  JasperServerTestResult,
} from "@/types/studio";

export interface JasperServerProfilesTabProps {
  profiles?: JasperServerProfileRead[];
  dbProfiles?: DbProfileRead[];
  loading?: boolean;
  onRefresh?: () => Promise<void>;
}

interface JsProfileFormState {
  name: string;
  base_url: string;
  organization: string;
  username: string;
  password: string;
  credential_mode: CredentialMode;
  default_folder_uri: string;
  environment: EnvironmentKind;
  read_only: boolean;
  linked_db_profile_id: string;
}

const INITIAL_FORM: JsProfileFormState = {
  name: "",
  base_url: "",
  organization: "",
  username: "",
  password: "",
  credential_mode: "default",
  default_folder_uri: "/",
  environment: "HML",
  read_only: false,
  linked_db_profile_id: "",
};

export function JasperServerProfilesTab({
  profiles: externalProfiles,
  dbProfiles = [],
  loading: externalLoading,
  onRefresh,
}: JasperServerProfilesTabProps) {
  const { pushToast } = useToast();

  const [internalProfiles, setInternalProfiles] = useState<
    JasperServerProfileRead[]
  >([]);
  const [internalLoading, setInternalLoading] = useState(false);

  const isControlled = externalProfiles !== undefined;
  const profiles = isControlled ? externalProfiles : internalProfiles;
  const loading = externalLoading ?? internalLoading;

  const [modalOpen, setModalOpen] = useState(false);
  const [editingProfile, setEditingProfile] =
    useState<JasperServerProfileRead | null>(null);
  const [form, setForm] = useState<JsProfileFormState>(INITIAL_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] =
    useState<JasperServerProfileRead | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<
    Record<string, JasperServerTestResult>
  >({});

  const loadInternal = useCallback(async () => {
    if (isControlled) return;
    setInternalLoading(true);
    try {
      const list = await jasperServerApi.listProfiles();
      setInternalProfiles(list);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Erro ao carregar perfis JasperServer",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setInternalLoading(false);
    }
  }, [isControlled, pushToast]);

  useEffect(() => {
    if (!isControlled) {
      void loadInternal();
    }
  }, [isControlled, loadInternal]);

  const refreshList = async () => {
    if (onRefresh) {
      await onRefresh();
    } else {
      await loadInternal();
    }
  };

  const openCreateModal = () => {
    setEditingProfile(null);
    setForm(INITIAL_FORM);
    setFormError(null);
    setModalOpen(true);
  };

  const openEditModal = (profile: JasperServerProfileRead) => {
    setEditingProfile(profile);
    setForm({
      name: profile.name,
      base_url: profile.base_url,
      organization: profile.organization,
      username: profile.username,
      password: "",
      credential_mode: profile.credential_mode,
      default_folder_uri: profile.default_folder_uri || "/",
      environment: profile.environment,
      read_only: profile.read_only,
      linked_db_profile_id: profile.linked_db_profile_id || "",
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleEnvironmentChange = (nextEnv: EnvironmentKind) => {
    setForm((prev) => ({
      ...prev,
      environment: nextEnv,
      read_only: !editingProfile && nextEnv === "PRD" ? true : prev.read_only,
    }));
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.base_url.trim()) {
      setFormError("Preencha o nome do perfil e a URL base do JasperServer.");
      return;
    }
    if (form.credential_mode === "custom" && !form.username.trim()) {
      setFormError(
        "Informe o usuário quando o modo de credencial for Personalizada.",
      );
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      if (editingProfile) {
        const payload: JasperServerProfileUpdatePayload = {
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          organization: form.organization.trim(),
          username: form.username.trim(),
          credential_mode: form.credential_mode,
          default_folder_uri: form.default_folder_uri.trim() || "/",
          environment: form.environment,
          read_only: form.read_only,
          linked_db_profile_id: form.linked_db_profile_id || null,
        };
        if (form.credential_mode === "custom" && form.password !== "") {
          payload.password = form.password;
        }
        await jasperServerApi.updateProfile(editingProfile.id, payload);
        pushToast({
          tone: "success",
          title: "Perfil JasperServer atualizado",
          description: payload.name,
        });
      } else {
        const payload: JasperServerProfileCreatePayload = {
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          organization: form.organization.trim(),
          username: form.username.trim(),
          credential_mode: form.credential_mode,
          default_folder_uri: form.default_folder_uri.trim() || "/",
          environment: form.environment,
          read_only: form.read_only,
          linked_db_profile_id: form.linked_db_profile_id || null,
          password:
            form.credential_mode === "custom" && form.password !== ""
              ? form.password
              : undefined,
        };
        await jasperServerApi.createProfile(payload);
        pushToast({
          tone: "success",
          title: "Perfil JasperServer criado",
          description: payload.name,
        });
      }

      setModalOpen(false);
      await refreshList();
    } catch (err) {
      setFormError(
        err instanceof Error
          ? err.message
          : "Erro ao salvar perfil JasperServer.",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await jasperServerApi.deleteProfile(deleteTarget.id);
      pushToast({
        tone: "success",
        title: "Perfil JasperServer removido",
        description: deleteTarget.name,
      });
      setDeleteTarget(null);
      await refreshList();
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

  const handleTestConnection = async (profile: JasperServerProfileRead) => {
    setTestingId(profile.id);
    try {
      const result = await jasperServerApi.testProfile(profile.id);
      setTestResults((prev) => ({ ...prev, [profile.id]: result }));
      pushToast({
        tone: result.ok ? "success" : "error",
        title: result.ok
          ? `JasperServer OK (${Math.round(result.latency_ms)} ms)`
          : "Falha ao conectar no JasperServer",
        description: result.ok
          ? [result.edition, result.version].filter(Boolean).join(" ") ||
            result.message
          : result.error || result.message,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestResults((prev) => ({
        ...prev,
        [profile.id]: {
          profile_id: profile.id,
          ok: false,
          latency_ms: 0,
          version: null,
          edition: null,
          build: null,
          message: msg,
          error: msg,
        },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const dbNameById = new Map(dbProfiles.map((db) => [db.id, db.name]));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Servidores JasperReports Server (REST v2)
          </h2>
          <p className="text-xs text-ink-muted">
            Configure instâncias para importar Report Units e publicar alterações
            JRXML com validação JVM e backup local.
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          onClick={openCreateModal}
          icon={<Plus className="h-3.5 w-3.5" />}
        >
          Novo perfil JasperServer
        </Button>
      </div>

      {loading && profiles.length === 0 ? (
        <Card className="p-6 text-center text-xs text-ink-muted">
          Carregando perfis JasperReports Server...
        </Card>
      ) : profiles.length === 0 ? (
        <EmptyState
          icon={<Server className="h-5 w-5" />}
          title="Nenhum servidor JasperReports configurado"
          description="Cadastre uma instância de homologação ou produção para navegar, importar Report Units e publicar atualizações com segurança."
          action={
            <Button
              variant="primary"
              size="sm"
              onClick={openCreateModal}
              icon={<Plus className="h-3.5 w-3.5" />}
            >
              Cadastrar servidor
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {profiles.map((profile) => {
            const testResult = testResults[profile.id];
            const isTesting = testingId === profile.id;
            const linkedDbName = profile.linked_db_profile_id
              ? dbNameById.get(profile.linked_db_profile_id)
              : null;

            return (
              <Card key={profile.id}>
                <CardBody className="space-y-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-ink">
                          {profile.name}
                        </span>

                        <Badge
                          tone={
                            profile.environment === "PRD"
                              ? "danger"
                              : profile.environment === "HML"
                                ? "blueprint"
                                : "neutral"
                          }
                        >
                          {profile.environment}
                        </Badge>

                        {profile.read_only ? (
                          <Badge tone="warning" dot>
                            Somente leitura
                          </Badge>
                        ) : (
                          <Badge tone="blueprint">Deploy habilitado</Badge>
                        )}

                        <Badge tone="neutral">
                          <KeyRound className="h-3 w-3" />
                          {profile.credential_mode === "default"
                            ? "Credencial Padrão"
                            : "Personalizada"}
                        </Badge>

                        {profile.has_password && (
                          <Badge tone="success">
                            <Lock className="h-3 w-3" />
                            Senha protegida
                          </Badge>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs text-ink-secondary">
                        <span className="break-all">{profile.base_url}</span>
                        {profile.username && (
                          <span>
                            {profile.username}
                            {profile.organization
                              ? `|${profile.organization}`
                              : ""}
                          </span>
                        )}
                        <span className="text-ink-muted">
                          pasta={profile.default_folder_uri || "/"}
                        </span>
                        {linkedDbName && (
                          <span className="text-ink-muted">
                            PG={linkedDbName}
                          </span>
                        )}
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
                        Modo somente leitura ativo: publicações (PUT) estão
                        bloqueadas neste perfil.
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
                      <div className="flex min-w-0 items-center gap-2">
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
                          {(testResult.edition || testResult.version) && (
                            <span className="ml-2 font-mono text-[11px] opacity-90">
                              {[
                                testResult.edition,
                                testResult.version,
                                testResult.build
                                  ? `build ${testResult.build}`
                                  : null,
                              ]
                                .filter(Boolean)
                                .join(" · ")}
                            </span>
                          )}
                          {!testResult.ok && (
                            <p className="break-words text-[11px]">
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
        </div>
      )}

      {/* Create / Edit Dialog */}
      <Dialog
        open={modalOpen}
        onClose={() => {
          if (!saving) setModalOpen(false);
        }}
        title={
          editingProfile
            ? `Editar perfil — ${editingProfile.name}`
            : "Novo perfil JasperServer"
        }
        description="Configure a URL REST v2 e o modo de credenciais (Padrão do cofre local ou Personalizada)."
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
              form="jasperserver-profile-form"
              variant="primary"
              loading={saving}
            >
              {editingProfile ? "Salvar alterações" : "Criar perfil"}
            </Button>
          </>
        }
      >
        <form
          id="jasperserver-profile-form"
          onSubmit={handleSave}
          className="space-y-3.5"
        >
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <FieldLabel htmlFor="js-profile-name">
                Nome do perfil *
              </FieldLabel>
              <Input
                id="js-profile-name"
                placeholder="Ex.: JasperServer Hospitalar HML"
                value={form.name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, name: e.target.value }))
                }
                required
              />
            </div>

            <div>
              <FieldLabel htmlFor="js-profile-env">Ambiente</FieldLabel>
              <Select
                id="js-profile-env"
                value={form.environment}
                onChange={(e) =>
                  handleEnvironmentChange(e.target.value as EnvironmentKind)
                }
              >
                <option value="DEV">DEV</option>
                <option value="HML">HML</option>
                <option value="PRD">PRD</option>
              </Select>
            </div>
          </div>

          <div>
            <FieldLabel htmlFor="js-profile-url">
              URL Base (sem /rest_v2) *
            </FieldLabel>
            <Input
              id="js-profile-url"
              placeholder="https://servidor.exemplo.local/jasperserver"
              value={form.base_url}
              onChange={(e) =>
                setForm((f) => ({ ...f, base_url: e.target.value }))
              }
              required
            />
          </div>

          <div>
            <FieldLabel htmlFor="js-profile-cred-mode">
              Modo de Credenciais
            </FieldLabel>
            <Select
              id="js-profile-cred-mode"
              value={form.credential_mode}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  credential_mode: e.target.value as CredentialMode,
                }))
              }
            >
              <option value="default">
                Credencial Padrão (herda do cofre local)
              </option>
              <option value="custom">Personalizada (exclusiva deste perfil)</option>
            </Select>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="js-profile-user">
                Usuário {form.credential_mode === "custom" ? "*" : "(opcional)"}
              </FieldLabel>
              <Input
                id="js-profile-user"
                placeholder={
                  form.credential_mode === "default"
                    ? "Herdar usuário padrão"
                    : "Ex.: jasperadmin"
                }
                value={form.username}
                onChange={(e) =>
                  setForm((f) => ({ ...f, username: e.target.value }))
                }
                required={form.credential_mode === "custom"}
              />
            </div>

            <div>
              <FieldLabel htmlFor="js-profile-org">
                Organização (opcional)
              </FieldLabel>
              <Input
                id="js-profile-org"
                placeholder="Ex.: organization_1"
                value={form.organization}
                onChange={(e) =>
                  setForm((f) => ({ ...f, organization: e.target.value }))
                }
              />
            </div>
          </div>

          {form.credential_mode === "custom" && (
            <div>
              <div className="flex items-center justify-between">
                <FieldLabel htmlFor="js-profile-password">Senha</FieldLabel>
                {editingProfile?.has_password && (
                  <Badge tone="success" className="text-[10px]">
                    <Lock className="h-2.5 w-2.5" />
                    Senha protegida
                  </Badge>
                )}
              </div>
              <Input
                id="js-profile-password"
                type="password"
                autoComplete="new-password"
                placeholder={
                  editingProfile?.has_password
                    ? "Deixe em branco para manter a senha atual"
                    : "Senha do JasperReports Server"
                }
                value={form.password}
                onChange={(e) =>
                  setForm((f) => ({ ...f, password: e.target.value }))
                }
              />
            </div>
          )}

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="js-profile-folder">
                Pasta inicial no repositório
              </FieldLabel>
              <Input
                id="js-profile-folder"
                placeholder="/"
                value={form.default_folder_uri}
                onChange={(e) =>
                  setForm((f) => ({ ...f, default_folder_uri: e.target.value }))
                }
              />
            </div>

            <div>
              <FieldLabel htmlFor="js-profile-db">
                Perfil PostgreSQL vinculado
              </FieldLabel>
              <Select
                id="js-profile-db"
                value={form.linked_db_profile_id}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    linked_db_profile_id: e.target.value,
                  }))
                }
              >
                <option value="">Nenhum</option>
                {dbProfiles.map((db) => (
                  <option key={db.id} value={db.id}>
                    {db.name} ({db.host})
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="rounded-md border border-border bg-surface-subtle/50 p-3">
            <Switch
              id="js-profile-readonly"
              checked={form.read_only}
              onChange={(checked) =>
                setForm((f) => ({ ...f, read_only: checked }))
              }
              label="Somente leitura (bloqueia deploy / PUT neste servidor)"
            />
          </div>

          {formError && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger-soft/70 px-3 py-2 text-xs text-danger"
            >
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{formError}</span>
            </div>
          )}
        </form>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog
        open={Boolean(deleteTarget)}
        onClose={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        title="Excluir perfil JasperServer"
        description="Esta ação remove o perfil e apaga sua senha personalizada do cofre local."
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
            >
              Confirmar exclusão
            </Button>
          </>
        }
      >
        <div className="flex items-start gap-2.5 text-xs text-ink-secondary">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <p>
            Deseja realmente excluir o perfil{" "}
            <strong className="text-ink">{deleteTarget?.name}</strong>?
          </p>
        </div>
      </Dialog>
    </div>
  );
}
