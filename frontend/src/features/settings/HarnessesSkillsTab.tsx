import {
  BookOpen,
  CheckCircle2,
  Cpu,
  Eye,
  Plug,
  Terminal,
  XCircle,
} from "lucide-react";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  EmptyState,
} from "@/components/ui";
import type { HarnessStatus, SkillInfo } from "@/types/studio";

export interface HarnessesSkillsTabProps {
  harnesses: HarnessStatus[];
  skills: SkillInfo[];
  loading: boolean;
}

export function HarnessesSkillsTab({
  harnesses,
  skills,
  loading,
}: HarnessesSkillsTabProps) {
  return (
    <div className="space-y-6">
      {/* AI Harnesses section */}
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Harnesses de IA Detectados
          </h2>
          <p className="text-xs text-ink-muted">
            Status em tempo real dos executáveis e SDKs suportados pelo Studio
            para extração clínica e engenharia JRXML.
          </p>
        </div>

        {loading && harnesses.length === 0 ? (
          <Card className="p-6 text-center text-xs text-ink-muted">
            Verificando harnesses instalados...
          </Card>
        ) : harnesses.length === 0 ? (
          <EmptyState
            icon={<Cpu className="h-5 w-5" />}
            title="Nenhum harness reportado"
            description="Não foi possível detectar harnesses de IA disponíveis neste ambiente."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {harnesses.map((harness) => (
              <Card key={harness.id}>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Terminal className="h-4 w-4 text-accent" />
                    <CardTitle>{harness.display_name}</CardTitle>
                    <span className="rounded bg-surface-subtle px-1.5 py-0.5 font-mono text-[10px] text-ink-muted">
                      {harness.id}
                    </span>
                  </div>

                  <Badge tone={harness.installed ? "success" : "danger"} dot>
                    {harness.installed ? (
                      <>
                        <CheckCircle2 className="h-3 w-3" />
                        Instalado
                      </>
                    ) : (
                      <>
                        <XCircle className="h-3 w-3" />
                        Não instalado
                      </>
                    )}
                  </Badge>
                </CardHeader>

                <CardBody className="space-y-2.5 text-xs">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={harness.sdk_available ? "accent" : "neutral"}>
                      SDK: {harness.sdk_available ? "Disponível" : "Ausente"}
                    </Badge>

                    <Badge
                      tone={harness.supports_vision ? "blueprint" : "neutral"}
                    >
                      <Eye className="h-3 w-3" />
                      Visão: {harness.supports_vision ? "Sim" : "Não"}
                    </Badge>

                    <Badge
                      tone={harness.supports_mcp ? "blueprint" : "neutral"}
                    >
                      <Plug className="h-3 w-3" />
                      MCP: {harness.supports_mcp ? "Sim" : "Não"}
                    </Badge>

                    {harness.version && (
                      <Badge tone="neutral" className="font-mono tabular-nums">
                        {harness.version}
                      </Badge>
                    )}
                  </div>

                  {harness.executable_path && (
                    <div className="rounded border border-border bg-surface-subtle/60 px-2.5 py-1.5 font-mono text-[11px] text-ink-secondary break-all">
                      {harness.executable_path}
                    </div>
                  )}

                  {harness.auth_hint && (
                    <p className="text-[11px] text-ink-muted leading-relaxed">
                      <strong className="font-medium text-ink-secondary">
                        Autenticação:
                      </strong>{" "}
                      {harness.auth_hint}
                    </p>
                  )}
                </CardBody>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* Embedded Skills section */}
      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">
            Skills Clínicas Embutidas
          </h2>
          <p className="text-xs text-ink-muted">
            Instruções especializadas carregadas automaticamente nos prompts dos
            agentes para o domínio Salutem.
          </p>
        </div>

        {loading && skills.length === 0 ? (
          <Card className="p-6 text-center text-xs text-ink-muted">
            Carregando skills embutidas...
          </Card>
        ) : skills.length === 0 ? (
          <EmptyState
            icon={<BookOpen className="h-5 w-5" />}
            title="Nenhuma skill embutida encontrada"
            description="Verifique o diretório backend/app/skills para registrar SKILL.md."
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {skills.map((skill) => (
              <Card key={skill.id}>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <BookOpen className="h-4 w-4 text-blueprint" />
                    <CardTitle>{skill.name}</CardTitle>
                  </div>
                  <Badge tone="blueprint" className="font-mono text-[10px]">
                    {skill.id}
                  </Badge>
                </CardHeader>
                <CardBody className="space-y-2 text-xs">
                  <p className="text-ink-secondary leading-relaxed">
                    {skill.description || "Sem descrição no frontmatter."}
                  </p>
                  <p
                    className="truncate font-mono text-[10px] text-ink-muted"
                    title={skill.path}
                  >
                    {skill.path}
                  </p>
                </CardBody>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
