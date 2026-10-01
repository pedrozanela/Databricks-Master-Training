# 04 - IA Generativa no SQL

![Trilha do Master Training com destaque no que foi construído até o Exercício 04](../assets/04%20-%20arquitetura.gif?v=20260928)

> _Em destaque, o que você já construiu na trilha até este ponto; em cinza, o que ainda vem._

Vamos aplicar **IA Generativa direto no SQL** sobre o texto dos tickets de suporte (a "voz do cliente"), sem treinar modelo e sem sair do SQL Editor.

> Você pode encontrar todas as consultas usadas aqui em [`ai_functions.sql`](./ai_functions.sql)

## Objetivo
Usar as **AI Functions** do Databricks para analisar o campo `texto_reclamacao` da tabela `fato_ticket_suporte`:
- `ai_analyze_sentiment`: sentimento (positive / neutral / negative)
- `ai_classify`: classificar o assunto do ticket
- `ai_mask`: mascarar dados pessoais (PII)
- `ai_summarize`: resumir as principais dores

> As funções chamam um modelo de IA, então podem levar alguns segundos por linha. Por isso as consultas usam `LIMIT`

---

## Passo 0: Abrir o SQL Editor
1. No menu lateral à esquerda, selecione **SQL Editor**
2. Você já deverá ser direcionado ao editor com uma query, caso contrário, crie uma através de **SQL Query** abaixo de **Create New**

Para cada consulta deste exercício, copie a consulta clicando no ícone de dois quadrados no canto do bloco, cole no SQL Editor e rode.

## Passo 1: Análise de sentimento

### 1a. Sentimento com `ai_analyze_sentiment`
```sql
WITH amostra AS (
    ( SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 5 ORDER BY id_ticket LIMIT 2)
    UNION ALL
    ( SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 3 ORDER BY id_ticket LIMIT 2)
    UNION ALL
    ( SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 1 ORDER BY id_ticket LIMIT 2)
)
SELECT
    LEFT(texto_reclamacao, 60) AS trecho,
    csat,
    ai_analyze_sentiment(texto_reclamacao) AS sentimento
FROM amostra
ORDER BY csat DESC;
```
Resultado:
- `csat 5 → positive`
- `csat 3 → neutral`
- `csat 1 → negative`

O sentimento acompanha a nota.

> **Dica:** usamos uma amostra variada (csat 5, 3 e 1) de propósito, para ver a IA distinguindo os casos. Se você ordenar só pelos piores tickets, tudo volta negativo. O `ORDER BY id_ticket` garante que toda a turma veja os **mesmos** tickets: sem ele, o `LIMIT 2` pega linhas quaisquer, e alguns tickets de csat 3 têm texto positivo ("Estou satisfeito...").

### 1b. Distribuição de sentimento com Genie Code (últimos 100)
Agora vamos pedir o SQL ao Genie Code em vez de escrevê-lo:
1. Abra o Genie Code clicando na lâmpada no canto superior direito
2. Cole o prompt abaixo
3. Revise o SQL gerado e execute
```text
Usando a tabela dbacademy.churn.fato_ticket_suporte, escreva uma consulta que aplique ai_analyze_sentiment na coluna texto_reclamacao dos últimos 100 tickets (por data_abertura) e conte quantos são positivos, neutros e negativos.
```

<details>
<summary>👉 Resultado esperado:</summary>

```sql
SELECT
    sentimento,
    COUNT(*) AS qtd
FROM (
    SELECT
        ai_analyze_sentiment(texto_reclamacao) AS sentimento
    FROM dbacademy.churn.fato_ticket_suporte
    ORDER BY data_abertura DESC
    LIMIT 100
)
GROUP BY sentimento
ORDER BY qtd DESC;
```

</details>

Resultado esperado (últimos 100), podendo variar 1–2 por ser IA:
- **~32** positive
- **~36** neutral
- **~32** negative

> O texto livre virou um indicador contável, e você gerou a consulta só descrevendo o que queria


## Passo 2: Classificação

### 2a. Classificação com `ai_classify`
```sql
WITH amostra AS (
    (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 5 ORDER BY id_ticket LIMIT 2)
    UNION ALL
    (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 3 ORDER BY id_ticket LIMIT 2)
    UNION ALL
    (SELECT texto_reclamacao, csat FROM dbacademy.churn.fato_ticket_suporte WHERE csat = 1 ORDER BY id_ticket LIMIT 2)
)
SELECT
    LEFT(texto_reclamacao, 60) AS trecho,
    csat,
    ai_classify(texto_reclamacao, ARRAY('Cobrança','Técnico','Cancelamento','Elogio','Dúvida')) AS categoria_ia
FROM amostra
ORDER BY csat DESC;
```
A IA lê o texto livre e escolhe uma das categorias que você definiu (ex.: elogio → `Elogio`, "já pedi cancelamento…" → `Cancelamento`).


## Passo 3: Mascaramento de PII com `ai_mask`
```sql
SELECT
    ai_mask(texto_reclamacao, ARRAY('person','phone','email')) AS texto_anonimizado
FROM dbacademy.churn.fato_ticket_suporte
WHERE texto_reclamacao LIKE '%@%' OR texto_reclamacao LIKE '%-____%'
LIMIT 5;
```
Ex.: *"Meu email é c00015@exemplo.com.br e ainda não recebi retorno."* → *"Meu email é **[MASKED]** e ainda não recebi retorno."*

Ótimo para compartilhar dados de suporte sem expor informações pessoais: um gancho com a governança do Unity Catalog.

## Passo 4: Resumo dos comentários com Genie Code e `ai_summarize`
Novamente, vamos pedir o SQL ao Genie Code:
1. Abra o Genie Code clicando na lâmpada no canto superior direito
2. Cole o prompt abaixo
3. Revise o SQL gerado e execute
```text
Usando a tabela dbacademy.churn.fato_ticket_suporte, gere uma consulta que pegue os últimos 100 comentários e use ai_summarize para resumir o que os clientes estão dizendo.
```

<details>
<summary>👉 Resultado esperado:</summary>

```sql
SELECT
    ai_summarize(array_join(collect_list(texto_reclamacao), ' | '), 150) AS resumo
FROM (
    SELECT
        texto_reclamacao
    FROM dbacademy.churn.fato_ticket_suporte
    ORDER BY data_abertura DESC
    LIMIT 100
);
```

</details>

Retorna algo como:
> *"Os últimos 100 tickets revelam que os clientes relatam principalmente problemas com atendimento, cobranças indevidas e instabilidade do serviço, mas também há registros de elogios ao suporte e atendimento de qualidade."*

Em vez de ler 100 tickets, você tem o panorama em um parágrafo, e gerou a consulta só descrevendo o que queria.

---

## 🎯 Desafio
Você está recebendo muitos comentários negativos e isso está impactando a relação com seus clientes. Mostre como você pode selecionar 50 comentários negativos e gerar respostas para eles.

**Dica:** Genie Code + AI Functions 😉

Esperado: uma consulta que seleciona 50 comentários com `ai_analyze_sentiment(...) = 'negative'` (use `LIMIT 50`) e redige uma resposta de atendimento. O resultado traz, por linha, o comentário original e a resposta sugerida, pronta para revisão.

## Explore
As AI Functions transformam texto livre em dados estruturados: sentimento e categoria viram colunas que você pode agregar, filtrar e cruzar com churn.
