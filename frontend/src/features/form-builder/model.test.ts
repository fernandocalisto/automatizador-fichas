import { describe, expect, it } from "vitest";
import {
  applyUppercaseClinicalForm,
  cloneAnswer,
  cloneQuestion,
  createBlankClinicalForm,
  normalizeWarnings,
  parseClinicalFormJson,
  renumberClinicalForm,
  reorderArray,
} from "./model";

describe("form-builder model helpers", () => {
  it("creates a valid Salutem blank form with 1..N ordering", () => {
    const blank = createBlankClinicalForm("Ficha de Triagem");
    expect(blank.template.nome).toBe("FICHA DE TRIAGEM");
    expect(blank.template.layout).toBe("ficha-clinica");
    expect(blank.template.orientacao).toBe("RETRATO");
    expect(blank.template.posicao_assinatura).toBe("RODAPE");
    expect(blank.template.quantidade_pagina).toBe(1);
    expect(blank.perguntas.length).toBeGreaterThanOrEqual(2);
    expect(blank.perguntas[0].ordenacao).toBe(1);
    expect(blank.perguntas[1].ordenacao).toBe(2);
    expect(blank.perguntas[1].respostas[0].ordenacao).toBe(1);
  });

  it("parses valid clinical JSON and rejects malformed or incomplete JSON", () => {
    const empty = parseClinicalFormJson("   ");
    expect(empty.data).toBeNull();
    expect(empty.error).toMatch(/vazio/i);

    const syntaxErr = parseClinicalFormJson("{ invalid");
    expect(syntaxErr.data).toBeNull();
    expect(syntaxErr.error).toMatch(/sintaxe/i);

    const missingTemplate = parseClinicalFormJson(JSON.stringify({ perguntas: [] }));
    expect(missingTemplate.data).toBeNull();
    expect(missingTemplate.error).toMatch(/template/i);

    const missingQuestions = parseClinicalFormJson(
      JSON.stringify({ template: { nome: "X" } }),
    );
    expect(missingQuestions.data).toBeNull();
    expect(missingQuestions.error).toMatch(/perguntas/i);

    const valid = parseClinicalFormJson(
      JSON.stringify({
        template: { nome: "Ficha", layout: "ficha-clinica" },
        perguntas: [
          {
            nome: "Alergias",
            titulo: false,
            respostas: [{ label: "Sim", tipo_campo: "BOOLEANO" }],
          },
        ],
      }),
    );
    expect(valid.error).toBeNull();
    expect(valid.schemaWarnings).toEqual([]);
    expect(valid.data?.template.nome).toBe("Ficha");
    expect(valid.data?.perguntas[0].respostas[0].label).toBe("Sim");

    const mismatched = parseClinicalFormJson(
      JSON.stringify({
        template: { nome: "Ficha Incompatível" },
        perguntas: [{ id: 1, titulo_errado: "Sem nome e sem respostas" }],
      }),
    );
    expect(mismatched.error).toBeNull();
    expect(mismatched.schemaWarnings.length).toBeGreaterThanOrEqual(2);
    expect(mismatched.schemaWarnings.map((w) => w.code)).toContain(
      "SCHEMA_MISSING_QUESTION_TEXT",
    );
    expect(mismatched.schemaWarnings.map((w) => w.code)).toContain(
      "SCHEMA_MISSING_RESPOSTAS",
    );
  });

  it("applies UPPERCASE to text fields while preserving layout and boolean titulo", () => {
    const doc = {
      template: {
        nome: "ficha pediatrica",
        descricao: "atendimento inicial",
        layout: "ficha-clinica",
        ativo: true,
        orientacao: "RETRATO" as const,
        posicao_assinatura: "RODAPE" as const,
        quantidade_pagina: 1,
      },
      perguntas: [
        {
          nome: "possui alergia?",
          titulo: false,
          ordenacao: 5,
          respostas: [
            {
              label: "tipo de alergia",
              tipo_campo: "COMBOBOX",
              ordenacao: 9,
              opcoes: ["medicamento", "alimento"],
            },
          ],
        },
      ],
    };

    const upper = applyUppercaseClinicalForm(doc);
    expect(upper.template.nome).toBe("FICHA PEDIATRICA");
    expect(upper.template.descricao).toBe("ATENDIMENTO INICIAL");
    expect(upper.template.layout).toBe("ficha-clinica");
    expect(upper.perguntas[0].nome).toBe("POSSUI ALERGIA?");
    expect(upper.perguntas[0].titulo).toBe(false);
    expect(upper.perguntas[0].ordenacao).toBe(1);
    expect(upper.perguntas[0].respostas[0].label).toBe("TIPO DE ALERGIA");
    expect(upper.perguntas[0].respostas[0].ordenacao).toBe(1);
    expect(upper.perguntas[0].respostas[0].opcoes).toEqual([
      "MEDICAMENTO",
      "ALIMENTO",
    ]);
  });

  it("reorders, renumbers, clones, and normalizes warnings", () => {
    expect(reorderArray(["a", "b", "c"], 0, 2)).toEqual(["b", "c", "a"]);

    const blank = createBlankClinicalForm("Teste");
    const clonedQ = cloneQuestion(blank.perguntas[1]);
    expect(clonedQ.nome).toContain("(CÓPIA)");
    expect(clonedQ.respostas).not.toBe(blank.perguntas[1].respostas);

    const clonedA = cloneAnswer(blank.perguntas[1].respostas[0]);
    expect(clonedA.label).toContain("(CÓPIA)");

    const renumbered = renumberClinicalForm({
      ...blank,
      perguntas: [
        { ...blank.perguntas[1], ordenacao: 99 },
        { ...blank.perguntas[0], ordenacao: 42 },
      ],
    });
    expect(renumbered.perguntas.map((q) => q.ordenacao)).toEqual([1, 2]);

    const normalized = normalizeWarnings([
      "Aviso simples",
      { code: "TITLE_WITH_ANSWERS", path: "perguntas[0]", message: "Detalhe" },
    ]);
    expect(normalized).toHaveLength(2);
    expect(normalized[0].message).toBe("Aviso simples");
    expect(normalized[1].code).toBe("TITLE_WITH_ANSWERS");
  });
});
