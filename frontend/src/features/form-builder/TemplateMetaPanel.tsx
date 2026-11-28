import { useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  CardTitle,
  FieldLabel,
  Input,
  Select,
  Switch,
} from "@/components/ui";
import type {
  ClinicalOrientation,
  ClinicalTemplateMeta,
  SignaturePosition,
} from "@/types/studio";
import {
  ORIENTACAO_OPTIONS,
  POSICAO_ASSINATURA_OPTIONS,
} from "./model";

export interface TemplateMetaPanelProps {
  template: ClinicalTemplateMeta;
  onChange: (next: ClinicalTemplateMeta) => void;
}

export function TemplateMetaPanel({
  template,
  onChange,
}: TemplateMetaPanelProps) {
  const [expanded, setExpanded] = useState(true);

  const orientacao: ClinicalOrientation =
    template.orientacao === "PAISAGEM" ? "PAISAGEM" : "RETRATO";
  const posicaoAssinatura: SignaturePosition =
    template.posicao_assinatura === "LATERAL" ? "LATERAL" : "RODAPE";
  const quantidadePagina =
    typeof template.quantidade_pagina === "number"
      ? template.quantidade_pagina
      : 1;
  const ativo = template.ativo !== false;
  const importaHistorico = Boolean(template.importa_historico_ficha_clinica);

  const update = (patch: Partial<ClinicalTemplateMeta>) => {
    onChange({
      ...template,
      ...patch,
    });
  };

  return (
    <Card>
      <CardHeader className="py-2.5 px-3.5">
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-center gap-2 text-left cursor-pointer"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-ink-muted" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-ink-muted" />
          )}
          <FileText className="h-4 w-4 shrink-0 text-accent" />
          <CardTitle className="truncate">Metadados do Template</CardTitle>
        </button>

        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone="blueprint">{orientacao}</Badge>
          <Badge tone="neutral">{posicaoAssinatura}</Badge>
          <Badge tone={ativo ? "success" : "warning"} dot>
            {ativo ? "Ativo" : "Inativo"}
          </Badge>
        </div>
      </CardHeader>

      {expanded && (
        <CardBody className="space-y-3 p-3.5">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <FieldLabel htmlFor="tpl-nome">Nome do template</FieldLabel>
              <Input
                id="tpl-nome"
                value={template.nome ?? ""}
                placeholder="Ex.: FICHA DE ATENDIMENTO AMBULATORIAL"
                onChange={(e) => update({ nome: e.target.value })}
              />
            </div>

            <div>
              <FieldLabel htmlFor="tpl-descricao">Descrição</FieldLabel>
              <Input
                id="tpl-descricao"
                value={template.descricao ?? ""}
                placeholder="Descrição opcional do formulário clínico"
                onChange={(e) => update({ descricao: e.target.value })}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-12">
            <div className="min-w-0 md:col-span-5">
              <FieldLabel htmlFor="tpl-orientacao" className="whitespace-nowrap">
                Orientação
              </FieldLabel>
              <Select
                id="tpl-orientacao"
                value={orientacao}
                className="text-xs whitespace-nowrap"
                onChange={(e) =>
                  update({
                    orientacao: e.target.value as ClinicalOrientation,
                  })
                }
              >
                {ORIENTACAO_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </div>

            <div className="min-w-0 md:col-span-4">
              <FieldLabel htmlFor="tpl-assinatura" className="whitespace-nowrap">
                Posição da assinatura
              </FieldLabel>
              <Select
                id="tpl-assinatura"
                value={posicaoAssinatura}
                className="text-xs whitespace-nowrap"
                onChange={(e) =>
                  update({
                    posicao_assinatura: e.target.value as SignaturePosition,
                  })
                }
              >
                {POSICAO_ASSINATURA_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </div>

            <div className="min-w-0 md:col-span-3">
              <FieldLabel htmlFor="tpl-paginas" className="whitespace-nowrap">
                Quantidade de páginas
              </FieldLabel>
              <Input
                id="tpl-paginas"
                type="number"
                min={1}
                max={10}
                value={quantidadePagina}
                onChange={(e) => {
                  const parsed = Number.parseInt(e.target.value, 10);
                  update({
                    quantidade_pagina:
                      Number.isNaN(parsed) || parsed < 1 ? 1 : parsed,
                  });
                }}
              />
              {quantidadePagina !== 1 && (
                <p className="mt-1 text-[11px] text-warning">
                  Padrão Salutem recomenda sempre 1 página.
                </p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-5 border-t border-border/70 pt-2.5">
            <Switch
              id="tpl-ativo"
              checked={ativo}
              onChange={(checked) => update({ ativo: checked })}
              label="Template ativo"
            />
            <Switch
              id="tpl-importa-historico"
              checked={importaHistorico}
              onChange={(checked) =>
                update({ importa_historico_ficha_clinica: checked })
              }
              label="Importa histórico da ficha clínica"
            />
          </div>
        </CardBody>
      )}
    </Card>
  );
}
