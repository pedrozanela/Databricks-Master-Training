# Databricks notebook source
# /// script
# [tool.databricks.environment]
# environment_version = "5"
# ///
# MAGIC %md
# MAGIC # Setup do Workshop — Base de Churn + Habilitação da turma
# MAGIC Rode **1x** como **administrador de conta**. Este notebook faz tudo de uma vez:
# MAGIC 1. **Prepara a turma**: grupo `dbacademy_workshop` (participantes + acessos), catálogo,
# MAGIC    SQL Warehouse, cluster multiuso e as concessões.
# MAGIC 2. **Carrega a base COMPARTILHADA** `<catálogo>.churn` (CSVs → Delta, `feature_churn`,
# MAGIC    comentários + PK/FK, volume de conhecimento) e libera **leitura** dela para a turma.
# MAGIC 3. **Verifica** que cada participante tem o que precisa e que o workspace tem as features
# MAGIC    de IA usadas nos Ex. 4/6/7 (Model Serving/Foundation Model APIs e Multi-Agent Supervisor).
# MAGIC
# MAGIC **É idempotente** (create-if-not-exists + grants idempotentes): seguro re-executar.
# MAGIC
# MAGIC > ⚠️ Rode as **duas primeiras células** para exibir os widgets, selecione os participantes e
# MAGIC > use **Run all**. **Todas as células devem terminar com sucesso.** O veredito final está na
# MAGIC > seção **7. Relatório final** (`✅ CHECKS COMPLETOS`). Se houver ❌/⚠️, corrija e re-execute.
# MAGIC
# MAGIC > Metric views (Ex.3), modelo (Ex.6) e os Genies/Supervisor (Ex.7) são criados por cada aluno
# MAGIC > no schema pessoal `<catálogo>.<seu_schema>` — habilitado aqui via `CREATE SCHEMA`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Parâmetros

# COMMAND ----------

# Conectar e reunir os usuários do workspace que preenchem o seletor de participantes.
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

_PICK_ATT = "(escolha participantes)"
_user_choices = sorted({u.user_name for u in w.users.list(attributes="userName") if u.user_name})
_attendee_opts = [_PICK_ATT] + _user_choices

print(f"Encontrados {len(_user_choices)} usuário(s) do workspace para o seletor de participantes.")
more_than_1024_users = len(_attendee_opts) > 1024
if more_than_1024_users:
    print("⚠️  Esse workspace possui mais usuários do que o suportado pelo widget multisseletor. "
          "Será necessário preencher a lista de participantes manualmente na célula a seguir.")

# COMMAND ----------

# Criar os widgets de entrada.
# (Se você vir "widget already exists with a different type", use Edit -> Clear all widget values
#  uma vez e re-execute esta célula.)
dbutils.widgets.dropdown("create_catalog", "true", ["true", "false"], "1. Criar Catálogo")
dbutils.widgets.dropdown("create_warehouse", "true", ["true", "false"], "2. Criar SQL Warehouse")
dbutils.widgets.dropdown("create_cluster", "true", ["true", "false"], "3. Criar Cluster Multiuso")
if not more_than_1024_users:
    dbutils.widgets.multiselect("attendees", _PICK_ATT, _attendee_opts, "4. Participantes (usuários do workspace)")
else:
    attendees_manual = [
        # preencha essa lista com os emails dos participantes apenas se indicado na célula acima
    ]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ação necessária
# MAGIC Preencha o widget `4. Participantes` com todos os participantes e clique em **Run all**.

# COMMAND ----------

# Convenções fixas para os recursos que este notebook gerencia.
NOME_CATALOGO = "dbacademy"                 # catálogo Unity Catalog de destino
NOME_SCHEMA   = "churn"                      # schema COMPARTILHADO (somente leitura p/ alunos)
GROUP          = "dbacademy_workshop"
WAREHOUSE_NAME = "dbacademy_workshop_wh"
CLUSTER_NAME   = "dbacademy_workshop_cluster"
CSV_BASE = "https://raw.githubusercontent.com/CaduBettanim/Databricks-Master-Training/main/00%20-%20Setup%20and%20teardown/data"
fq = f"{NOME_CATALOGO}.{NOME_SCHEMA}"

CREATE_CATALOG   = dbutils.widgets.get("create_catalog") == "true"
CREATE_WAREHOUSE = dbutils.widgets.get("create_warehouse") == "true"
CREATE_CLUSTER   = dbutils.widgets.get("create_cluster") == "true"
ATTENDEES = ([a.strip() for a in dbutils.widgets.get("attendees").split(",")
              if a.strip() and a.strip() != _PICK_ATT] if not more_than_1024_users else attendees_manual)

if not ATTENDEES:
    dbutils.notebook.exit("⏳ Escolha pelo menos um participante acima e execute 'Run all'.")

def nice_print(resource, resource_name, should_create=None):
    print(f"{resource}:".rjust(16), resource_name.ljust(28),
          f"(criar={should_create})" if should_create is not None else "")
    print("-" * 70)

print("-" * 70)
nice_print("Catálogo", NOME_CATALOGO, CREATE_CATALOG)
nice_print("Base compart.", fq)
nice_print("Grupo", GROUP)
nice_print("Warehouse", WAREHOUSE_NAME, CREATE_WAREHOUSE)
nice_print("Cluster", CLUSTER_NAME, CREATE_CLUSTER)
print(f"Participantes ({len(ATTENDEES)}):".rjust(16), *[f"\t\t- {a}" for a in ATTENDEES], sep="\n")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Funções auxiliares

# COMMAND ----------

import time
from urllib.parse import quote

OK, NO, ERR, NA = "✅", "❌", "⚠️", "➖"

def _sym(v):
    return OK if v is True else (NO if v is False else ERR)

def _acct_scim(method, path, **kw):
    return w.api_client.do(method, f"/api/2.0/account/scim/v2{path}", **kw)

def _acct_user_id(email):
    res = _acct_scim("GET", "/Users", query={"filter": f'userName eq "{email}"'}).get("Resources") or []
    return res[0]["id"] if res else None

def grant_with_retry(sql, attempts=5, delay=3):
    """Tentar novamente uma concessão enquanto UC se atualiza para um principal recém-criado."""
    last = None
    for _ in range(attempts):
        try:
            spark.sql(sql)
            return True
        except Exception as e:
            last = e
            if "PRINCIPAL_DOES_NOT_EXIST" in str(e) or "Could not find principal" in str(e):
                time.sleep(delay)
                continue
            raise
    raise last

def uc_effective_privileges(securable_type, full_name, principal):
    try:
        resp = w.api_client.do(
            "GET",
            f"/api/2.1/unity-catalog/effective-permissions/{securable_type}/{quote(full_name, safe='')}",
            query={"principal": principal})
    except Exception:
        return None
    privs = set()
    for pa in (resp.get("privilege_assignments") or []):
        for p in (pa.get("privileges") or []):
            if p.get("privilege"):
                privs.add(p["privilege"])
    return privs

def uc_has(privs, needed):
    if privs is None:
        return None
    return ("ALL_PRIVILEGES" in privs) or (needed in privs)

def get_user_info(email):
    users = list(w.users.list(filter=f'userName eq "{email}"',
                              attributes="userName,groups,entitlements"))
    if not users:
        return None
    u = users[0]
    groups = {g.display for g in (u.groups or []) if g.display}
    ents = {e.value for e in (u.entitlements or []) if e.value}
    for gname in groups:
        ents |= GROUP_ENTITLEMENTS.get(gname, set())
    return {"groups": groups, "entitlements": ents}

def acl_has_permission(acl, user_email, user_groups, accepted_levels):
    """True = concedido (direto ou via grupo); False = não; None = ACL indisponível."""
    if acl is None:
        return None
    email_l = user_email.lower()
    for entry in acl:
        levels = {p.permission_level.value for p in (entry.all_permissions or []) if p.permission_level}
        if not (levels & accepted_levels):
            continue
        if entry.user_name and entry.user_name.lower() == email_l:
            return True
        if entry.group_name and entry.group_name in user_groups:
            return True
    return False

print("Funções auxiliares definidas.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Preparação da turma (idempotente)

# COMMAND ----------

from databricks.sdk.service.compute import (
    AutoScale, DataSecurityMode, ClusterAccessControlRequest, ClusterPermissionLevel,
)
from databricks.sdk.service.sql import (
    WarehouseAccessControlRequest, WarehousePermissionLevel, CreateWarehouseRequestWarehouseType,
)

print("=" * 70); print("PREPARAÇÃO"); print("=" * 70)

# --- 3a. Grupo do workshop (nível de CONTA, para que Unity Catalog possa conceder) ----
# UC aceita apenas grupos no nível de CONTA como principais de concessão. Um grupo local de
# workspace falha com PRINCIPAL_DOES_NOT_EXIST. Provisionamos um grupo de conta, o atribuímos a
# este workspace e adicionamos os participantes como usuários de conta.
try:
    # Remover qualquer grupo local de workspace remanescente do mesmo nome (evita ambiguidade).
    for _g in w.groups.list(filter=f'displayName eq "{GROUP}"'):
        _meta = w.groups.get(_g.id).meta
        if _meta and _meta.resource_type == "WorkspaceGroup":
            w.groups.delete(_g.id)
            print(f"  removido grupo obsoleto local de workspace '{GROUP}' (id {_g.id}).")

    _found = _acct_scim("GET", "/Groups", query={"filter": f'displayName eq "{GROUP}"'}).get("Resources") or []
    if _found:
        GROUP_ID = _found[0]["id"]
        print(f"{OK} Grupo de conta '{GROUP}' existe (id {GROUP_ID}).")
    else:
        GROUP_ID = _acct_scim("POST", "/Groups",
            body={"schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"], "displayName": GROUP})["id"]
        print(f"{OK} Criado grupo de conta '{GROUP}' (id {GROUP_ID}).")

    # Atribuir o grupo a ESTE workspace (necessário para ACLs de warehouse/cluster + visibilidade).
    w.api_client.do("PUT", f"/api/2.0/preview/permissionassignments/principals/{GROUP_ID}",
                    body={"permissions": ["USER"]})
    print(f"{OK} Grupo atribuído a este workspace.")

    # Adicionar os participantes selecionados (resolvidos para IDs de usuário de CONTA) como membros.
    _existing = {m["value"] for m in (_acct_scim("GET", f"/Groups/{GROUP_ID}").get("members") or [])}
    _to_add = []
    for _email in ATTENDEES:
        _uid = _acct_user_id(_email)
        if not _uid:
            print(f"  {ERR} não encontrado como usuário de conta, não é possível adicionar: {_email}")
            continue
        if _uid not in _existing:
            _to_add.append(_uid)
    if _to_add:
        _acct_scim("PATCH", f"/Groups/{GROUP_ID}",
            body={"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                  "Operations": [{"op": "add", "path": "members",
                                  "value": [{"value": u} for u in _to_add]}]})
    print(f"{OK} Associação ao grupo: {len(_existing)} já membros, {len(_to_add)} adicionados.")

    # Definir os direitos de acesso do workspace NO GRUPO.
    _ws_gid = None
    for _ in range(6):
        _wsg = list(w.groups.list(filter=f'displayName eq "{GROUP}"', attributes="id"))
        if _wsg:
            _ws_gid = _wsg[0].id
            break
        time.sleep(3)
    if _ws_gid:
        w.api_client.do("PATCH", f"/api/2.0/preview/scim/v2/Groups/{_ws_gid}",
            body={"schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                  "Operations": [{"op": "add", "path": "entitlements",
                                  "value": [{"value": "workspace-access"}, {"value": "databricks-sql-access"}]}]})
        print(f"{OK} Direitos de acesso garantidos para '{GROUP}': workspace-access, databricks-sql-access.")
    else:
        print(f"{ERR} Grupo não visível no SCIM do workspace para definir direitos; re-execute para aplicar.")
except Exception as e:
    if any(k in str(e) for k in ("403", "PERMISSION_DENIED")) or "not authorized" in str(e).lower():
        raise RuntimeError(
            "Provisionar o grupo no nível de conta requer ADMIN DE CONTA. Execute como administrador "
            f"de conta, ou no console da conta crie um grupo '{GROUP}', atribua-o a este workspace, "
            "adicione os participantes e re-execute o restante.") from e
    raise

# COMMAND ----------

# --- 3b. Catálogo (lidar com metastore sem armazenamento padrão) -----------
try:
    w.catalogs.get(NOME_CATALOGO)
    print(f"{OK} Catálogo '{NOME_CATALOGO}' existe (criação omitida).")
except Exception as _e:
    if "404" not in str(_e) and "NotFound" not in type(_e).__name__:
        raise  # 403, timeout etc. — não é "catálogo não existe"
    if CREATE_CATALOG:
        try:
            spark.sql(f"CREATE CATALOG IF NOT EXISTS {NOME_CATALOGO}")
            print(f"{OK} Catálogo '{NOME_CATALOGO}' pronto.")
        except Exception as e:
            msg = str(e).lower()
            if any(k in msg for k in ["managed location", "storage location", "default storage",
                                      "location is required", "no metastore storage", "storage root"]):
                raise RuntimeError(
                    f"Catálogo '{NOME_CATALOGO}' não pode ser criado automaticamente: este metastore não "
                    f"tem armazenamento padrão, então precisa de um LOCAL DE GERENCIAMENTO explícito. Crie na "
                    f"mão (Catalog Explorer → Create catalog → Default Storage), ou:\n"
                    f"    CREATE CATALOG {NOME_CATALOGO} MANAGED LOCATION 'gs://<bucket>/<path>';\n"
                    f"depois re-execute com 'Criar Catálogo' = false.") from e
            raise
    else:
        print(f"{NO} Catálogo '{NOME_CATALOGO}' não encontrado e 'Criar Catálogo' = false. Crie-o ou ative a opção.")

# --- 3c. Permissões de catálogo para o grupo (criar schema pessoal do aluno) ---
# Modelo: aluno tem USE CATALOG + CREATE SCHEMA; ao criar seu schema, vira dono (leitura+escrita
# apenas no schema próprio).
try:
    grant_with_retry(f"GRANT USE CATALOG, CREATE SCHEMA ON CATALOG {NOME_CATALOGO} TO `{GROUP}`")
    print(f"{OK} Concedidos USE CATALOG + CREATE SCHEMA em {NOME_CATALOGO} para {GROUP}.")
except Exception as e:
    print(f"{NO} Não foi possível conceder permissões no catálogo '{NOME_CATALOGO}': {e}")

# COMMAND ----------

# --- 3d. SQL Warehouse (Ex. 01, 02, 04, 05, 06) ------------------------------
def ensure_warehouse(name):
    existing = next((x for x in w.warehouses.list() if x.name == name), None)
    if existing:
        return existing.id, "existe"
    try:
        wh = w.warehouses.create(name=name, cluster_size="Small", min_num_clusters=1, max_num_clusters=3,
                                 auto_stop_mins=30, enable_serverless_compute=True,
                                 warehouse_type=CreateWarehouseRequestWarehouseType.PRO)
    except Exception as e:
        if "serverless" not in str(e).lower() and "not supported" not in str(e).lower():
            raise  # quota, auth, naming — não é limitação de serverless
        print("  warehouse serverless falhou; tentando PRO clássico")
        wh = w.warehouses.create(name=name, cluster_size="Small", min_num_clusters=1, max_num_clusters=3,
                                 auto_stop_mins=30, enable_serverless_compute=False,
                                 warehouse_type=CreateWarehouseRequestWarehouseType.PRO)
    return wh.id, "criado"

WAREHOUSE_ID = None
if CREATE_WAREHOUSE:
    try:
        WAREHOUSE_ID, _st = ensure_warehouse(WAREHOUSE_NAME)
        print(f"{OK} Warehouse '{WAREHOUSE_NAME}' {_st} (id {WAREHOUSE_ID}).")
    except Exception as e:
        print(f"{NO} Não foi possível criar o warehouse '{WAREHOUSE_NAME}': {e}")
else:
    WAREHOUSE_ID = next((x.id for x in w.warehouses.list() if x.name == WAREHOUSE_NAME), None)
    print(f"{OK if WAREHOUSE_ID else NO} Warehouse '{WAREHOUSE_NAME}' "
          f"{'encontrado' if WAREHOUSE_ID else 'não encontrado'} (criação omitida).")

if WAREHOUSE_ID:
    try:
        w.warehouses.update_permissions(warehouse_id=WAREHOUSE_ID, access_control_list=[
            WarehouseAccessControlRequest(group_name=GROUP, permission_level=WarehousePermissionLevel.CAN_MANAGE)])
        print(f"{OK} Concedido CAN_MANAGE do warehouse para {GROUP}.")
    except Exception as e:
        print(f"{NO} Não foi possível conceder permissão de warehouse: {e}")

# COMMAND ----------

# --- 3e. Cluster Multiuso (notebooks: Setup, Ex. 03, Ex. 06) -----------------
def ensure_cluster(name):
    existing = next((c for c in w.clusters.list() if c.cluster_name == name), None)
    if existing:
        return existing.cluster_id, "existe"
    # Mesmo tipo de nó p/ driver + workers: consciente da nuvem e evita incompatibilidade ARM/não-ARM.
    _node = w.clusters.select_node_type(min_memory_gb=32, local_disk=True)
    cl = w.clusters.create(
        cluster_name=name,
        spark_version=w.clusters.select_spark_version(latest=True, long_term_support=True),
        node_type_id=_node, driver_node_type_id=_node,
        autoscale=AutoScale(min_workers=2, max_workers=8),
        autotermination_minutes=240,
        data_security_mode=DataSecurityMode.USER_ISOLATION)  # Compartilhado (multi-usuário + UC)
    return cl.cluster_id, "criado"

CLUSTER_ID = None
if CREATE_CLUSTER:
    try:
        CLUSTER_ID, _st = ensure_cluster(CLUSTER_NAME)
        print(f"{OK} Cluster '{CLUSTER_NAME}' {_st} (id {CLUSTER_ID}). Auto-encerra quando ocioso.")
    except Exception as e:
        print(f"{NO} Não foi possível criar o cluster '{CLUSTER_NAME}': {e}")
else:
    CLUSTER_ID = next((c.cluster_id for c in w.clusters.list() if c.cluster_name == CLUSTER_NAME), None)
    print(f"{OK if CLUSTER_ID else NO} Cluster '{CLUSTER_NAME}' "
          f"{'encontrado' if CLUSTER_ID else 'não encontrado'} (criação omitida).")

if CLUSTER_ID:
    try:
        w.clusters.update_permissions(cluster_id=CLUSTER_ID, access_control_list=[
            ClusterAccessControlRequest(group_name=GROUP, permission_level=ClusterPermissionLevel.CAN_ATTACH_TO)])
        print(f"{OK} Concedido CAN_ATTACH_TO do cluster para {GROUP}.")
    except Exception as e:
        print(f"{NO} Não foi possível conceder permissão de cluster: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Base COMPARTILHADA de churn
# MAGIC Lê os CSVs deste repositório (via URL) → tabelas Delta, deriva `feature_churn`, documenta
# MAGIC (comentários + PK/FK) e monta a base de conhecimento. **O sucesso da carga confirma que a
# MAGIC computação tem saída de internet** — os alunos usarão a mesma no Ex. 3.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {fq} COMMENT 'Base compartilhada de churn do Master Training'")

# ## 4.1 Carrega os CSVs (do repositório) → tabelas Delta
import pandas as pd
from pyspark.sql.functions import to_date, col, lower, when, trim

def carrega(nome, dates=(), bools=()):
    pdf = pd.read_csv(f"{CSV_BASE}/{nome}.csv", keep_default_na=False)  # "" em vez de NaN
    df = spark.createDataFrame(pdf)   # numéricos inferidos; datas/bools vêm como string
    for d in dates:  # trata vazio como NULL antes do cast (ANSI: to_date('') estoura)
        df = df.withColumn(d, to_date(when(trim(col(d)) == "", None).otherwise(col(d))))
    for b in bools:
        df = df.withColumn(b, lower(col(b).cast("string")) == "true")
    df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{fq}.{nome}")
    print(f"  {nome:22} {df.count():>6} linhas")

carrega("dim_plano")
carrega("dim_cliente", dates=["data_cadastro"])
carrega("dim_data", dates=["data"], bools=["fim_de_semana"])
carrega("fato_assinatura", dates=["data_inicio", "data_fim"])
carrega("fato_uso", dates=["competencia"])
carrega("fato_faturamento", dates=["competencia"], bools=["pago"])
carrega("fato_ticket_suporte", dates=["data_abertura"])

# COMMAND ----------
# ## 4.2 feature_churn (features comportamentais, sem leakage)
spark.sql(f"""CREATE OR REPLACE TABLE {fq}.feature_churn AS
WITH u AS (SELECT id_cliente, AVG(logins_mes) uso_medio, AVG(horas_uso) horas_medio FROM {fq}.fato_uso GROUP BY id_cliente),
f AS (SELECT id_cliente, AVG(dias_atraso) dias_atraso_medio, AVG(CASE WHEN NOT pago THEN 1.0 ELSE 0.0 END) pct_faturas_atraso FROM {fq}.fato_faturamento GROUP BY id_cliente),
t AS (SELECT id_cliente, AVG(csat) csat_medio, AVG(nps) nps_medio FROM {fq}.fato_ticket_suporte GROUP BY id_cliente)
SELECT c.id_cliente, c.segmento, p.nome_plano, CAST(p.preco_mensal AS DOUBLE) preco_mensal,
 CAST(COALESCE(u.uso_medio,0) AS DOUBLE) uso_medio, CAST(COALESCE(u.horas_medio,0) AS DOUBLE) horas_medio,
 CAST(COALESCE(f.dias_atraso_medio,0) AS DOUBLE) dias_atraso_medio, CAST(COALESCE(f.pct_faturas_atraso,0) AS DOUBLE) pct_faturas_atraso,
 CAST(COALESCE(t.csat_medio,3) AS DOUBLE) csat_medio, CAST(COALESCE(t.nps_medio,7) AS DOUBLE) nps_medio, a.churn_flag
FROM {fq}.dim_cliente c JOIN {fq}.fato_assinatura a ON a.id_cliente=c.id_cliente
JOIN {fq}.dim_plano p ON p.id_plano=a.id_plano
LEFT JOIN u ON u.id_cliente=c.id_cliente LEFT JOIN f ON f.id_cliente=c.id_cliente LEFT JOIN t ON t.id_cliente=c.id_cliente""")

# COMMAND ----------
# ## 4.3 Comentários + constraints (documentação p/ Genie e Discovery)
tabc={"dim_cliente":"Dimensão de clientes.","dim_plano":"Dimensão de planos.","dim_data":"Dimensão calendário.",
 "fato_assinatura":"Assinaturas: uma por cliente, com status e churn.","fato_uso":"Uso mensal por cliente.",
 "fato_faturamento":"Faturamento mensal por cliente.","fato_ticket_suporte":"Tickets de suporte com texto, CSAT e NPS.",
 "feature_churn":"Tabela analítica por cliente (features comportamentais) para o modelo de churn."}
colc={"dim_cliente":{"id_cliente":"Identificador único do cliente","nome_cliente":"Nome do cliente","segmento":"Segmento: Consumidor, PME ou Corporativo","cidade":"Cidade","uf":"Estado (UF)","data_cadastro":"Data de cadastro","canal_aquisicao":"Canal de aquisição","faixa_etaria":"Faixa etária"},
 "dim_plano":{"id_plano":"Identificador do plano","nome_plano":"Nome do plano: Básico, Padrão, Premium ou Empresarial","periodicidade":"Mensal ou Anual","preco_mensal":"Preço mensal em reais"},
 "dim_data":{"data":"Data","ano":"Ano","mes":"Mês","nome_mes":"Nome do mês","trimestre":"Trimestre","dia_semana":"Dia da semana","fim_de_semana":"Fim de semana?"},
 "fato_assinatura":{"id_assinatura":"ID da assinatura","id_cliente":"FK dim_cliente","id_plano":"FK dim_plano","data_inicio":"Início","data_fim":"Cancelamento (nulo se ativa)","status":"Ativa ou Cancelada","motivo_cancelamento":"Motivo do cancelamento","churn_flag":"1 se cancelou (churn), 0 se ativo"},
 "fato_uso":{"id_uso":"ID","id_cliente":"FK dim_cliente","competencia":"Mês de referência","logins_mes":"Logins no mês","horas_uso":"Horas de uso","funcionalidades_usadas":"Funcionalidades usadas"},
 "fato_faturamento":{"id_fatura":"ID","id_cliente":"FK dim_cliente","id_assinatura":"FK assinatura","competencia":"Mês","valor":"Valor em R$","pago":"Pago?","dias_atraso":"Dias de atraso"},
 "fato_ticket_suporte":{"id_ticket":"ID","id_cliente":"FK dim_cliente","data_abertura":"Abertura","canal":"Chat, Email ou Telefone","categoria":"Cobrança, Técnico, Cancelamento ou Dúvida","texto_reclamacao":"Texto do contato (pode conter PII)","csat":"Satisfação 1-5","nps":"NPS 0-10"}}
for t,c in tabc.items(): spark.sql(f"COMMENT ON TABLE {fq}.{t} IS '{c}'")
for t,cols in colc.items():
    for cc,cm in cols.items(): spark.sql(f"ALTER TABLE {fq}.{t} ALTER COLUMN {cc} COMMENT '{cm}'")
def _run(s):
    try: spark.sql(s)
    except Exception as e: print("skip:", str(e)[:70])
_run(f"ALTER TABLE {fq}.dim_cliente ALTER COLUMN id_cliente SET NOT NULL")
_run(f"ALTER TABLE {fq}.dim_plano ALTER COLUMN id_plano SET NOT NULL")
_run(f"ALTER TABLE {fq}.dim_cliente ADD CONSTRAINT pk_cliente PRIMARY KEY (id_cliente)")
_run(f"ALTER TABLE {fq}.dim_plano ADD CONSTRAINT pk_plano PRIMARY KEY (id_plano)")
for t in ["fato_assinatura","fato_uso","fato_faturamento","fato_ticket_suporte"]:
    _run(f"ALTER TABLE {fq}.{t} ADD CONSTRAINT fk_{t}_cli FOREIGN KEY (id_cliente) REFERENCES {fq}.dim_cliente(id_cliente) NOT ENFORCED RELY")

# COMMAND ----------
# ## 4.4 Base de conhecimento (volume + documentos)
spark.sql(f"CREATE VOLUME IF NOT EXISTS {fq}.kb_volume COMMENT 'Base de conhecimento de retenção'")
docs={
"FAQ_Atendimento.md":"# FAQ de Atendimento\n\n## Cancelamento\n- Como cancelar? Em Conta > Assinatura > Cancelar, ou com o Customer Success.\n- Multa? Planos mensais não têm; anuais têm multa proporcional aos meses restantes.\n\n## Reembolso\n- Até 7 dias após a cobrança (arrependimento) ou falha comprovada. Anual: reembolso proporcional.\n\n## Cobrança\n- Vencimento dia 10. Atraso acima de 20 dias suspende o serviço.\n\n## Suporte\n- Chat 24/7, Email e Telefone (seg-sex 8h-20h).\n",
"Politica_Retencao.md":"# Política de Retenção e Cancelamento\n\n## Ofertas autorizadas\n- Preço: até 20% de desconto por 3 meses OU upgrade grátis por 1 mês.\n- Atendimento/Insatisfação: atendimento prioritário 60 dias + gerente de contas.\n- Concorrência: match de preço por até 6 meses.\n- Corporativo: revisão contratual, desconto por volume e SLA dedicado.\n\n## Regras\n- Descontos acima de 20% exigem aprovação do gestor de CS.\n- Cliente de alto risco (score do modelo) deve ser contatado em até 48h.\n",
"Playbook_Customer_Success.md":"# Playbook de Customer Success\n\n## Priorização\n1. Alto valor (Premium/Empresarial) com risco alto.\n2. Queda de uso > 40% no trimestre.\n3. Faturas em atraso e CSAT < 3.\n\n## Fluxo\n1. Detectar risco. 2. Diagnosticar causa. 3. Selecionar oferta (Política). 4. Contatar e registrar. 5. Acompanhar 90 dias.\n"}
import os
base=f"/Volumes/{NOME_CATALOGO}/{NOME_SCHEMA}/kb_volume"
for nome,conteudo in docs.items():
    with open(f"{base}/{nome}","w") as fp: fp.write(conteudo)
print("KB:", os.listdir(base))

# COMMAND ----------

# --- 4.5 Liberar LEITURA da base compartilhada para a turma ------------------
# Modelo: alunos têm apenas leitura em {fq} (sem MODIFY, CREATE TABLE, etc.).
try:
    grant_with_retry(f"GRANT USE SCHEMA, SELECT ON SCHEMA {fq} TO `{GROUP}`")
    print(f"{OK} Concedidos USE SCHEMA + SELECT (somente leitura) em {fq} para {GROUP}.")
    try:
        grant_with_retry(f"GRANT READ VOLUME ON VOLUME {fq}.kb_volume TO `{GROUP}`")
        print(f"{OK} Concedido READ VOLUME em {fq}.kb_volume para {GROUP}.")
    except Exception as ve:
        print(f"{ERR} Não foi possível conceder READ VOLUME (volume pode não existir ainda): {ve}")
except Exception as e:
    print(f"{NO} Não foi possível conceder leitura da base compartilhada: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Verificação: matriz de permissões por participante
# MAGIC | Coluna | Requisito | Necessário por |
# MAGIC |---|---|---|
# MAGIC | Acesso ao workspace | `workspace-access` | Todos |
# MAGIC | Databricks SQL | `databricks-sql-access` | 01, 02, 04, 05, 06 |
# MAGIC | USE CATALOG | `USE CATALOG` no catálogo | Todos |
# MAGIC | CREATE SCHEMA | `CREATE SCHEMA` no catálogo (schema pessoal) | 01, 03, 07 |
# MAGIC | Base churn READ | `SELECT` no schema `churn` compartilhado | 01-07 |
# MAGIC | Warehouse CAN USE | `CAN_USE` no SQL Warehouse | 01, 02, 04, 05, 06 |
# MAGIC | Cluster CAN ATTACH | `CAN_ATTACH_TO` no cluster | 00, 03, 07 (notebooks) |

# COMMAND ----------

# Reconstruir o mapa de grupo->direitos DEPOIS da preparação para refletir o novo grupo.
GROUP_ENTITLEMENTS = {}
for g in w.groups.list(attributes="displayName,entitlements"):
    if g.display_name:
        GROUP_ENTITLEMENTS[g.display_name] = {e.value for e in (g.entitlements or []) if e.value}

WAREHOUSE = next((x for x in w.warehouses.list() if x.name == WAREHOUSE_NAME), None)
CLUSTER = next((c for c in w.clusters.list() if c.cluster_name == CLUSTER_NAME), None)
try:
    WAREHOUSE_ACL = w.warehouses.get_permissions(warehouse_id=WAREHOUSE.id).access_control_list if WAREHOUSE else None
except Exception:
    WAREHOUSE_ACL = None
try:
    CLUSTER_ACL = w.clusters.get_permissions(cluster_id=CLUSTER.cluster_id).access_control_list if CLUSTER else None
except Exception:
    CLUSTER_ACL = None

# Grants recém-aplicados levam alguns segundos para chegar ao UC; pesquisa breve evita ❌ falsos.
for _ in range(6):
    _p = uc_effective_privileges("catalog", NOME_CATALOGO, ATTENDEES[-1])
    if _p and ("USE_CATALOG" in _p or "ALL_PRIVILEGES" in _p):
        break
    time.sleep(3)

import pandas as pd
COLUMNS = ["Acesso ao workspace", "Databricks SQL", "USE CATALOG", "CREATE SCHEMA",
           "Base churn READ", "Warehouse CAN USE", "Cluster CAN ATTACH"]
matrix_rows, detail_rows = {}, []

def note(email, col, symbol, message):
    if symbol in (NO, ERR):
        detail_rows.append({"Participante": email, "Verificação": col, "Status": symbol, "Detalhe": message})

for email in ATTENDEES:
    row = {c: NA for c in COLUMNS}
    info = get_user_info(email)
    if info is None:
        matrix_rows[email] = {c: ERR for c in COLUMNS}
        detail_rows.append({"Participante": email, "Verificação": "(pesquisa de usuário)", "Status": ERR,
                            "Detalhe": "Usuário não encontrado no workspace (SCIM)."})
        continue
    groups, ents = info["groups"], info["entitlements"]

    row["Acesso ao workspace"] = OK if "workspace-access" in ents else NO
    note(email, "Acesso ao workspace", row["Acesso ao workspace"], "Direito 'workspace-access' faltando")
    row["Databricks SQL"] = OK if "databricks-sql-access" in ents else NO
    note(email, "Databricks SQL", row["Databricks SQL"], "Direito 'databricks-sql-access' faltando")

    cat_privs = uc_effective_privileges("catalog", NOME_CATALOGO, email)
    for _col, priv in [("USE CATALOG", "USE_CATALOG"), ("CREATE SCHEMA", "CREATE_SCHEMA")]:
        res = uc_has(cat_privs, priv)
        row[_col] = OK if res else (NO if res is False else ERR)
        if res is False:
            note(email, _col, NO, f"Nenhum {priv} no catálogo '{NOME_CATALOGO}'")
        elif res is None:
            note(email, _col, ERR, f"Não foi possível ler permissões no catálogo '{NOME_CATALOGO}'")

    sch_privs = uc_effective_privileges("schema", fq, email)
    res = uc_has(sch_privs, "SELECT")
    row["Base churn READ"] = OK if res else (NO if res is False else ERR)
    if res is False:
        note(email, "Base churn READ", NO, f"Nenhum SELECT no schema '{fq}'")
    elif res is None:
        note(email, "Base churn READ", ERR, f"Não foi possível ler permissões no schema '{fq}'")

    ok = acl_has_permission(WAREHOUSE_ACL, email, groups, {"CAN_USE", "CAN_MANAGE"})
    row["Warehouse CAN USE"] = OK if ok else (NO if ok is False else ERR)
    if ok is False:
        note(email, "Warehouse CAN USE", NO, f"Nenhum CAN_USE no warehouse '{WAREHOUSE_NAME}'")
    elif ok is None:
        note(email, "Warehouse CAN USE", ERR, f"Warehouse '{WAREHOUSE_NAME}' não encontrado / ACL ilegível")

    ok = acl_has_permission(CLUSTER_ACL, email, groups, {"CAN_ATTACH_TO", "CAN_RESTART", "CAN_MANAGE"})
    row["Cluster CAN ATTACH"] = OK if ok else (NO if ok is False else ERR)
    if ok is False:
        note(email, "Cluster CAN ATTACH", NO, f"Nenhum CAN_ATTACH_TO no cluster '{CLUSTER_NAME}'")
    elif ok is None:
        note(email, "Cluster CAN ATTACH", ERR, f"Cluster '{CLUSTER_NAME}' não encontrado / ACL ilegível")

    matrix_rows[email] = row

matrix_df = pd.DataFrame.from_dict(matrix_rows, orient="index", columns=COLUMNS)
matrix_df.index.name = "Participante"
print(f"Verificados {len(ATTENDEES)} participante(s). Legenda: {OK} ok  {NO} ausente  {ERR} indeterminado  {NA} n/a")
display(matrix_df.reset_index())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5b. Detalhes: apenas falhas e avisos

# COMMAND ----------

if detail_rows:
    display(pd.DataFrame(detail_rows, columns=["Participante", "Verificação", "Status", "Detalhe"]))
else:
    print("Sem falhas ou avisos. Todos os participantes têm todas as permissões verificadas. 🎉")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Features de IA do workspace
# MAGIC Features do **workspace inteiro** (não por participante), necessárias para os Ex. 4, 6 e 7:
# MAGIC | Feature | Sinal | Necessária por |
# MAGIC |---|---|---|
# MAGIC | Model Serving / Foundation Model APIs | `serving_endpoints.list()` funciona vs `NotFound` | 4 (AI Functions) |
# MAGIC | Endpoints do `ai_query` (Ex. 4) | `databricks-meta-llama-3-3-70b-instruct` e `databricks-gpt-oss-120b` presentes na lista | 4 (passos 1c, 2b) |
# MAGIC | Multi-Agent Supervisor (Agent Bricks) | co-gated com Knowledge Assistant (`GET /knowledge-assistants` responde vs 404) | 7 (Supervisor) |
# MAGIC
# MAGIC > O registro do modelo no UC (Ex. 6) usa o Model Registry do Unity Catalog — inerente a
# MAGIC > workspaces com UC, sem probe dedicado. Ex. 6 **não** cria endpoint de serving.

# COMMAND ----------

# O `list` do Multi-Agent Supervisor responde [] mesmo em regiões sem a feature, então não serve de
# gate; derivamos MAS do Knowledge Assistant (co-gated, cujo 404 é sinal limpo). Cliente com timeout
# curto para o probe não pendurar o notebook por minutos em regiões sem a feature.
from databricks.sdk.core import Config
try:
    w_probe = WorkspaceClient(config=Config(http_timeout_seconds=5, retry_timeout_seconds=5))
except Exception:
    w_probe = w

def _feature_probe(path, attempts=2):
    """True = API servida; False = indisponível (404 ou timeout); None = indeterminado."""
    last = None
    for _i in range(attempts):
        try:
            w_probe.api_client.do("GET", path)
            return True
        except Exception as e:
            s, tn = str(e), type(e).__name__
            if "Timeout" in tn or "Timed out" in s:
                last = False; continue  # região sem a feature (ou blip transitório: tenta de novo)
            if "NotFound" in tn or "404" in s:
                return False  # API não servida — feature não habilitada
            if "403" in s or "PERMISSION_DENIED" in s or "not authorized" in s.lower():
                return None  # sem permissão para verificar — feature provavelmente existe
            return None  # indeterminado
    return last

# O Ex. 4 executa ai_query contra estes endpoints (passos 1c e 2b). Se não estiverem provisionados
# na região/workspace, o exercício falha — então verificamos que existem, não só que a API responde.
EX4_QUERY_ENDPOINTS = ["databricks-meta-llama-3-3-70b-instruct", "databricks-gpt-oss-120b"]
EX4_OPTIONAL = ["databricks-claude-haiku-4-5"]  # 3ª opção citada no Ex. 4 (não executada por padrão)

SERVING_OK, _ep_ready = False, {}
try:
    for e in w.serving_endpoints.list():
        _ep_ready[e.name] = getattr(getattr(getattr(e, "state", None), "ready", None), "value", None)
    SERVING_OK = True  # a API respondeu (região sem serving devolve NotFound)
except Exception as e:
    print(f"{NO} Model Serving indisponível neste workspace ({type(e).__name__}).")

_missing_ex4 = [n for n in EX4_QUERY_ENDPOINTS if n not in _ep_ready]
EX4_OK = SERVING_OK and not _missing_ex4
if SERVING_OK and _missing_ex4:
    print(f"{NO} Endpoints do Ex. 4 ausentes (o ai_query como está escrito vai falhar): {', '.join(_missing_ex4)}")
_opt = [n for n in EX4_OPTIONAL if n in _ep_ready]
print(f"ℹ️  Opção adicional do Ex. 4 presente: {', '.join(_opt) if _opt else 'nenhuma (databricks-claude-haiku-4-5)'}")

KA_OK = _feature_probe("/api/2.1/knowledge-assistants")
MAS_OK = KA_OK  # co-gated com KA

feature_report = [
    ("Model Serving / Foundation Model APIs — AI Functions (Ex. 4)", SERVING_OK),
    ("Endpoints do ai_query do Ex. 4 (llama-3-3-70b + gpt-oss-120b)", EX4_OK),
    ("Multi-Agent Supervisor / Agent Bricks (Ex. 7)", MAS_OK),
]
print(f"Features de IA. Legenda: {OK} disponível  {NO} indisponível  {ERR} indeterminado")
display(pd.DataFrame([{"Feature": _l, "Status": _sym(_v)} for _l, _v in feature_report],
                     columns=["Feature", "Status"]))

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Relatório final
# MAGIC Um único ✅ / ❌ por item preparado ou verificado (⚠️ = não foi possível determinar).
# MAGIC Inclui as features de IA da seção 6: se qualquer uma faltar, o ambiente é NÃO PRONTO.

# COMMAND ----------

def _group_has_uc(securable_type, full_name, group, needed):
    try:
        r = w.api_client.do("GET",
            f"/api/2.1/unity-catalog/permissions/{securable_type}/{quote(full_name, safe='')}",
            query={"principal": group})
        privs = {p for pa in (r.get("privilege_assignments") or []) for p in (pa.get("privileges") or [])}
        return ("ALL_PRIVILEGES" in privs) or needed.issubset(privs)
    except Exception:
        return None

def _group_in_acl(acl, group, levels):
    if acl is None:
        return None
    for e in acl:
        if e.group_name == group and (
                {p.permission_level.value for p in (e.all_permissions or []) if p.permission_level} & levels):
            return True
    return False

def _account_group_exists(group):
    try:
        return len(_acct_scim("GET", "/Groups", query={"filter": f'displayName eq "{group}"'}).get("Resources") or []) > 0
    except Exception:
        return None

# Relatório de validação da base (valores exatos esperados: 2000 / 1253 / 0.27 / -0.504 / 0.125)
try:
    rep = spark.sql(f"""SELECT
     (SELECT COUNT(*) FROM {fq}.dim_cliente) clientes,
     (SELECT COUNT(*) FROM {fq}.fato_ticket_suporte) tickets,
     (SELECT ROUND(AVG(churn_flag),3) FROM {fq}.fato_assinatura) taxa_churn,
     (SELECT ROUND(corr(uso_medio, churn_flag),3) FROM {fq}.feature_churn) corr_uso_churn,
     (SELECT ROUND(corr(dias_atraso_medio, churn_flag),3) FROM {fq}.feature_churn) corr_atraso_churn""").first()
    display(spark.createDataFrame([rep]))
    _base_ok = (rep["clientes"] == 2000 and rep["tickets"] == 1253 and
                round(rep["taxa_churn"], 3) == 0.27 and
                round(rep["corr_uso_churn"], 3) == -0.504 and
                round(rep["corr_atraso_churn"], 3) == 0.125)
except Exception as _e:
    print(f"{NO} Não foi possível validar a base (tabela ausente?): {_e}")
    _base_ok = False

try:
    w.catalogs.get(NOME_CATALOGO); _catalog_exists = True
except Exception:
    _catalog_exists = False

_schema_grants = _group_has_uc("schema", fq, GROUP, {"USE_SCHEMA", "SELECT"})
_volume_grants = _group_has_uc("volume", f"{fq}.kb_volume", GROUP, {"READ_VOLUME"})
if ATTENDEES:
    _det_statuses = {d["Status"] for d in detail_rows}
    _attendees_ok = False if NO in _det_statuses else (None if ERR in _det_statuses else True)
else:
    _attendees_ok = None

report = [
    ("Grupo do workshop existe e foi atribuído", _account_group_exists(GROUP)),
    ("Direitos do grupo (workspace + Databricks SQL)", {"workspace-access", "databricks-sql-access"}.issubset(GROUP_ENTITLEMENTS.get(GROUP, set()))),
    ("Catálogo existe", _catalog_exists),
    ("Permissões do catálogo p/ grupo (USE CATALOG + CREATE SCHEMA)", _group_has_uc("catalog", NOME_CATALOGO, GROUP, {"USE_CATALOG", "CREATE_SCHEMA"})),
    ("Base churn carregada (2000 clientes / 1253 tickets / churn 0.27)", _base_ok),
    ("Leitura da base churn p/ grupo (USE SCHEMA + SELECT, somente leitura)", _schema_grants),
    ("Leitura do volume kb_volume p/ grupo (READ VOLUME)", _volume_grants),
    ("SQL Warehouse existe", WAREHOUSE is not None),
    ("CAN_USE de warehouse concedido ao grupo", _group_in_acl(WAREHOUSE_ACL, GROUP, {"CAN_USE", "CAN_MANAGE"})),
    ("Cluster Multiuso existe", CLUSTER is not None),
    ("CAN_ATTACH_TO de cluster concedido ao grupo", _group_in_acl(CLUSTER_ACL, GROUP, {"CAN_ATTACH_TO", "CAN_MANAGE"})),
    (f"Todos os {len(ATTENDEES)} participante(s) passam em todas as verificações", _attendees_ok),
]
report += feature_report  # features de IA (seção 6) bloqueiam o veredito

_all_ok = all(v is True for _, v in report)
print("=" * 70)
if _all_ok:
    print(f"{OK} CHECKS COMPLETOS: base compartilhada carregada e todos os {len(ATTENDEES)} participante(s) "
          f"habilitados. Ambiente pronto — pode iniciar o treinamento. 🎉")
else:
    print(f"{NO} AMBIENTE NÃO PRONTO: um ou mais itens estão ❌/⚠️ abaixo. Corrija a causa e re-execute "
          f"o notebook inteiro antes do treinamento (detalhes por participante na seção 5b).")
print("=" * 70)
display(pd.DataFrame([{"Item": label, "Status": _sym(val)} for label, val in report], columns=["Item", "Status"]))
