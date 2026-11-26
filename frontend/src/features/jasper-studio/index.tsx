import { EmptyState } from "@/components/ui";
import type { JasperStudioViewProps } from "@/types/feature-props";

export function JasperStudioView({ project }: JasperStudioViewProps) {
  return (
    <div className="p-6">
      <EmptyState
        title={`Jasper Studio — ${project.name}`}
        description="Módulo JasperStudioView em implementação."
      />
    </div>
  );
}
