-- Exercício 2 — Geração de Alertas
-- Base compartilhada (somente leitura): dbacademy.churn

-- Alerta principal — Taxa de churn global (%)
-- Condição do alerta: taxa_churn_pct > 25   (valor atual: 27,0 -> dispara)
SELECT ROUND(AVG(churn_flag) * 100, 1) AS taxa_churn_pct
FROM dbacademy.churn.fato_assinatura;

-- Variação — NPS médio dos tickets de suporte
-- Condição do alerta: nps_medio < 7         (valor atual: 6,53 -> dispara)
SELECT ROUND(AVG(nps), 2) AS nps_medio
FROM dbacademy.churn.fato_ticket_suporte;
