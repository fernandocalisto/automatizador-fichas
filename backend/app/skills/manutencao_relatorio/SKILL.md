---
name: manutencao-relatorio-salutem
description: Cria, investiga e realiza manutenção cirúrgica em relatórios JasperReports (.jrxml) livres dos sistemas Salutem Ambulatorial e Salutem Hospitalar, incluindo exploração segura READ ONLY do schema PostgreSQL, ajuste de queries SQL com parâmetros $P{}, sincronização de <field> e validação visual via compilação JVM e preview PNG.
---
# Manutenção e Criação de Relatórios Livres JasperReports (Salutem Ambulatorial & Hospitalar)

Esta skill orienta agentes de IA na criação e manutenção cirúrgica de **relatórios JasperReports livres** (`project_kind = "free_report"`), cobrindo tanto relatórios do **Salutem Ambulatorial** (fichas, declarações, laudos, relatórios operacionais) quanto do **Salutem Hospitalar** (Report Units no JasperReports Server, internação, prescrição, faturamento, evolução clínica e relatórios gerenciais).

## 1. Princípios de Manutenção Cirúrgica em `.jrxml`

Quando estiver editando um relatório já existente (importado via upload, SFTP ou JasperReports Server):

1. **Preserve integralmente o que não precisa mudar:**
   - Mantenha `<property>`, `<import>`, `<style>`, `<subDataset>`, `<parameter>`, `<subreportExpression>` (incluindo referências `repo:/...` do JasperServer ou `$P{caminho_relatorio}` / `$P{SUBREPORT_DIR}`), margens e bandas existentes.
   - Nunca remova parâmetros de sistema ou parâmetros usados por Input Controls do JasperServer sem confirmação expressa.
   - Preserve UUIDs existentes nos elementos intocados; gere UUIDs v4 únicos **apenas** para elementos recém-criados.
2. **Nenhuma exibição da string `"null"`:**
   - Todo `<textField>` novo ou ajustado deve declarar `isBlankWhenNull="true"`.
   - Em concatenações Java/Groovy dentro de `<textFieldExpression>`, proteja campos nulos com ternário (`$F{campo} != null ? $F{campo} : ""`).
   - Em `<printWhenExpression>`, use `Boolean.TRUE.equals($F{flag})` (nunca `$F{flag} == true`).
3. **Ordem estrita XSD do `<jasperReport>`:**
   - Respeite rigorosamente a sequência JasperReports 6.21: `property` → `import` → `template` → `style` → `subDataset` → `scriptlet` → `parameter` → `queryString` → `field` → `sortField` → `variable` → `filterExpression` → `group` → `background` → `title` → `pageHeader` → `columnHeader` → `detail` → `columnFooter` → `pageFooter` → `lastPageFooter` → `summary` → `noData`.
4. **Coordenadas e Bandas:**
   - Nenhum elemento pode ultrapassar `columnWidth` (`x + width <= columnWidth`) nem a altura da banda (`y + height <= band.height`).
   - Use `positionType="Float"` e `isStretchWithOverflow="true"` (ou `textAdjust="StretchHeight"`) com critério em campos narrativos/multi-linha para evitar sobreposição.

## 2. Exploração Segura do Banco PostgreSQL (MCP READ ONLY)

Antes de inventar nomes de tabelas, colunas ou joins (especialmente entre schemas diferentes do **Salutem Ambulatorial** vs **Salutem Hospitalar**), **sempre** inspecione o banco real usando as ferramentas MCP de somente leitura:

1. **`list_db_tables(project_id=..., schema="public", search="...")`**
   - Descubra rapidamente as tabelas e views reais do ambiente conectado (ex.: `atendimento`, `paciente`, `internacao`, `prescricao`, `estabelecimento`, `prestador`, etc.) e a contagem estimada de linhas.
2. **`describe_db_table(table="...", schema="public", project_id=...)`**
   - Verifique os nomes exatos das colunas, seus tipos PostgreSQL, as **classes Java equivalentes** (`java.lang.Long`, `java.lang.Integer`, `java.math.BigDecimal`, `java.sql.Date`, `java.sql.Timestamp`, `java.lang.Boolean`, `java.lang.String`), chaves primárias (PK) e chaves estrangeiras (FK) para montar `JOIN`s corretos.
3. **`preview_db_select(sql_select="...", params={...}, limit=10, project_id=...)`**
   - Valide a query SQL real em transação `READ ONLY` (máximo 20 linhas, timeout de 10s, `ROLLBACK` automático), passando valores de teste para os parâmetros `$P{...}` / `${...}`.
   - Confirme os aliases exatos das colunas retornadas e seus tipos Java antes de declarar `<field name="..." class="..."/>` no `.jrxml`.

> **Regra de segurança:** Jamais tente executar DML/DDL (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`) ou embutir credenciais/URLs internas em comentários ou código do relatório.

## 3. Alinhamento entre `<queryString>`, `<parameter>` e `<field>`

- Todo parâmetro usado na query (`$P{nome}` ou `$P!{nome}`) deve estar declarado em `<parameter name="nome" class="..."/>` com a classe Java correta:
  - IDs numéricos grandes: `java.lang.Long`
  - Contadores / códigos inteiros: `java.lang.Integer`
  - Valores monetários / decimais: `java.math.BigDecimal` ou `java.lang.Double`
  - Datas: `java.sql.Date` ou `java.sql.Timestamp` (ou `java.lang.String` quando formatado/convertido explicitamente na query)
  - Flags: `java.lang.Boolean`
- Cada coluna da cláusula `SELECT` da `<queryString>` usada no layout deve possuir o `<field name="..." class="..."/>` correspondente, com o mesmo nome/alias (case-sensitive no JasperReports) e classe compatível com o retorno do PostgreSQL.
- Sempre envolva a `<queryString>` em `<![CDATA[ ... ]]>`.

## 4. Fluxo Recomendado de Validação e Entrega

1. **Gate 1 (Planejamento — quando `gate_authorized = False`):**
   - Inspecione o `.jrxml` atual e, quando necessário, consulte o schema via `list_db_tables`, `describe_db_table` e `preview_db_select`.
   - Apresente um plano objetivo e cirúrgico: quais tabelas/colunas serão consultadas, quais `<parameter>`, `<field>` ou elementos visuais serão adicionados/alterados, e peça confirmação para aplicar.
2. **Gate 2 (Execução — quando `gate_authorized = True`):**
   - Aplique as alterações no `.jrxml` diretamente no workspace ou via `validate_and_compile_jrxml(project_id=..., jrxml_content=..., save_artifact=True)`.
   - **Compilação obrigatória:** Confirme que `validate_and_compile_jrxml` retorna `compiled: true` sem erros XSD/Groovy/Java.
   - **Inspeção visual:** Sempre que possível, execute `render_preview_images(project_id=..., scenario="full", mode=...)` para renderizar o PDF/PNG e conferir alinhamento, quebras de página, ausência de `"null"` e truncamento de textos.
   - **Resposta limpa no chat:** Não despeje o arquivo `.jrxml` inteiro no chat; resuma de forma objetiva o que foi alterado, os resultados da compilação/preview e os parâmetros `$P{...}` necessários para testar o relatório em modo **Live (Banco Real)**.
