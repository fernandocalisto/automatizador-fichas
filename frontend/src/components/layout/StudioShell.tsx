import { useEffect, useRef, type ReactNode } from "react";
import {
  ArrowLeft,
  Building2,
  Database,
  FileCode2,
  FolderKanban,
  Home,
  LayoutList,
  Moon,
  Search,
  Settings,
  Sparkles,
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
  onOpenCommandPalette?: () => void;
  onExitProject?: () => void;
  children: ReactNode;
}

interface NavItem {
  id: StudioSection;
  label: string;
  icon: ReactNode;
}

const GLOBAL_NAV: NavItem[] = [
  {
    id: "home",
    label: "Início",
    icon: <Home className="h-3.5 w-3.5" />,
  },
  {
    id: "clients",
    label: "Clientes",
    icon: <Building2 className="h-3.5 w-3.5" />,
  },
  {
    id: "projects",
    label: "Meus Projetos",
    icon: <FolderKanban className="h-3.5 w-3.5" />,
  },
];

const FREE_REPORT_NAV: NavItem[] = [
  {
    id: "jasper_studio",
    label: "Relatório & Preview",
    icon: <FileCode2 className="h-3.5 w-3.5" />,
  },
  {
    id: "sql_db",
    label: "Banco & SQL",
    icon: <Database className="h-3.5 w-3.5" />,
  },
];

const CLINICAL_FORM_NAV: NavItem[] = [
  {
    id: "workspace",
    label: "1. Resumo & PDF",
    icon: <Workflow className="h-3.5 w-3.5" />,
  },
  {
    id: "form_builder",
    label: "2. Perguntas",
    icon: <LayoutList className="h-3.5 w-3.5" />,
  },
  {
    id: "sql_db",
    label: "3. SQL & Banco",
    icon: <Database className="h-3.5 w-3.5" />,
  },
  {
    id: "jasper_studio",
    label: "4. Layout & PDF",
    icon: <FileCode2 className="h-3.5 w-3.5" />,
  },
];

const WORKSPACE_SECTIONS = new Set<StudioSection>([
  "workspace",
  "form_builder",
  "sql_db",
  "jasper_studio",
]);

export function StudioShell({
  activeSection,
  onNavigate,
  activeProject,
  onSelectProjectId,
  theme,
  onToggleTheme,
  health,
  jasperUp,
  chatOpen = false,
  onToggleChat,
  onOpenCommandPalette,
  onExitProject,
  children,
}: StudioShellProps) {
  const isProjectMode = Boolean(
    activeProject && WORKSPACE_SECTIONS.has(activeSection),
  );

  const isFreeReport = activeProject?.project_kind === "free_report";
  const projectTabs = isFreeReport ? FREE_REPORT_NAV : CLINICAL_FORM_NAV;
  const projectNavRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!isProjectMode) return;
    const activeTabEl = projectNavRef.current?.querySelector<HTMLElement>(
      '[aria-current="page"]',
    );
    activeTabEl?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [activeSection, activeProject?.id, isProjectMode]);

  const handleBackToHome = () => {
    if (onExitProject) {
      onExitProject();
    } else {
      onNavigate("home");
    }
  };

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-canvas text-ink">
      <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-b border-border bg-surface px-3">
        {isProjectMode && activeProject ? (
          <>
            {/* Project Mode: Left (Back + Project Name + Origin Badge) */}
            <div className="flex min-w-0 items-center gap-1.5">
              <Button
                variant="ghost"
                size="xs"
                onClick={handleBackToHome}
                icon={<ArrowLeft className="h-3.5 w-3.5" />}
                className="shrink-0"
              >
                Início
              </Button>

              <div className="h-4 w-px shrink-0 bg-border" />

              <div className="flex min-w-0 items-center gap-1.5">
                <span
                  title={activeProject.name}
                  className="max-w-[130px] truncate text-xs font-semibold text-ink sm:max-w-[160px] lg:max-w-[180px] 2xl:max-w-[260px]"
                >
                  {activeProject.name}
                </span>

                <Badge
                  tone={isFreeReport ? "blueprint" : "accent"}
                  className="hidden lg:inline-flex shrink-0 text-[10px] py-0"
                >
                  {isFreeReport ? "Relatório" : "Ficha Clínica"}
                </Badge>

                {activeProject.template_db_id !== null &&
                  activeProject.template_db_id !== undefined && (
                    <Badge
                      tone="neutral"
                      className="hidden xl:inline-flex shrink-0 tabular-nums text-[10px] py-0"
                    >
                      ID #{activeProject.template_db_id}
                    </Badge>
                  )}
              </div>
            </div>

            {/* Project Mode: Center (Context-only tabs) */}
            <nav
              ref={projectNavRef}
              aria-label="Etapas do Projeto"
              className="flex min-w-0 items-center gap-0.5 overflow-x-auto"
            >
              {projectTabs.map((item) => {
                const active = activeSection === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => onNavigate(item.id)}
                    className={cn(
                      "inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-[11px] xl:text-xs font-medium transition-colors whitespace-nowrap cursor-pointer",
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

            {/* Project Mode: Right (AI Assistant + Settings + Theme) */}
            <div className="flex shrink-0 items-center gap-1">
              {onOpenCommandPalette && (
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={onOpenCommandPalette}
                  aria-label="Busca global (Ctrl+K)"
                  title="Busca global (Ctrl+K)"
                >
                  <Search className="h-3.5 w-3.5" />
                </Button>
              )}

              {onToggleChat && (
                <Button
                  variant={chatOpen ? "primary" : "outline"}
                  size="sm"
                  onClick={onToggleChat}
                  icon={<Sparkles className="h-3.5 w-3.5" />}
                  aria-label="Assistente IA"
                  aria-expanded={chatOpen}
                  className={cn(
                    !chatOpen &&
                      "border-accent/40 bg-accent-soft/50 text-accent hover:bg-accent-soft hover:border-accent/60",
                  )}
                >
                  <span className="hidden sm:inline">Assistente IA</span>
                </Button>
              )}

              <Button
                variant="ghost"
                size="sm"
                onClick={() => onNavigate("settings")}
                icon={<Settings className="h-3.5 w-3.5" />}
                aria-label="Configurações"
                title="Configurações"
              >
                <span className="hidden 2xl:inline">Configurações</span>
              </Button>

              <Button
                variant="ghost"
                size="icon"
                onClick={onToggleTheme}
                aria-label={
                  theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"
                }
                title={
                  theme === "dark"
                    ? "Alternar para tema claro"
                    : "Alternar para tema escuro"
                }
              >
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </Button>
            </div>
          </>
        ) : (
          <>
            {/* Global Mode: Left (Brand + 3 Clean Nav Items) */}
            <div className="flex min-w-0 items-center gap-3">
              <button
                type="button"
                onClick={() => onNavigate("home")}
                className="flex shrink-0 items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-surface-subtle transition-colors cursor-pointer"
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-accent text-xs font-bold tracking-tight text-accent-ink">
                  SF
                </span>
                <div className="hidden sm:block leading-tight whitespace-nowrap">
                  <div className="text-xs font-semibold tracking-tight text-ink">
                    Salutem Ficha Studio
                  </div>
                  <div className="text-[10px] text-ink-muted tabular-nums">
                    {health?.version ? `v${health.version}` : "v1.1.1"}
                  </div>
                </div>
              </button>

              <nav
                aria-label="Navegação Principal"
                className="flex min-w-0 items-center gap-0.5 overflow-x-auto border-l border-border pl-2.5"
              >
                {GLOBAL_NAV.map((item) => {
                  const active = activeSection === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      aria-current={active ? "page" : undefined}
                      onClick={() => onNavigate(item.id)}
                      className={cn(
                        "inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors whitespace-nowrap cursor-pointer",
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

              {activeProject && (
                <button
                  type="button"
                  onClick={() => onSelectProjectId(activeProject.id)}
                  title={`Voltar ao trabalho aberto: ${activeProject.name}`}
                  className="hidden xl:inline-flex max-w-[200px] items-center gap-1.5 rounded-md border border-accent/25 bg-accent-soft/40 px-2 py-1 text-[11px] font-medium text-accent hover:bg-accent-soft transition-colors cursor-pointer"
                >
                  <FileCode2 className="h-3 w-3 shrink-0" />
                  <span className="truncate">{activeProject.name}</span>
                </button>
              )}
            </div>

            {/* Global Mode: Center/Right (Search Ctrl+K + Status + Settings + Theme) */}
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                type="button"
                onClick={() => onOpenCommandPalette?.()}
                aria-label="Buscar clientes, bancos, relatórios (Ctrl+K)"
                className="hidden md:inline-flex h-8 w-48 lg:w-56 xl:w-68 items-center justify-between gap-2 rounded-md border border-border bg-surface-subtle/70 px-2.5 text-xs text-ink-muted transition-colors hover:border-border-strong hover:bg-surface hover:text-ink cursor-pointer"
              >
                <span className="inline-flex items-center gap-1.5 truncate">
                  <Search className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">
                    Buscar clientes, bancos, relatórios...
                  </span>
                </span>
                <kbd className="shrink-0 rounded border border-border bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-secondary">
                  Ctrl+K
                </kbd>
              </button>

              <Button
                variant="ghost"
                size="icon"
                onClick={() => onOpenCommandPalette?.()}
                aria-label="Busca rápida"
                title="Busca rápida (Ctrl+K)"
                className="md:hidden"
              >
                <Search className="h-4 w-4" />
              </Button>

              <div className="hidden lg:flex items-center gap-1 border-l border-border pl-2">
                <Badge
                  tone={health?.status === "ok" ? "success" : "warning"}
                  dot
                  title="Status da API FastAPI"
                  className="text-[10px] py-0 px-1.5"
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
                  className="text-[10px] py-0 px-1.5"
                >
                  JVM
                </Badge>
              </div>

              <Button
                variant={activeSection === "settings" ? "primary" : "ghost"}
                size="sm"
                onClick={() => onNavigate("settings")}
                icon={<Settings className="h-3.5 w-3.5" />}
                aria-label="Configurações"
              >
                <span className="hidden lg:inline">Configurações</span>
              </Button>

              <Button
                variant="ghost"
                size="icon"
                onClick={onToggleTheme}
                aria-label={
                  theme === "dark" ? "Ativar tema claro" : "Ativar tema escuro"
                }
                title={
                  theme === "dark"
                    ? "Alternar para tema claro"
                    : "Alternar para tema escuro"
                }
              >
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </Button>
            </div>
          </>
        )}
      </header>

      <main
        className={cn(
          "min-h-0 flex-1 overflow-hidden transition-[padding] duration-150",
          chatOpen && activeProject && "xl:pr-[440px]",
        )}
      >
        {children}
      </main>
    </div>
  );
}
