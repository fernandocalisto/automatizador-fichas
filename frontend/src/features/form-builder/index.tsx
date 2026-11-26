import { EmptyState } from "@/components/ui";
import type { FormBuilderViewProps } from "@/types/feature-props";

export function FormBuilderView({ project }: FormBuilderViewProps) {
  return (
    <div className="p-6">
      <EmptyState
        title={`Form Builder — ${project.name}`}
        description="Módulo FormBuilderView em implementação."
      />
    </div>
  );
}
