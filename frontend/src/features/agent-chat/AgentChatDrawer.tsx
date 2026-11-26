import { useEffect } from "react";
import { cn } from "@/lib/cn";
import { AgentChatPanel, type AgentChatPanelProps } from "./AgentChatPanel";

export interface AgentChatDrawerProps
  extends Omit<AgentChatPanelProps, "onClose"> {
  open: boolean;
  onClose: () => void;
}

/**
 * Slide-over lateral responsivo acoplável à direita do Studio sem cobrir o header (`h-12`).
 */
export function AgentChatDrawer({
  open,
  onClose,
  className,
  ...panelProps
}: AgentChatDrawerProps) {
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <aside
      role="complementary"
      aria-label="Drawer de Chat do Agente"
      data-testid="agent-chat-drawer"
      className={cn(
        "fixed top-12 right-0 bottom-0 z-40 flex w-[440px] max-w-[95vw] flex-col",
        "border-l border-border-strong bg-surface shadow-2xl",
        className,
      )}
    >
      <AgentChatPanel {...panelProps} onClose={onClose} className="h-full" />
    </aside>
  );
}
