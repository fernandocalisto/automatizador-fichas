import { EmptyState } from "@/components/ui";
import type { SettingsViewProps } from "@/types/feature-props";

export function SettingsView(_props: SettingsViewProps) {
  return (
    <div className="p-6">
      <EmptyState
        title="Configurações"
        description="Módulo SettingsView em implementação."
      />
    </div>
  );
}
