---
name: gerador-layout-jrxml-salutem-v3
description: Cria, desenha e estrutura relatórios JasperReports (.jrxml) do sistema Salutem, incluindo a geração de arquivo .jrxml padrão vazio (com os 3 subreports padrão, título padrão e query base) e a construção de bandas (<detail>) a partir de fichas clínicas em PDF ou imagens. Use quando o usuário pedir para gerar um .jrxml padrão/vazio, montar o layout visual da ficha clínica no JasperStudio, converter PDF/imagem em componentes do JasperReports, desenhar campos booleanos (bolas/quadrados) ou paginar fichas médicas/odontológicas.
---
# Gerador de Layout JRXML Salutem

Constrói relatórios JasperReports (`.jrxml`) completos ou apenas a camada visual (`<detail>`) reproduzindo fielmente o design de fichas clínicas em PDF ou imagem, além de gerar o template `.jrxml` padrão vazio do sistema Salutem quando solicitado, garantindo zero erros de compilação/execução no JasperReports, proibição absoluta de exibição da palavra `"null"` e entrega em arquivo compacto para download.

## Quando Usar

  - O usuário pedir para gerar um `.jrxml` padrão vazio (ou base) do Salutem contendo os 3 subreports padrão (`cabecalho_retrato.jasper`, `dados_paciente.jasper`, `rodape_retrato.jasper`), o título estático padrão e a query SQL padrão sem perguntas.
  - O usuário enviar um arquivo `.jrxml` (ou apenas a query/PDF) junto com um PDF ou imagem do modelo da ficha clínica e pedir para gerar o `<detail>` ou o `.jrxml` completo.
  - O usuário solicitar a criação ou ajuste de layout visual de formulários clínicos do sistema Salutem para Jaspersoft Studio.
  - O usuário pedir para converter um PDF de ficha médica/odontológica em componentes gráficos do JasperReports (`staticText`, `textField`, `ellipse`, `rectangle`, `break`).

## Estrutura Padrão da Ficha Salutem (Template Base / Vazio)

Quando o usuário pedir um **JRXML padrão vazio** (ou quando precisar montar um `.jrxml` completo do zero sem que o usuário tenha anexado um `.jrxml` base), utilize exatamente a estrutura oficial abaixo:

1.  **Métricas e Nome da Página (`<jasperReport>`):**
      - `pageWidth="595"` `pageHeight="842"` `columnWidth="555"` `leftMargin="20"` `rightMargin="20"` `topMargin="20"` `bottomMargin="20"`
      - Área útil vertical máxima por banda no `<detail>` (com `pageHeader` de `162 px` e `pageFooter` de `17 px`): `842 - 20 - 20 - 162 - 17 = 623 px`.
      - **Convenção de `name`:** Em fichas específicas, definir o atributo `name` do `<jasperReport>` em `snake_case` correspondente ao nome da ficha (ex.: `avaliacao_alta_hospital_dia`). No template vazio genérico, manter `ficha_padrao`.
2.  **Parâmetros Padrão:**
      - `<parameter name="id" class="java.lang.Long"/>`
      - `<parameter name="caminho_relatorio" class="java.lang.String"/>`
3.  **Os 3 Subreports Padrão e o Título Padrão:**
      - **Subreport 1 (`cabecalho_retrato.jasper`):** Em `<pageHeader>` (`height="162"`), posicionado em `x="0" y="-1" width="555" height="45"`, recebendo o parâmetro `caminho_relatorio` (`$P{caminho_relatorio}`).
      - **Título Padrão (`<staticText>`):** Em `<pageHeader>`, posicionado em `x="0" y="47" width="555" height="34"`, com borda superior e inferior de `1.0 px` (`topPen` e `bottomPen` `1.0`, `leftPen` e `rightPen` `0.0`), alinhamento centralizado (`Center` / `Middle`), fonte `size="12" isBold="true"`.
      - **Subreport 2 (`dados_paciente.jasper`):** Em `<pageHeader>`, posicionado em `x="0" y="82" width="555" height="77"`, recebendo o parâmetro `atendimento_id` (`$F{atendimento_id}`).
          - **Campos já cobertos pelo `dados_paciente.jasper` (NÃO repetir no `<detail>`):** prontuário, CROSS, registro, nome do paciente, nome da mãe, sexo, data de nascimento, idade, RG, CPF, CNS, endereço, convênio, telefone, tipo de encaminhamento e especialidade do agendamento.
      - **Subreport 3 (`rodape_retrato.jasper`):** Em `<pageFooter>` (`height="17"`), posicionado em `x="0" y="-1" width="555" height="17"`, recebendo o parâmetro `caminho_relatorio` (`$P{caminho_relatorio}`).
4.  **Query SQL Padrão (Sem Perguntas) e os 36 Fields Base:**
      - A query padrão contém exclusivamente os blocos `----- CABEÇALHO -----`, `----- PERGUNTAS -----` (vazio por padrão, onde são injetados os `max(case when pfc.ordenacao = ...)` quando houver perguntas), `----- PACIENTE ) -----` e `----- PROFISSIONAL -----`, seguidos dos `LEFT JOIN` padrão filtrando por `where fc.id = $P{id}` e `group by p.endereco_endereco, p.endereco_numero, p.endereco_bairro;`.
      - Os `<field>` padrão compreendem apenas os 3 campos do cabeçalho (`solicitante_cnes`, `solicitante`, `data_criacao`) e os 33 campos de paciente/profissional/atendimento (`pac_id` até `descricao_ficha`). Jamais inclua `<field>` órfãos de outras fichas quando gerar um template vazio.

### Template XML Oficial (`ficha_padrao_vazia.jrxml`)

``` xml
<?xml version="1.0" encoding="UTF-8"?>
<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://jasperreports.sourceforge.net/jasperreports http://jasperreports.sourceforge.net/xsd/jasperreport.xsd" name="ficha_padrao" pageWidth="595" pageHeight="842" columnWidth="555" leftMargin="20" rightMargin="20" topMargin="20" bottomMargin="20" uuid="ed0f92e4-047e-4684-85b6-2e3ac78bbb14">
	<property name="com.jaspersoft.studio.data.sql.tables" value=""/>
	<property name="com.jaspersoft.studio.data.defaultdataadapter" value="(192) AME Barradas"/>
	<parameter name="id" class="java.lang.Long"/>
	<parameter name="caminho_relatorio" class="java.lang.String"/>
	<queryString>
		<![CDATA[select

         ----- CABEÇALHO -----
        (select xx.cnes from estabelecimento xx) AS SOLICITANTE_CNES,
        (select xx.nome_fanta from estabelecimento xx) AS SOLICITANTE,
        'Lorena, '||to_char(max(fc.criacao),'dd/MM/yyyy HH24:mi') data_criacao,


        ----- PERGUNTAS -----


        ----- PACIENTE ) -----
        max (p.id ) AS PAC_ID,
        max (p.nome ) AS PAC_NOME,
        max (p.data_nascimento ) AS PAC_NASC,
        MAX(CASE
        WHEN age.responsavel IS NOT NULL THEN age.responsavel
        ELSE '_____________________________________'
            END) AS PAC_RESP,
        max (p.nome_mae ) AS PAC_MAE,
        max(extract(year FROM age(p.data_nascimento)) )AS PAC_IDADE_A,
        max(extract(month FROM age(p.data_nascimento)) )AS PAC_IDADE_M,
        max(extract(day FROM age(p.data_nascimento)) )AS PAC_IDADE_D,
        max (CASE  WHEN p.sexo = 'MASCULINO' THEN '[M](X) [F](  )'
              WHEN p.sexo = 'FEMININO'  THEN '[F](X) [M](  )' END )AS PAC_SEXO,
        max(p.raca) as PAC_RACA,
        max(e.nome) as pac_etnia,
        max(p.cns) AS PAC_CNS,
        max(p.id) AS PAC_PRONT,
        max(p.cpf) AS PAC_CPF,
        max(p.rg_numero) AS PAC_RG,
        max(p.telefone) PAC_TEL,
        max(p.celular) PAC_CEL,
            UPPER(p.endereco_endereco||', '||
            p.endereco_numero||'  -  '||
            p.endereco_bairro) as PAC_LOG,
        max(p.endereco_complemento) as pac_compl,
        max(UPPER(ci.nome)) AS PAC_MUN,
        max(ci.codigo_ibge  )as PAC_IDMUN,
        max(ci.uf_sigla  ) as PAC_UF,
        max(regexp_replace(lo.cep, '([[:digit:]]{5})([[:digit:]]{3})','\1-\2') ) AS PAC_CEP,
        max(p.codigo_cross) codigo_cross,
        max(replace(p.assinatura,'data:image/png;base64,','')) as assinatura,
        max(replace(age.responsavel_assinatura,'data:image/png;base64,','')) as responsavel_assinatura,
        coalesce(max(age.rg_reponsavel),'_________________') rg_reponsavel,
        ----- PROFISSIONAL -----
        max(pres.id ) as SOLICITANTEID,
        max(pres.nome) AS PROF_NOME,
        max(pres.cns ) AS PROF_CNS,
        max(pres.tipo_registro ) AS PROF_ORG,
        max(pres.numero_conselho ) as PROF_CRM,
        max(cast('(X)CNS (  )CPF' as varchar)) as PROF_DOC,
        max(cast(age.horario as date) ) as data_atendimento,
        max(atendimento_id) as atendimento_id,
        max(tfc.descricao) descricao_ficha

 from ficha_clinica fc
        left join pergunta_ficha_clinica pfc on pfc.ficha_clinica_id = fc.id
        left join resposta_ficha_clinica c on c.pergunta_ficha_clinica_id = pfc.id
        left join template_ficha_clinica tfc on fc.template_ficha_clinica_id = tfc.id
        left join atendimento a on a.id = fc.atendimento_id
        left join agenda age on age.id = a.agenda_id
        left join paciente p on p.id = age.paciente_id
        left join etnia e on e.codigo = p.etnia_codigo
        left join logradouro lo on lo.cep = p.endereco_logradouro_cep
        left join cidade ci on ci.id = lo.cidade_id
        left join usuario usu on usu.id = fc.usuario_id
        left join prestador pres on pres.id = usu.prestador_id

        where
        fc.id = $P{id}

 group by p.endereco_endereco, p.endereco_numero, p.endereco_bairro;]]>
	</queryString>
	<field name="solicitante_cnes" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="solicitante_cnes"/>
		<property name="com.jaspersoft.studio.field.label" value="solicitante_cnes"/>
	</field>
	<field name="solicitante" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="solicitante"/>
		<property name="com.jaspersoft.studio.field.label" value="solicitante"/>
	</field>
	<field name="data_criacao" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="data_criacao"/>
		<property name="com.jaspersoft.studio.field.label" value="data_criacao"/>
	</field>
		<field name="pac_id" class="java.lang.Long">
		<property name="com.jaspersoft.studio.field.name" value="pac_id"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_id"/>
	</field>
	<field name="pac_nome" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_nome"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_nome"/>
	</field>
	<field name="pac_nasc" class="java.sql.Date">
		<property name="com.jaspersoft.studio.field.name" value="pac_nasc"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_nasc"/>
	</field>
	<field name="pac_resp" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_resp"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_resp"/>
	</field>
	<field name="pac_mae" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_mae"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_mae"/>
	</field>
	<field name="pac_idade_a" class="java.lang.Double">
		<property name="com.jaspersoft.studio.field.name" value="pac_idade_a"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_idade_a"/>
	</field>
	<field name="pac_idade_m" class="java.lang.Double">
		<property name="com.jaspersoft.studio.field.name" value="pac_idade_m"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_idade_m"/>
	</field>
	<field name="pac_idade_d" class="java.lang.Double">
		<property name="com.jaspersoft.studio.field.name" value="pac_idade_d"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_idade_d"/>
	</field>
	<field name="pac_sexo" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_sexo"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_sexo"/>
	</field>
	<field name="pac_raca" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_raca"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_raca"/>
	</field>
	<field name="pac_etnia" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_etnia"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_etnia"/>
	</field>
	<field name="pac_cns" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_cns"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_cns"/>
	</field>
	<field name="pac_pront" class="java.lang.Long">
		<property name="com.jaspersoft.studio.field.name" value="pac_pront"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_pront"/>
	</field>
	<field name="pac_cpf" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_cpf"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_cpf"/>
	</field>
	<field name="pac_rg" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_rg"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_rg"/>
	</field>
	<field name="pac_tel" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_tel"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_tel"/>
	</field>
	<field name="pac_cel" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_cel"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_cel"/>
	</field>
	<field name="pac_log" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_log"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_log"/>
	</field>
	<field name="pac_compl" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_compl"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_compl"/>
	</field>
	<field name="pac_mun" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_mun"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_mun"/>
	</field>
	<field name="pac_idmun" class="java.lang.Long">
		<property name="com.jaspersoft.studio.field.name" value="pac_idmun"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_idmun"/>
	</field>
	<field name="pac_uf" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_uf"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_uf"/>
	</field>
	<field name="pac_cep" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="pac_cep"/>
		<property name="com.jaspersoft.studio.field.label" value="pac_cep"/>
	</field>
	<field name="codigo_cross" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="codigo_cross"/>
		<property name="com.jaspersoft.studio.field.label" value="codigo_cross"/>
		<property name="com.jaspersoft.studio.field.tree.path" value="paciente"/>
	</field>
	<field name="assinatura" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="assinatura"/>
		<property name="com.jaspersoft.studio.field.label" value="assinatura"/>
	</field>
	<field name="responsavel_assinatura" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="responsavel_assinatura"/>
		<property name="com.jaspersoft.studio.field.label" value="responsavel_assinatura"/>
	</field>
	<field name="rg_reponsavel" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="rg_reponsavel"/>
		<property name="com.jaspersoft.studio.field.label" value="rg_reponsavel"/>
	</field>
	<field name="solicitanteid" class="java.lang.Long">
		<property name="com.jaspersoft.studio.field.name" value="solicitanteid"/>
		<property name="com.jaspersoft.studio.field.label" value="solicitanteid"/>
	</field>
	<field name="prof_nome" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="prof_nome"/>
		<property name="com.jaspersoft.studio.field.label" value="prof_nome"/>
	</field>
	<field name="prof_cns" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="prof_cns"/>
		<property name="com.jaspersoft.studio.field.label" value="prof_cns"/>
	</field>
	<field name="prof_org" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="prof_org"/>
		<property name="com.jaspersoft.studio.field.label" value="prof_org"/>
	</field>
	<field name="prof_crm" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="prof_crm"/>
		<property name="com.jaspersoft.studio.field.label" value="prof_crm"/>
	</field>
	<field name="prof_doc" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="prof_doc"/>
		<property name="com.jaspersoft.studio.field.label" value="prof_doc"/>
	</field>
	<field name="data_atendimento" class="java.sql.Date">
		<property name="com.jaspersoft.studio.field.name" value="data_atendimento"/>
		<property name="com.jaspersoft.studio.field.label" value="data_atendimento"/>
		<property name="com.jaspersoft.studio.field.tree.path" value="agenda"/>
	</field>
	<field name="atendimento_id" class="java.lang.Long">
		<property name="com.jaspersoft.studio.field.name" value="atendimento_id"/>
		<property name="com.jaspersoft.studio.field.label" value="atendimento_id"/>
		<property name="com.jaspersoft.studio.field.tree.path" value="atendimento"/>
	</field>
	<field name="descricao_ficha" class="java.lang.String">
		<property name="com.jaspersoft.studio.field.name" value="descricao_ficha"/>
		<property name="com.jaspersoft.studio.field.label" value="descricao_ficha"/>
		<property name="com.jaspersoft.studio.field.tree.path" value="template_ficha_clinica"/>
	</field>
	<title>
		<band splitType="Stretch">
			<property name="com.jaspersoft.studio.unit.height" value="px"/>
		</band>
	</title>
	<pageHeader>
		<band height="162" splitType="Stretch">
			<property name="com.jaspersoft.studio.unit.height" value="px"/>
			<staticText>
				<reportElement x="0" y="47" width="555" height="34" uuid="176c5013-4f43-485d-ab7d-5eb13e507939"/>
				<box>
					<pen lineWidth="0.25"/>
					<topPen lineWidth="1.0" lineStyle="Solid" lineColor="#000000"/>
					<leftPen lineWidth="0.0" lineStyle="Solid" lineColor="#000000"/>
					<bottomPen lineWidth="1.0" lineStyle="Solid" lineColor="#000000"/>
					<rightPen lineWidth="0.0" lineStyle="Solid" lineColor="#000000"/>
				</box>
				<textElement textAlignment="Center" verticalAlignment="Middle">
					<font size="12" isBold="true"/>
				</textElement>
				<text><![CDATA[TÍTULO DA FICHA CLÍNICA]]></text>
			</staticText>
			<subreport>
				<reportElement x="0" y="-1" width="555" height="45" uuid="bb313971-9828-44cd-aafa-ec72a3c17fc2"/>
				<subreportParameter name="caminho_relatorio">
					<subreportParameterExpression><![CDATA[$P{caminho_relatorio}]]></subreportParameterExpression>
				</subreportParameter>
				<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>
				<subreportExpression><![CDATA[$P{caminho_relatorio} + "cabecalho_retrato.jasper"]]></subreportExpression>
			</subreport>
			<subreport>
				<reportElement x="0" y="82" width="555" height="77" uuid="df8c1eaf-cf6b-4b9c-b7fc-8e2dbdddc865"/>
				<subreportParameter name="atendimento_id">
					<subreportParameterExpression><![CDATA[$F{atendimento_id}]]></subreportParameterExpression>
				</subreportParameter>
				<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>
				<subreportExpression><![CDATA[$P{caminho_relatorio} + "dados_paciente.jasper"]]></subreportExpression>
			</subreport>
		</band>
	</pageHeader>
	<columnHeader>
		<band>
			<property name="com.jaspersoft.studio.unit.height" value="px"/>
		</band>
	</columnHeader>
	<detail>
		<band height="50"/>
	</detail>
	<columnFooter>
		<band>
			<property name="com.jaspersoft.studio.unit.height" value="px"/>
		</band>
	</columnFooter>
	<pageFooter>
		<band height="17" splitType="Stretch">
			<property name="com.jaspersoft.studio.unit.height" value="px"/>
			<subreport>
				<reportElement x="0" y="-1" width="555" height="17" uuid="8088c97a-30c1-4ac3-9d08-713925bc2376"/>
				<subreportParameter name="caminho_relatorio">
					<subreportParameterExpression><![CDATA[$P{caminho_relatorio}]]></subreportParameterExpression>
				</subreportParameter>
				<connectionExpression><![CDATA[$P{REPORT_CONNECTION}]]></connectionExpression>
				<subreportExpression><![CDATA[$P{caminho_relatorio} + "rodape_retrato.jasper"]]></subreportExpression>
			</subreport>
		</band>
	</pageFooter>
	<summary>
		<band splitType="Stretch">
			<property name="com.jaspersoft.studio.unit.height" value="px"/>
		</band>
	</summary>
</jasperReport>
```

## Fluxo de Trabalho para Construção de Layout (`<detail>`) a partir de PDF/Imagem

*(Exceção: Quando o usuário pedir apenas o JRXML padrão vazio, entregue diretamente o arquivo `.xml`/`.jrxml` limpo acima sem precisar das fases de perguntas de layout abaixo).*

### Fase 1: Análise Técnica Silenciosa

Antes de responder ao usuário ou gerar qualquer código XML, inspecione os arquivos enviados (usando Python no interpretador para extrair coordenadas exatas de textos, retângulos, linhas e curvas do PDF, além de ler a estrutura do `.jrxml` ou usar o template padrão acima caso o usuário envie apenas o PDF/query):

1.  **Validação Cruzada (PDF × Solicitação):** Confira se o nome do arquivo, o título interno do PDF e as observações da solicitação falam da mesma ficha e se todos os campos citados na solicitação existem no PDF. Caso haja divergência (ex.: PDF salvo com layout de outra ficha ou campos solicitados ausentes), destaque o problema na Fase 2 e pergunte como prosseguir — jamais invente itens.
2.  **Mapeamento de Fields e Textos Fixos:** Liste todos os `<field>` das perguntas e cruze com os rótulos visuais do PDF/imagem. Verifique tipos de dados (`java.lang.Boolean`, `java.lang.String`, `java.lang.Double`, `java.sql.Date`, etc.). Separe o que é **texto fixo do modelo** (orientações, destinatários como *"A/C Dr. ..."*, dias da semana, observações de rodapé), que deve entrar apenas como `<staticText>` no `.jrxml` sem virar pergunta ou `<field>`.
3.  **Cálculo Estrito de Área Útil Vertical:** Verifique `pageHeight`, `topMargin`, `bottomMargin`, altura do `pageHeader` e altura do `pageFooter` no `.jrxml` (no padrão com `pageHeader="162"` e `pageFooter="17"`, o limite é `842 - 20 - 20 - 162 - 17 = 623 px` livres por página).
4.  **Inspeção de Coordenadas, Largura de Texto e Componentes:** Identifique a posição exata (`x`, `y`, `width`, `height`), tamanho de fonte, bordas e o tipo visual de cada marcador booleano (círculo/rádio vs. quadrado/checkbox). Aplique a heurística de largura de texto (`rótulo negrito tamanho 9 ≈ 5,5 px/caractere`; `opção normal tamanho 8 ≈ 4,5 px/caractere`) e planeje altura para 2 linhas sempre que o texto não couber confortavelmente em uma única linha.

### Fase 2: Exibição das Decisões de Design, Perguntas e Autorização (Pausa Obrigatória)

**NUNCA gere o código JRXML do layout na primeira resposta e NUNCA gere código se tiver qualquer dúvida.** Siga estritamente esta ordem na resposta ao usuário:

1.  **Apresente primeiro o Resumo das Decisões de Design** que serão aplicadas na ficha:
      - Eventuais divergências encontradas na validação cruzada entre PDF, título interno e solicitação.
      - Repetição do `pageHeader` em todas as páginas (para manter a identificação do paciente) e omissão dos campos que já constam nos subreports (`cabecalho_retrato.jasper` e `dados_paciente.jasper`: prontuário, CROSS, registro, paciente, mãe, sexo, data nasc., idade, RG, CPF, CNS, endereço, convênio, telefone, tipo encaminhamento e especialidade do agendamento).
      - Mapeamento exato de quais campos booleanos serão desenhados como **círculos** (`<ellipse>` 10x10 px com bola preta interna condicional de 6x6 px) e quais serão **quadrados** (`<rectangle>` 10x10 px com quadrado preto interno condicional de 6x6 px).
      - Quantidade de bandas `<band>` no `<detail>`, alturas planejadas (respeitando o limite máximo de altura útil da página), uso de tamanhos fixos nas caixas de texto para evitar loops e garantia de `isBlankWhenNull="true"` em 100% dos `<textField>` para que jamais apareça `"null"`.
      - Mapeamento entre os rótulos do PDF e os `<field>` do `.jrxml` (além da indicação de textos fixos que ficarão apenas como `<staticText>` e frases com lacunas que usarão `markup="styled"`).
2.  **Regra da Certeza Absoluta (Pergunte Sempre):**
      - Logo após mostrar as decisões de design, faça todas as perguntas necessárias ao usuário.
      - Se houver **qualquer ambiguidade** (ex.: PDF que não bate com a solicitação, campo no PDF sem `<field>` claro correspondente no JRXML, dúvida se um marcador é bola ou quadrado, dúvida sobre onde quebrar a página, ou campo sobrando na query), **pergunte explicitamente ao usuário**. Jamais assuma, invente itens ou gere no escuro.
3.  **Pedido de Autorização Expressa:**
      - Finalize a resposta aguardando a confirmação das dúvidas e o **"Autorizado"** expresso do usuário. Só avance para a Fase 3 após essa autorização.

### Fase 3: Regras de Design e Blindagem Total Contra Erros do JasperReports

Ao construir o XML após a autorização, aplique todas as travas abaixo para garantir que o `.jrxml` compile e execute de primeira sem nenhuma exceção (`SAXParseException`, `JRValidationException`, `JRException` ou `NullPointerException`):

1.  **Proibição Absoluta de Exibição de `"null"` (`isBlankWhenNull="true"`) e Frases com Lacunas (`markup="styled"`):**
      - **TODO E QUALQUER `<textField>` deve obrigatoriamente conter a propriedade `isBlankWhenNull="true"`** na tag de abertura (`<textField isBlankWhenNull="true">`).
      - Nunca concatene campos diretamente com `+` dentro de `<textFieldExpression>` (ex.: evite `$F{campo1} + " - " + $F{campo2}`, pois em Java `null + " - " + null` resulta na string literal `"null - null"`, ignorando o `isBlankWhenNull`). Se precisar concatenar valores na expressão, trate nulos explicitamente com operador ternário (`($F{c1} != null ? $F{c1} : "")`). Para campos simples, use apenas `<![CDATA[$F{nome_do_campo}]]>` com `isBlankWhenNull="true"`.
      - **Frases com lacunas:** Quando o modelo trouxer texto corrido com campos embutidos (ex.: *"Encaminhamos a paciente ___ para..."*), utilize um único `<textField isBlankWhenNull="true">` com `<textElement markup="styled">`, substituindo campos nulos por `"____________"`, destacando valores preenchidos com `<style isBold=\"true\">...</style>` e escapando `&` (`&amp;`) e `<` (`&lt;`) nos valores dinâmicos (ex.: `$F{campo}.replace("&", "&amp;").replace("<", "&lt;")`) para não quebrar o parser de styled text.
2.  **Textos Fixos do Modelo e Dimensionamento de Largura:**
      - Orientações, destinatários (*"A/C Dr. ..."*), dias da semana e observações de rodapé do modelo ficam exclusivamente no `.jrxml` como `<staticText>` — nunca crie `<field>` ou pergunta artificial para texto estático.
      - Dimensione as caixas de texto usando a heurística prática (`rótulo negrito 9 ≈ 5,5 px/caractere`; `opção normal 8 ≈ 4,5 px/caractere`) e dê altura para 2 linhas sempre que o conteúdo não couber em 1 linha.
3.  **UUIDs v4 Reais e Válidos (`Invalid UUID string`):**
      - O parser SAX do JasperReports executa `java.util.UUID.fromString()`. Gere sempre UUIDs v4 hexadecimais reais e únicos (via `str(uuid.uuid4())` no Python) para 100% dos atributos `uuid` em `<reportElement>`. Jamais use nomes descritivos como `uuid="titulo_1"`.
4.  **Ordem Estrita das Tags no Schema XSD (`SAXParseException: Invalid content was found starting with element`):**
      - Respeite rigorosamente a sequência exigida pelo `jasperreport.xsd`:
          - Dentro de `<reportElement>`: `<property>` (1º) -> `<propertyExpression>` -> `<printWhenExpression>` (último).
          - Dentro de `<ellipse>` ou `<rectangle>`: `<reportElement>` (1º) -> `<graphicElement>` (2º).
          - Dentro de `<staticText>`: `<reportElement>` (1º) -> `<box>` (2º) -> `<textElement>` (3º) -> `<text>` (4º).
          - Dentro de `<textField isBlankWhenNull="true">`: `<reportElement>` (1º) -> `<box>` (2º) -> `<textElement>` (3º) -> `<textFieldExpression>` (4º).
          - Dentro de `<box>`: `<pen>` -> `<topPen>` -> `<leftPen>` -> `<bottomPen>` -> `<rightPen>`.
          - Dentro de `<textElement>`: `<font>` -> `<paragraph>`.
5.  **Prevenção de Estouro de Página e Loop Infinito (`Infinite loop creating new page` / `Band height validation`):**
      - A altura (`height`) de cada `<band>` nunca pode ultrapassar `pageHeight - topMargin - bottomMargin - pageHeaderHeight - pageFooterHeight` (`623 px` na ficha padrão com `pageHeader="162"`).
      - Dentro de uma `<band>`, nenhum elemento pode ter `y + height > bandHeight`.
      - Dentro de uma `<band>`, nenhum elemento pode ter `x + width > columnWidth` (`555 px`) nem `x < 0` ou `y < 0`.
      - Utilize alturas fixas nos `<textField>` (`isBlankWhenNull="true"`) sem `isStretchWithOverflow="true"`, evitando expansão descontrolada que empurre elementos além do limite da folha.
6.  **Expressões Condicionais Null-Safe (`NullPointerException` / Erro de Unboxing):**
      - Em todo `<printWhenExpression>`, use sempre `Boolean.TRUE.equals($F{nome_do_campo})` dentro de `<![CDATA[...]]>`. Nunca use `$F{campo} == true` para evitar erro quando o banco retornar `null` ou quando o compilador Java exigir tipo `Boolean` / `boolean` compatível.
7.  **Escapamento XML e Uso Obrigatório de CDATA (`SAXParseException` em caracteres especiais):**
      - Todo conteúdo de `<text>`, `<textFieldExpression>` e `<printWhenExpression>` deve estar obrigatoriamente envelopado em `<![CDATA[...]]>`, evitando que caracteres como `&`, `<`, `>` ou aspas quebrem o parser XML.
8.  **Integridade de Fields e Parameters (`JRValidationException: Field not found`):**
      - Nunca referencie um `$F{...}` ou `$P{...}` que não esteja declarado no topo do `.jrxml` com exatamente a mesma grafia (case-sensitive).
      - Quando o arquivo enviado tiver `<field>` antigos de outra ficha que não existem na `<queryString>` atual, sincronize os `<field>` do arquivo completo com os aliases reais das perguntas na `<queryString>` mais os 36 `<field>` padrão da ficha.
9.  **Fontes Seguras (`JRFontNotFoundException`) e Símbolos Especiais:**
      - Utilize `fontName="SansSerif"` (ou omita `fontName` para herdar o padrão do Jasper), evitando fontes proprietárias não instaladas no servidor Linux/Docker onde o ERP roda.
      - **Atenção a símbolos especiais (`≥`, `±`, etc.):** A renderização depende das fontes instaladas no servidor. Para evitar "quadradinhos" no PDF final, dê preferência a equivalentes ASCII seguros (`>=`, `+/-`) ou alerte o usuário para conferir no preview.
10. **Estilo Padrão dos Marcadores Booleanos:**
      - **Círculos (Rádio):** `<ellipse>` externo (`10x10 px`, `<pen lineWidth="0.75"/>`) + `<ellipse>` interno condicional (`x + 2`, `y + 2`, `6x6 px`, `mode="Opaque"`, `backcolor="#000000"`, `<pen lineWidth="0.0"/>`).
      - **Quadrados (Checkbox):** `<rectangle>` externo (`10x10 px`, `<pen lineWidth="0.75"/>`) + `<rectangle>` interno condicional (`x + 2`, `y + 2`, `6x6 px`, `mode="Opaque"`, `backcolor="#000000"`, `<pen lineWidth="0.0"/>`).

### Fase 4: Validação Automatizada, Entrega Compacta e Troubleshooting Pós-Preview

1.  **Checklist de Validação via Script Python (Obrigatório antes de entregar):**
      - Gere o XML via script no `ds_python_interpreter` e rode uma função de auditoria automática que verifique:
          - Parse completo da árvore XML com `xml.etree.ElementTree.fromstring()`.
          - Verificação de que **100% das tags `<textField>` possuem o atributo `isBlankWhenNull="true"`** e não possuem concatenações inseguras que gerem a string `"null"`.
          - Validação de todos os atributos `uuid` com `uuid.UUID(val)` e garantia de que não há UUIDs duplicados.
          - Verificação de que todos os `$F{...}` usados existem nos `<field>` declarados no `.jrxml`.
          - Verificação matemática em cada `<band>` garantindo que `band_height <= max_available_height`, e que para todo `<reportElement>` vale `x >= 0`, `y >= 0`, `x + width <= columnWidth` e `y + height <= band_height`.
          - Verificação da ordem dos filhos em todos os elementos (`reportElement`, `staticText`, `textField`, `ellipse`, `rectangle`, `box`).
2.  **Padrão de Entrega Compacta (Sem Poluir o Chat):**
      - **NUNCA cole o código XML longo diretamente na mensagem do chat**, pois deixa a interface pesada.
      - Salve sempre dois arquivos no interpretador Python com extensão `.xml` (para que a interface exiba o botão compacto de abrir/visualizar/baixar):
          - `detail_<nome_da_ficha>.xml`: contendo apenas o bloco `<detail>...</detail>` pronto para copiar e colar.
          - `<nome_da_ficha>_completo.xml`: contendo o arquivo `.jrxml` completo e integrado (orientando o usuário a renomear para `.jrxml` se preferir substituir o arquivo inteiro).
      - Inclua as file-tags geradas pelo interpretador na resposta final para disponibilizar os botões de download.
3.  **Troubleshooting Pós-Preview (Jaspersoft Studio):**
      - Ao receber retorno ou print após o Preview no Jaspersoft Studio, oriente e corrija considerando as causas mais comuns:
          - **Campo imprimindo vazio:** geralmente indica divergência exata de nome/label/ordenação entre a query e a ficha gravada, ou ficha de teste preenchida antes de a pergunta existir no template.
          - **Símbolo especial saindo como quadradinho no PDF:** substituir por equivalente ASCII (`>=`, `+/-`).
          - **Texto cortado ou desalinhado:** recalcular largura/altura pela heurística de pixels por caractere (solicitando o print do preview se necessário para ajuste fino).
