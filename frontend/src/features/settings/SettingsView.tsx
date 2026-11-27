import { useCallback, useEffect, useState } from "react";
import {
  Cloud,
  Cpu,
  Database,
  FileArchive,
  KeyRound,
  RefreshCw,
  Server,
  Settings,
  Sliders,
  X,
} from "lucide-react";
import { Button, Tabs, useToast, type TabOption } from "@/components/ui";
import { api } from "@/lib/api";
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

export function SettingsView({ onClose, initialTab }: SettingsViewProps) {
  const { pushToast } = useToast();

  const [activeTab, setActiveTab] = useState<SettingsTabId>(
    initialTab ?? "db_profiles",
  );
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

  const tabOptions: TabOption<SettingsTabId>[] = [
    {
      id: "db_profiles",
      label: "Perfis PostgreSQL",
      icon: <Database className="h-3.5 w-3.5" />,
      badge: profiles.length,
    },
    {
      id: "default_credentials",
      label: "Credenciais Padrão",
      icon: <KeyRound className="h-3.5 w-3.5" />,
    },
    {
      id: "sftp_profiles",
      label: "Servidores SFTP",
      icon: <Server className="h-3.5 w-3.5" />,
    },
    {
      id: "jasperserver_profiles",
      label: "JasperReports Server",
      icon: <Cloud className="h-3.5 w-3.5" />,
    },
    {
      id: "subreports",
      label: "Subreports Jasper",
      icon: <FileArchive className="h-3.5 w-3.5" />,
      badge: subreports.length,
    },
    {
      id: "harnesses",
      label: "Harnesses & Skills",
      icon: <Cpu className="h-3.5 w-3.5" />,
      badge:
        harnesses.length > 0
          ? `${installedHarnessesCount}/${harnesses.length}`
          : undefined,
    },
    {
      id: "preferences",
      label: "Preferências do Studio",
      icon: <Sliders className="h-3.5 w-3.5" />,
    },
  ];

  return (
    <div className="flex h-full flex-col overflow-hidden bg-canvas">
      {/* Header */}
      <div className="shrink-0 border-b border-border bg-surface px-5 py-3.5">
        <div className="mx-auto flex max-w-6xl flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
                <Settings className="h-4.5 w-4.5" />
              </div>
              <div>
                <h1 className="text-base font-semibold tracking-tight text-ink">
                  Configurações
                </h1>
                <p className="text-xs text-ink-muted">
                  Conexões PostgreSQL, credenciais padrão locais, servidores
                  SFTP, JasperReports Server, subreports e harnesses de IA.
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

          <div className="overflow-x-auto">
            <Tabs
              options={tabOptions}
              value={activeTab}
              onChange={setActiveTab}
            />
          </div>
        </div>
      </div>

      {/* Tab Body */}
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="mx-auto max-w-6xl">
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
  );
}
