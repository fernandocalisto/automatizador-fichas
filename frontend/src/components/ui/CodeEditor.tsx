import { lazy, Suspense, useEffect, useState } from "react";
import { cn } from "@/lib/cn";

const MonacoEditorLazy = lazy(() =>
  import("@monaco-editor/react").then((mod) => ({ default: mod.default })),
);

export interface CodeEditorProps {
  value: string;
  onChange?: (next: string) => void;
  language: "json" | "sql" | "xml" | "plaintext";
  readOnly?: boolean;
  height?: string;
  theme?: "light" | "dark";
  className?: string;
  ariaLabel?: string;
  revealLine?: number | null;
}

function isJsdomEnvironment(): boolean {
  return (
    typeof navigator !== "undefined" &&
    navigator.userAgent.toLowerCase().includes("jsdom")
  );
}

export function CodeEditor({
  value,
  onChange,
  language,
  readOnly = false,
  height = "100%",
  theme,
  className,
  ariaLabel,
  revealLine,
}: CodeEditorProps) {
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(() => {
    if (theme) return theme;
    if (typeof document !== "undefined") {
      return document.documentElement.getAttribute("data-theme") === "dark"
        ? "dark"
        : "light";
    }
    return "light";
  });

  useEffect(() => {
    if (theme) {
      setResolvedTheme(theme);
      return;
    }
    if (typeof document === "undefined") return;
    const sync = () => {
      setResolvedTheme(
        document.documentElement.getAttribute("data-theme") === "dark"
          ? "dark"
          : "light",
      );
    };
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => obs.disconnect();
  }, [theme]);

  if (isJsdomEnvironment()) {
    return (
      <textarea
        aria-label={ariaLabel || `Editor ${language.toUpperCase()}`}
        value={value}
        readOnly={readOnly}
        onChange={(e) => onChange?.(e.target.value)}
        className={cn(
          "h-full w-full resize-none border-0 bg-surface p-3 font-mono text-xs text-ink focus:outline-none",
          className,
        )}
      />
    );
  }

  return (
    <div className={cn("h-full w-full min-h-0 overflow-hidden", className)}>
      <Suspense
        fallback={
          <textarea
            aria-label={ariaLabel || `Editor ${language.toUpperCase()}`}
            value={value}
            readOnly={readOnly}
            onChange={(e) => onChange?.(e.target.value)}
            className="h-full w-full resize-none border-0 bg-surface p-3 font-mono text-xs text-ink focus:outline-none"
          />
        }
      >
        <MonacoEditorLazy
          height={height}
          language={language}
          value={value}
          theme={resolvedTheme === "dark" ? "vs-dark" : "light"}
          onChange={(val) => onChange?.(val ?? "")}
          onMount={(editor) => {
            if (revealLine && revealLine > 0) {
              editor.revealLineInCenter(revealLine);
              editor.setPosition({ lineNumber: revealLine, column: 1 });
            }
          }}
          options={{
            readOnly,
            minimap: { enabled: false },
            fontSize: 12.5,
            fontFamily: '"JetBrains Mono", Consolas, monospace',
            lineNumbers: "on",
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            wordWrap: "on",
            padding: { top: 10, bottom: 10 },
          }}
        />
      </Suspense>
    </div>
  );
}
