# Databricks notebook source
# MAGIC %md
# MAGIC # Exercício 3 — Metric Views (métricas governadas)
# MAGIC Cria `mvw_churn`, `mvw_receita` e `mvw_suporte` no **seu schema pessoal**, lendo da base
# MAGIC compartilhada `dbacademy.churn`. Depois consulte com `MEASURE()`.

# COMMAND ----------

dbutils.widgets.text("schema", "", "Seu schema")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Criar as metric views

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE SCHEMA IF NOT EXISTS IDENTIFIER('dbacademy.' || :schema)

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE VIEW IDENTIFIER('dbacademy.' || :schema || '.mvw_churn') (
# MAGIC   `Segmento`      COMMENT 'Segmento do cliente',
# MAGIC   `Plano`         COMMENT 'Nome do plano',
# MAGIC   `Mês`           COMMENT 'Mês do cancelamento',
# MAGIC   `Cancelamentos` COMMENT 'Assinaturas canceladas',
# MAGIC   `Clientes`      COMMENT 'Total de clientes',
# MAGIC   `Taxa de Churn` COMMENT 'Cancelamentos / Clientes'
# MAGIC ) WITH METRICS LANGUAGE YAML
# MAGIC COMMENT 'Métricas de churn/retenção' AS $$
# MAGIC version: 0.1
# MAGIC source: dbacademy.churn.fato_assinatura
# MAGIC joins:
# MAGIC   - name: cliente
# MAGIC     source: dbacademy.churn.dim_cliente
# MAGIC     'on': source.id_cliente = cliente.id_cliente
# MAGIC   - name: plano
# MAGIC     source: dbacademy.churn.dim_plano
# MAGIC     'on': source.id_plano = plano.id_plano
# MAGIC dimensions:
# MAGIC   - name: Segmento
# MAGIC     expr: cliente.segmento
# MAGIC   - name: Plano
# MAGIC     expr: plano.nome_plano
# MAGIC   - name: Mês
# MAGIC     expr: date_trunc('MONTH', source.data_fim)
# MAGIC measures:
# MAGIC   - name: Cancelamentos
# MAGIC     expr: SUM(source.churn_flag)
# MAGIC   - name: Clientes
# MAGIC     expr: COUNT(DISTINCT source.id_cliente)
# MAGIC   - name: Taxa de Churn
# MAGIC     expr: COUNT(source.churn_flag) / COUNT(DISTINCT source.id_cliente)
# MAGIC $$

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE VIEW IDENTIFIER('dbacademy.' || :schema || '.mvw_receita') (
# MAGIC   `Segmento`      COMMENT 'Segmento do cliente',
# MAGIC   `Mês`           COMMENT 'Competência (mês)',
# MAGIC   `Receita`       COMMENT 'Soma faturada',
# MAGIC   `Inadimplência` COMMENT 'Percentual de faturas não pagas',
# MAGIC   `Ticket Médio`  COMMENT 'Valor médio por fatura'
# MAGIC ) WITH METRICS LANGUAGE YAML
# MAGIC COMMENT 'Métricas de receita' AS $$
# MAGIC version: 0.1
# MAGIC source: dbacademy.churn.fato_faturamento
# MAGIC joins:
# MAGIC   - name: cliente
# MAGIC     source: dbacademy.churn.dim_cliente
# MAGIC     'on': source.id_cliente = cliente.id_cliente
# MAGIC dimensions:
# MAGIC   - name: Segmento
# MAGIC     expr: cliente.segmento
# MAGIC   - name: Mês
# MAGIC     expr: date_trunc('MONTH', source.competencia)
# MAGIC measures:
# MAGIC   - name: Receita
# MAGIC     expr: SUM(source.valor)
# MAGIC   - name: Inadimplência
# MAGIC     expr: AVG(CASE WHEN NOT source.pago THEN 1.0 ELSE 0.0 END)
# MAGIC   - name: Ticket Médio
# MAGIC     expr: AVG(source.valor)
# MAGIC $$

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE VIEW IDENTIFIER('dbacademy.' || :schema || '.mvw_suporte') (
# MAGIC   `Segmento`   COMMENT 'Segmento do cliente',
# MAGIC   `Canal`      COMMENT 'Canal do ticket',
# MAGIC   `Categoria`  COMMENT 'Categoria do ticket',
# MAGIC   `Tickets`    COMMENT 'Quantidade de tickets',
# MAGIC   `CSAT Médio` COMMENT 'CSAT médio (1-5)',
# MAGIC   `NPS Médio`  COMMENT 'NPS médio (0-10)'
# MAGIC ) WITH METRICS LANGUAGE YAML
# MAGIC COMMENT 'Métricas de atendimento' AS $$
# MAGIC version: 0.1
# MAGIC source: dbacademy.churn.fato_ticket_suporte
# MAGIC joins:
# MAGIC   - name: cliente
# MAGIC     source: dbacademy.churn.dim_cliente
# MAGIC     'on': source.id_cliente = cliente.id_cliente
# MAGIC dimensions:
# MAGIC   - name: Segmento
# MAGIC     expr: cliente.segmento
# MAGIC   - name: Canal
# MAGIC     expr: source.canal
# MAGIC   - name: Categoria
# MAGIC     expr: source.categoria
# MAGIC measures:
# MAGIC   - name: Tickets
# MAGIC     expr: COUNT(1)
# MAGIC   - name: CSAT Médio
# MAGIC     expr: AVG(source.csat)
# MAGIC   - name: NPS Médio
# MAGIC     expr: AVG(source.nps)
# MAGIC $$

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Consultar com MEASURE()

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Taxa de churn por segmento
# MAGIC SELECT `Segmento`, ROUND(MEASURE(`Taxa de Churn`), 3) AS taxa_churn
# MAGIC FROM IDENTIFIER('dbacademy.' || :schema || '.mvw_churn')
# MAGIC GROUP BY `Segmento`
# MAGIC ORDER BY taxa_churn DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Receita e inadimplência por segmento
# MAGIC SELECT `Segmento`,
# MAGIC        ROUND(MEASURE(`Receita`), 2)       AS receita,
# MAGIC        ROUND(MEASURE(`Inadimplência`), 3) AS inadimplencia
# MAGIC FROM IDENTIFIER('dbacademy.' || :schema || '.mvw_receita')
# MAGIC GROUP BY `Segmento`
# MAGIC ORDER BY receita DESC

# COMMAND ----------

# MAGIC %sql
# MAGIC -- CSAT e NPS por categoria de ticket
# MAGIC SELECT `Categoria`,
# MAGIC        MEASURE(`Tickets`)              AS tickets,
# MAGIC        ROUND(MEASURE(`CSAT Médio`), 2) AS csat,
# MAGIC        ROUND(MEASURE(`NPS Médio`), 2)  AS nps
# MAGIC FROM IDENTIFIER('dbacademy.' || :schema || '.mvw_suporte')
# MAGIC GROUP BY `Categoria`
# MAGIC ORDER BY tickets DESC

# COMMAND ----------

print(f"✅ Metric views criadas em dbacademy.{dbutils.widgets.get('schema')}")
