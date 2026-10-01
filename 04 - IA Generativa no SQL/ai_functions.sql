-- Exercício 4 — AI Functions (GenAI no SQL)
-- Base compartilhada (somente leitura): dbacademy.churn.fato_ticket_suporte
-- Rode no SQL Editor. As funções chamam um modelo de IA — pode levar alguns segundos por linha.

-- Amostra variada (csat alto, médio e baixo) para ver a IA distinguindo os casos
-- 1) ai_analyze_sentiment — sentimento das reclamações
WITH amostra AS (
  (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 5 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 3 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 1 ORDER BY id_ticket LIMIT 2)
)
SELECT LEFT(texto_reclamacao, 60) AS trecho, csat,
       ai_analyze_sentiment(texto_reclamacao) AS sentimento
FROM amostra ORDER BY csat DESC;

-- 1b) Distribuição de sentimento nos ÚLTIMOS 100 tickets (por data_abertura)
-- A ordenação fixa a amostra: todos os alunos rodam sobre os mesmos 100 registros.
-- Para a base inteira, remova ORDER BY + LIMIT (roda a IA em toda a tabela — mais lento).
SELECT sentimento, COUNT(*) AS qtd
FROM (
  SELECT ai_analyze_sentiment(texto_reclamacao) AS sentimento
  FROM dbacademy.churn.fato_ticket_suporte
  ORDER BY data_abertura DESC
  LIMIT 100
)
GROUP BY sentimento
ORDER BY qtd DESC;

-- 1c) Sentimento com um MODELO ESPECÍFICO via ai_query
--     Troque o endpoint: databricks-meta-llama-3-3-70b-instruct | databricks-gpt-oss-120b | databricks-claude-haiku-4-5
WITH amostra AS (
  (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 5 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 3 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 1 ORDER BY id_ticket LIMIT 2)
)
SELECT csat, LEFT(texto_reclamacao, 60) AS trecho,
       ai_query('databricks-meta-llama-3-3-70b-instruct',
                'Classifique o sentimento como positive, neutral ou negative. Responda apenas com a palavra. Comentário: ' || texto_reclamacao) AS sentimento
FROM amostra ORDER BY csat DESC;

-- 2) ai_classify — classificar o assunto do ticket
WITH amostra AS (
  (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 5 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 3 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 1 ORDER BY id_ticket LIMIT 2)
)
SELECT LEFT(texto_reclamacao, 60) AS trecho, csat,
       ai_classify(texto_reclamacao,
                   ARRAY('Cobrança','Técnico','Cancelamento','Elogio','Dúvida')) AS categoria_ia
FROM amostra ORDER BY csat DESC;

-- 2b) Classificação com um MODELO ESPECÍFICO via ai_query
WITH amostra AS (
  (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 5 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 3 ORDER BY id_ticket LIMIT 2)
  UNION ALL (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 1 ORDER BY id_ticket LIMIT 2)
)
SELECT csat, LEFT(texto_reclamacao, 60) AS trecho,
       ai_query('databricks-gpt-oss-120b',
                'Classifique o assunto em uma destas categorias: Cobrança, Técnico, Cancelamento, Elogio, Dúvida. Responda apenas com a categoria. Comentário: ' || texto_reclamacao) AS categoria
FROM amostra ORDER BY csat DESC;

-- 3) ai_mask — mascarar dados pessoais (PII) no texto
SELECT ai_mask(texto_reclamacao, ARRAY('person','phone','email')) AS texto_anonimizado
FROM dbacademy.churn.fato_ticket_suporte
WHERE texto_reclamacao LIKE '%@%' OR texto_reclamacao LIKE '%-____%'
LIMIT 5;

-- 4) ai_summarize — resumir os últimos 100 comentários (por data_abertura)
--    No exercício, esta consulta é gerada pelo Genie Code (ver README).
SELECT ai_summarize(array_join(collect_list(texto_reclamacao), ' | '), 150) AS resumo
FROM (
  SELECT texto_reclamacao
  FROM dbacademy.churn.fato_ticket_suporte
  ORDER BY data_abertura DESC
  LIMIT 100
);
