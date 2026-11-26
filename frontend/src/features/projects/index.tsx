import { EmptyState } from "@/components/ui";
import type {
  ProjectOverviewProps,
  ProjectsDashboardProps,
} from "@/types/feature-props";

export function ProjectsDashboardView({ projects }: ProjectsDashboardProps) {
  return (
    <div className="p-6">
      <EmptyState
        title="Projetos"
        description={`Carregados ${projects.length} projetos. Módulo ProjectsDashboardView em implementação.`}
      />
    </div>
  );
}

export function ProjectOverviewView({ project }: ProjectOverviewProps) {
  return (
    <div className="p-6">
      <EmptyState
        title={project.name}
        description="Módulo ProjectOverviewView em implementação."
      />
    </div>
  );
}
