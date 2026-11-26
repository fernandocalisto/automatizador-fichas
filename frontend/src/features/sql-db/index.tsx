import { EmptyState } from "@/components/ui";
import type { SqlDbViewProps } from "@/types/feature-props";

export function SqlDbView({ project }: SqlDbViewProps) {
  return (
    <div className="p-6">
      <EmptyState
        title={`SQL & Banco — ${project.name}`}
        description="Módulo SqlDbView em implementação."
      />
    </div>
  );
}
