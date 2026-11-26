import { useEffect, useState, type FormEvent } from "react";
import { RotateCcw, Save } from "lucide-react";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  FieldLabel,
  Input,
  Select,
  Switch,
  useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import type { PreviewMode } from "@/types/studio";

export interface StudioPreferencesTabProps {
  settings: Record<string, unknown>;
  loading: boolean;
  onSettingsSaved: (updated: Record<string, unknown>) => void;
}

interface PreferencesFormState {
  default_harness: string;
  default_preview_mode: PreviewMode;
  default_preview_dpi: string;
  default_unit_name: string;
  auto_regenerate_sql: boolean;
  apply_uppercase_default: boolean;
}

function toFormState(raw: Record<string, unknown>): PreferencesFormState {
  const mode = raw.default_preview_mode;
  const previewMode: PreviewMode =
    mode === "offline" || mode === "db_hybrid" || mode === "auto"
      ? mode
      : "auto";

  return {
    default_harness:
      typeof raw.default_harness === "string" && raw.default_harness
        ? raw.default_harness
        : "agy",
    default_preview_mode: previewMode,
    default_preview_dpi:
      raw.default_preview_dpi !== undefined && raw.default_preview_dpi !== null
        ? String(raw.default_preview_dpi)
        : "150",
    default_unit_name:
      typeof raw.default_unit_name === "string" ? raw.default_unit_name : "",
    auto_regenerate_sql:
      typeof raw.auto_regenerate_sql === "boolean"
        ? raw.auto_regenerate_sql
        : true,
    apply_uppercase_default:
      typeof raw.apply_uppercase_default === "boolean"
        ? raw.apply_uppercase_default
        : true,
  };
}

export function StudioPreferencesTab({
  settings,
  loading,
  onSettingsSaved,
}: StudioPreferencesTabProps) {
  const { pushToast } = useToast();

  const [form, setForm] = useState<PreferencesFormState>(() =>
    toFormState(settings),
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setForm(toFormState(settings));
  }, [settings]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const parsedDpi = Number(form.default_preview_dpi);
      const payload: Record<string, unknown> = {
        ...settings,
        default_harness: form.default_harness,
        default_preview_mode: form.default_preview_mode,
        default_preview_dpi:
          Number.isFinite(parsedDpi) && parsedDpi >= 72 ? parsedDpi : 150,
        default_unit_name: form.default_unit_name.trim(),
        auto_regenerate_sql: form.auto_regenerate_sql,
        apply_uppercase_default: form.apply_uppercase_default,
      };
      const saved = await api.updateSettings(payload);
      onSettingsSaved(
        saved && typeof saved === "object" && !Array.isArray(saved)
          ? saved
          : payload,
      );
      pushToast({
        tone: "success",
        title: "Preferências salvas",
        description: "Configurações gerais do Studio atualizadas com sucesso.",
      });
    } catch (err) {
      pushToast({
        tone: "error",
        title: "Falha ao salvar preferências",
        description: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-ink">
          Preferências Gerais do Studio
        </h2>
        <p className="text-xs text-ink-muted">
          Defina padrões globais para novos projetos, geração SQL e compilação
          de previews JasperReports.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Padrões de Execução e Preview</CardTitle>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="pref-default-harness">
                Harness de IA padrão
              </FieldLabel>
              <Select
                id="pref-default-harness"
                disabled={loading || saving}
                value={form.default_harness}
                onChange={(e) =>
                  setForm((f) => ({ ...f, default_harness: e.target.value }))
                }
              >
                <option value="agy">AGY (Antigravity)</option>
                <option value="opencode">OpenCode</option>
                <option value="claude">Claude Code</option>
                <option value="codex">Codex CLI</option>
              </Select>
            </div>

            <div>
              <FieldLabel htmlFor="pref-preview-mode">
                Modo de preview Jasper padrão
              </FieldLabel>
              <Select
                id="pref-preview-mode"
                disabled={loading || saving}
                value={form.default_preview_mode}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    default_preview_mode: e.target.value as PreviewMode,
                  }))
                }
              >
                <option value="auto">Automático (DB híbrido ou offline)</option>
                <option value="offline">Offline (dados mockados)</option>
                <option value="db_hybrid">Híbrido PostgreSQL</option>
              </Select>
            </div>

            <div>
              <FieldLabel htmlFor="pref-preview-dpi">
                Resolução padrão de preview (DPI)
              </FieldLabel>
              <Select
                id="pref-preview-dpi"
                disabled={loading || saving}
                value={form.default_preview_dpi}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    default_preview_dpi: e.target.value,
                  }))
                }
              >
                <option value="120">120 DPI (rápido)</option>
                <option value="150">150 DPI (padrão equilibrado)</option>
                <option value="200">200 DPI (alta nitidez)</option>
                <option value="300">300 DPI (impressão)</option>
              </Select>
            </div>

            <div>
              <FieldLabel htmlFor="pref-unit-name">
                Nome padrão da unidade de saúde
              </FieldLabel>
              <Input
                id="pref-unit-name"
                disabled={loading || saving}
                placeholder="Ex.: UPA Central — Rede Salutem"
                value={form.default_unit_name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, default_unit_name: e.target.value }))
                }
              />
            </div>
          </div>

          <div className="space-y-3 border-t border-border pt-3.5">
            <Switch
              id="pref-auto-sql"
              disabled={loading || saving}
              checked={form.auto_regenerate_sql}
              onChange={(checked) =>
                setForm((f) => ({ ...f, auto_regenerate_sql: checked }))
              }
              label="Regenerar SQL INSERT e SELECT automaticamente ao salvar JSON"
            />
            <div>
              <Switch
                id="pref-uppercase"
                disabled={loading || saving}
                checked={form.apply_uppercase_default}
                onChange={(checked) =>
                  setForm((f) => ({ ...f, apply_uppercase_default: checked }))
                }
                label="Normalizar rótulos clínicos em CAIXA ALTA por padrão (padrão Salutem)"
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2 border-t border-border pt-3.5">
            <Button
              variant="ghost"
              size="sm"
              disabled={loading || saving}
              onClick={() => setForm(toFormState(settings))}
              icon={<RotateCcw className="h-3.5 w-3.5" />}
            >
              Descartar alterações
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={saving}
              disabled={loading}
              icon={<Save className="h-3.5 w-3.5" />}
            >
              Salvar preferências
            </Button>
          </div>
        </CardBody>
      </Card>
    </form>
  );
}
