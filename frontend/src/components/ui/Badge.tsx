import type { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export type BadgeTone =
  | "neutral"
  | "accent"
  | "blueprint"
  | "success"
  | "warning"
  | "danger";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  dot?: boolean;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-surface-subtle text-ink-secondary border-border",
  accent: "bg-accent-soft text-accent border-accent/25",
  blueprint: "bg-blueprint-soft text-blueprint border-blueprint/25",
  success: "bg-success-soft text-success border-success/25",
  warning: "bg-warning-soft text-warning border-warning/30",
  danger: "bg-danger-soft text-danger border-danger/30",
};

const DOT_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-ink-muted",
  accent: "bg-accent",
  blueprint: "bg-blueprint",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
};

export function Badge({
  tone = "neutral",
  dot = false,
  className,
  children,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-medium border whitespace-nowrap",
        TONE_CLASSES[tone],
        className,
      )}
      {...rest}
    >
      {dot && (
        <span
          aria-hidden="true"
          className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASSES[tone])}
        />
      )}
      {children}
    </span>
  );
}
