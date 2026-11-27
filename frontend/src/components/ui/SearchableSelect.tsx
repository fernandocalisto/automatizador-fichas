import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { Check, ChevronDown, Search, X } from "lucide-react";
import { cn } from "@/lib/cn";

export interface SearchableSelectOption {
  value: string;
  label: string;
  sublabel?: string;
  badge?: string;
  keywords?: string;
}

export interface SearchableSelectProps {
  id?: string;
  ariaLabel?: string;
  value: string;
  onChange: (value: string) => void;
  options: SearchableSelectOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyLabel?: string;
  allowClear?: boolean;
  clearLabel?: string;
  disabled?: boolean;
  className?: string;
  size?: "sm" | "md";
}

export function SearchableSelect({
  id,
  ariaLabel,
  value,
  onChange,
  options,
  placeholder = "Selecionar...",
  searchPlaceholder = "Buscar...",
  emptyLabel = "Nenhum item encontrado.",
  allowClear = false,
  clearLabel = "Nenhum",
  disabled = false,
  className,
  size = "md",
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);

  const selectedOption = useMemo(
    () => options.find((opt) => opt.value === value) ?? null,
    [options, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((opt) => {
      const hay = `${opt.label} ${opt.sublabel ?? ""} ${opt.badge ?? ""} ${opt.keywords ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [options, query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
    };
  }, [open]);

  const handleSelect = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
    setQuery("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((idx) =>
        filtered.length === 0 ? 0 : (idx + 1) % filtered.length,
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((idx) =>
        filtered.length === 0
          ? 0
          : (idx - 1 + filtered.length) % filtered.length,
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = filtered[activeIndex];
      if (target) {
        handleSelect(target.value);
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <button
        id={id}
        type="button"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => {
          if (!disabled) setOpen((prev) => !prev);
        }}
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface text-left text-ink transition-colors cursor-pointer",
          "hover:border-border-strong focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20",
          "disabled:cursor-not-allowed disabled:opacity-50",
          size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-2.5 text-xs",
        )}
      >
        <span className="min-w-0 flex-1 truncate">
          {selectedOption ? (
            <span className="inline-flex items-center gap-1.5 truncate">
              <span className="truncate font-medium text-ink">
                {selectedOption.label}
              </span>
              {selectedOption.badge && (
                <span className="shrink-0 rounded bg-surface-subtle px-1.5 py-0.5 text-[10px] font-medium text-ink-muted">
                  {selectedOption.badge}
                </span>
              )}
            </span>
          ) : (
            <span className="text-ink-muted">{placeholder}</span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          {allowClear && value && !disabled && (
            <span
              role="button"
              tabIndex={-1}
              aria-label="Limpar seleção"
              onClick={(e) => {
                e.stopPropagation();
                handleSelect("");
              }}
              className="rounded p-0.5 text-ink-muted hover:bg-surface-subtle hover:text-ink"
            >
              <X className="h-3 w-3" />
            </span>
          )}
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 text-ink-muted transition-transform",
              open && "rotate-180",
            )}
          />
        </span>
      </button>

      {open && (
        <div
          role="listbox"
          className="absolute left-0 right-0 z-50 mt-1 overflow-hidden rounded-lg border border-border-strong bg-surface-elevated shadow-xl"
        >
          <div className="flex items-center gap-1.5 border-b border-border bg-surface px-2.5 py-1.5">
            <Search className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={searchPlaceholder}
              className="w-full bg-transparent text-xs text-ink placeholder:text-ink-muted focus:outline-none"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                aria-label="Limpar busca"
                className="rounded p-0.5 text-ink-muted hover:text-ink cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          <div className="max-h-60 overflow-y-auto p-1">
            {allowClear && (
              <button
                type="button"
                role="option"
                aria-selected={!value}
                onClick={() => handleSelect("")}
                className={cn(
                  "flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors cursor-pointer",
                  !value
                    ? "bg-accent-soft text-accent font-medium"
                    : "text-ink-muted hover:bg-surface-subtle hover:text-ink",
                )}
              >
                <span>{clearLabel}</span>
                {!value && <Check className="h-3.5 w-3.5 shrink-0" />}
              </button>
            )}

            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-ink-muted">
                {emptyLabel}
              </div>
            ) : (
              filtered.map((opt, idx) => {
                const selected = opt.value === value;
                const active = idx === activeIndex;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => handleSelect(opt.value)}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-xs transition-colors cursor-pointer",
                      selected
                        ? "bg-accent-soft/80 text-accent"
                        : active
                          ? "bg-surface-subtle text-ink"
                          : "text-ink hover:bg-surface-subtle/70",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate font-medium">
                          {opt.label}
                        </span>
                        {opt.badge && (
                          <span className="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10px] text-ink-muted border border-border">
                            {opt.badge}
                          </span>
                        )}
                      </div>
                      {opt.sublabel && (
                        <p className="truncate font-mono text-[10px] text-ink-muted">
                          {opt.sublabel}
                        </p>
                      )}
                    </div>
                    {selected && (
                      <Check className="h-3.5 w-3.5 shrink-0 text-accent" />
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
