import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import {
  AlertCircle,
  CheckCircle2,
  Database,
  FileCode2,
  FolderKey,
  KeyRound,
  Lock,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardBody,
  FieldLabel,
  Input,
  Select,
  Textarea,
  useToast,
} from "@/components/ui";
import { clientsApi } from "@/features/clients/clientsApi";
import type {
  CredentialKind,
  DefaultCredentialRead,
  DefaultCredentialUpdatePayload,
  SftpAuthType,
} from "@/types/studio";

interface PgFormState {
  username: string;
  password: string;
  default_dbname: string;
  default_dbname_ambulatorial: string;
  default_dbname_hospitalar: string;
}

interface SftpFormState {
  username: string;
  auth_type: SftpAuthType;
  password: string;
  private_key: string;
  private_key_filename: string;
  private_key_path: string;
  clear_private_key: boolean;
  passphrase: string;
  default_remote_base_dir: string;
}

interface JasperFormState {
  username: string;
  organization: string;
  password: string;
}

const EMPTY_PG: PgFormState = {
  username: "",
  password: "",
  default_dbname: "",
  default_dbname_ambulatorial: "",
  default_dbname_hospitalar: "",
};

const EMPTY_SFTP: SftpFormState = {
  username: "",
  auth_type: "password",
  password: "",
  private_key: "",
  private_key_filename: "",
  private_key_path: "",
  clear_private_key: false,
  passphrase: "",
  default_remote_base_dir: "/",
};

const EMPTY_JASPER: JasperFormState = {
  username: "",
  organization: "",
  password: "",
};

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

export function DefaultCredentialsTab() {
  const { pushToast } = useToast();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [defaults, setDefaults] = useState<
    Partial<Record<CredentialKind, DefaultCredentialRead>>
  >({});

  const [pgForm, setPgForm] = useState<PgFormState>(EMPTY_PG);
  const [sftpForm, setSftpForm] = useState<SftpFormState>(EMPTY_SFTP);
  const [jasperForm, setJasperForm] = useState<JasperFormState>(EMPTY_JASPER);

  const [savingKind, setSavingKind] = useState<CredentialKind | null>(null);
  const [clearingKind, setClearingKind] = useState<CredentialKind | null>(null);

  const sftpKeyInputRef = useRef<HTMLInputElement | null>(null);

  const hydrateFromResponse = useCallback(
    (data: Record<CredentialKind, DefaultCredentialRead>) => {
      setDefaults(data);
      if (data.postgres) {
        setPgForm({
          username: data.postgres.username || "",
          password: "",
          default_dbname: data.postgres.default_dbname || "",
          default_dbname_ambulatorial:
            data.postgres.default_dbname_ambulatorial || "",
          default_dbname_hospitalar:
            data.postgres.default_dbname_hospitalar || "",
        });
      }
      if (data.sftp) {
        setSftpForm({
          username: data.sftp.username || "",
          auth_type: data.sftp.auth_type || "password",
          password: "",
          private_key: "",
          private_key_filename: data.sftp.private_key_filename || "",
          private_key_path: data.sftp.private_key_path || "",
          clear_private_key: false,
          passphrase: "",
          default_remote_base_dir: data.sftp.default_remote_base_dir || "/",
        });
      }
      if (data.jasperserver) {
        setJasperForm({
          username: data.jasperserver.username || "",
          organization: data.jasperserver.organization || "",
          password: "",
        });
      }
    },
    [],
  );

  const loadDefaults = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await clientsApi.listDefaultCredentials();
      hydrateFromResponse(res);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Falha ao carregar credenciais padrão.",
      );
    } finally {
      setLoading(false);
    }
  }, [hydrateFromResponse]);

  useEffect(() => {
    void loadDefaults();
  }, [loadDefaults]);

  const handleSave = async (
    kind: CredentialKind,
    payload: DefaultCredentialUpdatePayload,
    label: string,
  ) => {
    setSavingKind(kind);
    setError(null);
    try {
      const updated = await clientsApi.updateDefaultCredential(kind, payload);
      setDefaults((prev) => ({ ...prev, [kind]: updated }));
      if (kind === "postgres") {
        setPgForm((f) => ({ ...f, password: "" }));
      } else if (kind === "sftp") {
        setSftpForm((f) => ({
          ...f,
          password: "",
          private_key: "",
          private_key_filename: updated.private_key_filename || "",
          private_key_path: updated.private_key_path || "",
          clear_private_key: false,
          passphrase: "",
        }));
      } else if (kind === "jasperserver") {
        setJasperForm((f) => ({ ...f, password: "" }));
      }
      pushToast({
        tone: "success",
        title: `Credenciais padrão (${label}) salvas`,
        description: "Armazenadas somente no cofre local criptografado.",
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : `Falha ao salvar credenciais padrão de ${label}.`,
      );
    } finally {
      setSavingKind(null);
    }
  };

  const handleClear = async (kind: CredentialKind, label: string) => {
    setClearingKind(kind);
    setError(null);
    try {
      const cleared = await clientsApi.deleteDefaultCredential(kind);
      setDefaults((prev) => ({ ...prev, [kind]: cleared }));
      if (kind === "postgres") setPgForm(EMPTY_PG);
      if (kind === "sftp") setSftpForm(EMPTY_SFTP);
      if (kind === "jasperserver") setJasperForm(EMPTY_JASPER);
      pushToast({
        tone: "success",
        title: `Credenciais padrão (${label}) removidas`,
        description: "Segredos apagados do cofre local.",
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : `Falha ao limpar credenciais padrão de ${label}.`,
      );
    } finally {
      setClearingKind(null);
    }
  };

  const handleSftpKeyFileSelected = async (
    e: ChangeEvent<HTMLInputElement>,
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const content = await readKeyFileText(file);
      if (!content.trim()) {
        setError(`O arquivo '${file.name}' está vazio.`);
        return;
      }
      setError(null);
      setSftpForm((f) => ({
        ...f,
        private_key: content,
        private_key_filename: file.name,
        clear_private_key: false,
      }));
      pushToast({
        tone: "info",
        title: `Chave '${file.name}' carregada`,
        description: "Clique em Salvar SFTP padrão para guardar no cofre local.",
      });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Não foi possível ler o arquivo de chave privada.",
      );
    } finally {
      e.target.value = "";
    }
  };

  const handleRemoveSftpKey = () => {
    setSftpForm((f) => ({
      ...f,
      private_key: "",
      private_key_filename: "",
      clear_private_key: true,
    }));
  };

  const handleSavePostgres = (e: FormEvent) => {
    e.preventDefault();
    const payload: DefaultCredentialUpdatePayload = {
      username: pgForm.username.trim(),
      default_dbname: pgForm.default_dbname.trim(),
      default_dbname_ambulatorial: pgForm.default_dbname_ambulatorial.trim(),
      default_dbname_hospitalar: pgForm.default_dbname_hospitalar.trim(),
    };
    if (pgForm.password !== "") payload.password = pgForm.password;
    void handleSave("postgres", payload, "PostgreSQL");
  };

  const handleSaveSftp = (e: FormEvent) => {
    e.preventDefault();
    const payload: DefaultCredentialUpdatePayload = {
      username: sftpForm.username.trim(),
      auth_type: sftpForm.auth_type,
      default_remote_base_dir: sftpForm.default_remote_base_dir.trim() || "/",
    };
    if (sftpForm.auth_type === "password") {
      if (sftpForm.password !== "") payload.password = sftpForm.password;
    } else {
      payload.private_key_path = sftpForm.private_key_path.trim();
      if (sftpForm.private_key.trim() !== "") {
        payload.private_key = sftpForm.private_key;
        payload.private_key_filename = sftpForm.private_key_filename.trim();
      } else if (sftpForm.clear_private_key) {
        payload.private_key = "";
        payload.private_key_filename = "";
      }
      if (sftpForm.passphrase !== "") payload.passphrase = sftpForm.passphrase;
    }
    void handleSave("sftp", payload, "SSH / SFTP");
  };

  const handleSaveJasper = (e: FormEvent) => {
    e.preventDefault();
    const payload: DefaultCredentialUpdatePayload = {
      username: jasperForm.username.trim(),
      organization: jasperForm.organization.trim(),
    };
    if (jasperForm.password !== "") payload.password = jasperForm.password;
    void handleSave("jasperserver", payload, "JasperReports Server");
  };

  const pgMeta = defaults.postgres;
  const sftpMeta = defaults.sftp;
  const jasperMeta = defaults.jasperserver;

  const hasSelectedOrSavedVaultKey =
    Boolean(sftpForm.private_key.trim()) ||
    (!sftpForm.clear_private_key &&
      Boolean(sftpMeta?.has_private_key && !sftpMeta?.private_key_path)) ||
    (!sftpForm.clear_private_key && Boolean(sftpForm.private_key_filename));

  const activeKeyChipLabel =
    sftpForm.private_key_filename ||
    (sftpForm.private_key.trim()
      ? "Chave PEM pronta para salvar"
      : "Chave privada salva no cofre");

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-ink">
          Credenciais Padrão (Cofre Local)
        </h2>
        <p className="text-xs text-ink-muted">
          Configure uma única vez suas credenciais padrão por tipo de conexão.
          Perfis configurados em modo Padrão herdam estes valores
          automaticamente.
        </p>
      </div>

      {/* Explicit Local-Only Security Banner */}
      <div
        role="note"
        className="flex items-start gap-2.5 rounded-md border border-accent/30 bg-accent-soft/60 px-3.5 py-2.5 text-xs text-ink"
      >
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
        <div className="space-y-0.5">
          <div className="font-semibold text-accent">
            Armazenamento exclusivamente no cofre local desta máquina
          </div>
          <p className="text-[11px] text-ink-secondary">
            Nenhuma credencial é embutida no aplicativo ou enviada para fora.
            Senhas e chaves privadas são salvas apenas no cofre local
            criptografado (OS Keyring / AES-256-GCM) e nunca são exibidas
            novamente após salvar.
          </p>
        </div>
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

      {loading ? (
        <Card className="p-6 text-center text-xs text-ink-muted">
          Carregando credenciais padrão...
        </Card>
      ) : (
        <div className="space-y-4">
          {/* PostgreSQL Default Credentials Card */}
          <Card>
            <CardBody className="space-y-3.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-accent" />
                  <h3 className="text-sm font-semibold text-ink">
                    PostgreSQL Padrão
                  </h3>
                  {pgMeta?.configured ? (
                    <Badge tone="success" dot>
                      Configurado
                    </Badge>
                  ) : (
                    <Badge tone="neutral">Não configurado</Badge>
                  )}
                  {pgMeta?.has_password && (
                    <Badge tone="success">
                      <Lock className="h-3 w-3" />
                      Senha no cofre
                    </Badge>
                  )}
                </div>

                <Button
                  variant="ghost"
                  size="xs"
                  loading={clearingKind === "postgres"}
                  disabled={!pgMeta?.configured}
                  onClick={() => void handleClear("postgres", "PostgreSQL")}
                  icon={<Trash2 className="h-3 w-3" />}
                  className="text-ink-muted hover:bg-danger-soft hover:text-danger"
                >
                  Limpar PostgreSQL
                </Button>
              </div>

              <form onSubmit={handleSavePostgres} className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <FieldLabel htmlFor="def-pg-user">Usuário padrão</FieldLabel>
                    <Input
                      id="def-pg-user"
                      placeholder="Ex.: postgres"
                      value={pgForm.username}
                      onChange={(e) =>
                        setPgForm((f) => ({ ...f, username: e.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel htmlFor="def-pg-pass">Senha padrão</FieldLabel>
                    <Input
                      id="def-pg-pass"
                      type="password"
                      autoComplete="new-password"
                      placeholder={
                        pgMeta?.has_password
                          ? "Deixe em branco para manter a senha atual"
                          : "Informe a senha padrão do banco"
                      }
                      value={pgForm.password}
                      onChange={(e) =>
                        setPgForm((f) => ({ ...f, password: e.target.value }))
                      }
                    />
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <FieldLabel htmlFor="def-pg-dbname">
                      Banco padrão (fallback)
                    </FieldLabel>
                    <Input
                      id="def-pg-dbname"
                      placeholder="Ex.: postgres"
                      value={pgForm.default_dbname}
                      onChange={(e) =>
                        setPgForm((f) => ({
                          ...f,
                          default_dbname: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel htmlFor="def-pg-dbname-amb">
                      Banco padrão Ambulatorial
                    </FieldLabel>
                    <Input
                      id="def-pg-dbname-amb"
                      placeholder="Opcional"
                      value={pgForm.default_dbname_ambulatorial}
                      onChange={(e) =>
                        setPgForm((f) => ({
                          ...f,
                          default_dbname_ambulatorial: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel htmlFor="def-pg-dbname-hosp">
                      Banco padrão Hospitalar
                    </FieldLabel>
                    <Input
                      id="def-pg-dbname-hosp"
                      placeholder="Opcional"
                      value={pgForm.default_dbname_hospitalar}
                      onChange={(e) =>
                        setPgForm((f) => ({
                          ...f,
                          default_dbname_hospitalar: e.target.value,
                        }))
                      }
                    />
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button
                    type="submit"
                    variant="primary"
                    size="sm"
                    loading={savingKind === "postgres"}
                    icon={<Save className="h-3.5 w-3.5" />}
                  >
                    Salvar PostgreSQL padrão
                  </Button>
                </div>
              </form>
            </CardBody>
          </Card>

          {/* SSH / SFTP Default Credentials Card */}
          <Card>
            <CardBody className="space-y-3.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Server className="h-4 w-4 text-accent" />
                  <h3 className="text-sm font-semibold text-ink">
                    SSH / SFTP Padrão
                  </h3>
                  {sftpMeta?.configured ? (
                    <Badge tone="success" dot>
                      Configurado
                    </Badge>
                  ) : (
                    <Badge tone="neutral">Não configurado</Badge>
                  )}
                  {sftpMeta?.has_password && (
                    <Badge tone="success">
                      <Lock className="h-3 w-3" />
                      Senha no cofre
                    </Badge>
                  )}
                  {sftpMeta?.has_private_key && (
                    <Badge tone="blueprint">
                      <KeyRound className="h-3 w-3" />
                      {sftpMeta.private_key_filename
                        ? sftpMeta.private_key_filename
                        : sftpMeta.private_key_path
                          ? "Chave local (.key)"
                          : "Chave privada no cofre"}
                    </Badge>
                  )}
                </div>

                <Button
                  variant="ghost"
                  size="xs"
                  loading={clearingKind === "sftp"}
                  disabled={!sftpMeta?.configured}
                  onClick={() => void handleClear("sftp", "SSH / SFTP")}
                  icon={<Trash2 className="h-3 w-3" />}
                  className="text-ink-muted hover:bg-danger-soft hover:text-danger"
                >
                  Limpar SFTP
                </Button>
              </div>

              <form onSubmit={handleSaveSftp} className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <FieldLabel htmlFor="def-sftp-user">Usuário SSH</FieldLabel>
                    <Input
                      id="def-sftp-user"
                      placeholder="Ex.: deploy"
                      value={sftpForm.username}
                      onChange={(e) =>
                        setSftpForm((f) => ({ ...f, username: e.target.value }))
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel htmlFor="def-sftp-auth">
                      Tipo de autenticação
                    </FieldLabel>
                    <Select
                      id="def-sftp-auth"
                      value={sftpForm.auth_type}
                      onChange={(e) =>
                        setSftpForm((f) => ({
                          ...f,
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
                  <div>
                    <FieldLabel htmlFor="def-sftp-basedir">
                      Diretório remoto padrão
                    </FieldLabel>
                    <Input
                      id="def-sftp-basedir"
                      placeholder="/opt/reports"
                      value={sftpForm.default_remote_base_dir}
                      onChange={(e) =>
                        setSftpForm((f) => ({
                          ...f,
                          default_remote_base_dir: e.target.value,
                        }))
                      }
                    />
                  </div>
                </div>

                {sftpForm.auth_type === "password" ? (
                  <div>
                    <FieldLabel htmlFor="def-sftp-pass">
                      Senha SSH padrão
                    </FieldLabel>
                    <Input
                      id="def-sftp-pass"
                      type="password"
                      autoComplete="new-password"
                      placeholder={
                        sftpMeta?.has_password
                          ? "Deixe em branco para manter a senha atual"
                          : "Informe a senha SSH padrão"
                      }
                      value={sftpForm.password}
                      onChange={(e) =>
                        setSftpForm((f) => ({ ...f, password: e.target.value }))
                      }
                    />
                  </div>
                ) : (
                  <div className="space-y-3 rounded-lg border border-border bg-surface-subtle/40 p-3">
                    {/* Prominent .key / .pem file picker */}
                    <div className="space-y-2">
                      <FieldLabel className="mb-0">
                        Arquivo de chave privada SSH (.key / .pem)
                      </FieldLabel>

                      <input
                        ref={sftpKeyInputRef}
                        id="def-sftp-key-file"
                        type="file"
                        accept=".key,.pem,.rsa,.ed25519,.pub,*"
                        aria-label="Selecionar arquivo .key ou .pem"
                        onChange={(e) => void handleSftpKeyFileSelected(e)}
                        className="sr-only"
                      />

                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => sftpKeyInputRef.current?.click()}
                          icon={<Upload className="h-3.5 w-3.5" />}
                        >
                          Selecionar arquivo .key / .pem...
                        </Button>

                        {hasSelectedOrSavedVaultKey && (
                          <div className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success-soft px-2.5 py-1 text-xs font-medium text-success">
                            <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                            <span className="max-w-[220px] truncate font-mono text-[11px]">
                              {activeKeyChipLabel} ✓
                            </span>
                            <button
                              type="button"
                              onClick={() => sftpKeyInputRef.current?.click()}
                              title="Substituir arquivo de chave"
                              aria-label="Substituir arquivo de chave"
                              className="ml-0.5 rounded p-0.5 text-success/80 hover:bg-success/15 hover:text-success cursor-pointer"
                            >
                              <RefreshCw className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              onClick={handleRemoveSftpKey}
                              title="Remover chave selecionada"
                              aria-label="Remover chave selecionada"
                              className="rounded p-0.5 text-success/80 hover:bg-danger-soft hover:text-danger cursor-pointer"
                            >
                              <X className="h-3 w-3" />
                            </button>
                          </div>
                        )}
                      </div>
                      <p className="text-[11px] text-ink-muted">
                        O conteúdo do arquivo é importado de forma criptografada
                        para o cofre local (suporta OpenSSH, RSA, Ed25519 e
                        ECDSA).
                      </p>
                    </div>

                    {/* Optional local .key path */}
                    <div>
                      <FieldLabel htmlFor="def-sftp-key-path">
                        <span className="inline-flex items-center gap-1.5">
                          <FolderKey className="h-3.5 w-3.5 text-ink-muted" />
                          Ou caminho local do arquivo .key (opcional)
                        </span>
                      </FieldLabel>
                      <Input
                        id="def-sftp-key-path"
                        placeholder="Ex.: C:\chaves\acesso.key ou ~/.ssh/id_ed25519"
                        className="font-mono text-xs"
                        value={sftpForm.private_key_path}
                        onChange={(e) =>
                          setSftpForm((f) => ({
                            ...f,
                            private_key_path: e.target.value,
                          }))
                        }
                      />
                    </div>

                    {/* Collapsible manual PEM paste */}
                    <details className="rounded-md border border-border bg-surface px-3 py-2">
                      <summary className="cursor-pointer select-none text-xs font-medium text-ink-secondary hover:text-ink">
                        Colar texto PEM manualmente (avançado)
                      </summary>
                      <div className="mt-2.5">
                        <FieldLabel htmlFor="def-sftp-key">
                          Chave privada SSH
                        </FieldLabel>
                        <Textarea
                          id="def-sftp-key"
                          rows={4}
                          className="font-mono text-xs"
                          placeholder={
                            sftpMeta?.has_private_key
                              ? "Deixe em branco para manter a chave salva no cofre"
                              : "-----BEGIN OPENSSH PRIVATE KEY-----"
                          }
                          value={sftpForm.private_key}
                          onChange={(e) =>
                            setSftpForm((f) => ({
                              ...f,
                              private_key: e.target.value,
                              clear_private_key: false,
                            }))
                          }
                        />
                      </div>
                    </details>

                    <div>
                      <FieldLabel htmlFor="def-sftp-passphrase">
                        Passphrase da chave (opcional)
                      </FieldLabel>
                      <Input
                        id="def-sftp-passphrase"
                        type="password"
                        autoComplete="new-password"
                        placeholder={
                          sftpMeta?.has_passphrase
                            ? "Deixe em branco para manter a passphrase atual"
                            : "Opcional"
                        }
                        value={sftpForm.passphrase}
                        onChange={(e) =>
                          setSftpForm((f) => ({
                            ...f,
                            passphrase: e.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>
                )}

                <div className="flex justify-end">
                  <Button
                    type="submit"
                    variant="primary"
                    size="sm"
                    loading={savingKind === "sftp"}
                    icon={<Save className="h-3.5 w-3.5" />}
                  >
                    Salvar SFTP padrão
                  </Button>
                </div>
              </form>
            </CardBody>
          </Card>

          {/* JasperReports Server Default Credentials Card */}
          <Card>
            <CardBody className="space-y-3.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <FileCode2 className="h-4 w-4 text-accent" />
                  <h3 className="text-sm font-semibold text-ink">
                    JasperReports Server Padrão
                  </h3>
                  {jasperMeta?.configured ? (
                    <Badge tone="success" dot>
                      Configurado
                    </Badge>
                  ) : (
                    <Badge tone="neutral">Não configurado</Badge>
                  )}
                  {jasperMeta?.has_password && (
                    <Badge tone="success">
                      <Lock className="h-3 w-3" />
                      Senha no cofre
                    </Badge>
                  )}
                </div>

                <Button
                  variant="ghost"
                  size="xs"
                  loading={clearingKind === "jasperserver"}
                  disabled={!jasperMeta?.configured}
                  onClick={() =>
                    void handleClear("jasperserver", "JasperReports Server")
                  }
                  icon={<Trash2 className="h-3 w-3" />}
                  className="text-ink-muted hover:bg-danger-soft hover:text-danger"
                >
                  Limpar JasperServer
                </Button>
              </div>

              <form onSubmit={handleSaveJasper} className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                  <div>
                    <FieldLabel htmlFor="def-js-user">Usuário padrão</FieldLabel>
                    <Input
                      id="def-js-user"
                      placeholder="Ex.: jasperadmin"
                      value={jasperForm.username}
                      onChange={(e) =>
                        setJasperForm((f) => ({
                          ...f,
                          username: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel htmlFor="def-js-org">
                      Organização (opcional)
                    </FieldLabel>
                    <Input
                      id="def-js-org"
                      placeholder="Ex.: organization_1"
                      value={jasperForm.organization}
                      onChange={(e) =>
                        setJasperForm((f) => ({
                          ...f,
                          organization: e.target.value,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <FieldLabel htmlFor="def-js-pass">Senha padrão</FieldLabel>
                    <Input
                      id="def-js-pass"
                      type="password"
                      autoComplete="new-password"
                      placeholder={
                        jasperMeta?.has_password
                          ? "Deixe em branco para manter a senha atual"
                          : "Informe a senha padrão do JasperServer"
                      }
                      value={jasperForm.password}
                      onChange={(e) =>
                        setJasperForm((f) => ({
                          ...f,
                          password: e.target.value,
                        }))
                      }
                    />
                  </div>
                </div>

                <div className="flex justify-end">
                  <Button
                    type="submit"
                    variant="primary"
                    size="sm"
                    loading={savingKind === "jasperserver"}
                    icon={<Save className="h-3.5 w-3.5" />}
                  >
                    Salvar JasperServer padrão
                  </Button>
                </div>
              </form>
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  );
}
