import { useCallback, useEffect, useState } from "react";
import { CloudUpload, UploadCloud } from "lucide-react";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { StudioShell } from "@/components/layout/StudioShell";
import { Button, ToastProvider, useToast } from "@/components/ui";
import { AgentChatDrawer } from "@/features/agent-chat";
import { ClientsView } from "@/features/clients";
import { FormBuilderView } from "@/features/form-builder";
import { HomeView } from "@/features/home";
import { JasperStudioView } from "@/features/jasper-studio";
import { JasperServerDeployModal } from "@/features/jasperserver";
import {
  CreateProjectDialog,
  ProjectOverviewView,
  ProjectsDashboardView,
} from "@/features/projects";
import { SettingsView } from "@/features/settings";
import { SftpDeployModal } from "@/features/sftp";
import { SqlDbView } from "@/features/sql-db";
import { useTheme } from "@/hooks/useTheme";
import { api } from "@/lib/api";
import type { SettingsTabId } from "@/types/feature-props";
import type {
  ChatPhase,
  EntryMode,
  HealthResponse,
  ProjectRead,
  StudioSection,
} from "@/types/studio";

const VALID_SECTIONS = new Set<StudioSection>([
  "home",
  "projects",
  "clients",
  "workspace",
  "form_builder",
  "sql_db",
  "jasper_studio",
  "settings",
]);

function readHashNavigation(): {
  projectId: string | null;
  section: StudioSection | null;
} {
  if (typeof window === "undefined") {
    return { projectId: null, section: null };
  }
  const raw = window.location.hash.replace(/^#\/?/, "");
  if (!raw) {
    return { projectId: null, section: null };
  }
  const params = new URLSearchParams(raw);
  const projectId = params.get("project") || null;
  const rawSection = params.get("section") as StudioSection | null;
  const section =
    rawSection && VALID_SECTIONS.has(rawSection) ? rawSection : null;
  return { projectId, section };
}

function writeHashNavigation(
  projectId: string | null,
  section: StudioSection,
): void {
  if (typeof window === "undefined") return;
  const params = new URLSearchParams();
  if (projectId) params.set("project", projectId);
  if (section && section !== "home") params.set("section", section);
  const encoded = params.toString();
  const nextHash = encoded ? `#${encoded}` : "";
  if (window.location.hash !== nextHash) {
    window.history.replaceState(
      null,
      "",
      nextHash || `${window.location.pathname}${window.location.search}`,
    );
  }
}

function stageToDefaultSection(project: ProjectRead): StudioSection {
  if (project.project_kind === "free_report") {
    return project.current_stage === "sql_db" ? "sql_db" : "jasper_studio";
  }
  switch (project.current_stage) {
    case "form_builder":
      return "form_builder";
    case "sql_db":
      return "sql_db";
    case "jrxml_design":
    case "completed":
      return "jasper_studio";
    default:
      return "workspace";
  }
}

interface QuickCreateState {
  open: boolean;
  initialEntryMode?: EntryMode;
  initialName?: string;
  initialDbProfileId?: string | null;
  initialClientSystemId?: string | null;
  initialSftpProfileId?: string;
  initialJasperProfileId?: string;
}

function StudioAppInner() {
  const { theme, toggleTheme } = useTheme();
  const { pushToast } = useToast();

  const initialNav = readHashNavigation();
  const [projects, setProjects] = useState<ProjectRead[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(
    initialNav.projectId,
  );
  const [activeSection, setActiveSection] = useState<StudioSection>(
    initialNav.section ?? "home",
  );
  const [settingsInitialTab, setSettingsInitialTab] = useState<
    SettingsTabId | undefined
  >(undefined);
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [quickCreate, setQuickCreate] = useState<QuickCreateState>({
    open: false,
  });
  const [sftpDeployOpen, setSftpDeployOpen] = useState(false);
  const [jasperDeployOpen, setJasperDeployOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatPhaseOverride, setChatPhaseOverride] = useState<ChatPhase | null>(
    null,
  );
  const [artifactSyncTick, setArtifactSyncTick] = useState(0);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [jasperUp, setJasperUp] = useState<boolean | null>(null);

  const activeProject =
    projects.find((p) => p.id === activeProjectId) ?? null;

  useEffect(() => {
    writeHashNavigation(activeProjectId, activeSection);
  }, [activeProjectId, activeSection]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const refreshProjects = useCallback(async () => {
    setLoadingProjects(true);
    try {
      const list = await api.listProjects();
      setProjects(list);
      setActiveProjectId((curr) =>
        curr && list.some((p) => p.id === curr) ? curr : null,
      );
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao carregar projetos",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoadingProjects(false);
    }
  }, [pushToast]);

  useEffect(() => {
    void refreshProjects();
    api
      .getHealth()
      .then((h) => setHealth(h))
      .catch(() => setHealth(null));
    api
      .getJasperHealth()
      .then((res) => setJasperUp(res?.status === "UP" || res?.ok === true))
      .catch(() => setJasperUp(false));
  }, [refreshProjects]);

  const handleSelectProject = useCallback(
    (project: ProjectRead, nextSection?: StudioSection) => {
      setProjects((prev) =>
        prev.some((p) => p.id === project.id)
          ? prev.map((p) => (p.id === project.id ? project : p))
          : [project, ...prev],
      );
      setActiveProjectId(project.id);
      setActiveSection(nextSection ?? stageToDefaultSection(project));
    },
    [],
  );

  const handleSelectProjectId = useCallback(
    (projectId: string) => {
      const target = projects.find((p) => p.id === projectId);
      if (target) {
        setActiveProjectId(target.id);
        if (
          activeSection === "home" ||
          activeSection === "projects" ||
          activeSection === "clients" ||
          activeSection === "settings"
        ) {
          setActiveSection(stageToDefaultSection(target));
        }
      }
    },
    [projects, activeSection],
  );

  const handleExitProject = useCallback(() => {
    setActiveProjectId(null);
    setChatOpen(false);
    setChatPhaseOverride(null);
    setActiveSection("home");
  }, []);

  const handleOpenClientById = useCallback((clientId: string) => {
    setSelectedClientId(clientId);
    setActiveSection("clients");
  }, []);

  const handleProjectUpdated = useCallback((updated: ProjectRead) => {
    setProjects((prev) =>
      prev.map((p) => (p.id === updated.id ? updated : p)),
    );
  }, []);

  const handleDeleteProject = useCallback(
    async (projectId: string) => {
      await api.deleteProject(projectId);
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
      if (activeProjectId === projectId) {
        setActiveProjectId(null);
        setActiveSection("projects");
      }
      pushToast({ tone: "success", title: "Projeto excluído" });
    },
    [activeProjectId, pushToast],
  );

  const renderBody = () => {
    if (activeSection === "home") {
      return (
        <HomeView
          projects={projects}
          onSelectProject={handleSelectProject}
          onNavigateSection={(section) => {
            if (section !== "settings") {
              setSettingsInitialTab(undefined);
            }
            setActiveSection(section);
          }}
          onOpenCreateDialog={(mode) => {
            setQuickCreate({
              open: true,
              initialEntryMode: mode,
            });
          }}
          onOpenClientById={handleOpenClientById}
          onOpenCommandPalette={() => setCommandPaletteOpen(true)}
        />
      );
    }

    if (activeSection === "settings") {
      return (
        <SettingsView
          initialTab={settingsInitialTab}
          onClose={() => {
            setSettingsInitialTab(undefined);
            setActiveSection(
              activeProject ? stageToDefaultSection(activeProject) : "home",
            );
          }}
        />
      );
    }

    if (activeSection === "clients") {
      return (
        <ClientsView
          initialSelectedClientId={selectedClientId}
          onProjectImported={(imported) => handleSelectProject(imported)}
          onCreateFreeReport={({ clientSystemId, dbProfileId, defaultName }) => {
            setQuickCreate({
              open: true,
              initialEntryMode: "blank_report",
              initialName: defaultName,
              initialDbProfileId: dbProfileId ?? null,
              initialClientSystemId: clientSystemId,
            });
          }}
          onOpenSftpImport={(sftpProfileId, dbProfileId) => {
            setQuickCreate({
              open: true,
              initialEntryMode: "sftp_import",
              initialSftpProfileId: sftpProfileId,
              initialDbProfileId: dbProfileId ?? null,
            });
          }}
          onOpenJasperImport={(jasperProfileId, dbProfileId) => {
            setQuickCreate({
              open: true,
              initialEntryMode: "jasperserver_import",
              initialJasperProfileId: jasperProfileId,
              initialDbProfileId: dbProfileId ?? null,
            });
          }}
          onOpenSettings={() => {
            setSettingsInitialTab("default_credentials");
            setActiveSection("settings");
          }}
        />
      );
    }

    if (activeSection === "projects" || !activeProject) {
      return (
        <ProjectsDashboardView
          projects={projects}
          loading={loadingProjects}
          onRefreshProjects={refreshProjects}
          onSelectProject={handleSelectProject}
          onDeleteProject={handleDeleteProject}
        />
      );
    }

    switch (activeSection) {
      case "workspace":
        return (
          <ProjectOverviewView
            project={activeProject}
            onProjectUpdated={handleProjectUpdated}
            onNavigateSection={setActiveSection}
            artifactSyncTick={artifactSyncTick}
          />
        );
      case "form_builder":
        return (
          <FormBuilderView
            project={activeProject}
            onProjectUpdated={handleProjectUpdated}
            onNavigateSection={setActiveSection}
            artifactSyncTick={artifactSyncTick}
          />
        );
      case "sql_db":
        return (
          <SqlDbView
            project={activeProject}
            onProjectUpdated={handleProjectUpdated}
            onNavigateSection={setActiveSection}
            artifactSyncTick={artifactSyncTick}
          />
        );
      case "jasper_studio": {
        const originProvider =
          typeof activeProject.source_origin?.provider === "string"
            ? activeProject.source_origin.provider
            : null;
        const isJasperOrigin =
          originProvider === "jasperserver" ||
          activeProject.entry_mode === "jasperserver_import";
        const isSftpOrigin =
          originProvider === "sftp" ||
          activeProject.entry_mode === "sftp_import";

        const publishActions = isJasperOrigin ? (
          <>
            <Button
              variant="primary"
              size="xs"
              icon={<CloudUpload className="h-3.5 w-3.5" />}
              onClick={() => setJasperDeployOpen(true)}
            >
              Publicar no JasperServer
            </Button>
            <Button
              variant="ghost"
              size="xs"
              icon={<UploadCloud className="h-3.5 w-3.5" />}
              onClick={() => setSftpDeployOpen(true)}
              title="Publicar via SFTP"
            >
              SFTP
            </Button>
          </>
        ) : isSftpOrigin ? (
          <>
            <Button
              variant="primary"
              size="xs"
              icon={<UploadCloud className="h-3.5 w-3.5" />}
              onClick={() => setSftpDeployOpen(true)}
            >
              Publicar no SFTP
            </Button>
            <Button
              variant="ghost"
              size="xs"
              icon={<CloudUpload className="h-3.5 w-3.5" />}
              onClick={() => setJasperDeployOpen(true)}
              title="Publicar no JasperReports Server"
            >
              JasperServer
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="outline"
              size="xs"
              icon={<UploadCloud className="h-3.5 w-3.5" />}
              onClick={() => setSftpDeployOpen(true)}
            >
              Publicar SFTP
            </Button>
            <Button
              variant="outline"
              size="xs"
              icon={<CloudUpload className="h-3.5 w-3.5" />}
              onClick={() => setJasperDeployOpen(true)}
            >
              Publicar JasperServer
            </Button>
          </>
        );

        return (
          <>
            <JasperStudioView
              project={activeProject}
              onProjectUpdated={handleProjectUpdated}
              onNavigateSection={setActiveSection}
              artifactSyncTick={artifactSyncTick}
              onOpenAgentChat={(phase) => {
                setChatPhaseOverride(phase ?? "jrxml");
                setChatOpen(true);
              }}
              headerExtraActions={publishActions}
            />
            <SftpDeployModal
              open={sftpDeployOpen}
              onClose={() => setSftpDeployOpen(false)}
              project={activeProject}
            />
            <JasperServerDeployModal
              open={jasperDeployOpen}
              onClose={() => setJasperDeployOpen(false)}
              project={activeProject}
            />
          </>
        );
      }
      default:
        return null;
    }
  };

  const chatPhase: ChatPhase =
    chatPhaseOverride ??
    (activeSection === "jasper_studio" ? "jrxml" : "extraction");

  return (
    <StudioShell
      activeSection={activeSection}
      onNavigate={(section) => {
        setChatPhaseOverride(null);
        if (section !== "settings") {
          setSettingsInitialTab(undefined);
        }
        setActiveSection(section);
      }}
      projects={projects}
      activeProject={activeProject}
      onSelectProjectId={handleSelectProjectId}
      theme={theme}
      onToggleTheme={toggleTheme}
      health={health}
      jasperUp={jasperUp}
      chatOpen={chatOpen}
      onToggleChat={() => setChatOpen((prev) => !prev)}
      onOpenCommandPalette={() => setCommandPaletteOpen(true)}
      onExitProject={handleExitProject}
    >
      {renderBody()}
      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        projects={projects}
        onSelectProject={(project) => {
          setCommandPaletteOpen(false);
          handleSelectProject(project);
        }}
        onSelectClient={(clientId) => {
          setCommandPaletteOpen(false);
          handleOpenClientById(clientId);
        }}
        onOpenSettingsTab={(tab) => {
          setCommandPaletteOpen(false);
          setSettingsInitialTab(tab);
          setActiveSection("settings");
        }}
      />
      <CreateProjectDialog
        open={quickCreate.open}
        onClose={() => setQuickCreate({ open: false })}
        onCreated={(created) => {
          setQuickCreate({ open: false });
          handleSelectProject(created);
        }}
        initialEntryMode={quickCreate.initialEntryMode}
        initialName={quickCreate.initialName}
        initialDbProfileId={quickCreate.initialDbProfileId}
        initialClientSystemId={quickCreate.initialClientSystemId}
        initialSftpProfileId={quickCreate.initialSftpProfileId}
        initialJasperProfileId={quickCreate.initialJasperProfileId}
      />
      {activeProject && (
        <AgentChatDrawer
          open={chatOpen}
          onClose={() => setChatOpen(false)}
          project={activeProject}
          initialPhase={chatPhase}
          onProjectUpdated={handleProjectUpdated}
          onNavigateSection={setActiveSection}
          onArtifactSynced={() => setArtifactSyncTick((prev) => prev + 1)}
        />
      )}
    </StudioShell>
  );
}

export function App() {
  return (
    <ToastProvider>
      <StudioAppInner />
    </ToastProvider>
  );
}

export default App;
