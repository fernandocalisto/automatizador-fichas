import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "outline"
  | "ghost"
  | "danger"
  | "blueprint";
export type ButtonSize = "xs" | "sm" | "md" | "lg" | "icon";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-accent-ink border border-accent hover:bg-accent-hover shadow-xs",
  blueprint:
    "bg-blueprint text-white border border-blueprint hover:opacity-90 shadow-xs",
  secondary:
    "bg-surface-subtle text-ink border border-border hover:bg-border/60",
  outline:
    "bg-surface text-ink border border-border hover:border-border-strong hover:bg-surface-subtle/60",
  ghost: "bg-transparent text-ink-secondary hover:text-ink hover:bg-surface-subtle",
  danger:
    "bg-danger text-white border border-danger hover:opacity-90 shadow-xs",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  xs: "h-7 px-2 text-xs gap-1 rounded",
  sm: "h-8 px-2.5 text-xs gap-1.5 rounded-md",
  md: "h-9 px-3.5 text-sm gap-2 rounded-md",
  lg: "h-10 px-4 text-sm gap-2 rounded-md",
  icon: "h-8 w-8 p-0 rounded-md justify-center",
};

export function Button({
  variant = "outline",
  size = "sm",
  loading = false,
  icon,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center font-medium transition-colors cursor-pointer select-none",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        VARIANT_CLASSES[variant],
        SIZE_CLASSES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span
          aria-hidden="true"
          className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      ) : (
        icon
      )}
      {children}
    </button>
  );
}
