import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface TabOption<T extends string = string> {
  id: T;
  label: string;
  icon?: ReactNode;
  badge?: string | number;
  disabled?: boolean;
}

export interface TabsProps<T extends string = string> {
  options: TabOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

export function Tabs<T extends string = string>({
  options,
  value,
  onChange,
  className,
}: TabsProps<T>) {
  return (
    <div
      role="tablist"
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md border border-border bg-surface-subtle p-0.5",
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.id === value;
        return (
          <button
            key={opt.id}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={opt.disabled}
            onClick={() => onChange(opt.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors cursor-pointer",
              "disabled:opacity-40 disabled:cursor-not-allowed",
              active
                ? "bg-surface text-ink shadow-xs"
                : "text-ink-muted hover:text-ink",
            )}
          >
            {opt.icon}
            <span>{opt.label}</span>
            {opt.badge !== undefined && (
              <span
                className={cn(
                  "rounded px-1.5 py-0.2 text-[10px] font-semibold tabular-nums",
                  active
                    ? "bg-accent-soft text-accent"
                    : "bg-border/60 text-ink-secondary",
                )}
              >
                {opt.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
