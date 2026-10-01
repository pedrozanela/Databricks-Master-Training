# 07 - Análise de Dados com Solução Multi-Agent

![Trilha do Master Training com destaque no que foi construído até o Exercício 07](../assets/07%20-%20arquitetura.gif?v=20260928)

> _Em destaque, o que você já construiu na trilha até este ponto; em cinza, o que ainda vem._

Até aqui, você montou as análises. Agora vamos abrir isso para o time de negócio com os **Genie Agents**: qualquer pessoa pergunta em português (*"qual a receita por segmento?"*) e o Genie escreve o SQL, executa e responde, sem escrever uma linha de código.

E vamos um passo além. Você vai criar dois Genies especializados, um de **Faturamento** e um de **Suporte**, e no fim um **Supervisor** que orquestra os dois. O usuário faz uma pergunta só, e o Supervisor descobre sozinho qual especialista deve responder. É isso que chamamos de solução *multi-agent*.

---

# Parte 1: Genie de Faturamento

## Passo 1: Criar o Genie Agent
1. No menu lateral à esquerda, clique em **Genie Agents**
2. Clique em **New**
3. Em **Connect your data**, adicione:
    - `dbacademy.churn.dim_cliente`
    - `dbacademy.churn.dim_plano`
    - `dbacademy.churn.fato_assinatura`
    - `dbacademy.churn.fato_faturamento`
4. Dê o nome `Faturamento - <seu_schema>`, trocando `<seu_schema>` pelo nome do seu schema

> O Genie infere os relacionamentos entre as tabelas; você não precisa configurar os joins na mão. Vamos reutilizar este Genie Agent na Parte 3, no Supervisor

## Passo 2: Perguntar
Faça as perguntas abaixo, uma por vez:

```text
Qual a receita total por segmento?
```
Resultado esperado:
- Consumidor **R$ 3,62 mi**
- PME **R$ 1,80 mi**
- Corporativo **R$ 680 mil**

```text
Qual o percentual de faturas não pagas por plano?
```
Resultado esperado:
- Básico **7,90%**
- Padrão **6,49%**
- Premium **5,90%**
- Empresarial **5,45%**

A inadimplência acompanha o churn: é pior no Básico.

Note que você não disse de qual tabela vem o dado: o Genie descobre sozinho, mostra o SQL que escreveu e ainda desenha um gráfico.

---

# Parte 2: Genie de Suporte

## Passo 3: Criar o Genie Agent
1. Crie um novo Genie Agent como no Passo 1 (**Genie Agents → New**)
2. Em **Connect your data**, adicione:
    - `dbacademy.churn.dim_cliente`
    - `dbacademy.churn.fato_ticket_suporte`
3. Dê o nome `Suporte - <seu_schema>`, trocando `<seu_schema>` pelo nome do seu schema

## Passo 4: Perguntar
Faça as perguntas abaixo, uma por vez:

```text
Qual o CSAT médio por categoria de ticket?
```
Resultado esperado:
- Dúvida **4,08**
- Cobrança **2,99**
- Técnico **2,28**
- Cancelamento **2,27**

```text
Quantos tickets de suporte temos por canal?
```
Resultado esperado:
- Chat **447**
- Email **407**
- Telefone **399**

## Passo 5: Pergunte sobre o ano fiscal
```text
Qual a média de NPS do ano fiscal de 2024 no estado do Amazonas (AM)?
```
O Genie responde **≈ 7,3**, mas vale ler a explicação dele: *"não há definição de ano fiscal, então interpretei como o ano-calendário (jan–dez de 2024)"*. Ou seja, ele chutou que ano fiscal é o mesmo que ano civil, porque ninguém contou a ele quando começa o seu ano fiscal.

## Passo 6: Ensine a regra e pergunte de novo
1. Abra o menu de configurações do agente em **Configure** no canto superior direito
2. Na aba **Instructions**, cole a regra do seu ano fiscal:
```text
O ano fiscal (AF) da empresa vai de 1º de outubro a 30 de setembro do ano seguinte, identificado pelo ano em que começa. Exemplo: o AF2024 vai de 01/10/2024 a 30/09/2025. Sempre que a pergunta mencionar "ano fiscal", use esse período (com base em data_abertura), nunca o ano-calendário.
```
3. Faça exatamente a mesma pergunta:
```text
Qual a média de NPS do ano fiscal de 2024 no estado do Amazonas (AM)?
```

Desta vez o Genie filtra de **01/10/2024 a 30/09/2025** e responde **≈ 6,5**. É um número diferente porque o período mudou: a mesma pergunta deu duas respostas, e a diferença foi a regra que você forneceu.

> É a mesma ideia da métrica governada do Ex. 3: sem a regra explícita, a IA chuta. As *Instructions* são onde você transforma o conhecimento do negócio em respostas confiáveis, e valem para todos que usam o Genie Agent.

---
