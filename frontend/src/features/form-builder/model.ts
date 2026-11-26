import {
  SALUTEM_FIELD_TYPES,
  type ClinicalAnswer,
  type ClinicalFormJson,
  type ClinicalOrientation,
  type ClinicalQuestion,
  type ClinicalWarningItem,
  type SalutemFieldType,
  type SignaturePosition,
} from "@/types/studio";

export const TEXT_FIELDS_UPPERCASE = new Set([
  "label",
  "labels",
  "nome",
  "name",
  "descricao",
  "description",
  "titulo",
  "title",
  "valor_texto",
  "opcoes",
]);

export const PRESERVE_CASE_FIELDS = new Set([
  "layout",
  "id",
  "codigo_ficha",
  "cid_codigo",
  "procedimento_codigo",
  "exame_id",
]);

export const SALUTEM_FIELD_TYPE_LABELS: Record<SalutemFieldType, string> = {
  TEXTO: "TEXTO — Texto livre",
  NUMERICO: "NUMERICO — Valor numérico",
  BOOLEANO: "BOOLEANO — Checkbox (múltipla escolha)",
  BOOLEANO_RADIO: "BOOLEANO_RADIO — Opção exclusiva (radio)",
  COMBOBOX: "COMBOBOX — Lista suspensa",
  DATA: "DATA — Data (dd/mm/aaaa)",
  HORA: "HORA — Horário (hh:mm)",
  CID: "CID — Código CID-10",
  EXAME: "EXAME — Solicitação de exame",
  PROCEDIMENTO: "PROCEDIMENTO — Código SIGTAP/TUSS",
  PROCEDIMENTO_CID: "PROCEDIMENTO_CID — Procedimento + CID",
};

export const ORIENTACAO_OPTIONS: { value: ClinicalOrientation; label: string }[] = [
  { value: "RETRATO", label: "RETRATO (A4 Vertical)" },
  { value: "PAISAGEM", label: "PAISAGEM (A4 Horizontal)" },
];

export const POSICAO_ASSINATURA_OPTIONS: {
  value: SignaturePosition;
  label: string;
}[] = [
  { value: "RODAPE", label: "RODAPÉ" },
  { value: "LATERAL", label: "LATERAL" },
];

export function isOfficialSalutemFieldType(
  value: string,
): value is SalutemFieldType {
  return (SALUTEM_FIELD_TYPES as readonly string[]).includes(value);
}

export function createDefaultAnswer(ordenacao = 1): ClinicalAnswer {
  return {
    label: "",
    tipo_campo: "TEXTO",
    ordenacao,
    obrigatorio: false,
    observacao: false,
    quantidade_linhas: 1,
  };
}

export function createDefaultQuestion(
  options: { isTitle?: boolean; ordenacao?: number } = {},
): ClinicalQuestion {
  const isTitle = Boolean(options.isTitle);
  const ordenacao = options.ordenacao ?? 1;
  return {
    nome: isTitle ? "NOVA SEÇÃO" : "NOVA PERGUNTA",
    titulo: isTitle,
    ordenacao,
    obrigatorio: false,
    observacao: false,
    respostas: isTitle ? [] : [createDefaultAnswer(1)],
  };
}

export function createBlankClinicalForm(projectName?: string): ClinicalFormJson {
  const nome = (projectName?.trim() || "NOVA FICHA CLÍNICA").toUpperCase();
  return {
    template: {
      nome,
      descricao: "",
      ativo: true,
      layout: "ficha-clinica",
      orientacao: "RETRATO",
      posicao_assinatura: "RODAPE",
      quantidade_pagina: 1,
      importa_historico_ficha_clinica: false,
    },
    perguntas: [
      {
        nome: "IDENTIFICAÇÃO / AVALIAÇÃO INICIAL",
        titulo: true,
        ordenacao: 1,
        obrigatorio: false,
        observacao: false,
        respostas: [],
      },
      {
        nome: "QUEIXA PRINCIPAL",
        titulo: false,
        ordenacao: 2,
        obrigatorio: false,
        observacao: false,
        respostas: [
          {
            label: "DESCRIÇÃO",
            tipo_campo: "TEXTO",
            ordenacao: 1,
            obrigatorio: false,
            observacao: false,
            quantidade_linhas: 2,
          },
        ],
      },
    ],
  };
}

export function renumberClinicalForm(data: ClinicalFormJson): ClinicalFormJson {
  const perguntas = (Array.isArray(data.perguntas) ? data.perguntas : []).map(
    (pergunta, qIndex): ClinicalQuestion => {
      const respostas = (
        Array.isArray(pergunta.respostas) ? pergunta.respostas : []
      ).map((resposta, aIndex): ClinicalAnswer => ({
        ...resposta,
        ordenacao: aIndex + 1,
      }));
      return {
        ...pergunta,
        titulo: Boolean(pergunta.titulo),
        ordenacao: qIndex + 1,
        respostas,
      };
    },
  );

  return {
    ...data,
    template: {
      ...data.template,
    },
    perguntas,
  };
}

function uppercaseRecursive(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => uppercaseRecursive(item));
  }
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const next: Record<string, unknown> = {};
    for (const [key, val] of Object.entries(record)) {
      const keyLower = key.toLowerCase();
      if (PRESERVE_CASE_FIELDS.has(keyLower)) {
        next[key] = val;
      } else if (TEXT_FIELDS_UPPERCASE.has(keyLower)) {
        if (typeof val === "string") {
          next[key] = val.toUpperCase();
        } else if (Array.isArray(val)) {
          next[key] = val.map((item) =>
            typeof item === "string"
              ? item.toUpperCase()
              : uppercaseRecursive(item),
          );
        } else if (val !== null && typeof val === "object") {
          const nested: Record<string, unknown> = {};
          for (const [nk, nv] of Object.entries(val as Record<string, unknown>)) {
            nested[nk] =
              typeof nv === "string" ? nv.toUpperCase() : uppercaseRecursive(nv);
          }
          next[key] = nested;
        } else {
          // Preserves booleans (e.g. titulo: false), numbers, null
          next[key] = val;
        }
      } else {
        next[key] = uppercaseRecursive(val);
      }
    }
    return next;
  }
  return value;
}

export function applyUppercaseClinicalForm(
  data: ClinicalFormJson,
): ClinicalFormJson {
  return renumberClinicalForm(uppercaseRecursive(data) as ClinicalFormJson);
}

export function formatClinicalFormJson(data: ClinicalFormJson): string {
  return JSON.stringify(data, null, 2);
}

export interface ClinicalJsonParseResult {
  data: ClinicalFormJson | null;
  error: string | null;
}

export function parseClinicalFormJson(rawText: string): ClinicalJsonParseResult {
  const trimmed = rawText.trim();
  if (!trimmed) {
    return { data: null, error: "O conteúdo JSON está vazio." };
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { data: null, error: `Erro de sintaxe JSON: ${msg}` };
  }

  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      data: null,
      error: "O elemento raiz do JSON deve ser um objeto ({...}).",
    };
  }

  const obj = parsed as Record<string, unknown>;
  if (
    !obj.template ||
    typeof obj.template !== "object" ||
    Array.isArray(obj.template)
  ) {
    return {
      data: null,
      error: "Estrutura inválida: a chave 'template' (objeto) é obrigatória.",
    };
  }

  if (!Array.isArray(obj.perguntas)) {
    return {
      data: null,
      error: "Estrutura inválida: a chave 'perguntas' (lista) é obrigatória.",
    };
  }

  const normalizedPerguntas: ClinicalQuestion[] = obj.perguntas.map(
    (item, idx) => {
      if (item === null || typeof item !== "object" || Array.isArray(item)) {
        return createDefaultQuestion({ ordenacao: idx + 1 });
      }
      const q = item as Record<string, unknown>;
      const rawRespostas = Array.isArray(q.respostas) ? q.respostas : [];
      const respostas: ClinicalAnswer[] = rawRespostas.map((ans, rIdx) => {
        if (ans === null || typeof ans !== "object" || Array.isArray(ans)) {
          return createDefaultAnswer(rIdx + 1);
        }
        const a = ans as Record<string, unknown>;
        return {
          ...a,
          label: typeof a.label === "string" ? a.label : "",
          tipo_campo:
            typeof a.tipo_campo === "string" ? a.tipo_campo : "TEXTO",
          ordenacao:
            typeof a.ordenacao === "number" ? a.ordenacao : rIdx + 1,
        } as ClinicalAnswer;
      });
      return {
        ...q,
        nome: typeof q.nome === "string" ? q.nome : "",
        titulo: Boolean(q.titulo),
        ordenacao: typeof q.ordenacao === "number" ? q.ordenacao : idx + 1,
        respostas,
      } as ClinicalQuestion;
    },
  );

  const templateObj = obj.template as Record<string, unknown>;
  const normalized: ClinicalFormJson = {
    ...obj,
    template: {
      ...templateObj,
      nome: typeof templateObj.nome === "string" ? templateObj.nome : "",
    },
    perguntas: normalizedPerguntas,
  };

  return { data: normalized, error: null };
}

export function reorderArray<T>(
  items: readonly T[],
  fromIndex: number,
  toIndex: number,
): T[] {
  if (
    fromIndex === toIndex ||
    fromIndex < 0 ||
    toIndex < 0 ||
    fromIndex >= items.length ||
    toIndex >= items.length
  ) {
    return [...items];
  }
  const next = [...items];
  const [moved] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, moved);
  return next;
}

export function cloneQuestion(question: ClinicalQuestion): ClinicalQuestion {
  return {
    ...question,
    nome: question.nome ? `${question.nome} (CÓPIA)` : "CÓPIA",
    respostas: (question.respostas ?? []).map((ans) => ({
      ...ans,
      opcoes: ans.opcoes ? [...ans.opcoes] : undefined,
    })),
  };
}

export function cloneAnswer(answer: ClinicalAnswer): ClinicalAnswer {
  return {
    ...answer,
    label: answer.label ? `${answer.label} (CÓPIA)` : "",
    opcoes: answer.opcoes ? [...answer.opcoes] : undefined,
  };
}

export function getAnswerRequired(answer: ClinicalAnswer): boolean {
  if (typeof answer.obrigatorio === "boolean") {
    return answer.obrigatorio;
  }
  if (typeof answer.campo_obrigatorio === "boolean") {
    return answer.campo_obrigatorio;
  }
  return false;
}

export function normalizeWarnings(
  raw: (string | ClinicalWarningItem)[] | undefined | null,
): ClinicalWarningItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    if (typeof item === "string") {
      return { severity: "warning", message: item };
    }
    return {
      code: item.code,
      severity: item.severity ?? "warning",
      path: item.path,
      message: item.message || JSON.stringify(item),
    };
  });
}

export function countTotalAnswers(data: ClinicalFormJson | null): number {
  if (!data || !Array.isArray(data.perguntas)) return 0;
  return data.perguntas.reduce(
    (sum, q) => sum + (Array.isArray(q.respostas) ? q.respostas.length : 0),
    0,
  );
}
