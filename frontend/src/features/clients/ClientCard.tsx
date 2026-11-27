import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Cloud,
  Database,
  Edit3,
  ExternalLink,
  FilePlus2,
  FolderDown,
  HardDrive,
  Link2,
  Plus,
  Server,
  Shield,
  Tag,
  Trash2,
} from "lucide-react";
import { Badge, Button, Card, CardBody } from "@/components/ui";
import type { BadgeTone } from "@/components/ui";
import type {
  ClientSystemRead,
  ClientSystemType,
  ClientUnitRead,
  EnvironmentKind,
} from "@/types/studio";

export interface ClientCardProps {
  client: ClientUnitRead;
  defaultExpanded?: boolean;
  onEditClient: (client: ClientUnitRead) => void;
  onDeleteClient: (client: ClientUnitRead) => void;
  onAddSystem: (client: ClientUnitRead) => void;
  onEditSystem: (client: ClientUnitRead, system: ClientSystemRead) => void;
  onDeleteSystem: (client: ClientUnitRead, system: ClientSystemRead) => void;
  onCreateFreeReport?: (opts: {
    clientSystemId: string;
    dbProfileId?: string | null;
    defaultName: string;
  }) => void;
  onOpenSftpImport?: (
    sftpProfileId: string,
    dbProfileId?: string | null,
  ) => void;
  onOpenJasperImport?: (
    jasperProfileId: string,
    dbProfileId?: string | null,
  ) => void;
}

export const SYSTEM_TYPE_META: Record<
  ClientSystemType,
  { label: string; tone: BadgeTone }
> = {
  ambulatorial: { label: "Ambulatorial", tone: "accent" },
  hospitalar: { label: "Hospitalar", tone: "blueprint" },
  painel: { label: "Painel", tone: "success" },
  compras: { label: "Compras", tone: "warning" },
  outro: { label: "Outro", tone: "neutral" },
};

export const ENVIRONMENT_META: Record<
  EnvironmentKind,
  { label: string; tone: BadgeTone }
> = {
  PRD: { label: "PRD", tone: "danger" },
  HML: { label: "HML", tone: "warning" },
  DEV: { label: "DEV", tone: "blueprint" },
};

function isSafeExternalUrl(url: string): boolean {
  const trimmed = url.trim();
  return trimmed.startsWith("http://") || trimmed.startsWith("https://");
}

function getLicenseTone(status: string): BadgeTone {
  const lower = status.toLowerCase();
  if (lower.includes("ativ")) return "success";
  if (lower.includes("susp") || lower.includes("bloq") || lower.includes("venc"))
    return "danger";
  if (lower.includes("trial") || lower.includes("pend")) return "warning";
  return "neutral";
}

export function ClientCard({
  client,
  defaultExpanded = false,
  onEditClient,
  onDeleteClient,
  onAddSystem,
  onEditSystem,
  onDeleteSystem,
  onCreateFreeReport,
  onOpenSftpImport,
  onOpenJasperImport,
}: ClientCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  const isCloud = client.hosting.toLowerCase().includes("cloud") ||
    client.hosting.toLowerCase().includes("nuvem") ||
    client.hosting.toLowerCase().includes("saas");

  return (
    <Card className="transition-colors hover:border-border-strong">
      <CardBody className="space-y-3">
        {/* Card Header */}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setExpanded((prev) => !prev)}
                aria-expanded={expanded}
                className="inline-flex items-center gap-1.5 text-left text-sm font-semibold text-ink hover:text-accent transition-colors cursor-pointer"
              >
                {expanded ? (
                  <ChevronDown className="h-4 w-4 shrink-0 text-ink-muted" />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-ink-muted" />
                )}
                <span>{client.name}</span>
              </button>

              <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                {client.unit_code}
              </span>

              {client.external_id && (
                <Badge tone="neutral" className="tabular-nums text-[11px]">
                  ID: {client.external_id}
                </Badge>
              )}

              {client.hosting && (
                <Badge tone={isCloud ? "blueprint" : "neutral"}>
                  {isCloud ? (
                    <Cloud className="h-3 w-3" />
                  ) : (
                    <HardDrive className="h-3 w-3" />
                  )}
                  {client.hosting}
                </Badge>
              )}

              {client.license_status && (
                <Badge tone={getLicenseTone(client.license_status)} dot>
                  {client.license_status}
                </Badge>
              )}

              <Badge tone="neutral" className="tabular-nums">
                {client.systems.length}{" "}
                {client.systems.length === 1 ? "sistema" : "sistemas"}
              </Badge>
            </div>

            {client.notes && (
              <p className="text-xs text-ink-secondary">{client.notes}</p>
            )}

            {(client.tags.length > 0 || client.integrations.length > 0) && (
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                {client.tags.map((tag) => (
                  <span
                    key={`tag-${tag}`}
                    className="inline-flex items-center gap-1 rounded border border-border bg-surface-subtle/70 px-1.5 py-0.5 text-ink-secondary"
                  >
                    <Tag className="h-2.5 w-2.5 text-ink-muted" />
                    {tag}
                  </span>
                ))}

                {client.integrations.map((integ) => (
                  <span
                    key={`integ-${integ}`}
                    className="inline-flex items-center gap-1 rounded border border-accent/20 bg-accent-soft/50 px-1.5 py-0.5 text-accent"
                  >
                    <Link2 className="h-2.5 w-2.5" />
                    {integ}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            <Button
              variant="outline"
              size="xs"
              onClick={() => onAddSystem(client)}
              icon={<Plus className="h-3 w-3" />}
            >
              Adicionar sistema
            </Button>

            <Button
              variant="outline"
              size="xs"
              onClick={() => onEditClient(client)}
              icon={<Edit3 className="h-3 w-3" />}
            >
              Editar
            </Button>

            <Button
              variant="ghost"
              size="icon"
              onClick={() => onDeleteClient(client)}
              aria-label={`Excluir cliente ${client.name}`}
              title="Excluir cliente"
              className="text-ink-muted hover:bg-danger-soft hover:text-danger"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>

        {/* Systems Rows */}
        {expanded && (
          <div className="border-t border-border pt-3 space-y-2">
            {client.systems.length === 0 ? (
              <div className="flex items-center justify-between rounded-md border border-dashed border-border bg-surface-subtle/40 px-3 py-2.5 text-xs text-ink-muted">
                <span>Nenhum sistema vinculado a este cliente ainda.</span>
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => onAddSystem(client)}
                  icon={<Plus className="h-3 w-3" />}
                >
                  Novo sistema
                </Button>
              </div>
            ) : (
              client.systems.map((sys) => {
                const typeMeta =
                  SYSTEM_TYPE_META[sys.system_type] ?? SYSTEM_TYPE_META.outro;
                const envMeta =
                  ENVIRONMENT_META[sys.environment] ?? ENVIRONMENT_META.PRD;
                const hasValidUrl = isSafeExternalUrl(sys.system_url);

                return (
                  <div
                    key={sys.id}
                    className="flex flex-col gap-2.5 rounded-md border border-border bg-surface-subtle/40 p-3 xl:flex-row xl:items-center xl:justify-between"
                  >
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-xs font-semibold text-ink">
                          {sys.label}
                        </span>

                        <Badge tone={typeMeta.tone}>{typeMeta.label}</Badge>

                        <Badge tone={envMeta.tone} dot>
                          {envMeta.label}
                        </Badge>

                        {sys.environment === "PRD" && (
                          <Badge
                            tone="warning"
                            title="Perfis de produção nascem somente leitura por padrão"
                          >
                            <Shield className="h-2.5 w-2.5" />
                            RO
                          </Badge>
                        )}

                        {sys.version_label && (
                          <span className="rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-secondary">
                            v{sys.version_label.replace(/^v/i, "")}
                          </span>
                        )}

                        {hasValidUrl && (
                          <a
                            href={sys.system_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 rounded border border-accent/30 bg-accent-soft/60 px-2 py-0.5 text-[11px] font-medium text-accent hover:bg-accent-soft transition-colors"
                          >
                            <ExternalLink className="h-3 w-3" />
                            Abrir Sistema
                          </a>
                        )}
                      </div>

                      {/* Connection profile badges */}
                      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                        <Badge
                          tone={sys.db_profile_id ? "success" : "neutral"}
                          className="text-[10px] py-0"
                        >
                          <Database className="h-2.5 w-2.5" />
                          {sys.db_profile_id ? "PG vinculado" : "Sem PG"}
                        </Badge>

                        <Badge
                          tone={sys.sftp_profile_id ? "success" : "neutral"}
                          className="text-[10px] py-0"
                        >
                          <Server className="h-2.5 w-2.5" />
                          {sys.sftp_profile_id ? "SFTP vinculado" : "Sem SFTP"}
                        </Badge>

                        <Badge
                          tone={
                            sys.jasperserver_profile_id ? "success" : "neutral"
                          }
                          className="text-[10px] py-0"
                        >
                          <FolderDown className="h-2.5 w-2.5" />
                          {sys.jasperserver_profile_id
                            ? "Jasper vinculado"
                            : "Sem Jasper"}
                        </Badge>
                      </div>
                    </div>

                    {/* 1-Click Workflow Actions */}
                    <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                      {onCreateFreeReport && (
                        <Button
                          variant="primary"
                          size="xs"
                          onClick={() =>
                            onCreateFreeReport({
                              clientSystemId: sys.id,
                              dbProfileId: sys.db_profile_id,
                              defaultName: `${client.name} — ${sys.label}`,
                            })
                          }
                          icon={<FilePlus2 className="h-3 w-3" />}
                        >
                          Novo Relatório Livre
                        </Button>
                      )}

                      {onOpenSftpImport && sys.sftp_profile_id && (
                        <Button
                          variant="outline"
                          size="xs"
                          onClick={() =>
                            onOpenSftpImport(
                              sys.sftp_profile_id!,
                              sys.db_profile_id,
                            )
                          }
                          icon={<Server className="h-3 w-3" />}
                        >
                          Importar SFTP
                        </Button>
                      )}

                      {onOpenJasperImport && sys.jasperserver_profile_id && (
                        <Button
                          variant="outline"
                          size="xs"
                          onClick={() =>
                            onOpenJasperImport(
                              sys.jasperserver_profile_id!,
                              sys.db_profile_id,
                            )
                          }
                          icon={<FolderDown className="h-3 w-3" />}
                        >
                          Importar JasperServer
                        </Button>
                      )}

                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onEditSystem(client, sys)}
                        aria-label={`Editar sistema ${sys.label}`}
                        title="Editar sistema"
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </Button>

                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onDeleteSystem(client, sys)}
                        aria-label={`Excluir sistema ${sys.label}`}
                        title="Excluir sistema"
                        className="text-ink-muted hover:bg-danger-soft hover:text-danger"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
