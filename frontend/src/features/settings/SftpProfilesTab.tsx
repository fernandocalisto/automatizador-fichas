import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Edit3,
  FolderKey,
  KeyRound,
  Lock,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldAlert,
  Trash2,
  Upload,
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
  SearchableSelect,
  Select,
  Switch,
  Textarea,
  useToast,
  type SearchableSelectOption,
} from "@/components/ui";
import { sftpApi } from "@/features/sftp/sftpApi";
import type {
  CredentialMode,
  DbProfileRead,
  EnvironmentKind,
  SftpAuthType,
  SftpConnectionTestResult,
  SftpProfileCreatePayload,
  SftpProfileRead,
  SftpProfileUpdatePayload,
} from "@/types/studio";

export interface SftpProfilesTabProps {
  profiles?: SftpProfileRead[];
  dbProfiles?: DbProfileRead[];
  loading?: boolean;
  onRefresh?: () => Promise<void>;
  initialSearch?: string;
}

interface SftpFormState {
  name: string;
  host: string;
  port: string;
  username: string;
  credential_mode: CredentialMode;
  auth_type: SftpAuthType;
  password: string;
  private_key: string;
  private_key_filename: string;
  private_key_path: string;
  clear_private_key: boolean;
  passphrase: string;
  remote_base_dir: string;
  environment: EnvironmentKind;
  read_only: boolean;
  linked_db_profile_id: string;
}

const INITIAL_FORM: SftpFormState = {
  name: "",
  host: "",
  port: "22",
  username: "",
  credential_mode: "default",
  auth_type: "password",
  password: "",
  private_key: "",
  private_key_filename: "",
  private_key_path: "",
  clear_private_key: false,
  passphrase: "",
  remote_base_dir: "/",
  environment: "HML",
  read_only: false,
  linked_db_profile_id: "",
};

const ENV_BADGE_TONE: Record<EnvironmentKind, "neutral" | "warning" | "danger"> = {
  DEV: "neutral",
  HML: "warning",
  PRD: "danger",
};

type EnvFilter = "ALL" | EnvironmentKind;
const PAGE_SIZE = 25;

async function readKeyFileText(file: File): Promise<string> {
  if (typeof file.text === "function") {
    return file.text();
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () =>
      reject(reader.error ?? new Error("Falha ao ler arquivo selecionado."));
    reader.readAsText(file);
  });
}

export function SftpProfilesTab({
  profiles: externalProfiles,
  dbProfiles = [],
  loading: externalLoading,
  onRefresh: externalOnRefresh,
  initialSearch,
}: SftpProfilesTabProps) {
  const { pushToast } = useToast();

  const [internalProfiles, setInternalProfiles] = useState<SftpProfileRead[]>(
    [],
  );
  const [internalLoading, setInternalLoading] = useState(
    externalProfiles === undefined,
  );

  const profiles = externalProfiles ?? internalProfiles;
  const loading = externalLoading ?? internalLoading;

  const [searchQuery, setSearchQuery] = useState(initialSearch ?? "");
  const [envFilter, setEnvFilter] = useState<EnvFilter>("ALL");
  const [page, setPage] = useState(1);

  useEffect(() => {
    if (initialSearch !== undefined) {
      setSearchQuery(initialSearch);
      setEnvFilter("ALL");
    }
  }, [initialSearch]);

  const loadProfiles = useCallback(async () => {
    if (externalOnRefresh) {
      await externalOnRefresh();
      return;
    }
    setInternalLoading(true);
    try {
      const data = await sftpApi.listProfiles();
      setInternalProfiles(Array.isArray(data) ? data : []);
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao carregar perfis SFTP",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setInternalLoading(false);
    }
  }, [externalOnRefresh, pushToast]);

  useEffect(() => {
    if (externalProfiles === undefined) {
      void loadProfiles();
    }
  }, [externalProfiles, loadProfiles]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<SftpProfileRead | null>(
    null,
  );
  const [form, setForm] = useState<SftpFormState>(INITIAL_FORM);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<SftpProfileRead | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);

  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<
    Record<string, SftpConnectionTestResult>
  >({});

  const keyFileInputRef = useRef<HTMLInputElement | null>(null);

  const dbSelectOptions = useMemo<SearchableSelectOption[]>(
    () =>
      dbProfiles.map((db) => ({
        value: db.id,
        label: db.name,
        sublabel: `${db.host}:${db.port}/${db.dbname}`,
        badge: db.environment,
        keywords: `${db.user} ${db.host} ${db.dbname} ${db.environment ?? ""}`,
      })),
    [dbProfiles],
  );

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
      const hay =
        `${p.name} ${p.host} ${p.username} ${p.remote_base_dir}`.toLowerCase();
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
    setForm(INITIAL_FORM);
    setFormError(null);
    setModalOpen(true);
  };

  const openEditModal = (profile: SftpProfileRead) => {
    setEditingProfile(profile);
    setForm({
      name: profile.name,
      host: profile.host,
      port: String(profile.port),
      username: profile.username,
      credential_mode: profile.credential_mode,
      auth_type: profile.auth_type,
      password: "",
      private_key: "",
      private_key_filename: profile.private_key_filename || "",
      private_key_path: profile.private_key_path || "",
      clear_private_key: false,
      passphrase: "",
      remote_base_dir: profile.remote_base_dir,
      environment: profile.environment,
      read_only: profile.read_only,
      linked_db_profile_id: profile.linked_db_profile_id ?? "",
    });
    setFormError(null);
    setModalOpen(true);
  };

  const handleEnvironmentChange = (nextEnv: EnvironmentKind) => {
    setForm((prev) => ({
      ...prev,
      environment: nextEnv,
      read_only: nextEnv === "PRD" ? true : prev.read_only,
    }));
  };

  const handleKeyFileSelected = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const content = await readKeyFileText(file);
      if (!content.trim()) {
        setFormError(`O arquivo '${file.name}' está vazio.`);
        return;
      }
      setFormError(null);
      setForm((prev) => ({
        ...prev,
        private_key: content,
        private_key_filename: file.name,
        clear_private_key: false,
      }));
    } catch (err) {
      setFormError(
        err instanceof Error
          ? err.message
          : "Não foi possível ler o arquivo de chave privada.",
      );
    } finally {
      e.target.value = "";
    }
  };

  const handleRemoveSelectedKey = () => {
    setForm((prev) => ({
      ...prev,
      private_key: "",
      private_key_filename: "",
      clear_private_key: true,
    }));
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    const portNum = Number(form.port);
    if (!form.name.trim() || !form.host.trim()) {
      setFormError("Informe o nome e o host do servidor SFTP.");
      return;
    }
    if (!Number.isInteger(portNum) || portNum < 1 || portNum > 65535) {
      setFormError("Informe uma porta SSH válida entre 1 e 65535.");
      return;
    }
    if (form.credential_mode === "custom" && !form.username.trim()) {
      setFormError(
        "Informe o usuário SSH quando estiver usando Credencial Personalizada.",
      );
      return;
    }

    setSaving(true);
    setFormError(null);
    try {
      if (editingProfile) {
        const payload: SftpProfileUpdatePayload = {
          name: form.name.trim(),
          host: form.host.trim(),
          port: portNum,
          username: form.username.trim(),
          credential_mode: form.credential_mode,
          auth_type: form.auth_type,
          remote_base_dir: form.remote_base_dir.trim() || "/",
          environment: form.environment,
          read_only: form.read_only,
          linked_db_profile_id: form.linked_db_profile_id || null,
        };
        if (form.credential_mode === "custom") {
          if (form.auth_type === "password" && form.password !== "") {
            payload.password = form.password;
          }
          if (form.auth_type === "private_key") {
            payload.private_key_path = form.private_key_path.trim();
            if (form.private_key.trim() !== "") {
              payload.private_key = form.private_key;
              payload.private_key_filename = form.private_key_filename.trim();
            } else if (form.clear_private_key) {
              payload.private_key = "";
              payload.private_key_filename = "";
            }
            if (form.passphrase !== "") {
              payload.passphrase = form.passphrase;
            }
          }
        }
        await sftpApi.updateProfile(editingProfile.id, payload);
        pushToast({
          tone: "success",
          title: "Perfil SFTP atualizado",
          description: payload.name,
        });
      } else {
        const payload: SftpProfileCreatePayload = {
          name: form.name.trim(),
          host: form.host.trim(),
          port: portNum,
          username: form.username.trim(),
          credential_mode: form.credential_mode,
          auth_type: form.auth_type,
          remote_base_dir: form.remote_base_dir.trim() || "/",
          environment: form.environment,
          read_only: form.read_only,
          linked_db_profile_id: form.linked_db_profile_id || null,
        };
        if (form.credential_mode === "custom") {
          if (form.auth_type === "password" && form.password !== "") {
            payload.password = form.password;
          }
          if (form.auth_type === "private_key") {
            payload.private_key_path = form.private_key_path.trim();
            if (form.private_key.trim() !== "") {
              payload.private_key = form.private_key;
              payload.private_key_filename = form.private_key_filename.trim();
            }
            if (form.passphrase !== "") {
              payload.passphrase = form.passphrase;
            }
          }
        }
        await sftpApi.createProfile(payload);
        pushToast({
          tone: "success",
          title: "Perfil SFTP criado",
          description: payload.name,
        });
      }

      setModalOpen(false);
      await loadProfiles();
    } catch (err) {
      setFormError(
        err instanceof Error ? err.message : "Erro ao salvar perfil SFTP.",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await sftpApi.deleteProfile(deleteTarget.id);
      pushToast({
        tone: "success",
        title: "Perfil SFTP removido",
        description: deleteTarget.name,
      });
      setDeleteTarget(null);
      await loadProfiles();
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao remover perfil SFTP",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setDeleting(false);
    }
  };

  const handleTestConnection = async (profile: SftpProfileRead) => {
    setTestingId(profile.id);
    try {
      const result = await sftpApi.testProfile(profile.id);
      setTestResults((prev) => ({ ...prev, [profile.id]: result }));
      pushToast({
        tone: result.ok ? "success" : "error",
        title: result.ok
          ? `SFTP OK (${Math.round(result.latency_ms)} ms)`
          : "Falha na conexão SFTP",
        description: result.ok
          ? result.message
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
          remote_base_dir: profile.remote_base_dir,
          item_count: 0,
          message: msg,
          error: msg,
        },
      }));
      pushToast({
        tone: "error",
        title: "Erro ao testar conexão SFTP",
        description: msg,
      });
    } finally {
      setTestingId(null);
    }
  };

  const dbProfileNameById = new Map(dbProfiles.map((d) => [d.id, d.name]));

  const hasSelectedOrSavedProfileKey =
    Boolean(form.private_key.trim()) ||
    (!form.clear_private_key &&
      Boolean(
        editingProfile?.has_secret &&
          editingProfile.credential_mode === "custom" &&
          editingProfile.auth_type === "private_key" &&
          !editingProfile.private_key_path,
      )) ||
    (!form.clear_private_key && Boolean(form.private_key_filename));

  const profileKeyChipLabel =
    form.private_key_filename ||
    (form.private_key.trim()
      ? "Chave PEM pronta para salvar"
      : "Chave privada salva no cofre");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Servidores SSH / SFTP
          </h2>
          <p className="text-xs text-ink-muted">
            Conecte servidores Linux de fichas ambulatoriais para importar
            relatórios (.jrxml / .jasper) e publicar com diff e backup .bak
            automático.
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          onClick={openCreateModal}
          icon={<Plus className="h-3.5 w-3.5" />}
        >
          Novo servidor SFTP
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
              placeholder="Buscar servidor por nome, host ou usuário..."
              aria-label="Buscar servidores SFTP"
              className="h-8 w-full rounded-md border border-border bg-canvas pl-8 pr-7 text-xs text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery("")}
                aria-label="Limpar busca SFTP"
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-ink-muted hover:text-ink cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          <div
            role="group"
            aria-label="Filtrar SFTP por ambiente"
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
          Carregando servidores SFTP...
        </Card>
      ) : profiles.length === 0 ? (
        <EmptyState
          icon={<Server className="h-5 w-5" />}
          title="Nenhum servidor SFTP configurado"
          description="Adicione um servidor Linux ambulatorial usando Credencial Padrão ou Personalizada (senha ou arquivo .key)."
          action={
            <Button
              variant="primary"
              size="sm"
              onClick={openCreateModal}
              icon={<Plus className="h-3.5 w-3.5" />}
            >
              Cadastrar servidor SFTP
            </Button>
          }
        />
      ) : filteredProfiles.length === 0 ? (
        <Card className="p-6 text-center space-y-2">
          <p className="text-xs text-ink-muted">
            Nenhum servidor SFTP encontrado para os filtros aplicados.
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
            const testRes = testResults[profile.id];
            const linkedDbName = profile.linked_db_profile_id
              ? dbProfileNameById.get(profile.linked_db_profile_id)
              : null;

            return (
              <Card key={profile.id}>
                <CardBody className="space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-ink">
                          {profile.name}
                        </span>
                        <Badge tone={ENV_BADGE_TONE[profile.environment]}>
                          {profile.environment}
                        </Badge>
                        {profile.read_only ? (
                          <Badge tone="danger">
                            <Lock className="h-3 w-3" />
                            Somente leitura
                          </Badge>
                        ) : (
                          <Badge tone="success">Gravável</Badge>
                        )}
                        <Badge tone="blueprint">
                          {profile.credential_mode === "default"
                            ? "Credencial Padrão"
                            : "Personalizada"}
                        </Badge>
                        {profile.has_secret && (
                          <Badge tone="neutral">
                            <KeyRound className="h-3 w-3" />
                            {profile.auth_type === "private_key"
                              ? profile.private_key_filename ||
                                (profile.private_key_path
                                  ? "Chave local .key"
                                  : "Chave protegida")
                              : "Senha protegida"}
                          </Badge>
                        )}
                      </div>

                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted font-mono">
                        <span>
                          {profile.username ? `${profile.username}@` : ""}
                          {profile.host}:{profile.port}
                        </span>
                        <span>base: {profile.remote_base_dir}</span>
                        {linkedDbName && (
                          <span className="font-sans text-ink-secondary">
                            Banco vinculado: {linkedDbName}
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <Button
                        variant="outline"
                        size="xs"
                        loading={testingId === profile.id}
                        onClick={() => void handleTestConnection(profile)}
                        icon={<Play className="h-3 w-3" />}
                      >
                        Testar conexão
                      </Button>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => openEditModal(profile)}
                        icon={<Edit3 className="h-3 w-3" />}
                      >
                        Editar
                      </Button>
                      <Button
                        variant="ghost"
                        size="xs"
                        onClick={() => setDeleteTarget(profile)}
                        icon={<Trash2 className="h-3 w-3 text-danger" />}
                        aria-label={`Excluir ${profile.name}`}
                      />
                    </div>
                  </div>

                  {testRes && (
                    <div
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs ${
                        testRes.ok
                          ? "border-success/30 bg-success-soft/50 text-success"
                          : "border-danger/30 bg-danger-soft/60 text-danger"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {testRes.ok ? (
                          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                        ) : (
                          <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                        )}
                        <span>{testRes.message}</span>
                      </div>
                      <span className="font-mono tabular-nums">
                        {Math.round(testRes.latency_ms)} ms
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
                {filteredProfiles.length} servidores
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

      {/* Create / Edit Modal */}
      <Dialog
        open={modalOpen}
        onClose={() => {
          if (!saving) setModalOpen(false);
        }}
        title={editingProfile ? "Editar servidor SFTP" : "Novo servidor SFTP"}
        description="Segredos ficam exclusivamente no cofre local (OS Keyring / AES-256-GCM) e nunca são salvos em texto plano."
        size="lg"
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
              form="sftp-profile-form"
              variant="primary"
              loading={saving}
            >
              {editingProfile ? "Salvar alterações" : "Criar perfil SFTP"}
            </Button>
          </>
        }
      >
        <form id="sftp-profile-form" onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="sftp-name">Nome do servidor</FieldLabel>
              <Input
                id="sftp-name"
                value={form.name}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, name: e.target.value }))
                }
                placeholder="Ex.: Unidade Central — Ambulatorial"
                required
              />
            </div>

            <div>
              <FieldLabel htmlFor="sftp-env">Ambiente</FieldLabel>
              <Select
                id="sftp-env"
                value={form.environment}
                onChange={(e) =>
                  handleEnvironmentChange(e.target.value as EnvironmentKind)
                }
              >
                <option value="DEV">DEV — Desenvolvimento</option>
                <option value="HML">HML — Homologação</option>
                <option value="PRD">PRD — Produção</option>
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <FieldLabel htmlFor="sftp-host">Host / IP</FieldLabel>
              <Input
                id="sftp-host"
                value={form.host}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, host: e.target.value }))
                }
                placeholder="10.0.0.10 ou sftp.exemplo.local"
                className="font-mono text-xs"
                required
              />
            </div>

            <div>
              <FieldLabel htmlFor="sftp-port">Porta SSH</FieldLabel>
              <Input
                id="sftp-port"
                type="number"
                min={1}
                max={65535}
                value={form.port}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, port: e.target.value }))
                }
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="sftp-base-dir">
                Diretório base remoto (POSIX)
              </FieldLabel>
              <Input
                id="sftp-base-dir"
                value={form.remote_base_dir}
                onChange={(e) =>
                  setForm((prev) => ({
                    ...prev,
                    remote_base_dir: e.target.value,
                  }))
                }
                placeholder="/opt/salutem/relatorios"
                className="font-mono text-xs"
              />
            </div>

            <div>
              <FieldLabel htmlFor="sftp-linked-db">
                Perfil PostgreSQL vinculado (opcional)
              </FieldLabel>
              <SearchableSelect
                id="sftp-linked-db"
                ariaLabel="Perfil PostgreSQL vinculado"
                value={form.linked_db_profile_id}
                onChange={(nextVal) =>
                  setForm((prev) => ({
                    ...prev,
                    linked_db_profile_id: nextVal,
                  }))
                }
                options={dbSelectOptions}
                placeholder="Nenhum banco vinculado"
                searchPlaceholder="Buscar banco por nome, host ou dbname..."
                emptyLabel="Nenhum perfil PostgreSQL encontrado."
                allowClear
                clearLabel="Nenhum banco vinculado"
              />
            </div>
          </div>

          {/* Credential Mode Toggle */}
          <div className="rounded-md border border-border bg-surface-subtle/40 p-3 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <FieldLabel className="mb-0">Modo de credencial</FieldLabel>
              <div
                role="radiogroup"
                aria-label="Modo de credencial SFTP"
                className="inline-flex rounded-md border border-border bg-surface p-0.5 text-xs"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={form.credential_mode === "default"}
                  onClick={() =>
                    setForm((prev) => ({ ...prev, credential_mode: "default" }))
                  }
                  className={`rounded px-2.5 py-1 font-medium cursor-pointer transition-colors ${
                    form.credential_mode === "default"
                      ? "bg-accent text-accent-ink"
                      : "text-ink-muted hover:text-ink"
                  }`}
                >
                  Credencial Padrão
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={form.credential_mode === "custom"}
                  onClick={() =>
                    setForm((prev) => ({ ...prev, credential_mode: "custom" }))
                  }
                  className={`rounded px-2.5 py-1 font-medium cursor-pointer transition-colors ${
                    form.credential_mode === "custom"
                      ? "bg-accent text-accent-ink"
                      : "text-ink-muted hover:text-ink"
                  }`}
                >
                  Personalizada
                </button>
              </div>
            </div>

            {form.credential_mode === "default" ? (
              <div className="space-y-2 text-xs text-ink-muted">
                <p>
                  Herda usuário, autenticação e segredo das{" "}
                  <strong>Credenciais Padrão (SFTP)</strong> do cofre local.
                  Opcionalmente, informe um usuário abaixo para sobrescrever
                  apenas o login.
                </p>
                <div>
                  <FieldLabel htmlFor="sftp-user-override">
                    Usuário SSH (opcional — herda padrão se vazio)
                  </FieldLabel>
                  <Input
                    id="sftp-user-override"
                    value={form.username}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, username: e.target.value }))
                    }
                    placeholder="Deixe vazio para herdar o usuário padrão"
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <FieldLabel htmlFor="sftp-username">Usuário SSH</FieldLabel>
                    <Input
                      id="sftp-username"
                      value={form.username}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          username: e.target.value,
                        }))
                      }
                      placeholder="ex.: salutem_deploy"
                      required
                    />
                  </div>

                  <div>
                    <FieldLabel htmlFor="sftp-auth-type">
                      Tipo de autenticação
                    </FieldLabel>
                    <Select
                      id="sftp-auth-type"
                      value={form.auth_type}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          auth_type: e.target.value as SftpAuthType,
                        }))
                      }
                    >
                      <option value="password">Senha</option>
                      <option value="private_key">
                        Chave privada (.key / .pem)
                      </option>
                    </Select>
                  </div>
                </div>

                {form.auth_type === "password" ? (
                  <div>
                    <FieldLabel htmlFor="sftp-password">
                      Senha SSH{" "}
                      {editingProfile?.has_secret
                        ? "(deixe em branco para manter a atual)"
                        : ""}
                    </FieldLabel>
                    <Input
                      id="sftp-password"
                      type="password"
                      value={form.password}
                      onChange={(e) =>
                        setForm((prev) => ({
                          ...prev,
                          password: e.target.value,
                        }))
                      }
                      placeholder={
                        editingProfile?.has_secret ? "••••••••" : "Senha SSH"
                      }
                    />
                  </div>
                ) : (
                  <div className="space-y-3">
                    {/* Prominent .key / .pem file picker */}
                    <div className="space-y-2">
                      <FieldLabel className="mb-0">
                        Arquivo de chave privada SSH (.key / .pem)
                      </FieldLabel>

                      <input
                        ref={keyFileInputRef}
                        id="sftp-private-key-file"
                        type="file"
                        accept=".key,.pem,.rsa,.ed25519,.pub,*"
                        aria-label="Selecionar arquivo .key ou .pem do servidor"
                        onChange={(e) => void handleKeyFileSelected(e)}
                        className="sr-only"
                      />

                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => keyFileInputRef.current?.click()}
                          icon={<Upload className="h-3.5 w-3.5" />}
                        >
                          Selecionar arquivo .key / .pem...
                        </Button>

                        {hasSelectedOrSavedProfileKey && (
                          <div className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success-soft px-2.5 py-1 text-xs font-medium text-success">
                            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                            <span className="max-w-[200px] truncate font-mono text-[11px]">
                              {profileKeyChipLabel} ✓
                            </span>
                            <button
                              type="button"
                              onClick={() => keyFileInputRef.current?.click()}
                              title="Substituir arquivo de chave"
                              aria-label="Substituir arquivo de chave"
                              className="ml-0.5 rounded p-0.5 text-success/80 hover:bg-success/15 hover:text-success cursor-pointer"
                            >
                              <RefreshCw className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              onClick={handleRemoveSelectedKey}
                              title="Remover chave selecionada"
                              aria-label="Remover chave selecionada"
                              className="rounded p-0.5 text-success/80 hover:bg-danger-soft hover:text-danger cursor-pointer"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Local .key path input */}
                    <div>
                      <FieldLabel htmlFor="sftp-private-key-path">
                        <span className="inline-flex items-center gap-1.5">
                          <FolderKey className="h-3.5 w-3.5 text-ink-muted" />
                          Ou caminho local do arquivo .key (opcional)
                        </span>
                      </FieldLabel>
                      <Input
                        id="sftp-private-key-path"
                        value={form.private_key_path}
                        onChange={(e) =>
                          setForm((prev) => ({
                            ...prev,
                            private_key_path: e.target.value,
                          }))
                        }
                        placeholder="Ex.: C:\chaves\acesso.key ou ~/.ssh/id_ed25519"
                        className="font-mono text-xs"
                      />
                    </div>

                    {/* Collapsible manual PEM paste */}
                    <details className="rounded-md border border-border bg-surface px-3 py-2">
                      <summary className="cursor-pointer select-none text-xs font-medium text-ink-secondary hover:text-ink">
                        Colar texto PEM manualmente (avançado)
                      </summary>
                      <div className="mt-2.5">
                        <FieldLabel htmlFor="sftp-private-key">
                          Chave privada PEM (OpenSSH / RSA / Ed25519 / ECDSA)
                        </FieldLabel>
                        <Textarea
                          id="sftp-private-key"
                          value={form.private_key}
                          onChange={(e) =>
                            setForm((prev) => ({
                              ...prev,
                              private_key: e.target.value,
                              clear_private_key: false,
                            }))
                          }
                          placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                          className="font-mono text-xs"
                          rows={4}
                        />
                      </div>
                    </details>

                    <div>
                      <FieldLabel htmlFor="sftp-passphrase">
                        Passphrase da chave (opcional)
                      </FieldLabel>
                      <Input
                        id="sftp-passphrase"
                        type="password"
                        value={form.passphrase}
                        onChange={(e) =>
                          setForm((prev) => ({
                            ...prev,
                            passphrase: e.target.value,
                          }))
                        }
                        placeholder="Opcional"
                      />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Read-only switch & PRD notice */}
          <div className="rounded-md border border-border bg-surface p-3 space-y-2">
            <Switch
              id="sftp-read-only"
              checked={form.read_only}
              onChange={(checked) =>
                setForm((prev) => ({ ...prev, read_only: checked }))
              }
              label="Modo Somente Leitura (bloqueia publicação/deploy neste servidor)"
            />
            {form.environment === "PRD" && !form.read_only && (
              <div className="flex items-center gap-2 text-xs text-danger">
                <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
                <span>
                  Atenção: servidor de Produção (PRD) com escrita habilitada.
                  Backups .bak ainda serão obrigatórios.
                </span>
              </div>
            )}
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
        open={Boolean(deleteTarget)}
        onClose={() => {
          if (!deleting) setDeleteTarget(null);
        }}
        title="Excluir perfil SFTP"
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
              Excluir perfil
            </Button>
          </>
        }
      >
        <div className="flex items-start gap-2.5 text-xs text-ink-secondary">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <p>
            Remover o perfil <strong>{deleteTarget?.name}</strong> apagará
            também as credenciais personalizadas salvas no cofre local para este
            servidor.
          </p>
        </div>
      </Dialog>
    </div>
  );
}
