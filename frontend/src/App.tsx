import { useCallback, useEffect, useState } from "react";
import { StudioShell } from "@/components/layout/StudioShell";
import { ToastProvider, useToast } from "@/components/ui";
import { AgentChatDrawer } from "@/features/agent-chat";
import { FormBuilderView } from "@/features/form-builder";
import { JasperStudioView } from "@/features/jasper-studio";
import {
  ProjectOverviewView,
  ProjectsDashboardView,
} from "@/features/projects";
import { SettingsView } from "@/features/settings";
import { SqlDbView } from "@/features/sql-db";
import { useTheme } from "@/hooks/useTheme";
import { api } from "@/lib/api";
import type {
  ChatPhase,
  HealthResponse,
  ProjectRead,
  StudioSection,
} from "@/types/studio";

const VALID_SECTIONS = new Set<StudioSection>([
  "projects",
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
  if (section && section !== "projects") params.set("section", section);
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
    initialNav.section ?? "projects",
  );
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
        if (activeSection === "projects" || activeSection === "settings") {
          setActiveSection(stageToDefaultSection(target));
        }
      }
    },
    [projects, activeSection],
  );

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
    if (activeSection === "settings") {
      return <SettingsView onClose={() => setActiveSection(activeProject ? "workspace" : "projects")} />;
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
      case "jasper_studio":
        return (
          <JasperStudioView
            project={activeProject}
            onProjectUpdated={handleProjectUpdated}
            onNavigateSection={setActiveSection}
            artifactSyncTick={artifactSyncTick}
            onOpenAgentChat={(phase) => {
              setChatPhaseOverride(phase ?? "jrxml");
              setChatOpen(true);
            }}
          />
        );
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
    >
      {renderBody()}
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
