import type { ChatPhase, ProjectRead, StudioSection } from "@/types/studio";

export interface ProjectsDashboardProps {
  projects: ProjectRead[];
  loading: boolean;
  onRefreshProjects: () => Promise<void>;
  onSelectProject: (project: ProjectRead, nextSection?: StudioSection) => void;
  onDeleteProject: (projectId: string) => Promise<void>;
}

export interface ProjectOverviewProps {
  project: ProjectRead;
  onProjectUpdated: (project: ProjectRead) => void;
  onNavigateSection: (section: StudioSection) => void;
  artifactSyncTick?: number;
}

export interface FormBuilderViewProps {
  project: ProjectRead;
  onProjectUpdated: (project: ProjectRead) => void;
  onNavigateSection: (section: StudioSection) => void;
  artifactSyncTick?: number;
}

export interface SqlDbViewProps {
  project: ProjectRead;
  onProjectUpdated: (project: ProjectRead) => void;
  onNavigateSection: (section: StudioSection) => void;
  artifactSyncTick?: number;
}

export interface JasperStudioViewProps {
  project: ProjectRead;
  onProjectUpdated: (project: ProjectRead) => void;
  onNavigateSection: (section: StudioSection) => void;
  onOpenAgentChat?: (phase?: ChatPhase) => void;
  artifactSyncTick?: number;
}

export type SettingsTabId =
  | "db_profiles"
  | "default_credentials"
  | "sftp_profiles"
  | "jasperserver_profiles"
  | "subreports"
  | "harnesses"
  | "preferences";

export interface SettingsViewProps {
  onClose?: () => void;
  initialTab?: SettingsTabId;
}
