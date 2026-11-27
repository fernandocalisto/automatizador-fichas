import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ChevronDown,
  Cloud,
  Cpu,
  Database,
  FileArchive,
  KeyRound,
  Menu,
  RefreshCw,
  Server,
  Settings,
  Sliders,
  X,
} from "lucide-react";
import { Button, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { SettingsTabId, SettingsViewProps } from "@/types/feature-props";
import type {
  DbProfileRead,
  HarnessStatus,
  SkillInfo,
  SubreportInfo,
} from "@/types/studio";
import { DbProfilesTab } from "./DbProfilesTab";
import { DefaultCredentialsTab } from "./DefaultCredentialsTab";
import { HarnessesSkillsTab } from "./HarnessesSkillsTab";
import { JasperServerProfilesTab } from "./JasperServerProfilesTab";
import { SftpProfilesTab } from "./SftpProfilesTab";
import { StudioPreferencesTab } from "./StudioPreferencesTab";
import { SubreportsTab } from "./SubreportsTab";

interface NavItem {
  id: SettingsTabId;
  label: string;
  subtitle?: string;
  icon: ReactNode;
  badge?: string | number;
}

interface NavGroup {
  id: string;
  title: string;
  items: NavItem[];
}

export function SettingsView({ onClose, initialTab }: SettingsViewProps) {
  const { pushToast } = useToast();

  const [activeTab, setActiveTab] = useState<SettingsTabId>(
    initialTab ?? "db_profiles",
  );
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [loading, setLoading] = useState(true);

  const [profiles, setProfiles] = useState<DbProfileRead[]>([]);
  const [subreports, setSubreports] = useState<SubreportInfo[]>([]);
  const [harnesses, setHarnesses] = useState<HarnessStatus[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [studioSettings, setStudioSettings] = useState<Record<string, unknown>>(
    {},
  );

  useEffect(() => {
    if (initialTab) {
      setActiveTab(initialTab);
    }
  }, [initialTab]);

  const refreshProfiles = useCallback(async () => {
    const data = await api.listDbProfiles();
    setProfiles(Array.isArray(data) ? data : []);
  }, []);

  const refreshSubreports = useCallback(async () => {
    const data = await api.listSubreports();
    setSubreports(Array.isArray(data) ? data : []);
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    try {
      const [dbRes, subRes, harnessRes, skillRes, settingsRes] =
        await Promise.allSettled([
          api.listDbProfiles(),
          api.listSubreports(),
          api.listHarnesses(),
          api.listSkills(),
          api.getSettings(),
        ]);

      if (dbRes.status === "fulfilled") {
        setProfiles(Array.isArray(dbRes.value) ? dbRes.value : []);
      }
      if (subRes.status === "fulfilled") {
        setSubreports(Array.isArray(subRes.value) ? subRes.value : []);
      }
      if (harnessRes.status === "fulfilled") {
        setHarnesses(Array.isArray(harnessRes.value) ? harnessRes.value : []);
      }
      if (skillRes.status === "fulfilled") {
        setSkills(Array.isArray(skillRes.value) ? skillRes.value : []);
      }
      if (
        settingsRes.status === "fulfilled" &&
        settingsRes.value &&
        typeof settingsRes.value === "object" &&
        !Array.isArray(settingsRes.value)
      ) {
        setStudioSettings(settingsRes.value);
      }
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao carregar configurações",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }, [pushToast]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const installedHarnessesCount = harnesses.filter((h) => h.installed).length;

  const navGroups: NavGroup[] = [
    {
      id: "vault",
      title: "Acesso & Cofre",
      items: [
        {
          id: "default_credentials",
          label: "Credenciais Padrão",
          subtitle: "Chaves .key e senhas",
          icon: <KeyRound className="h-4 w-4" />,
        },
      ],
    },
    {
      id: "connections",
      title: "Conexões",
      items: [
        {
          id: "db_profiles",
          label: "Bancos PostgreSQL",
          icon: <Database className="h-4 w-4" />,
          badge: profiles.length,
        },
        {
          id: "sftp_profiles",
          label: "Servidores SFTP",
          icon: <Server className="h-4 w-4" />,
        },
        {
          id: "jasperserver_profiles",
          label: "JasperReports Server",
          icon: <Cloud className="h-4 w-4" />,
        },
      ],
    },
    {
      id: "studio_ai",
      title: "Studio & IA",
      items: [
        {
          id: "subreports",
          label: "Subreports Jasper",
          icon: <FileArchive className="h-4 w-4" />,
          badge: subreports.length,
        },
        {
          id: "harnesses",
          label: "Assistentes IA (Harnesses)",
          icon: <Cpu className="h-4 w-4" />,
          badge:
            harnesses.length > 0
              ? `${installedHarnessesCount}/${harnesses.length}`
              : undefined,
        },
        {
          id: "preferences",
          label: "Preferências",
          icon: <Sliders className="h-4 w-4" />,
        },
      ],
    },
  ];

  const allItems = navGroups.flatMap((g) => g.items);
  const activeItem = allItems.find((item) => item.id === activeTab) ?? allItems[0];

  const handleSelectTab = (tabId: SettingsTabId) => {
    setActiveTab(tabId);
    setMobileNavOpen(false);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden bg-canvas">
      {/* Header */}
      <div className="shrink-0 border-b border-border bg-surface px-5 py-3.5">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <Settings className="h-4.5 w-4.5" />
            </div>
            <div>
              <h1 className="text-base font-semibold tracking-tight text-ink">
                Configurações
              </h1>
              <p className="text-xs text-ink-muted">
                Cofre local, conexões PostgreSQL, SFTP, JasperReports Server,
                subreports e assistentes de IA.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              loading={loading}
              onClick={() => void refreshAll()}
              icon={<RefreshCw className="h-3.5 w-3.5" />}
            >
              Atualizar
            </Button>
            {onClose && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onClose}
                icon={<X className="h-3.5 w-3.5" />}
              >
                Fechar
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Responsive Mobile Category Selector */}
      <div className="shrink-0 border-b border-border bg-surface/80 px-4 py-2 md:hidden">
        <button
          type="button"
          onClick={() => setMobileNavOpen((prev) => !prev)}
          aria-expanded={mobileNavOpen}
          aria-controls="settings-sidebar-nav"
          className="flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 py-2 text-xs font-medium text-ink cursor-pointer hover:border-border-strong"
        >
          <span className="flex items-center gap-2 truncate">
            <Menu className="h-3.5 w-3.5 text-ink-muted" />
            <span className="truncate">{activeItem?.label ?? "Seções"}</span>
          </span>
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-ink-muted transition-transform",
              mobileNavOpen && "rotate-180",
            )}
          />
        </button>
      </div>

      {/* Main Split: Categorized Sidebar + Active Content */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden md:flex-row">
        <aside
          id="settings-sidebar-nav"
          aria-label="Categorias de configurações"
          className={cn(
            "shrink-0 border-b border-border bg-surface/60 md:w-64 md:border-b-0 md:border-r md:overflow-y-auto",
            mobileNavOpen ? "block max-h-80 overflow-y-auto" : "hidden md:block",
          )}
        >
          <nav
            role="tablist"
            aria-orientation="vertical"
            aria-label="Seções de configurações"
            className="space-y-5 p-3.5"
          >
            {navGroups.map((group) => (
              <div key={group.id} className="space-y-1">
                <div className="px-2.5 text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                  {group.title}
                </div>
                <div className="space-y-0.5">
                  {group.items.map((item) => {
                    const isActive = item.id === activeTab;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        role="tab"
                        aria-selected={isActive}
                        onClick={() => handleSelectTab(item.id)}
                        className={cn(
                          "group flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-2 text-left transition-colors cursor-pointer",
                          isActive
                            ? "bg-accent-soft text-accent font-semibold shadow-xs"
                            : "text-ink-secondary hover:bg-surface-subtle hover:text-ink",
                        )}
                      >
                        <div className="flex min-w-0 items-center gap-2.5">
                          <span
                            className={cn(
                              "shrink-0",
                              isActive
                                ? "text-accent"
                                : "text-ink-muted group-hover:text-ink-secondary",
                            )}
                          >
                            {item.icon}
                          </span>
                          <div className="min-w-0">
                            <div className="truncate text-xs leading-tight">
                              {item.label}
                            </div>
                            {item.subtitle && (
                              <div
                                className={cn(
                                  "truncate text-[10px] leading-tight mt-0.5 font-normal",
                                  isActive
                                    ? "text-accent/80"
                                    : "text-ink-muted",
                                )}
                              >
                                {item.subtitle}
                              </div>
                            )}
                          </div>
                        </div>

                        {item.badge !== undefined && (
                          <span
                            className={cn(
                              "shrink-0 rounded-full px-1.5 py-0.5 font-mono text-[10px] font-medium tabular-nums",
                              isActive
                                ? "bg-accent/15 text-accent"
                                : "bg-surface-subtle text-ink-muted",
                            )}
                          >
                            {item.badge}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
        </aside>

        {/* Active Section Body */}
        <div
          role="tabpanel"
          className="min-h-0 flex-1 overflow-y-auto px-5 py-5"
        >
          <div className="mx-auto max-w-4xl">
            {activeTab === "db_profiles" && (
              <DbProfilesTab
                profiles={profiles}
                loading={loading}
                onRefresh={refreshProfiles}
              />
            )}

            {activeTab === "default_credentials" && <DefaultCredentialsTab />}

            {activeTab === "sftp_profiles" && (
              <SftpProfilesTab dbProfiles={profiles} />
            )}

            {activeTab === "jasperserver_profiles" && (
              <JasperServerProfilesTab dbProfiles={profiles} />
            )}

            {activeTab === "subreports" && (
              <SubreportsTab
                subreports={subreports}
                loading={loading}
                onRefresh={refreshSubreports}
              />
            )}

            {activeTab === "harnesses" && (
              <HarnessesSkillsTab
                harnesses={harnesses}
                skills={skills}
                loading={loading}
              />
            )}

            {activeTab === "preferences" && (
              <StudioPreferencesTab
                settings={studioSettings}
                loading={loading}
                onSettingsSaved={setStudioSettings}
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
