import type { ReactNode } from "react";
import {
  Bot,
  Database,
  FileCode2,
  FolderKanban,
  LayoutList,
  Moon,
  Settings,
  Sun,
  Workflow,
} from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { StudioTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/cn";
import type {
  HealthResponse,
  ProjectRead,
  StudioSection,
} from "@/types/studio";

export interface StudioShellProps {
  activeSection: StudioSection;
  onNavigate: (section: StudioSection) => void;
  projects: ProjectRead[];
  activeProject: ProjectRead | null;
  onSelectProjectId: (projectId: string) => void;
  theme: StudioTheme;
  onToggleTheme: () => void;
  health: HealthResponse | null;
  jasperUp: boolean | null;
  chatOpen?: boolean;
  onToggleChat?: () => void;
  children: ReactNode;
}

interface NavItem {
  id: StudioSection;
  label: string;
  icon: ReactNode;
  requiresProject: boolean;
}

const WORKFLOW_NAV: NavItem[] = [
  {
    id: "projects",
    label: "Projetos",
    icon: <FolderKanban className="h-3.5 w-3.5" />,
    requiresProject: false,
  },
  {
    id: "workspace",
    label: "Resumo & PDF",
    icon: <Workflow className="h-3.5 w-3.5" />,
    requiresProject: true,
  },
  {
    id: "form_builder",
    label: "Form Builder",
    icon: <LayoutList className="h-3.5 w-3.5" />,
    requiresProject: true,
  },
  {
    id: "sql_db",
    label: "SQL & Banco",
    icon: <Database className="h-3.5 w-3.5" />,
    requiresProject: true,
  },
  {
    id: "jasper_studio",
    label: "Jasper Studio",
    icon: <FileCode2 className="h-3.5 w-3.5" />,
    requiresProject: true,
  },
];

export function StudioShell({
  activeSection,
  onNavigate,
  projects,
  activeProject,
  onSelectProjectId,
  theme,
  onToggleTheme,
  health,
  jasperUp,
  chatOpen = false,
  onToggleChat,
  children,
}: StudioShellProps) {
  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-canvas text-ink">
      <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border bg-surface px-3">
        {/* Brand + Active project switcher */}
        <div className="flex shrink-0 items-center gap-2.5">
          <button
            type="button"
            onClick={() => onNavigate("projects")}
            className="flex shrink-0 items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-surface-subtle transition-colors cursor-pointer"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent text-xs font-bold tracking-tight text-accent-ink">
              SF
            </span>
            <div className="hidden lg:block leading-tight whitespace-nowrap">
              <div className="text-xs font-semibold tracking-tight text-ink">
                Salutem Ficha Studio
              </div>
              <div className="text-[10px] text-ink-muted tabular-nums">
                {health?.version ? `v${health.version}` : "v1.0.0"}
              </div>
            </div>
          </button>

          {projects.length > 0 && (
            <div className="hidden md:flex shrink-0 items-center gap-1.5 border-l border-border pl-2.5">
              <label htmlFor="studio-project-switcher" className="sr-only">
                Projeto ativo
              </label>
              <select
                id="studio-project-switcher"
                value={activeProject?.id ?? ""}
                onChange={(e) => {
                  if (e.target.value) {
                    onSelectProjectId(e.target.value);
                  }
                }}
                className="h-7 max-w-[155px] xl:max-w-[210px] truncate rounded border border-border bg-surface-subtle px-2 text-xs font-medium text-ink focus:border-accent focus:outline-none cursor-pointer"
              >
                <option value="">Selecionar projeto...</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
              {activeProject?.template_db_id !== null &&
                activeProject?.template_db_id !== undefined && (
                  <Badge tone="accent" className="tabular-nums">
                    ID #{activeProject.template_db_id}
                  </Badge>
                )}
            </div>
          )}
        </div>

        {/* Center workflow navigation */}
        <nav
          aria-label="Etapas do Studio"
          className="flex min-w-0 items-center gap-0.5 overflow-x-auto"
        >
          {WORKFLOW_NAV.map((item) => {
            const disabled = item.requiresProject && !activeProject;
            const active = activeSection === item.id;
            return (
              <button
                key={item.id}
                type="button"
                disabled={disabled}
                aria-current={active ? "page" : undefined}
                onClick={() => onNavigate(item.id)}
                className={cn(
                  "inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors whitespace-nowrap cursor-pointer",
                  "disabled:opacity-40 disabled:cursor-not-allowed",
                  active
                    ? "bg-accent-soft text-accent border border-accent/25"
                    : "text-ink-secondary hover:bg-surface-subtle hover:text-ink border border-transparent",
                )}
              >
                {item.icon}
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Right utilities: status pills, settings, theme */}
        <div className="flex shrink-0 items-center gap-1.5">
          <div className="hidden xl:flex items-center gap-1.5">
            <Badge
              tone={health?.status === "ok" ? "success" : "warning"}
              dot
              title="Status da API FastAPI"
            >
              API
            </Badge>
            <Badge
              tone={
                jasperUp === true
                  ? "success"
                  : jasperUp === false
                    ? "danger"
                    : "neutral"
              }
              dot
              title="Status do Jasper Daemon JVM"
            >
              JVM
            </Badge>
          </div>

          {activeProject && onToggleChat && (
            <Button
              variant={chatOpen ? "primary" : "outline"}
              size="sm"
              onClick={onToggleChat}
              icon={<Bot className="h-3.5 w-3.5" />}
              aria-label="Abrir chat do agente"
              aria-expanded={chatOpen}
            >
              <span className="hidden sm:inline">Chat IA</span>
            </Button>
          )}

          <Button
            variant={activeSection === "settings" ? "primary" : "ghost"}
            size="sm"
            onClick={() => onNavigate("settings")}
            icon={<Settings className="h-3.5 w-3.5" />}
            aria-label="Configurações"
          >
            <span className="hidden xl:inline">Configurações</span>
          </Button>

          <Button
            variant="ghost"
            size="icon"
            onClick={onToggleTheme}
            aria-label={
              theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"
            }
            title={theme === "dark" ? "Alternar para tema claro" : "Alternar para tema escuro"}
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
          </Button>
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}
