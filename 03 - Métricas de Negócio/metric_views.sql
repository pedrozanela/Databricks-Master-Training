-- Exercício 3 — Metric Views
-- Fonte (somente leitura): dbacademy.churn
-- As views são criadas no SEU schema pessoal: substitua <seu_schema> pelo seu database.

-- =====================================================================
-- 1) mvw_churn — métricas de churn/retenção
-- =====================================================================
CREATE OR REPLACE VIEW dbacademy.<seu_schema>.mvw_churn (
  `Segmento`      COMMENT 'Segmento do cliente',
  `Plano`         COMMENT 'Nome do plano',
  `Mês`           COMMENT 'Mês do cancelamento',
  `Cancelamentos` COMMENT 'Assinaturas canceladas',
  `Clientes`      COMMENT 'Total de clientes',
  `Taxa de Churn` COMMENT 'Cancelamentos / Clientes'
) WITH METRICS LANGUAGE YAML
COMMENT 'Métricas de churn/retenção' AS $$
version: 0.1
source: dbacademy.churn.fato_assinatura
joins:
  - name: cliente
    source: dbacademy.churn.dim_cliente
    'on': source.id_cliente = cliente.id_cliente
  - name: plano
    source: dbacademy.churn.dim_plano
    'on': source.id_plano = plano.id_plano
dimensions:
  - name: Segmento
    expr: cliente.segmento
  - name: Plano
    expr: plano.nome_plano
  - name: Mês
    expr: date_trunc('MONTH', source.data_fim)
measures:
  - name: Cancelamentos
    expr: SUM(source.churn_flag)
  - name: Clientes
    expr: COUNT(DISTINCT source.id_cliente)
  - name: Taxa de Churn
    expr: SUM(source.churn_flag) / COUNT(DISTINCT source.id_cliente)
$$;

-- =====================================================================
-- 2) mvw_receita — métricas de receita e inadimplência
-- =====================================================================
CREATE OR REPLACE VIEW dbacademy.<seu_schema>.mvw_receita (
  `Segmento`      COMMENT 'Segmento do cliente',
  `Mês`           COMMENT 'Competência (mês)',
  `Receita`       COMMENT 'Soma faturada',
  `Inadimplência` COMMENT 'Percentual de faturas não pagas',
  `Ticket Médio`  COMMENT 'Valor médio por fatura'
) WITH METRICS LANGUAGE YAML
COMMENT 'Métricas de receita' AS $$
version: 0.1
source: dbacademy.churn.fato_faturamento
joins:
  - name: cliente
    source: dbacademy.churn.dim_cliente
    'on': source.id_cliente = cliente.id_cliente
dimensions:
  - name: Segmento
    expr: cliente.segmento
  - name: Mês
    expr: date_trunc('MONTH', source.competencia)
measures:
  - name: Receita
    expr: SUM(source.valor)
  - name: Inadimplência
    expr: AVG(CASE WHEN NOT source.pago THEN 1.0 ELSE 0.0 END)
  - name: Ticket Médio
    expr: AVG(source.valor)
$$;

-- =====================================================================
-- 3) mvw_suporte — métricas de atendimento
-- =====================================================================
CREATE OR REPLACE VIEW dbacademy.<seu_schema>.mvw_suporte (
  `Segmento`   COMMENT 'Segmento do cliente',
  `Canal`      COMMENT 'Canal do ticket',
  `Categoria`  COMMENT 'Categoria do ticket',
  `Tickets`    COMMENT 'Quantidade de tickets',
  `CSAT Médio` COMMENT 'CSAT médio (1-5)',
  `NPS Médio`  COMMENT 'NPS médio (0-10)'
) WITH METRICS LANGUAGE YAML
COMMENT 'Métricas de atendimento' AS $$
version: 0.1
source: dbacademy.churn.fato_ticket_suporte
joins:
  - name: cliente
    source: dbacademy.churn.dim_cliente
    'on': source.id_cliente = cliente.id_cliente
dimensions:
  - name: Segmento
    expr: cliente.segmento
  - name: Canal
    expr: source.canal
  - name: Categoria
    expr: source.categoria
measures:
  - name: Tickets
    expr: COUNT(1)
  - name: CSAT Médio
    expr: AVG(source.csat)
  - name: NPS Médio
    expr: AVG(source.nps)
$$;

-- =====================================================================
-- Consultando com MEASURE()
-- =====================================================================
-- Taxa de churn por segmento
SELECT `Segmento`, ROUND(MEASURE(`Taxa de Churn`), 3) AS taxa_churn
FROM dbacademy.<seu_schema>.mvw_churn
GROUP BY `Segmento`
ORDER BY taxa_churn DESC;

-- Receita e inadimplência por segmento
SELECT `Segmento`,
       ROUND(MEASURE(`Receita`), 2)       AS receita,
       ROUND(MEASURE(`Inadimplência`), 3) AS inadimplencia
FROM dbacademy.<seu_schema>.mvw_receita
GROUP BY `Segmento`
ORDER BY receita DESC;

-- CSAT e NPS por categoria de ticket
SELECT `Categoria`,
       MEASURE(`Tickets`)             AS tickets,
       ROUND(MEASURE(`CSAT Médio`),2) AS csat,
       ROUND(MEASURE(`NPS Médio`),2)  AS nps
FROM dbacademy.<seu_schema>.mvw_suporte
GROUP BY `Categoria`
ORDER BY tickets DESC;
