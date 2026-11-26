import { CheckCircle2, MessageSquarePlus, ShieldAlert } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { ChatPhase } from "@/types/studio";

export interface GateApprovalBannerProps {
  phase: ChatPhase;
  message?: string;
  authorizing: boolean;
  disabled?: boolean;
  onAuthorize: () => void;
  onRequestAdjustments: () => void;
}

export function GateApprovalBanner({
  phase,
  message,
  authorizing,
  disabled = false,
  onAuthorize,
  onRequestAdjustments,
}: GateApprovalBannerProps) {
  const isExtraction = phase === "extraction";
  const title = isExtraction
    ? "Aguardando aprovação do Gate 1 (Extração JSON)"
    : "Aguardando aprovação do Gate 3 (Layout JRXML)";
  const defaultBody = isExtraction
    ? "Revise o mapeamento e as dúvidas apresentadas pelo agente. Ao autorizar, o agente gravará o JSON clínico diretamente no workspace."
    : "Revise o planejamento visual e as dúvidas do layout. Ao autorizar, o agente gravará o arquivo .jrxml diretamente no workspace.";

  return (
    <div
      role="region"
      aria-label="Aprovação rápida do Gate"
      data-testid="gate-approval-banner"
      className="border-t border-warning/40 bg-warning-soft/70 px-3 py-2.5 text-xs"
    >
      <div className="flex items-start gap-2">
        <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-semibold text-ink">{title}</span>
            <Badge tone="warning" className="py-0 text-[10px]">
              Gate 1 → Gate 2
            </Badge>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-ink-secondary">
            {message?.trim() || defaultBody}
          </p>
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <Button
              variant="primary"
              size="xs"
              loading={authorizing}
              disabled={disabled || authorizing}
              icon={<CheckCircle2 className="h-3.5 w-3.5" />}
              onClick={onAuthorize}
            >
              Autorizar e gerar artefato (Autorizado)
            </Button>
            <Button
              variant="outline"
              size="xs"
              disabled={disabled || authorizing}
              icon={<MessageSquarePlus className="h-3.5 w-3.5" />}
              onClick={onRequestAdjustments}
            >
              Pedir ajustes
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
