select

         ----- CABEÇALHO -----
        (select xx.cnes from estabelecimento xx) AS SOLICITANTE_CNES,
        (select xx.nome_fanta from estabelecimento xx) AS SOLICITANTE,
        'Lorena, '||to_char(max(fc.criacao),'dd/MM/yyyy HH24:mi') data_criacao,

        ----- PERGUNTAS -----


        max(case when pfc.ordenacao = 10 and c.ordenacao = 1 and c.tipo_campo = 'HORA' then TO_CHAR(c.valor_hora, 'HH24:MI') end) as recuperacao_hora,
        coalesce(bool_or(case when pfc.ordenacao = 10 and c.ordenacao = 5 then c.valor_booleano::bool end), false) as acordado,
        coalesce(bool_or(case when pfc.ordenacao = 10 and c.ordenacao = 10 then c.valor_booleano::bool end), false) as sonolento,
        coalesce(bool_or(case when pfc.ordenacao = 10 and c.ordenacao = 15 then c.valor_booleano::bool end), false) as atend_estimulos_verbais,
        coalesce(bool_or(case when pfc.ordenacao = 10 and c.ordenacao = 20 then c.valor_booleano::bool end), false) as nao_atend_estimulos_verbais,

        max(case when pfc.ordenacao = 15 and c.ordenacao = 1 and c.tipo_campo = 'HORA' then TO_CHAR(c.valor_hora, 'HH24:MI') end) as oservo_apos_20_hora,
        max(case when pfc.ordenacao = 15 and c.ordenacao = 5 and c.tipo_campo = 'TEXTO' then c.valor_texto end) as pa,
        max(case when pfc.ordenacao = 15 and c.ordenacao = 10 and c.tipo_campo = 'TEXTO' then c.valor_texto end) as fc,
        max(case when pfc.ordenacao = 15 and c.ordenacao = 15 and c.tipo_campo = 'TEXTO' then c.valor_texto end) as fr,
        max(case when pfc.ordenacao = 15 and c.ordenacao = 20 and c.tipo_campo = 'TEXTO' then c.valor_texto end) as sp02,

        coalesce(bool_or(case when pfc.ordenacao = 16 and c.ordenacao = 5 then c.valor_booleano::bool end), false) as acordado_2,
        coalesce(bool_or(case when pfc.ordenacao = 16 and c.ordenacao = 10 then c.valor_booleano::bool end), false) as sonolento_2,
        coalesce(bool_or(case when pfc.ordenacao = 16 and c.ordenacao = 15 then c.valor_booleano::bool end), false) as atend_estimulos_verbais_2,
        coalesce(bool_or(case when pfc.ordenacao = 16 and c.ordenacao = 20 then c.valor_booleano::bool end), false) as nao_atend_estimulos_verbais_2,

        max(case when pfc.ordenacao = 17 and c.ordenacao = 1 and c.tipo_campo = 'HORA' then TO_CHAR(c.valor_hora, 'HH24:MI') end) as paciente_acordado_respondendo_hora,

        max(case when pfc.ordenacao = 20 and c.ordenacao = 1 and c.tipo_campo = 'HORA' then TO_CHAR(c.valor_hora, 'HH24:MI') end) as paciente_avaliado_liberado_hora,
        coalesce(bool_or(case when pfc.ordenacao = 20 and c.ordenacao = 5 then c.valor_booleano::bool end), false) as liberado_deambulando,
        coalesce(bool_or(case when pfc.ordenacao = 20 and c.ordenacao = 10 then c.valor_booleano::bool end), false) as liberado_cadeiraderodas,
        coalesce(bool_or(case when pfc.ordenacao = 20 and c.ordenacao = 15 then c.valor_booleano::bool end), false) as liberado_maca,

        max(case when pfc.ordenacao = 25 and c.ordenacao = 25 and c.tipo_campo = 'TEXTO' then c.valor_texto end) as intercorrencia,

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
        fc.id = ${id}

 group by p.endereco_endereco, p.endereco_numero, p.endereco_bairro;