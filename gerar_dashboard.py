import psycopg2
import pandas as pd
import json
import calendar
import html as htmlmod
from datetime import datetime, date, timedelta

HOST = "aws-0-sa-east-1.pooler.supabase.com"
PORT = 5432
DATABASE = "postgres"
USER = "analista_bi.cuofycgznnbtpotybpuu"
PASSWORD = "marvao#37m"

try:
    conn = psycopg2.connect(host=HOST, port=PORT, database=DATABASE, user=USER, password=PASSWORD)
    print("✅ Conectado.")
except Exception as e:
    print(f"❌ Erro: {e}"); raise e

def safe_read(query, default=None):
    try: return pd.read_sql(query, conn)
    except Exception as err:
        print(f"⚠️ Query falhou: {err}")
        return pd.DataFrame() if default is None else default

def jd(obj): return json.dumps(obj, ensure_ascii=False, default=str)
def n(v, d=0):
    try: return float(v)
    except: return d

def fmt(v):
    try: return f"{float(v):,.2f}".replace(",","X").replace(".",",").replace("X",".")
    except: return "0,00"

MESES_COLS = ['2026-04','2026-05','2026-06','2026-07','2026-08']
MESES_NOMES = {'2026-04':'Abr/26','2026-05':'Mai/26','2026-06':'Jun/26','2026-07':'Jul/26','2026-08':'Ago/26'}

def tendencia(vals):
    v = [x for x in vals if x is not None]
    if not v: return ("❓","S/DADOS","nd")
    if all(x == 0 for x in v): return ("⚫","SEM REGISTRO","zero")
    if v[-1] == 0 and any(x > 0 for x in v[:-1]): return ("🔴","REGREDIU TOTAL","crit")
    if len(v) < 2: return ("➡️","S/HISTÓRICO","nd")
    diff = v[-1] - v[-2]
    if diff <= -15: return ("🔴","EM QUEDA FORTE","crit")
    if diff <= -5: return ("🟠","EM QUEDA","warn")
    if diff >= 10: return ("🟢","MELHORANDO","ok")
    if diff >= 3: return ("🟡","LEVE MELHORA","stab")
    return ("➡️","ESTÁVEL","stab")

def score_gargalo(vals, suspeitas_total, total_escalas):
    v = [x for x in vals if x is not None]
    if not v: return 0
    ultimo = v[-1]
    penultimo = v[-2] if len(v) >= 2 else v[-1]
    queda = max(0, penultimo - ultimo)
    pct_susp = (suspeitas_total / max(total_escalas, 1)) * 100
    return round((100 - ultimo) * 0.5 + queda * 0.3 + pct_susp * 0.2, 1)

# ─── QUERIES ──────────────────────────────────────────────────────────────────

# ─── BASE OPERACIONAL DO PAINEL EXECUTIVO ─────────────────────────────────────
# O Painel Executivo é orientado a ROTAS/EXECUÇÕES, não a contratos.
# Total analisado = registros de rotas_escalarota não anulados no período.
# Concluída = início + fim registrados.
# Em andamento = início registrado e fim ainda vazio.
# Não executada = sem início de execução.
#
# A coluna rotas_rota.status (A/I) é cadastral. Não representa o estado da
# execução diária e, por isso, não é usada para classificar concluída/não executada.
df_exec_detalhe = safe_read("""
SELECT
    e.data::date AS data,
    COALESCE(e.tipo_rota,'SEM TIPO') AS tipo_rota,
    COALESCE(r.turno,'SEM TURNO') AS turno,
    COALESCE(r.direcao,'SEM DIREÇÃO') AS direcao,
    COALESCE(g.nome,'SEM GRE') AS gre,
    COALESCE(r.cidade, m.cidade, 'SEM CIDADE') AS cidade,
    COALESCE(func.nome,'SEM FISCAL') AS fiscal,
    CASE
        WHEN UPPER(TRIM(COALESCE(r.cidade,m.cidade,''))) = 'TERESINA' THEN 'CAPITAL'
        ELSE 'INTERIOR'
    END AS regiao,
    COALESCE(fm.nome, fv.nome, 'SEM FORNECEDOR') AS fornecedor,
    COALESCE(m.nome,'SEM MOTORISTA') AS motorista,
    COALESCE(v.placa,'SEM PLACA') AS placa,
    COALESCE(v.tipo_contrato_locacao,'SEM TIPO') AS tipo_frota,
    CASE WHEN e.inicio_execucao IS NOT NULL THEN true ELSE false END AS iniciou,
    CASE WHEN e.fim_execucao IS NOT NULL THEN true ELSE false END AS concluiu,
    e.via_app,
    COALESCE(e.km_executado,0) AS km_executado,
    COALESCE(e.km_planejado,0) AS km_planejado,
    COALESCE(NULLIF(TRIM(e.observacao),''),'') AS observacao
FROM airbyte.rotas_escalarota e
LEFT JOIN airbyte.rotas_rota r ON r.id = e.rota_id
LEFT JOIN airbyte.escolas_gre g ON g.id = r.gre_id
LEFT JOIN airbyte.motoristas_funcionario func ON func.id = g.fiscal_responsavel_id
LEFT JOIN airbyte.motoristas_motorista m ON m.id = e.motorista_id
LEFT JOIN airbyte.motoristas_fornecedor fm ON fm.id = m.fornecedor_id
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = e.veiculo_execucao_id
LEFT JOIN airbyte.motoristas_fornecedor fv ON fv.id = v.fornecedor_id
WHERE e.data >= DATE '2026-01-01'
  AND e.data <= CURRENT_DATE
  AND e.anulada = false
  AND e.data IS NOT NULL
ORDER BY e.data, e.id
""", pd.DataFrame())

df_exec_motoristas = safe_read("""
SELECT
    COALESCE(g.nome,'SEM GRE') AS gre,
    m.id,
    COALESCE(m.nome,'SEM NOME') AS motorista,
    CASE WHEN m.veiculo_id IS NOT NULL THEN true ELSE false END AS tem_veiculo,
    COALESCE(v.placa,'') AS placa
FROM airbyte.motoristas_motorista m
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = m.veiculo_id
WHERE m.status = 'A'
""", pd.DataFrame(columns=['gre','id','motorista','tem_veiculo','placa']))


# ─── QUERIES RESTAURADAS PARA COMPATIBILIDADE DAS ABAS ─────────────────────────

df_abast = safe_read("""
SELECT m.nome, COALESCE(f.nome,'PRÓPRIO') as empresa, m.cidade, g.nome as gre,
    COUNT(DISTINCT a.id) as abast, COALESCE(SUM(a.litros),0) as litros,
    COALESCE(SUM(a.valor_total),0) as gasto, COUNT(DISTINCT e.id) as escalas,
    CASE WHEN COUNT(DISTINCT e.id) > 0 THEN ROUND(COALESCE(SUM(a.valor_total),0)/COUNT(DISTINCT e.id),2) ELSE 0 END as rs_escala
FROM airbyte.motoristas_motorista m
LEFT JOIN airbyte.abastecimentos_abastecimento a ON a.motorista_id = m.id AND a.datetime_abastecimento >= '2026-01-01' AND a.litros <= 1000
LEFT JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id AND e.data >= '2026-01-01' AND e.anulada = false
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status='A' GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COALESCE(SUM(a.litros),0) BETWEEN 1 AND 50000 ORDER BY gasto DESC LIMIT 20
""")

df_bonificacao_cidade = safe_read("""
SELECT m.cidade, COUNT(DISTINCT m.id) as motoristas, COUNT(e.id) as total_escalas,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0),1) as pct_rastreado,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas,
    ROUND(COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0),1) as pct_suspeitas,
    ROUND((COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0))
        - (COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0))*2,1) as score
FROM airbyte.motoristas_motorista m JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE m.status = 'A' AND m.cidade IS NOT NULL AND e.data >= '2026-04-01'
GROUP BY m.cidade HAVING COUNT(e.id) >= 100 ORDER BY score DESC LIMIT 30
""")

df_bonificacao_gre = safe_read("""
SELECT g.nome as gre, func.nome as fiscal, COUNT(DISTINCT m.id) as motoristas, COUNT(e.id) as total_escalas,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0),1) as pct_rastreado,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas,
    ROUND(COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0),1) as pct_suspeitas,
    ROUND((COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0))
        - (COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0))*2,1) as score
FROM airbyte.motoristas_motorista m JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
JOIN airbyte.escolas_gre g ON g.id = m.gre_id
LEFT JOIN airbyte.motoristas_funcionario func ON func.id = g.fiscal_responsavel_id
WHERE m.status = 'A' AND e.data >= '2026-04-01'
  AND g.nome NOT IN ('ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','TESTE','SEMEC - SUDESTE')
GROUP BY g.nome, func.nome ORDER BY score DESC
""")

df_bonificacao_mot = safe_read("""
SELECT m.nome as motorista, COALESCE(f.nome,'PRÓPRIO') as empresa, m.cidade, g.nome as gre,
    COUNT(e.id) as total_escalas, COUNT(e.id) FILTER (WHERE e.via_app = true) as rastreadas,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0),1) as pct_rastreado,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas,
    ROUND(COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0),1) as pct_suspeitas,
    ROUND((COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0))
        - (COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0))*2,1) as score
FROM airbyte.motoristas_motorista m JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status = 'A' AND e.data >= '2026-04-01' GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COUNT(e.id) >= 30 ORDER BY score DESC LIMIT 30
""")

df_cidade_hist = safe_read("""
SELECT m.cidade, TO_CHAR(e.data,'YYYY-MM') as mes, COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE e.via_app = true) as rastreado,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0),1) as pct,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast
FROM airbyte.motoristas_motorista m JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE m.status = 'A' AND m.cidade IS NOT NULL AND e.data >= '2026-04-01'
GROUP BY m.cidade, TO_CHAR(e.data,'YYYY-MM') HAVING COUNT(e.id) >= 30 ORDER BY m.cidade, mes
""")

df_combust_empresa = safe_read("""
WITH abast AS (
    SELECT COALESCE(f.nome, 'PRÓPRIO') as empresa, TO_CHAR(a.datetime_abastecimento, 'YYYY-MM') as mes,
        COUNT(DISTINCT m.id) as motoristas, ROUND(SUM(COALESCE(a.litros,0))::numeric, 0) as total_litros,
        ROUND(SUM(COALESCE(a.valor_total,0))::numeric, 2) as total_gasto
    FROM airbyte.abastecimentos_abastecimento a JOIN airbyte.motoristas_motorista m ON m.id = a.motorista_id
    LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
    WHERE a.datetime_abastecimento >= '2026-01-01' AND (a.litros IS NULL OR a.litros <= 500) AND (a.valor_total IS NULL OR a.valor_total >= 0)
    GROUP BY f.nome, TO_CHAR(a.datetime_abastecimento, 'YYYY-MM')
),
esc AS (
    SELECT COALESCE(f.nome, 'PRÓPRIO') as empresa, TO_CHAR(e.data, 'YYYY-MM') as mes, COUNT(e.id) as escalas_mes
    FROM airbyte.rotas_escalarota e JOIN airbyte.motoristas_motorista m ON m.id = e.motorista_id AND m.status = 'A'
    LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
    WHERE e.data >= '2026-01-01' AND e.anulada = false GROUP BY f.nome, TO_CHAR(e.data, 'YYYY-MM')
)
SELECT a.empresa, a.mes, a.motoristas, a.total_litros, a.total_gasto, COALESCE(esc.escalas_mes, 0) as escalas_mes,
    ROUND(a.total_gasto / NULLIF(esc.escalas_mes, 0), 2) as rs_por_escala
FROM abast a LEFT JOIN esc ON esc.empresa = a.empresa AND esc.mes = a.mes ORDER BY a.empresa, a.mes
""")

df_combust_gre = safe_read("""
WITH abast AS (
    SELECT COALESCE(a.gre_id, m.gre_id) as gre_id, TO_CHAR(a.datetime_abastecimento, 'YYYY-MM') as mes,
        COUNT(DISTINCT m.id) as motoristas, COUNT(DISTINCT a.id) as abastecimentos,
        ROUND(SUM(COALESCE(a.litros,0))::numeric, 0) as total_litros,
        ROUND(SUM(COALESCE(a.valor_total,0))::numeric, 2) as total_gasto,
        COUNT(DISTINCT a.id) FILTER (WHERE a.id_profrotas IS NOT NULL) as convenio_profrotas
    FROM airbyte.abastecimentos_abastecimento a JOIN airbyte.motoristas_motorista m ON m.id = a.motorista_id
    WHERE a.datetime_abastecimento >= '2026-01-01' AND (a.litros IS NULL OR a.litros <= 500) AND (a.valor_total IS NULL OR a.valor_total >= 0)
    GROUP BY COALESCE(a.gre_id, m.gre_id), TO_CHAR(a.datetime_abastecimento, 'YYYY-MM')
),
esc AS (
    SELECT m.gre_id, TO_CHAR(e.data, 'YYYY-MM') as mes, COUNT(e.id) as escalas_mes
    FROM airbyte.rotas_escalarota e JOIN airbyte.motoristas_motorista m ON m.id = e.motorista_id AND m.status = 'A'
    WHERE e.data >= '2026-01-01' AND e.anulada = false GROUP BY m.gre_id, TO_CHAR(e.data, 'YYYY-MM')
)
SELECT g.nome as gre, func.nome as fiscal, a.mes, a.motoristas, a.abastecimentos, a.total_litros, a.total_gasto, a.convenio_profrotas,
    COALESCE(esc.escalas_mes, 0) as escalas_mes, ROUND(a.total_gasto / NULLIF(esc.escalas_mes, 0), 2) as rs_por_escala
FROM abast a JOIN airbyte.escolas_gre g ON g.id = a.gre_id
LEFT JOIN airbyte.motoristas_funcionario func ON func.id = g.fiscal_responsavel_id
LEFT JOIN esc ON esc.gre_id = a.gre_id AND esc.mes = a.mes ORDER BY g.nome, a.mes
""")

df_combust_mot = safe_read("""
WITH top_ids AS (
    SELECT m.id FROM airbyte.abastecimentos_abastecimento a JOIN airbyte.motoristas_motorista m ON m.id = a.motorista_id
    WHERE a.datetime_abastecimento >= '2026-01-01' AND (a.litros IS NULL OR a.litros <= 500) AND (a.valor_total IS NULL OR a.valor_total >= 0)
    GROUP BY m.id ORDER BY SUM(a.valor_total) DESC LIMIT 40
),
abast AS (
    SELECT m.id as mot_id, m.nome as motorista, COALESCE(f.nome,'PRÓPRIO') as empresa, m.cidade, g.nome as gre,
        TO_CHAR(a.datetime_abastecimento, 'YYYY-MM') as mes,
        ROUND(SUM(a.litros)::numeric, 1) as litros, ROUND(SUM(a.valor_total)::numeric, 2) as gasto
    FROM airbyte.abastecimentos_abastecimento a JOIN airbyte.motoristas_motorista m ON m.id = a.motorista_id
    JOIN top_ids t ON t.id = m.id LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
    LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
    WHERE a.datetime_abastecimento >= '2026-01-01' AND (a.litros IS NULL OR a.litros <= 500) AND (a.valor_total IS NULL OR a.valor_total >= 0)
    GROUP BY m.id, m.nome, f.nome, m.cidade, g.nome, TO_CHAR(a.datetime_abastecimento, 'YYYY-MM')
),
esc AS (
    SELECT e.motorista_id as mot_id, TO_CHAR(e.data, 'YYYY-MM') as mes, COUNT(*) as escalas_mes
    FROM airbyte.rotas_escalarota e JOIN top_ids t ON t.id = e.motorista_id
    WHERE e.data >= '2026-01-01' AND e.anulada = false GROUP BY e.motorista_id, TO_CHAR(e.data, 'YYYY-MM')
)
SELECT a.motorista, a.empresa, a.cidade, a.gre, a.mes, a.litros, a.gasto,
    COALESCE(esc.escalas_mes, 0) as escalas_mes, ROUND(a.gasto / NULLIF(esc.escalas_mes, 0), 2) as rs_por_escala
FROM abast a LEFT JOIN esc ON esc.mot_id = a.mot_id AND esc.mes = a.mes ORDER BY a.motorista, a.mes
""")

df_combust_total = safe_read("""
SELECT TO_CHAR(a.datetime_abastecimento, 'YYYY-MM') as mes, COUNT(*) as lancamentos,
    ROUND(SUM(COALESCE(a.litros,0))::numeric, 0) as litros,
    ROUND(SUM(COALESCE(a.valor_total,0))::numeric, 2) as valor_total,
    COUNT(*) FILTER (WHERE a.id_profrotas IS NOT NULL) as convenio
FROM airbyte.abastecimentos_abastecimento a
WHERE a.datetime_abastecimento >= '2026-01-01' AND a.litros > 0 AND a.litros <= 500 AND a.valor_total > 0
GROUP BY TO_CHAR(a.datetime_abastecimento, 'YYYY-MM') ORDER BY mes
""")

df_contratos = safe_read("""
SELECT DISTINCT ON (ci.id) ci.id as item, c.id as contrato_id, g.nome as gre, ci.valor_unitario,
    v.placa, v.status as sv, COALESCE(ct.nome,'Não definido') as turno,
    (SELECT COUNT(*) FROM airbyte.rotas_escalarota e2 WHERE e2.veiculo_execucao_id = v.id AND e2.data >= CURRENT_DATE - INTERVAL '30 days' AND e2.anulada = false) as esc30d
FROM airbyte.contratos_itemcontrato ci JOIN airbyte.contratos_contrato c ON ci.contrato_id = c.id
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
LEFT JOIN airbyte.motoristas_motorista m ON m.veiculo_id = v.id AND m.status = 'A'
LEFT JOIN airbyte.contratos_itemcontrato_turnos cit ON cit.itemcontrato_id = ci.id
LEFT JOIN airbyte.contratos_turno ct ON ct.id = cit.turno_id
LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
WHERE c.status = 'A' AND ci.status = 'ATIVO' AND m.id IS NULL
ORDER BY ci.id, ci.valor_unitario DESC LIMIT 60
""")

df_contratos_noite_sabado = safe_read("""
SELECT g.nome as gre, ci.id as item_contrato, v.placa, COALESCE(f.nome,'SEM FORN') as fornecedor,
    ci.valor_unitario, ct.nome as turno,
    STRING_AGG(DISTINCT ct2.nome, ' + ' ORDER BY ct2.nome) as todos_turnos,
    COUNT(e.id) as escalas_sabado_noite, COUNT(e.id) FILTER (WHERE e.anulada = false) as executadas,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as manuais_sem_gps,
    COUNT(e.id) FILTER (WHERE e.anulada = false) * ci.valor_unitario as valor_pago_estimado
FROM airbyte.contratos_itemcontrato ci JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id
JOIN airbyte.contratos_itemcontrato_turnos cit ON cit.itemcontrato_id = ci.id
JOIN airbyte.contratos_turno ct ON ct.id = cit.turno_id
JOIN airbyte.contratos_itemcontrato_turnos cit2 ON cit2.itemcontrato_id = ci.id
JOIN airbyte.contratos_turno ct2 ON ct2.id = cit2.turno_id
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
LEFT JOIN airbyte.rotas_escalarota e ON e.contrato_rota_id = ci.id AND EXTRACT(DOW FROM e.data) = 6 AND e.data >= '2026-01-01'
WHERE c.status = 'A' AND ci.status = 'ATIVO' AND ct.nome ILIKE '%noite%'
GROUP BY g.nome, ci.id, v.placa, f.nome, ci.valor_unitario, ct.nome
ORDER BY executadas DESC, ci.valor_unitario DESC LIMIT 25
""")

df_fiscal = safe_read("""
SELECT g.nome as gre, func.nome as fiscal, COUNT(e.id) as total,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app=true AND e.data BETWEEN '2026-04-01' AND '2026-06-30')
        *100.0/NULLIF(COUNT(e.id) FILTER (WHERE e.data BETWEEN '2026-04-01' AND '2026-06-30'),0),1) as pct_q2,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app=true AND e.data >= '2026-07-01')
        *100.0/NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-07-01'),0),1) as pct_q3,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10 AND e.data >= '2026-04-01') as suspeitas,
    COUNT(e.id) FILTER (WHERE e.via_app=false AND e.confirmado_manualmente=true AND e.data >= '2026-04-01') as sem_rast
FROM airbyte.rotas_escalarota e JOIN airbyte.rotas_rota r ON r.id = e.rota_id
JOIN airbyte.escolas_gre g ON g.id = r.gre_id
LEFT JOIN airbyte.motoristas_funcionario func ON func.id = g.fiscal_responsavel_id
WHERE e.data >= '2026-04-01' AND g.nome NOT IN ('ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','TESTE','SEMEC - SUDESTE')
GROUP BY g.nome, func.nome ORDER BY pct_q3 ASC
""")

df_fraude_emp = safe_read("""
SELECT COALESCE(f.nome,'SEM FORNECEDOR') as empresa, COUNT(DISTINCT m.id) as motoristas,
    COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas,
    ROUND(COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0),1) as pct_susp,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast
FROM airbyte.motoristas_fornecedor f JOIN airbyte.motoristas_motorista m ON m.fornecedor_id = f.id
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE e.data >= '2026-01-01' AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL
GROUP BY f.nome HAVING COUNT(e.id) >= 20 ORDER BY pct_susp DESC LIMIT 15
""")

df_fraude_mensal = safe_read("""
SELECT TO_CHAR(data,'YYYY-MM') as mes,
    COUNT(*) FILTER (WHERE inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL) as com_horario,
    COUNT(*) FILTER (WHERE inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10) as suspeitas,
    COUNT(*) FILTER (WHERE via_app = false AND confirmado_manualmente = true) as sem_rast
FROM airbyte.rotas_escalarota WHERE data >= '2026-01-01'
GROUP BY TO_CHAR(data,'YYYY-MM') ORDER BY mes
""")

df_fraude_mot = safe_read("""
SELECT m.nome as motorista, COALESCE(f.nome,'PRÓPRIO') as empresa, m.cidade, g.nome as gre,
    COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas,
    ROUND(COUNT(e.id) FILTER (WHERE EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10)*100.0/NULLIF(COUNT(e.id),0),1) as pct_susp,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast
FROM airbyte.motoristas_motorista m JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status = 'A' AND e.data >= '2026-01-01' AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL
GROUP BY m.nome, f.nome, m.cidade, g.nome HAVING COUNT(e.id) >= 10 ORDER BY pct_susp DESC LIMIT 20
""")

df_frota = safe_read("""
SELECT COALESCE(f.nome,'SEM FORNECEDOR') as fornecedor, COUNT(DISTINCT v.id) as total,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status='A') as ativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status='I') as inativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.multas=true) as multas,
    COUNT(DISTINCT v.id) FILTER (WHERE v.licenciamento::int < 2026) as lic_venc,
    COUNT(DISTINCT v.id) FILTER (WHERE v.licenciamento::int >= 2026) as lic_ok
FROM airbyte.motoristas_fornecedor f JOIN airbyte.veiculos_veiculo v ON v.fornecedor_id = f.id
WHERE v.licenciamento IS NOT NULL GROUP BY f.nome HAVING COUNT(DISTINCT v.id) >= 2
ORDER BY lic_venc DESC LIMIT 15
""")

df_frota_nunca = safe_read("""
SELECT DISTINCT ON (v.id) v.placa, v.modelo, v.tipo_contrato_locacao,
    COALESCE(f.nome,'SEM FORNECEDOR') as fornecedor, g.nome as gre, ci.valor_unitario, c.data_inicio, c.data_fim
FROM airbyte.veiculos_veiculo v JOIN airbyte.contratos_itemcontrato ci ON ci.veiculo_id = v.id
JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = v.gre_id
WHERE v.status = 'A' AND c.status = 'A' AND ci.status = 'ATIVO'
  AND NOT EXISTS (SELECT 1 FROM airbyte.rotas_escalarota e WHERE e.veiculo_execucao_id = v.id)
ORDER BY v.id, ci.valor_unitario DESC LIMIT 30
""")

df_frota_parada = safe_read("""
SELECT situacao, COUNT(*) as veiculos,
    COUNT(*) FILTER (WHERE tipo_contrato_locacao = 'FROTA_PROPRIA') as propria,
    COUNT(*) FILTER (WHERE tipo_contrato_locacao = 'FROTA_TERCEIRIZADA') as terceirizada,
    COUNT(*) FILTER (WHERE tipo_contrato_locacao = 'FROTA_PARCEIRO') as parceiro
FROM (
    SELECT v.id, v.tipo_contrato_locacao,
        CASE WHEN MAX(e.data) IS NULL THEN 'Nunca registrou rota'
            WHEN MAX(e.data)::date < CURRENT_DATE - INTERVAL '90 days' THEN 'Parado há +90 dias'
            WHEN MAX(e.data)::date < CURRENT_DATE - INTERVAL '60 days' THEN 'Parado há 60-90 dias'
            WHEN MAX(e.data)::date < CURRENT_DATE - INTERVAL '30 days' THEN 'Parado há 30-60 dias'
            ELSE 'Ativo (últimos 30 dias)' END as situacao
    FROM airbyte.veiculos_veiculo v LEFT JOIN airbyte.rotas_escalarota e ON e.veiculo_execucao_id = v.id
    WHERE v.status = 'A' GROUP BY v.id, v.tipo_contrato_locacao
) sub GROUP BY situacao ORDER BY veiculos DESC
""")

df_gc_resumo = safe_read("""
SELECT
    (SELECT COUNT(*) FROM airbyte.contratos_contrato WHERE status = 'A') AS contratos_ativos,
    (SELECT COUNT(*)
       FROM airbyte.contratos_itemcontrato ci
       JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id
      WHERE ci.status = 'ATIVO' AND c.status = 'A') AS contratos_rota_ativos,
    (SELECT COUNT(DISTINCT ci.veiculo_id)
       FROM airbyte.contratos_itemcontrato ci
       JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id
       JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
      WHERE ci.status = 'ATIVO' AND c.status = 'A'
        AND v.status = 'A' AND v.tipo_contrato_locacao = 'FROTA_TERCEIRIZADA') AS veic_terceirizados_contrato,
    (SELECT COUNT(DISTINCT ci.veiculo_id)
       FROM airbyte.contratos_itemcontrato ci
       JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id
       JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
      WHERE ci.status = 'ATIVO' AND c.status = 'A'
        AND v.status = 'A' AND v.tipo_contrato_locacao = 'FROTA_PROPRIA') AS veic_proprios_com_contrato,
    (SELECT COUNT(DISTINCT ci.veiculo_id)
       FROM airbyte.contratos_itemcontrato ci
       JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id
       JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
      WHERE ci.status = 'ATIVO' AND c.status = 'A'
        AND v.status = 'A' AND v.tipo_contrato_locacao = 'FROTA_LOCADA') AS veic_locados_com_contrato
""", pd.DataFrame([{
    'contratos_ativos':0,'contratos_rota_ativos':0,'veic_terceirizados_contrato':0,
    'veic_proprios_com_contrato':0,'veic_locados_com_contrato':0
}]))

# 2) FROTA GERAL — ATIVA, OPERAÇÃO REAL, OCIOSA COM CONTRATO, DISPONÍVEL E INATIVA COM CONTRATO
# Operação considera somente escala não anulada com início de execução registrado.

df_gre_hist = safe_read("""
SELECT g.nome as gre, TO_CHAR(e.data,'YYYY-MM') as mes, COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE e.via_app = true) as rastreado,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0),1) as pct,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast,
    COUNT(e.id) FILTER (WHERE anulada = true) as anuladas,
    COUNT(e.id) FILTER (WHERE inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas
FROM airbyte.rotas_escalarota e JOIN airbyte.rotas_rota r ON r.id = e.rota_id
JOIN airbyte.escolas_gre g ON g.id = r.gre_id
WHERE e.data >= '2026-04-01' AND g.nome NOT IN ('ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','TESTE','SEMEC - SUDESTE')
GROUP BY g.nome, TO_CHAR(e.data,'YYYY-MM') ORDER BY g.nome, mes
""")

df_manut_forn = safe_read("""
SELECT COALESCE(f.nome,'SEM FORNECEDOR') as fornecedor, COUNT(DISTINCT c.id) as chamados,
    COUNT(DISTINCT c.id) FILTER (WHERE c.status='CA') as abertos,
    COUNT(DISTINCT c.id) FILTER (WHERE c.status='CO') as oficina,
    COUNT(DISTINCT c.veiculo_id) as veiculos,
    ROUND(AVG(CASE WHEN c.entrega IS NOT NULL AND c.emissao IS NOT NULL
        THEN EXTRACT(EPOCH FROM (c.entrega - c.emissao))/86400 END)::numeric,1) as media_dias
FROM airbyte.ordens_chamado c JOIN airbyte.veiculos_veiculo v ON v.id = c.veiculo_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
WHERE c.emissao >= '2026-01-01' GROUP BY f.nome ORDER BY abertos DESC, chamados DESC LIMIT 12
""")

df_mot_chamados = safe_read("""
SELECT m.nome, COALESCE(f.nome,'PRÓPRIO') as empresa, g.nome as gre, COUNT(c.id) as chamados,
    COUNT(c.id) FILTER (WHERE c.falha_humana=true) as falha_hum, COUNT(c.id) FILTER (WHERE c.status='CA') as abertos
FROM airbyte.ordens_chamado c JOIN airbyte.motoristas_motorista m ON m.id = c.motorista_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE c.emissao >= '2026-01-01' GROUP BY m.nome, f.nome, g.nome HAVING COUNT(c.id) >= 3
ORDER BY chamados DESC LIMIT 15
""")

df_mot_rank = safe_read("""
SELECT m.nome, COALESCE(f.nome,'PRÓPRIO') as empresa, m.cidade, g.nome as gre, COUNT(e.id) as total,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app=true)*100.0/NULLIF(COUNT(e.id),0),1) as pct_rast,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10) as suspeitas,
    COUNT(e.id) FILTER (WHERE e.via_app=false AND e.confirmado_manualmente=true) as sem_rast
FROM airbyte.motoristas_motorista m JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status='A' AND e.data >= '2026-04-01' GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COUNT(e.id) >= 20 ORDER BY pct_rast ASC LIMIT 30
""")

df_veic_prob = safe_read("""
SELECT v.placa, v.modelo, v.ano, COALESCE(f.nome,'SEM FORN') as fornecedor, g.nome as gre,
    COUNT(DISTINCT c.id) as chamados, COUNT(DISTINCT c.id) FILTER (WHERE c.status='CA') as abertos,
    COUNT(DISTINCT c.id) FILTER (WHERE c.falha_humana=true) as falha_hum,
    ROUND(AVG(CASE WHEN c.entrega IS NOT NULL AND c.emissao IS NOT NULL
        THEN EXTRACT(EPOCH FROM (c.entrega - c.emissao))/86400 END)::numeric,1) as media_dias,
    ROUND(SUM(CASE WHEN c.entrega IS NOT NULL AND c.emissao IS NOT NULL
        THEN EXTRACT(EPOCH FROM (c.entrega - c.emissao))/86400 END)::numeric,0) as total_dias,
    COALESCE(SUM(p.valor * p.quantidade), 0) as custo_pecas,
    COALESCE(SUM(s.valor * s.quantidade), 0) as custo_servicos,
    COALESCE(SUM(p.valor * p.quantidade), 0) + COALESCE(SUM(s.valor * s.quantidade), 0) as custo_total
FROM airbyte.veiculos_veiculo v JOIN airbyte.ordens_chamado c ON c.veiculo_id = v.id
LEFT JOIN airbyte.ordens_ordemservico os ON os.chamado_id = c.id
LEFT JOIN airbyte.ordens_peca p ON p.os_id = os.id
LEFT JOIN airbyte.ordens_servico s ON s.os_id = os.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = v.gre_id
WHERE c.emissao >= '2026-01-01' GROUP BY v.placa, v.modelo, v.ano, f.nome, g.nome
HAVING COUNT(DISTINCT c.id) >= 5 ORDER BY custo_total DESC NULLS LAST, chamados DESC LIMIT 15
""")
# 2) FROTA GERAL — ATIVA, OPERAÇÃO REAL, OCIOSA COM CONTRATO, DISPONÍVEL E INATIVA COM CONTRATO
# Operação considera somente escala não anulada com início de execução registrado.
df_gc_frota_geral = safe_read("""
SELECT
    COUNT(DISTINCT v.id) AS frota_total,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'A') AS frota_ativa,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A'
          AND EXISTS (
              SELECT 1 FROM airbyte.rotas_escalarota e
              WHERE e.veiculo_execucao_id = v.id
                AND e.data >= CURRENT_DATE - INTERVAL '30 days'
                AND e.anulada = false
                AND e.inicio_execucao IS NOT NULL
          )
    ) AS em_operacao,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A'
          AND EXISTS (
              SELECT 1
              FROM airbyte.contratos_itemcontrato ci2
              JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
              WHERE ci2.veiculo_id = v.id
                AND ci2.status = 'ATIVO'
                AND c2.status = 'A'
          )
          AND NOT EXISTS (
              SELECT 1 FROM airbyte.rotas_escalarota e
              WHERE e.veiculo_execucao_id = v.id
                AND e.data >= CURRENT_DATE - INTERVAL '30 days'
                AND e.anulada = false
                AND e.inicio_execucao IS NOT NULL
          )
    ) AS ociosa_com_contrato,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A'
          AND v.tipo_contrato_locacao IN ('FROTA_TERCEIRIZADA','FROTA_LOCADA')
          AND NOT EXISTS (
              SELECT 1
              FROM airbyte.contratos_itemcontrato ci2
              JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
              WHERE ci2.veiculo_id = v.id
                AND ci2.status = 'ATIVO'
                AND c2.status = 'A'
          )
    ) AS disponivel_sem_contrato,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status <> 'A'
          AND EXISTS (
              SELECT 1
              FROM airbyte.contratos_itemcontrato ci2
              JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
              WHERE ci2.veiculo_id = v.id
                AND ci2.status = 'ATIVO'
                AND c2.status = 'A'
          )
    ) AS inativos_com_contrato,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A' AND v.tipo_contrato_locacao = 'FROTA_PROPRIA'
    ) AS ativa_propria,
    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A' AND v.tipo_contrato_locacao = 'FROTA_TERCEIRIZADA'
    ) AS ativa_terceirizada,
    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A' AND v.tipo_contrato_locacao = 'FROTA_PARCEIRO'
    ) AS ativa_parceiro,
    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A' AND v.tipo_contrato_locacao = 'FROTA_LOCADA'
    ) AS ativa_locada,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A'
          AND v.tipo_contrato_locacao = 'FROTA_PROPRIA'
          AND EXISTS (
              SELECT 1 FROM airbyte.contratos_itemcontrato ci2
              JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
              WHERE ci2.veiculo_id = v.id AND ci2.status = 'ATIVO' AND c2.status = 'A'
          )
    ) AS propria_com_contrato,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A'
          AND v.tipo_contrato_locacao = 'FROTA_PROPRIA'
          AND NOT EXISTS (
              SELECT 1 FROM airbyte.contratos_itemcontrato ci2
              JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
              WHERE ci2.veiculo_id = v.id AND ci2.status = 'ATIVO' AND c2.status = 'A'
          )
    ) AS propria_sem_contrato
FROM airbyte.veiculos_veiculo v
""", pd.DataFrame([{
    'frota_total':0,'frota_ativa':0,'em_operacao':0,'ociosa_com_contrato':0,'disponivel_sem_contrato':0,
    'inativos_com_contrato':0,'ativa_propria':0,'ativa_terceirizada':0,'ativa_parceiro':0,'ativa_locada':0,
    'propria_com_contrato':0,'propria_sem_contrato':0
}]))

# 3) FROTA POR TIPO — SEM TRATAR "SEM CONTRATO" COMO OCIOSIDADE
# Em frota própria, ter ou não contrato é uma análise de consistência, não ausência operacional.
df_gc_frota_status = safe_read("""
SELECT
    COALESCE(v.tipo_contrato_locacao,'SEM TIPO') AS tipo,
    COUNT(DISTINCT v.id) AS total,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'A') AS ativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'I') AS inativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'S') AS status_s,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A' AND EXISTS (
            SELECT 1 FROM airbyte.rotas_escalarota e
             WHERE e.veiculo_execucao_id = v.id
               AND e.data >= CURRENT_DATE - INTERVAL '30 days'
               AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
        )
    ) AS em_operacao,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A'
          AND EXISTS (
              SELECT 1 FROM airbyte.contratos_itemcontrato ci2
              JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
              WHERE ci2.veiculo_id = v.id AND ci2.status = 'ATIVO' AND c2.status = 'A'
          )
          AND NOT EXISTS (
              SELECT 1 FROM airbyte.rotas_escalarota e
              WHERE e.veiculo_execucao_id = v.id
                AND e.data >= CURRENT_DATE - INTERVAL '30 days'
                AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
          )
    ) AS ociosos_com_contrato,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A' AND EXISTS (
            SELECT 1 FROM airbyte.contratos_itemcontrato ci2
            JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
            WHERE ci2.veiculo_id = v.id AND ci2.status = 'ATIVO' AND c2.status = 'A'
        )
    ) AS com_contrato,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status = 'A' AND NOT EXISTS (
            SELECT 1 FROM airbyte.contratos_itemcontrato ci2
            JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
            WHERE ci2.veiculo_id = v.id AND ci2.status = 'ATIVO' AND c2.status = 'A'
        )
    ) AS sem_contrato,

    COUNT(DISTINCT v.id) FILTER (
        WHERE v.status <> 'A' AND EXISTS (
            SELECT 1 FROM airbyte.contratos_itemcontrato ci2
            JOIN airbyte.contratos_contrato c2 ON c2.id = ci2.contrato_id
            WHERE ci2.veiculo_id = v.id AND ci2.status = 'ATIVO' AND c2.status = 'A'
        )
    ) AS inativos_com_contrato
FROM airbyte.veiculos_veiculo v
GROUP BY COALESCE(v.tipo_contrato_locacao,'SEM TIPO')
ORDER BY ativos DESC, tipo
""", pd.DataFrame())

# 4) GAP POR GRE — SOMENTE DADOS DE OPERAÇÃO E FROTA ATIVA
# Para a frota da GRE, consideramos o vínculo do item ativo quando existir; caso contrário, a GRE do veículo.
df_gc_gap_gre = safe_read("""
WITH frota_gre AS (
    SELECT COALESCE(ci.gre_id, v.gre_id) AS gre_id,
        COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'A') AS frota_ativa,
        COUNT(DISTINCT v.id) FILTER (
            WHERE v.status = 'A' AND EXISTS (
                SELECT 1 FROM airbyte.rotas_escalarota e
                WHERE e.veiculo_execucao_id = v.id
                  AND e.data >= CURRENT_DATE - INTERVAL '30 days'
                  AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
            )
        ) AS frota_operando
    FROM airbyte.veiculos_veiculo v
    LEFT JOIN airbyte.contratos_itemcontrato ci
           ON ci.veiculo_id = v.id AND ci.status = 'ATIVO'
    LEFT JOIN airbyte.contratos_contrato c
           ON c.id = ci.contrato_id AND c.status = 'A'
    GROUP BY COALESCE(ci.gre_id, v.gre_id)
),
demanda_gre AS (
    SELECT m.gre_id,
           COUNT(DISTINCT e.id) AS escalas_30d,
           COUNT(DISTINCT e.veiculo_execucao_id) AS veiculos_usados
    FROM airbyte.rotas_escalarota e
    JOIN airbyte.motoristas_motorista m ON m.id = e.motorista_id
    WHERE e.data >= CURRENT_DATE - INTERVAL '30 days'
      AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
    GROUP BY m.gre_id
)
SELECT g.nome AS gre,
    COALESCE(f.frota_ativa,0) AS frota_ativa,
    COALESCE(f.frota_operando,0) AS frota_operando,
    COALESCE(d.escalas_30d,0) AS escalas_30d,
    COALESCE(d.veiculos_usados,0) AS veiculos_usados,
    ROUND(COALESCE(f.frota_operando,0)::numeric / NULLIF(f.frota_ativa,0) * 100,1) AS utilizacao_pct,
    CASE
        WHEN COALESCE(f.frota_ativa,0) = 0 THEN 'SEM FROTA'
        WHEN COALESCE(d.veiculos_usados,0) > COALESCE(f.frota_ativa,0) * 1.2 THEN 'SOBRECARGA'
        WHEN COALESCE(f.frota_operando,0) < COALESCE(f.frota_ativa,0) * 0.5 THEN 'FROTA OCIOSA'
        WHEN COALESCE(d.veiculos_usados,0) > COALESCE(f.frota_ativa,0) * 0.9 THEN 'LIMITE'
        ELSE 'EQUILIBRADO'
    END AS situacao
FROM airbyte.escolas_gre g
LEFT JOIN frota_gre f ON f.gre_id = g.id
LEFT JOIN demanda_gre d ON d.gre_id = g.id
WHERE g.nome NOT IN ('ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','TESTE','SEMEC - SUDESTE')
ORDER BY escalas_30d DESC
""", pd.DataFrame())

# 5) CUSTO MÉDIO POR TIPO DE FROTA — SOMENTE ITENS ATIVOS DE CONTRATOS ATIVOS
# Evita multiplicar o valor contratual por todas as escalas.
df_gc_custo_tipo = safe_read("""
WITH itens AS (
    SELECT DISTINCT ON (ci.id)
        ci.id AS item_id,
        v.tipo_contrato_locacao AS tipo,
        ci.valor_unitario,
        ci.modalidade_pagamento
    FROM airbyte.contratos_itemcontrato ci
    JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id AND c.status = 'A'
    LEFT JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
    WHERE ci.status = 'ATIVO'
),
meses AS (
    SELECT generate_series(
        DATE_TRUNC('month', CURRENT_DATE - INTERVAL '2 months')::date,
        DATE_TRUNC('month', CURRENT_DATE)::date,
        INTERVAL '1 month'
    )::date AS mes
),
escalas AS (
    SELECT TO_CHAR(e.data,'YYYY-MM') AS mes,
           v.tipo_contrato_locacao AS tipo,
           COUNT(DISTINCT e.id) AS escalas,
           COUNT(DISTINCT v.id) AS veiculos
    FROM airbyte.rotas_escalarota e
    JOIN airbyte.veiculos_veiculo v ON v.id = e.veiculo_execucao_id
    WHERE e.data >= CURRENT_DATE - INTERVAL '90 days'
      AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
      AND v.tipo_contrato_locacao IN ('FROTA_PROPRIA','FROTA_TERCEIRIZADA','FROTA_PARCEIRO','FROTA_LOCADA')
    GROUP BY TO_CHAR(e.data,'YYYY-MM'), v.tipo_contrato_locacao
),
custos AS (
    SELECT tipo,
           SUM(CASE WHEN modalidade_pagamento = 'MENSAL' THEN valor_unitario ELSE valor_unitario * 22 END) AS custo_mensal_estimado
    FROM itens
    WHERE tipo IS NOT NULL
    GROUP BY tipo
)
SELECT e.tipo,
       ROUND(AVG(e.escalas)::numeric,0) AS media_escalas,
       ROUND(AVG(e.veiculos)::numeric,0) AS media_veiculos,
       ROUND(COALESCE(c.custo_mensal_estimado,0)::numeric,2) AS media_custo_mensal,
       ROUND(COALESCE(c.custo_mensal_estimado,0) / NULLIF(AVG(e.escalas),0),2) AS custo_por_escala,
       ROUND(COALESCE(c.custo_mensal_estimado,0) / NULLIF(AVG(e.veiculos),0),2) AS custo_por_veiculo
FROM escalas e
LEFT JOIN custos c ON c.tipo = e.tipo
GROUP BY e.tipo, c.custo_mensal_estimado
ORDER BY custo_por_escala
""", pd.DataFrame())

# 6) FINANCEIRO DE TERCEIRIZADOS — EXATAMENTE MODALIDADE + TIPO DE FROTA
df_gc_financeiro = safe_read("""
SELECT
    COUNT(DISTINCT ci.id) FILTER (WHERE ci.modalidade_pagamento = 'DIARIA') AS qtd_diaria,
    COALESCE(SUM(ci.valor_unitario) FILTER (WHERE ci.modalidade_pagamento = 'DIARIA'),0) AS valor_diaria_dia,
    COUNT(DISTINCT ci.id) FILTER (WHERE ci.modalidade_pagamento = 'MENSAL') AS qtd_mensal,
    COALESCE(SUM(ci.valor_unitario) FILTER (WHERE ci.modalidade_pagamento = 'MENSAL'),0) AS valor_mensal,
    COUNT(DISTINCT ci.id) FILTER (WHERE ci.modalidade_pagamento NOT IN ('DIARIA','MENSAL') OR ci.modalidade_pagamento IS NULL) AS qtd_nao_identificado,
    COALESCE(SUM(ci.valor_unitario) FILTER (WHERE ci.modalidade_pagamento NOT IN ('DIARIA','MENSAL') OR ci.modalidade_pagamento IS NULL),0) AS valor_nao_identificado
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id AND c.status = 'A'
JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
WHERE ci.status = 'ATIVO'
  AND v.tipo_contrato_locacao = 'FROTA_TERCEIRIZADA'
""", pd.DataFrame([{
    'qtd_diaria':0,'valor_diaria_dia':0,'qtd_mensal':0,'valor_mensal':0,
    'qtd_nao_identificado':0,'valor_nao_identificado':0
}]))

# 7) FROTA LOCADA — MANTIDA SEPARADA DOS TERCEIRIZADOS
df_gc_fin_locada = safe_read("""
SELECT
    COUNT(DISTINCT ci.id) FILTER (WHERE ci.modalidade_pagamento = 'DIARIA') AS qtd_diaria,
    COALESCE(SUM(ci.valor_unitario) FILTER (WHERE ci.modalidade_pagamento = 'DIARIA'),0) AS valor_diaria_dia,
    COUNT(DISTINCT ci.id) FILTER (WHERE ci.modalidade_pagamento = 'MENSAL') AS qtd_mensal,
    COALESCE(SUM(ci.valor_unitario) FILTER (WHERE ci.modalidade_pagamento = 'MENSAL'),0) AS valor_mensal,
    COUNT(DISTINCT ci.id) AS itens_ativos
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id AND c.status = 'A'
JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
WHERE ci.status = 'ATIVO'
  AND v.tipo_contrato_locacao = 'FROTA_LOCADA'
""", pd.DataFrame([{
    'qtd_diaria':0,'valor_diaria_dia':0,'qtd_mensal':0,'valor_mensal':0,'itens_ativos':0
}]))

# 8) BASE MENSAL ATIVA GERAL — PARA ESTIMATIVA DE FECHAMENTO
# Não é o valor já computado. É o potencial mensal dos contratos rota ativos com modalidade MENSAL.
df_gc_mensal_ativo_geral = safe_read("""
SELECT
    COUNT(DISTINCT ci.id) AS qtd_mensal_ativo,
    COALESCE(SUM(ci.valor_unitario),0) AS valor_mensal_ativo
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c
  ON c.id = ci.contrato_id
 AND c.status = 'A'
WHERE ci.status = 'ATIVO'
  AND ci.modalidade_pagamento = 'MENSAL'
""", pd.DataFrame([{'qtd_mensal_ativo':0,'valor_mensal_ativo':0}]))

# 8) RANKING DOS TERCEIRIZADOS — QUANTIDADE DE CONTRATOS ROTA E VALOR DIÁRIO
# O fornecedor vem preferencialmente do contrato mestre. Só entram contratos rota ativos
# de veículos classificados como FROTA_TERCEIRIZADA.
df_gc_rank_terceiros = safe_read("""
SELECT
    COALESCE(f.nome,'SEM FORNECEDOR') AS fornecedor,
    COUNT(DISTINCT ci.id) AS contratos_rota,
    COUNT(DISTINCT ci.veiculo_id) AS veiculos,
    COALESCE(SUM(ci.valor_unitario) FILTER (WHERE ci.modalidade_pagamento = 'DIARIA'),0) AS valor_diaria_dia,
    COUNT(DISTINCT ci.id) FILTER (WHERE ci.modalidade_pagamento = 'DIARIA') AS qtd_diaria,
    COALESCE(SUM(ci.valor_unitario) FILTER (WHERE ci.modalidade_pagamento = 'MENSAL'),0) AS valor_mensal,
    COUNT(DISTINCT ci.id) FILTER (WHERE ci.modalidade_pagamento = 'MENSAL') AS qtd_mensal
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c
  ON c.id = ci.contrato_id AND c.status = 'A'
JOIN airbyte.veiculos_veiculo v
  ON v.id = ci.veiculo_id
LEFT JOIN airbyte.motoristas_fornecedor f
  ON f.id = COALESCE(c.fornecedor_id, v.fornecedor_id)
WHERE ci.status = 'ATIVO'
  AND v.tipo_contrato_locacao = 'FROTA_TERCEIRIZADA'
GROUP BY COALESCE(f.nome,'SEM FORNECEDOR')
HAVING COUNT(DISTINCT ci.id) > 0
ORDER BY contratos_rota DESC, valor_diaria_dia DESC
LIMIT 20
""", pd.DataFrame())

# 9) CONTRATOS ROTA ATIVOS SEM PLACA
# Controle específico dos itens ativos que ainda não possuem veículo/placa vinculada.
df_gc_sem_placa = safe_read("""
SELECT
    c.id AS contrato_id,
    ci.id AS contrato_rota_id,
    g.nome AS gre,
    COALESCE(f.nome,'SEM FORNECEDOR') AS fornecedor,
    ci.modalidade_pagamento,
    ci.valor_unitario,
    c.data_inicio,
    c.data_fim
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c
  ON c.id = ci.contrato_id
LEFT JOIN airbyte.veiculos_veiculo v
  ON v.id = ci.veiculo_id
LEFT JOIN airbyte.motoristas_fornecedor f
  ON f.id = c.fornecedor_id
LEFT JOIN airbyte.escolas_gre g
  ON g.id = ci.gre_id
WHERE ci.status = 'ATIVO'
  AND c.status = 'A'
  AND (ci.veiculo_id IS NULL OR v.id IS NULL OR v.placa IS NULL)
ORDER BY g.nome, f.nome, c.id, ci.id
""", pd.DataFrame())

# 10) HISTÓRICO REAL DE CONTRATOS MESTRES EM VIGÊNCIA POR MÊS
# Não restringimos pelo status atual: um contrato encerrado hoje pode ter estado ativo em meses anteriores.
df_gc_historico = safe_read("""
WITH meses AS (
    SELECT generate_series(
        DATE '2026-01-01',
        DATE_TRUNC('month', CURRENT_DATE)::date,
        INTERVAL '1 month'
    )::date AS mes
), contratos AS (
    SELECT id, data_inicio, data_fim
    FROM airbyte.contratos_contrato
    WHERE data_inicio IS NOT NULL
)
SELECT
    TO_CHAR(m.mes,'YYYY-MM') AS mes,
    COUNT(DISTINCT c.id) FILTER (
        WHERE c.data_inicio <= (m.mes + INTERVAL '1 month - 1 day')
          AND (c.data_fim IS NULL OR c.data_fim >= m.mes)
    ) AS contratos_ativos
FROM meses m
LEFT JOIN contratos c ON TRUE
GROUP BY m.mes
ORDER BY m.mes
""", pd.DataFrame())

# 10) Mantido como marcador lógico: os blocos seguintes passam a ser numerados a partir do alerta de inativos.

# 11) VEÍCULOS INATIVOS COM CONTRATOS ATIVOS — ALERTA PRIORITÁRIO
# Inclui status I e S, pois ambos não são status ativo.
df_gc_inativos_contrato = safe_read("""
SELECT
    v.id AS veiculo_id,
    v.placa,
    v.modelo,
    v.ano,
    v.status AS veiculo_status,
    COALESCE(v.tipo_contrato_locacao,'SEM TIPO') AS tipo_frota,
    COALESCE(f.nome,'SEM FORNECEDOR') AS fornecedor,
    g.nome AS gre,
    c.id AS contrato_id,
    ci.id AS contrato_rota_id,
    ci.modalidade_pagamento,
    ci.valor_unitario,
    c.data_inicio,
    c.data_fim,
    CASE WHEN v.status = 'I' THEN 'INATIVO' ELSE 'STATUS S' END AS alerta
FROM airbyte.veiculos_veiculo v
JOIN airbyte.contratos_itemcontrato ci ON ci.veiculo_id = v.id AND ci.status = 'ATIVO'
JOIN airbyte.contratos_contrato c ON c.id = ci.contrato_id AND c.status = 'A'
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
WHERE v.status <> 'A'
ORDER BY CASE WHEN v.status = 'I' THEN 0 ELSE 1 END, ci.valor_unitario DESC, v.placa
LIMIT 200
""", pd.DataFrame())

# 12) FROTA OCIOSA COM CONTRATO — UMA LINHA POR VEÍCULO
# O risco acumulado considera diária ou proporcional mensal.
df_gc_ociosa_contrato = safe_read("""
WITH base AS (
    SELECT DISTINCT ON (v.id)
        v.id AS veiculo_id,
        g.nome AS gre,
        v.placa,
        v.modelo,
        v.tipo_contrato_locacao AS tipo,
        COALESCE(f.nome,'PRÓPRIO') AS fornecedor,
        ci.id AS contrato_rota_id,
        ci.valor_unitario,
        ci.modalidade_pagamento,
        c.data_fim AS contrato_fim
    FROM airbyte.veiculos_veiculo v
    JOIN airbyte.contratos_itemcontrato ci
      ON ci.veiculo_id = v.id AND ci.status = 'ATIVO'
    JOIN airbyte.contratos_contrato c
      ON c.id = ci.contrato_id AND c.status = 'A'
    LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
    LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
    WHERE v.status = 'A'
    ORDER BY v.id, ci.id DESC
), ult AS (
    SELECT v.id AS veiculo_id, MAX(e.data)::date AS ultima_rota
    FROM airbyte.veiculos_veiculo v
    LEFT JOIN airbyte.rotas_escalarota e ON e.veiculo_execucao_id = v.id AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
    GROUP BY v.id
)
SELECT
    b.gre, b.placa, b.modelo, b.tipo, b.fornecedor,
    b.contrato_rota_id,
    b.valor_unitario,
    b.modalidade_pagamento,
    b.contrato_fim,
    u.ultima_rota,
    (CURRENT_DATE - COALESCE(u.ultima_rota, DATE_TRUNC('day', CURRENT_DATE)::date)) AS dias_parado,
    CASE
        WHEN b.modalidade_pagamento = 'MENSAL'
            THEN ROUND((b.valor_unitario / 30.0) * (CURRENT_DATE - COALESCE(u.ultima_rota, DATE_TRUNC('day', CURRENT_DATE)::date)),2)
        ELSE b.valor_unitario * (CURRENT_DATE - COALESCE(u.ultima_rota, DATE_TRUNC('day', CURRENT_DATE)::date))
    END AS valor_risco_acumulado
FROM base b
JOIN ult u ON u.veiculo_id = b.veiculo_id
WHERE u.ultima_rota IS NULL OR u.ultima_rota < CURRENT_DATE - INTERVAL '30 days'
ORDER BY dias_parado DESC, valor_unitario DESC
LIMIT 100
""", pd.DataFrame())

# 13) DEMANDA DIÁRIA POR GRE
df_gc_demanda_diaria = safe_read("""
SELECT g.nome AS gre,
    COUNT(DISTINCT e.data) AS dias_com_escala,
    COUNT(e.id) AS total_escalas,
    ROUND(COUNT(e.id)::numeric / NULLIF(COUNT(DISTINCT e.data),0),1) AS media_escalas_dia,
    COUNT(DISTINCT e.veiculo_execucao_id) AS veiculos_distintos,
    COUNT(DISTINCT e.veiculo_execucao_id) FILTER (WHERE v.tipo_contrato_locacao = 'FROTA_PROPRIA') AS veic_proprios,
    COUNT(DISTINCT e.veiculo_execucao_id) FILTER (WHERE v.tipo_contrato_locacao = 'FROTA_TERCEIRIZADA') AS veic_terceirizados,
    COUNT(DISTINCT e.veiculo_execucao_id) FILTER (WHERE v.tipo_contrato_locacao = 'FROTA_PARCEIRO') AS veic_parceiros,
    COUNT(DISTINCT e.veiculo_execucao_id) FILTER (WHERE v.tipo_contrato_locacao = 'FROTA_LOCADA') AS veic_locados
FROM airbyte.rotas_escalarota e
JOIN airbyte.veiculos_veiculo v ON v.id = e.veiculo_execucao_id
JOIN airbyte.motoristas_motorista m ON m.id = e.motorista_id
JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE e.data >= CURRENT_DATE - INTERVAL '30 days'
  AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
  AND g.nome NOT IN ('ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','TESTE','SEMEC - SUDESTE')
GROUP BY g.nome
ORDER BY total_escalas DESC
""")


# 14) CALENDÁRIO FINANCEIRO — EXECUÇÃO REAL DAS DIÁRIAS E MENSALIDADES
# Regra validada:
#   DIÁRIA = 1 pagamento por DATA + CONTRATO ROTA, desde que exista
#            pelo menos uma execução real (inicio_execucao preenchido) e não anulada.
#   MENSAL = 1 pagamento por MÊS + CONTRATO ROTA, desde que exista
#            pelo menos uma execução real no mês.
# Portanto, várias viagens/rotas/escalas do mesmo Contrato Rota no mesmo período NÃO duplicam o valor.
df_gc_pagamento_diario = safe_read("""
WITH base AS (
    SELECT
        e.data::date AS data,
        ci.id AS contrato_rota_id,
        ci.contrato_id AS contrato_id,
        ci.valor_unitario,
        COALESCE(fc.nome, fv.nome, 'SEM FORNECEDOR') AS fornecedor,
        COALESCE(vx.placa, vc.placa) AS placa,
        COALESCE(m.nome, 'SEM MOTORISTA') AS motorista,
        COALESCE(g.nome, gr.nome, 'SEM GRE') AS gre,
        COALESCE(r.nome, 'ROTA #' || COALESCE(e.rota_id::text,'')) AS rota_nome,
        e.id AS escala_id
    FROM airbyte.rotas_escalarota e
    JOIN airbyte.contratos_itemcontrato ci
      ON ci.id = e.contrato_rota_id
     AND ci.status = 'ATIVO'
     AND ci.modalidade_pagamento = 'DIARIA'
    JOIN airbyte.contratos_contrato c
      ON c.id = ci.contrato_id
     AND c.status = 'A'
    LEFT JOIN airbyte.veiculos_veiculo vx ON vx.id = e.veiculo_execucao_id
    LEFT JOIN airbyte.veiculos_veiculo vc ON vc.id = ci.veiculo_id
    LEFT JOIN airbyte.motoristas_motorista m ON m.id = e.motorista_id
    LEFT JOIN airbyte.motoristas_fornecedor fc ON fc.id = c.fornecedor_id
    LEFT JOIN airbyte.motoristas_fornecedor fv ON fv.id = COALESCE(vx.fornecedor_id, vc.fornecedor_id)
    LEFT JOIN airbyte.rotas_rota r ON r.id = e.rota_id
    LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
    LEFT JOIN airbyte.escolas_gre gr ON gr.id = r.gre_id
    WHERE e.data >= DATE '2026-01-01'
      AND e.data <= CURRENT_DATE
      AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
      AND e.contrato_rota_id IS NOT NULL
), unicas AS (
    SELECT DISTINCT ON (data, contrato_rota_id)
        data, contrato_rota_id, contrato_id, valor_unitario
    FROM base
    ORDER BY data, contrato_rota_id, escala_id
)
SELECT
    data,
    COUNT(*) AS contratos_rota_diaria,
    COALESCE(SUM(valor_unitario),0) AS valor_diarias
FROM unicas
GROUP BY data
ORDER BY data
""", pd.DataFrame())

df_gc_pagamento_mensal = safe_read("""
WITH unicos AS (
    SELECT DISTINCT
        DATE_TRUNC('month', e.data)::date AS mes,
        ci.id AS contrato_rota_id,
        ci.valor_unitario
    FROM airbyte.rotas_escalarota e
    JOIN airbyte.contratos_itemcontrato ci
      ON ci.id = e.contrato_rota_id
     AND ci.status = 'ATIVO'
     AND ci.modalidade_pagamento = 'MENSAL'
    JOIN airbyte.contratos_contrato c
      ON c.id = ci.contrato_id
     AND c.status = 'A'
    WHERE e.data >= DATE '2026-01-01'
      AND e.data <= CURRENT_DATE
      AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
      AND e.contrato_rota_id IS NOT NULL
)
SELECT
    mes,
    COUNT(*) AS contratos_mensais_executados,
    COALESCE(SUM(valor_unitario),0) AS valor_mensal
FROM unicos
GROUP BY mes
ORDER BY mes
""", pd.DataFrame())

df_gc_pagamento_detalhe = safe_read("""
WITH base AS (
    SELECT
        e.data::date AS data,
        ci.id AS contrato_rota_id,
        ci.contrato_id AS contrato_id,
        ci.valor_unitario,
        COALESCE(fc.nome, fv.nome, 'SEM FORNECEDOR') AS fornecedor,
        COALESCE(vx.placa, vc.placa, 'SEM PLACA') AS placa,
        COALESCE(m.nome, 'SEM MOTORISTA') AS motorista,
        COALESCE(g.nome, gr.nome, 'SEM GRE') AS gre,
        COALESCE(r.nome, 'ROTA #' || COALESCE(e.rota_id::text,'')) AS rota_nome,
        e.id AS escala_id
    FROM airbyte.rotas_escalarota e
    JOIN airbyte.contratos_itemcontrato ci
      ON ci.id = e.contrato_rota_id
     AND ci.status = 'ATIVO'
     AND ci.modalidade_pagamento = 'DIARIA'
    JOIN airbyte.contratos_contrato c
      ON c.id = ci.contrato_id
     AND c.status = 'A'
    LEFT JOIN airbyte.veiculos_veiculo vx ON vx.id = e.veiculo_execucao_id
    LEFT JOIN airbyte.veiculos_veiculo vc ON vc.id = ci.veiculo_id
    LEFT JOIN airbyte.motoristas_motorista m ON m.id = e.motorista_id
    LEFT JOIN airbyte.motoristas_fornecedor fc ON fc.id = c.fornecedor_id
    LEFT JOIN airbyte.motoristas_fornecedor fv ON fv.id = COALESCE(vx.fornecedor_id, vc.fornecedor_id)
    LEFT JOIN airbyte.rotas_rota r ON r.id = e.rota_id
    LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
    LEFT JOIN airbyte.escolas_gre gr ON gr.id = r.gre_id
    WHERE e.data >= DATE '2026-01-01'
      AND e.data <= CURRENT_DATE
      AND e.anulada = false
      AND e.inicio_execucao IS NOT NULL
      AND e.contrato_rota_id IS NOT NULL
)
SELECT
    data,
    contrato_rota_id,
    contrato_id,
    COALESCE(MAX(fornecedor),'SEM FORNECEDOR') AS fornecedor,
    COALESCE(MAX(gre),'SEM GRE') AS gre,
    STRING_AGG(DISTINCT motorista, ' | ' ORDER BY motorista) AS motoristas,
    STRING_AGG(DISTINCT placa, ' | ' ORDER BY placa) AS placas,
    STRING_AGG(DISTINCT rota_nome, ' | ' ORDER BY rota_nome) AS rotas,
    COUNT(DISTINCT escala_id) AS execucoes,
    MAX(valor_unitario) AS valor_diaria
FROM base
GROUP BY data, contrato_rota_id, contrato_id
ORDER BY data, valor_diaria DESC, contrato_rota_id
""", pd.DataFrame())

# 15) CONSOLIDADO OPERACIONAL DIÁRIO — EXECUÇÃO REAL
# Executada = não anulada + início de execução registrado.
# Concluída = início e fim registrados.
# Em andamento = início registrado e fim ainda vazio.
df_gc_operacao_diaria = safe_read("""
SELECT
    e.data::date AS data,
    COUNT(*) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL) AS execucoes,
    COUNT(*) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL) AS concluidas,
    COUNT(*) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NULL) AS em_andamento,
    COUNT(DISTINCT e.contrato_rota_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.contrato_rota_id IS NOT NULL) AS contratos_rota_executados,
    COUNT(DISTINCT e.rota_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.rota_id IS NOT NULL) AS rotas_viagens,
    COUNT(DISTINCT e.motorista_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.motorista_id IS NOT NULL) AS motoristas,
    COUNT(DISTINCT e.veiculo_execucao_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.veiculo_execucao_id IS NOT NULL) AS veiculos
FROM airbyte.rotas_escalarota e
WHERE e.data >= DATE '2026-01-01'
  AND e.data <= CURRENT_DATE
GROUP BY e.data::date
ORDER BY e.data::date
""", pd.DataFrame())

# 16) CONSOLIDADO OPERACIONAL MENSAL — EXECUÇÃO REAL
# Os contratos-rota do mês são distintos no mês; não somamos os dias.
df_gc_operacao_mensal = safe_read("""
SELECT
    DATE_TRUNC('month', e.data)::date AS mes,
    COUNT(*) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL) AS execucoes,
    COUNT(*) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL) AS concluidas,
    COUNT(*) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NULL) AS em_andamento,
    COUNT(DISTINCT e.contrato_rota_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.contrato_rota_id IS NOT NULL) AS contratos_rota_executados,
    COUNT(DISTINCT e.rota_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.rota_id IS NOT NULL) AS rotas_viagens,
    COUNT(DISTINCT e.motorista_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.motorista_id IS NOT NULL) AS motoristas,
    COUNT(DISTINCT e.veiculo_execucao_id) FILTER (WHERE e.anulada = false AND e.inicio_execucao IS NOT NULL AND e.veiculo_execucao_id IS NOT NULL) AS veiculos
FROM airbyte.rotas_escalarota e
WHERE e.data >= DATE '2026-01-01'
  AND e.data <= CURRENT_DATE
GROUP BY DATE_TRUNC('month', e.data)::date
ORDER BY mes
""", pd.DataFrame())

conn.close()
print("✅ Queries concluídas. Processando...")

# ─── PROCESSAR PIVÔ DE CIDADES ─────────────────────────────────────────────
pivot = {}
if not df_cidade_hist.empty:
    for _, r in df_cidade_hist.iterrows():
        c = r['cidade']; m = r['mes']
        if c not in pivot: pivot[c] = {}
        pivot[c][m] = {'total': int(r['total']), 'pct': float(r['pct'] or 0), 'suspeitas': int(r['suspeitas'] or 0), 'sem_rast': int(r['sem_rast'] or 0)}

cidade_scores = []
for cidade, dados in pivot.items():
    vals = [dados.get(m, {}).get('pct') for m in MESES_COLS]
    total_geral = sum(dados.get(m, {}).get('total', 0) for m in MESES_COLS)
    total_susp = sum(dados.get(m, {}).get('suspeitas', 0) for m in MESES_COLS)
    total_sem = sum(dados.get(m, {}).get('sem_rast', 0) for m in MESES_COLS)
    v_clean = [x for x in vals if x is not None]
    score = score_gargalo(v_clean, total_susp, total_geral)
    icon, status, cls = tendencia(v_clean)
    cidade_scores.append({'cidade': cidade, 'vals': vals, 'total': total_geral, 'suspeitas': total_susp, 'sem_rast': total_sem, 'score': score, 'icon': icon, 'status': status, 'cls': cls})
cidade_scores.sort(key=lambda x: -x['score'])

def cor_pct(pct):
    if pct is None: return "color:#334155"
    if pct == 0: return "color:#ef4444;font-weight:700"
    if pct < 15: return "color:#ef4444"
    if pct < 30: return "color:#f97316"
    if pct < 50: return "color:#f59e0b"
    return "color:#22c55e"

def cls_status(cls):
    m = {'ok':'badge-ok','warn':'badge-warn','crit':'badge-crit','zero':'badge-zero','stab':'badge-stab','nd':'badge-nd'}
    return m.get(cls,'badge-nd')

def html_pivo():
    if not cidade_scores: return "<tr><td colspan='8'>Sem dados</td></tr>"
    h = ""
    for r in cidade_scores:
        h += f"<tr><td><b>{r['cidade']}</b></td><td style='text-align:center'>{r['total']:,}</td>"
        for pct in r['vals']:
            h += "<td style='text-align:center;color:#334155'>—</td>" if pct is None else f"<td style='text-align:center;{cor_pct(pct)}'>{pct}%</td>"
        h += f"<td style='text-align:center'>{r['suspeitas']:,}</td><td><span class='tag {cls_status(r['cls'])}'>{r['icon']} {r['status']}</span></td><td style='text-align:right;color:#64748b;font-size:11px'>{r['score']}</td></tr>"
    return h

gre_pivot = {}
if not df_gre_hist.empty:
    for _, r in df_gre_hist.iterrows():
        g = r['gre']; m = r['mes']
        if g not in gre_pivot: gre_pivot[g] = {}
        gre_pivot[g][m] = {'total': int(r['total']), 'pct': float(r['pct'] or 0), 'sem_rast': int(r['sem_rast'] or 0), 'suspeitas': int(r['suspeitas'] or 0), 'anuladas': int(r['anuladas'] or 0)}

def html_gre_pivo():
    if not gre_pivot: return "<tr><td colspan='9'>Sem dados</td></tr>"
    h = ""
    for gre in sorted(gre_pivot.keys()):
        dados = gre_pivot[gre]
        vals = [dados.get(m,{}).get('pct') for m in MESES_COLS]
        v_clean = [x for x in vals if x is not None]
        icon, status, cls = tendencia(v_clean)
        total = sum(dados.get(m,{}).get('total',0) for m in MESES_COLS)
        sem_rast = sum(dados.get(m,{}).get('sem_rast',0) for m in MESES_COLS)
        suspeitas = sum(dados.get(m,{}).get('suspeitas',0) for m in MESES_COLS)
        h += f"<tr><td><b>{gre}</b></td><td style='text-align:center'>{total:,}</td>"
        for pct in vals:
            h += "<td style='text-align:center;color:#334155'>—</td>" if pct is None else f"<td style='text-align:center;{cor_pct(pct)}'>{pct}%</td>"
        h += f"<td style='text-align:center'>{sem_rast:,}</td><td style='text-align:center;color:#f97316'>{suspeitas:,}</td><td><span class='tag {cls_status(cls)}'>{icon} {status}</span></td></tr>"
    return h

def html_fraude_emp():
    if df_fraude_emp.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    h = ""
    for _, r in df_fraude_emp.iterrows():
        pct = float(r.get('pct_susp') or 0)
        cls = "color:#ef4444;font-weight:700" if pct > 20 else ("color:#f97316" if pct > 10 else "")
        h += f"<tr><td><b>{r['empresa']}</b></td><td>{int(r['motoristas'])}</td><td>{int(r['total']):,}</td><td>{int(r.get('suspeitas',0)):,}</td><td style='{cls}'>{pct}%</td><td>{int(r.get('sem_rast',0)):,}</td></tr>"
    return h

def html_fraude_mot():
    if df_fraude_mot.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for _, r in df_fraude_mot.iterrows():
        pct = float(r.get('pct_susp') or 0)
        cls = "color:#ef4444;font-weight:700" if pct > 20 else ""
        h += f"<tr><td><b>{r['motorista']}</b></td><td>{r['empresa']}</td><td>{r.get('cidade','')}</td><td>{r.get('gre','')}</td><td>{int(r.get('suspeitas',0))}</td><td style='{cls}'>{pct}%</td><td>{int(r.get('sem_rast',0))}</td></tr>"
    return h

def html_contratos_noite():
    if df_contratos_noite_sabado.empty: return "<tr><td colspan='9'>Sem dados</td></tr>"
    h = ""
    for _, r in df_contratos_noite_sabado.iterrows():
        exec_ = int(r.get('executadas') or 0); manuais = int(r.get('manuais_sem_gps') or 0)
        val = float(r.get('valor_unitario') or 0); pago = float(r.get('valor_pago_estimado') or 0)
        turnos = str(r.get('todos_turnos') or r.get('turno','Noite')); tem_combo = '+' in turnos
        cor_turnos = "color:#ef4444;font-weight:700" if tem_combo else "color:#f59e0b"
        h += f"<tr><td>{r.get('gre','—')}</td><td><b>{r.get('placa','—')}</b></td><td>{r.get('fornecedor','—')}</td>"
        h += f"<td style='text-align:right'>R$ {fmt(val)}/dia</td><td style='{cor_turnos}'>{turnos}</td>"
        h += f"<td style='text-align:center'>{int(r.get('escalas_sabado_noite') or 0)}</td>"
        h += f"<td style='text-align:center;color:#f59e0b;font-weight:700'>{exec_}</td>"
        h += f"<td style='text-align:center;{'color:#ef4444' if manuais > 0 else ''}'>{manuais}</td>"
        h += f"<td style='text-align:right;color:#ef4444;font-weight:700'>R$ {fmt(pago)}</td></tr>"
    return h

def html_contratos():
    if df_contratos.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    h = ""
    for _, r in df_contratos.iterrows():
        sv = "🔴 INATIVO" if r.get('sv') == 'I' else "🟡 SEM MOTORISTA"
        cor = "color:#ef4444" if r.get('sv') == 'I' else "color:#f59e0b"
        h += f"<tr><td>{r.get('gre','—')}</td><td><b>{r.get('placa','—')}</b></td><td style='text-align:center;color:#a78bfa;font-weight:700'>#{r.get('contrato_id','—')}</td>"
        h += f"<td style='text-align:center;color:#64748b;font-size:11px'>item {r.get('item','—')}</td><td>R$ {fmt(r.get('valor_unitario',0))}/dia</td>"
        h += f"<td>{r.get('turno','—')}</td><td style='{cor}'>{sv}</td><td style='text-align:center'>{int(r.get('esc30d',0))}</td></tr>"
    return h

def html_frota_parada():
    if df_frota_parada.empty: return "<tr><td colspan='5'>Sem dados</td></tr>"
    h = ""
    cores = {'Ativo (últimos 30 dias)': 'color:#22c55e;font-weight:700','Parado há 30-60 dias': 'color:#f59e0b','Parado há 60-90 dias': 'color:#f97316;font-weight:700','Parado há +90 dias': 'color:#ef4444;font-weight:700','Nunca registrou rota': 'color:#a78bfa;font-weight:700'}
    for _, r in df_frota_parada.iterrows():
        sit = r['situacao']; cor = cores.get(sit, '')
        h += f"<tr><td style='{cor}'>{sit}</td><td style='text-align:center;font-weight:700'>{int(r.get('veiculos',0))}</td>"
        h += f"<td style='text-align:center'>{int(r.get('propria',0))}</td><td style='text-align:center'>{int(r.get('terceirizada',0))}</td><td style='text-align:center'>{int(r.get('parceiro',0))}</td></tr>"
    return h

def html_frota_nunca():
    if df_frota_nunca.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    h = ""
    for _, r in df_frota_nunca.iterrows():
        val = float(r.get('valor_unitario') or 0); cor = 'color:#ef4444;font-weight:700' if val >= 1000 else 'color:#f59e0b'
        inicio = str(r.get('data_inicio','—'))[:10] if r.get('data_inicio') else '—'
        h += f"<tr><td><b>{r.get('placa','—')}</b></td><td>{r.get('modelo','—')}</td><td>{r.get('fornecedor','—')}</td><td>{r.get('gre','—')}</td>"
        h += f"<td style='{cor}'>R$ {fmt(val)}/dia</td><td>{inicio}</td></tr>"
    return h

def html_frota():
    if df_frota.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for _, r in df_frota.iterrows():
        tot = max(int(r.get('total',1)),1); pct_v = round(int(r.get('lic_venc',0))/tot*100)
        cls = "color:#ef4444;font-weight:700" if pct_v > 50 else ("color:#f97316" if pct_v > 20 else "")
        h += f"<tr><td><b>{r['fornecedor']}</b></td><td>{int(r.get('total',0))}</td><td>{int(r.get('ativos',0))}</td><td>{int(r.get('inativos',0))}</td>"
        h += f"<td style='{cls}'>{int(r.get('lic_venc',0))} ({pct_v}%)</td><td>{int(r.get('lic_ok',0))}</td><td>{int(r.get('multas',0))}</td></tr>"
    return h

def html_mot():
    if df_mot_rank.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    h = ""
    for _, r in df_mot_rank.iterrows():
        pct = float(r.get('pct_rast') or 0)
        cls = "color:#ef4444;font-weight:700" if pct < 20 else ("color:#f59e0b" if pct < 50 else "color:#22c55e")
        h += f"<tr><td><b>{r['nome']}</b></td><td>{r['empresa']}</td><td>{r.get('cidade','')}</td><td>{r.get('gre','')}</td>"
        h += f"<td>{int(r.get('total',0)):,}</td><td style='{cls}'>{pct}%</td>"
        h += f"<td style='{'color:#ef4444' if int(r.get('suspeitas',0))>5 else ''}'>{int(r.get('suspeitas',0))}</td><td>{int(r.get('sem_rast',0))}</td></tr>"
    return h

def html_abast():
    if df_abast.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    h = ""
    for _, r in df_abast.iterrows():
        h += f"<tr><td><b>{r['nome']}</b></td><td>{r['empresa']}</td><td>{r.get('cidade','')}</td><td>{r.get('gre','')}</td>"
        h += f"<td>{fmt(r.get('litros',0))} L</td><td>R$ {fmt(r.get('gasto',0))}</td><td>{int(r.get('escalas',0)):,}</td><td>R$ {fmt(r.get('rs_escala',0))}</td></tr>"
    return h

def html_fiscal():
    if df_fiscal.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for _, r in df_fiscal.iterrows():
        q2 = float(r.get('pct_q2') or 0); q3 = float(r.get('pct_q3') or 0)
        icon, _, cls = tendencia([q2, q3]); cls_badge = cls_status(cls)
        h += f"<tr><td><b>{r['gre']}</b></td><td>{r.get('fiscal','—')}</td><td style='text-align:center'>{int(r.get('total',0)):,}</td>"
        h += f"<td style='text-align:center;{cor_pct(q2)}'>{q2}%</td><td style='text-align:center'><span class='tag {cls_badge}'>{q3}% {icon}</span></td>"
        h += f"<td style='text-align:center;color:#f97316'>{int(r.get('suspeitas',0)):,}</td><td style='text-align:center'>{int(r.get('sem_rast',0)):,}</td></tr>"
    return h

def html_insights():
    if not cidade_scores: return "<tr><td colspan='9'>Sem dados</td></tr>"
    h = ""
    acoes = {'SEM REGISTRO': 'Notificação formal ao fornecedor + visita do coordenador com prazo de 15 dias','REGREDIU TOTAL': 'Visita imediata + relatório ao gestor regional + prazo de regularização','EM QUEDA FORTE': 'Reunião urgente com o fiscal responsável + cobrança formal','EM QUEDA': 'Reunião com fiscal + prazo de 15 dias para recuperação','ATENÇÃO': 'Monitoramento semanal + cobrança ao fiscal responsável','MELHORANDO': 'Manter pressão. Reconhecer melhora na próxima reunião','LEVE MELHORA': 'Continuar monitorando. Meta: superar 50% até fim do trimestre','ESTÁVEL': 'Monitoramento padrão mensal'}
    for i, r in enumerate(cidade_scores[:25]):
        acao = acoes.get(r['status'], 'Avaliar individualmente')
        h += f"<tr><td style='text-align:center;font-weight:700'>#{i+1}</td><td><b>{r['cidade']}</b></td><td style='text-align:center'>{r['total']:,}</td>"
        for pct in r['vals']:
            h += "<td style='text-align:center;color:#334155'>—</td>" if pct is None else f"<td style='text-align:center;{cor_pct(pct)}'>{pct}%</td>"
        cls_tag = cls_status(r['cls'])
        h += f"<td><span class='tag {cls_tag}'>{r['icon']} {r['status']}</span></td><td style='font-size:11px;color:#94a3b8'>{acao}</td></tr>"
    return h

# ─── PROCESSAMENTO DO PAINEL EXECUTIVO ───────────────────────────────────────
if df_exec_detalhe.empty:
    exec_data = []
else:
    _edf = df_exec_detalhe.copy()
    _edf['data'] = _edf['data'].astype(str).str[:10]
    for c in ['km_executado','km_planejado']:
        _edf[c] = pd.to_numeric(_edf[c], errors='coerce').fillna(0.0)

    def _s(v):
        return '' if pd.isna(v) else str(v)

    exec_data = []
    for _, r in _edf.iterrows():
        exec_data.append({
            'd': _s(r.get('data'))[:10],
            't': _s(r.get('tipo_rota')) or 'SEM TIPO',
            's': _s(r.get('turno')) or 'SEM TURNO',
            'di': _s(r.get('direcao')) or 'SEM DIREÇÃO',
            'g': _s(r.get('gre')) or 'SEM GRE',
            'c': _s(r.get('cidade')) or 'SEM CIDADE',
            'f': _s(r.get('fiscal')) or 'SEM FISCAL',
            'rg': _s(r.get('regiao')) or 'INTERIOR',
            'p': _s(r.get('fornecedor')) or 'SEM FORNECEDOR',
            'm': _s(r.get('motorista')) or 'SEM MOTORISTA',
            'v': _s(r.get('placa')) or 'SEM PLACA',
            'ft': _s(r.get('tipo_frota')) or 'SEM TIPO',
            'i': bool(r.get('iniciou')),
            'z': bool(r.get('concluiu')),
            'a': (None if pd.isna(r.get('via_app')) else bool(r.get('via_app'))),
            'k': float(r.get('km_executado') or 0),
            'kp': float(r.get('km_planejado') or 0),
            'o': _s(r.get('observacao')),
            'cr': _s(r.get('contrato_rota_id'))
        })

exec_today = datetime.now().date()
exec_today_iso = exec_today.isoformat()
exec_current_ym = exec_today.strftime('%Y-%m')

def _exec_rows_period(rows, period='current'):
    if period == 'year':
        return rows
    out=[]
    for r in rows:
        try:
            d=datetime.strptime(r['d'],'%Y-%m-%d').date()
        except Exception:
            continue
        if period == 'current':
            if r['d'][:7] == exec_current_ym:
                out.append(r)
        elif period == 'last30':
            if exec_today - timedelta(days=30) <= d <= exec_today:
                out.append(r)
    return out

_exec_cur = _exec_rows_period(exec_data,'current')
exec_total = len(_exec_cur)
exec_conc = sum(1 for r in _exec_cur if r['i'] and r['z'])
exec_and = sum(1 for r in _exec_cur if r['i'] and not r['z'])
exec_nao = sum(1 for r in _exec_cur if not r['i'])
_exec_started = sum(1 for r in _exec_cur if r['i'])
exec_rast = sum(1 for r in _exec_cur if r['i'] and r['a'] is True)
exec_extras = sum(1 for r in _exec_cur if str(r['t']).upper() == 'EX')
exec_km = sum(float(r['k'] or 0) for r in _exec_cur if r['i'])
exec_pct_assid = round(exec_conc/max(exec_total,1)*100,1)
exec_pct_rast = round(exec_rast/max(_exec_started,1)*100,1)
exec_pct_susp = 0.0
exec_rotas = len({(r['d'],r['m'],r['v']) for r in _exec_cur})
exec_contratos = len({r['cr'] for r in _exec_cur if r.get('cr')})

# Histórico mensal de operação para os gráficos do Executivo.
if exec_data:
    _hdf = pd.DataFrame(exec_data)
    _hdf['mes'] = _hdf['d'].astype(str).str[:7]
    _hdf['i'] = _hdf['i'].astype(bool)
    _hdf['z'] = _hdf['z'].astype(bool)
    _hdf['k'] = pd.to_numeric(_hdf['k'], errors='coerce').fillna(0.0)
    hist = _hdf.groupby('mes').agg(
        planejadas=('mes','size'),
        concluidas=('z','sum'),
        iniciadas=('i','sum'),
        km=('k','sum')
    ).reset_index()
    hist['nao_executadas'] = hist['planejadas'] - hist['iniciadas']
    hist['assiduidade'] = (hist['concluidas']/hist['planejadas'].replace(0,1)*100).round(1)
    meses_ev = hist['mes'].tolist()
    ev_tot = hist['planejadas'].astype(int).tolist()
    ev_conc = hist['concluidas'].astype(int).tolist()
    ev_nao = hist['nao_executadas'].astype(int).tolist()
    ev_km = hist['km'].round(1).tolist()
    ev_assid = hist['assiduidade'].tolist()
else:
    meses_ev=[]; ev_tot=[]; ev_conc=[]; ev_nao=[]; ev_km=[]; ev_assid=[]

def exec_html_options(values):
    opts = ["<option value=''>TODOS</option>"]
    seen=set()
    for v in sorted(str(x) for x in values if str(x).strip()):
        if v in seen: continue
        seen.add(v)
        opts.append(f"<option value='{htmlmod.escape(v,quote=True)}'>{htmlmod.escape(v)}</option>")
    return "".join(opts)

_exec_vals = {
    'turno': {r['s'] for r in exec_data},
    'direcao': {r['di'] for r in exec_data},
    'gre': {r['g'] for r in exec_data},
    'cidade': {r['c'] for r in exec_data},
    'fiscal': {r['f'] for r in exec_data},
    'fornecedor': {r['p'] for r in exec_data}
}
# ─── COMBUSTÍVEL ────────────────────────────────────────────────────────────
MESES_COMB = ['2026-02','2026-03','2026-04','2026-05','2026-06','2026-07','2026-08']
MESES_COMB_NOMES = {'2026-02':'Fev','2026-03':'Mar','2026-04':'Abr','2026-05':'Mai','2026-06':'Jun','2026-07':'Jul','2026-08':'Ago'}

comb_gre_pivot = {}
if not df_combust_gre.empty:
    for _, r in df_combust_gre.iterrows():
        g = r['gre']; m = r['mes']
        if g not in comb_gre_pivot: comb_gre_pivot[g] = {'fiscal': r.get('fiscal','—')}
        comb_gre_pivot[g][m] = {'gasto': float(r.get('total_gasto') or 0), 'litros': float(r.get('total_litros') or 0), 'escalas': int(r.get('escalas_mes') or 0), 'rs_escala': float(r.get('rs_por_escala') or 0)}

def html_comb_total():
    if df_combust_total.empty: return "<tr><td colspan='5'>Sem dados</td></tr>"
    h = ""; total_lanc = total_litros = total_val = total_conv = 0
    meses_nomes = {'2026-01':'Jan/26','2026-02':'Fev/26','2026-03':'Mar/26','2026-04':'Abr/26','2026-05':'Mai/26','2026-06':'Jun/26','2026-07':'Jul/26','2026-08':'Ago/26'}
    for _, r in df_combust_total.iterrows():
        lanc = int(r.get('lancamentos') or 0); litros = float(r.get('litros') or 0); val = float(r.get('valor_total') or 0); conv = int(r.get('convenio') or 0)
        total_lanc += lanc; total_litros += litros; total_val += val; total_conv += conv
        nome_mes = meses_nomes.get(r['mes'], r['mes'])
        h += f"<tr><td><b>{nome_mes}</b></td><td style='text-align:center'>{lanc:,}</td><td style='text-align:right'>{fmt(litros)} L</td>"
        h += f"<td style='text-align:right;font-weight:700;color:#38bdf8'>R$ {fmt(val)}</td><td style='text-align:center;{'color:#a78bfa;font-weight:700' if conv > 0 else 'color:#334155'}'>{conv if conv > 0 else '—'}</td></tr>"
    h += f"<tr style='background:#0f172a;border-top:2px solid #334155'><td style='font-weight:700'>TOTAL</td><td style='text-align:center;font-weight:700'>{total_lanc:,}</td>"
    h += f"<td style='text-align:right;font-weight:700'>{fmt(total_litros)} L</td><td style='text-align:right;font-weight:700;color:#38bdf8'>R$ {fmt(total_val)}</td><td style='text-align:center;font-weight:700;color:#a78bfa'>{total_conv}</td></tr>"
    return h

def html_comb_gre_pivo():
    if not comb_gre_pivot: return "<tr><td colspan='10'>Sem dados</td></tr>"
    h = ""; totais_mes = {m: 0 for m in MESES_COMB}; total_geral = 0
    ADMIN_GRES = {'ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','SEMEC - SUDESTE','SEMEC -  SUDESTE','TESTE'}
    gres_op = sorted([g for g in comb_gre_pivot.keys() if g not in ADMIN_GRES])
    gres_ad = sorted([g for g in comb_gre_pivot.keys() if g in ADMIN_GRES])
    for gre in gres_op + gres_ad:
        dados = comb_gre_pivot[gre]; fiscal = dados.get('fiscal','—'); total = sum(dados.get(m,{}).get('gasto',0) for m in MESES_COMB)
        total_geral += total; is_admin = gre in ADMIN_GRES; estilo_row = "opacity:0.55" if is_admin else ""
        label_adm = " <span style='font-size:10px;color:#64748b'>(adm)</span>" if is_admin else ""
        h += f"<tr style='{estilo_row}'><td><b>{gre}</b>{label_adm}</td><td style='font-size:11px;color:#64748b'>{fiscal}</td>"
        for m in MESES_COMB:
            v = dados.get(m,{}).get('gasto',0); totais_mes[m] += v
            if v == 0: h += "<td style='text-align:right;color:#334155'>—</td>"
            else:
                cor = "color:#ef4444;font-weight:700" if v > 400000 else ("color:#f59e0b" if v > 150000 else "color:#22c55e")
                h += f"<td style='text-align:right;{cor}'>R$ {fmt(v)}</td>"
        h += f"<td style='text-align:right;font-weight:700;color:#38bdf8'>R$ {fmt(total)}</td></tr>"
    h += "<tr style='background:#0f172a;border-top:2px solid #334155'><td colspan='2' style='font-weight:700;color:#f8fafc'>TOTAL GERAL</td>"
    for m in MESES_COMB: h += f"<td style='text-align:right;font-weight:700;color:#f8fafc'>R$ {fmt(totais_mes[m])}</td>"
    h += f"<td style='text-align:right;font-weight:700;color:#38bdf8'>R$ {fmt(total_geral)}</td></tr>"
    return h

comb_emp_pivot = {}
if not df_combust_empresa.empty:
    for _, r in df_combust_empresa.iterrows():
        emp = r['empresa']; m = r['mes']
        if emp not in comb_emp_pivot: comb_emp_pivot[emp] = {}
        comb_emp_pivot[emp][m] = {'gasto': float(r.get('total_gasto') or 0), 'litros': float(r.get('total_litros') or 0), 'escalas': int(r.get('escalas_mes') or 0), 'rs_escala': float(r.get('rs_por_escala') or 0), 'motoristas': int(r.get('motoristas') or 0)}

def html_comb_emp_pivo():
    if not comb_emp_pivot: return "<tr><td colspan='10'>Sem dados</td></tr>"
    ranking = sorted(comb_emp_pivot.items(), key=lambda x: sum(v.get('gasto',0) for v in x[1].values()), reverse=True)
    h = ""; totais_emp = {m: 0 for m in MESES_COMB}; total_emp_geral = 0
    for emp, dados in ranking[:20]:
        total = sum(dados.get(m,{}).get('gasto',0) for m in MESES_COMB)
        if total == 0: continue
        total_emp_geral += total; max_mot = max((dados.get(m,{}).get('motoristas',0) for m in MESES_COMB), default=0)
        h += f"<tr><td><b>{emp}</b></td><td style='text-align:center'>{max_mot}</td>"
        for m in MESES_COMB:
            v = dados.get(m,{}).get('gasto',0); totais_emp[m] += v
            if v == 0: h += "<td style='text-align:right;color:#334155'>—</td>"
            else:
                cor = "color:#ef4444;font-weight:700" if v > 500000 else ("color:#f59e0b" if v > 150000 else "color:#22c55e")
                h += f"<td style='text-align:right;{cor}'>R$ {fmt(v)}</td>"
        h += f"<td style='text-align:right;font-weight:700;color:#38bdf8'>R$ {fmt(total)}</td></tr>"
    h += "<tr style='background:#0f172a;border-top:2px solid #334155'><td colspan='2' style='font-weight:700;color:#f8fafc'>TOTAL (top 20)</td>"
    for m in MESES_COMB: h += f"<td style='text-align:right;font-weight:700;color:#f8fafc'>R$ {fmt(totais_emp[m])}</td>"
    h += f"<td style='text-align:right;font-weight:700;color:#38bdf8'>R$ {fmt(total_emp_geral)}</td></tr>"
    return h

comb_mot_pivot = {}
if not df_combust_mot.empty:
    for _, r in df_combust_mot.iterrows():
        k = r['motorista']; m = r['mes']
        if k not in comb_mot_pivot: comb_mot_pivot[k] = {'empresa': r['empresa'], 'cidade': r.get('cidade',''), 'gre': r.get('gre','')}
        comb_mot_pivot[k][m] = {'gasto': float(r.get('gasto') or 0), 'litros': float(r.get('litros') or 0), 'escalas': int(r.get('escalas_mes') or 0), 'rs_escala': float(r.get('rs_por_escala') or 0)}

def html_comb_mot_pivo():
    if not comb_mot_pivot: return "<tr><td colspan='12'>Sem dados</td></tr>"
    ranking = sorted(comb_mot_pivot.items(), key=lambda x: sum(x[1].get(m,{}).get('gasto',0) for m in MESES_COMB), reverse=True)
    h = ""
    for i, (nome, dados) in enumerate(ranking[:30]):
        total_esc = sum(dados.get(m,{}).get('escalas',0) for m in MESES_COMB)
        if total_esc == 0: continue
        total_g = sum(dados.get(m,{}).get('gasto',0) for m in MESES_COMB)
        rs_med = round(total_g / max(total_esc,1), 2)
        cor_rs = "color:#ef4444;font-weight:700" if rs_med > 8000 else ("color:#f59e0b" if rs_med > 5000 else "")
        h += f"<tr><td style='text-align:center;font-weight:700'>#{i+1}</td><td><b>{nome}</b></td><td style='font-size:11px'>{dados['empresa']}</td>"
        h += f"<td style='font-size:11px'>{dados['cidade']}</td><td style='font-size:11px'>{dados['gre']}</td>"
        for m in MESES_COMB:
            v = dados.get(m,{}).get('gasto',0)
            if v == 0: h += "<td style='text-align:right;color:#334155'>—</td>"
            else:
                cor = "color:#ef4444" if v > 1500000 else ("color:#f59e0b" if v > 800000 else "")
                h += f"<td style='text-align:right;{cor}'>R$ {fmt(v)}</td>"
        h += f"<td style='text-align:right;font-weight:700;color:#38bdf8'>R$ {fmt(total_g)}</td><td style='text-align:right;{cor_rs}'>R$ {fmt(rs_med)}</td></tr>"
    return h

# ─── COMENTÁRIOS AUTOMÁTICOS ─────────────────────────────────────────────────
def comentario_cidades():
    criticas = [r for r in cidade_scores if r['cls'] in ('crit','zero')][:3]
    if not criticas: return "Nenhuma cidade em situação crítica identificada no período."
    textos = []
    for r in criticas:
        v = [x for x in r['vals'] if x is not None]; ultimo = v[-1] if v else 0
        acoes = {'SEM REGISTRO': 'nunca registrou via rastreamento — resistência deliberada','REGREDIU TOTAL': 'regrediu para zero após ter iniciado o registro — ação imediata necessária','EM QUEDA FORTE': 'em queda acelerada nos últimos dois meses','EM QUEDA': 'em queda consistente — intervenção urgente'}
        desc = acoes.get(r['status'], 'índice abaixo do esperado')
        textos.append(f"<b>{r.get('cidade','?')}</b> ({r.get('total',0):,} escalas): {desc}. Índice atual: {ultimo}%.")
    return " &nbsp;·&nbsp; ".join(textos)

def comentario_fraude():
    if df_fraude_mensal.empty: return ""
    ultimo = df_fraude_mensal.iloc[-2] if len(df_fraude_mensal) > 1 else df_fraude_mensal.iloc[-1]
    penultimo = df_fraude_mensal.iloc[-3] if len(df_fraude_mensal) > 2 else df_fraude_mensal.iloc[-2]
    s_atual = int(ultimo.get('suspeitas') or 0); s_ant = int(penultimo.get('suspeitas') or 0)
    m_atual = int(ultimo.get('sem_rast') or 0); m_ant = int(penultimo.get('sem_rast') or 0)
    txt = f"Rotas suspeitas em {ultimo['mes']}: <b>{s_atual:,}</b>"
    if s_ant > 0:
        var = round((s_atual - s_ant)/s_ant*100, 1); sinal = "▲" if var > 0 else "▼"; cor = "color:#ef4444" if var > 0 else "color:#22c55e"
        txt += f" <span style='{cor}'>{sinal} {abs(var)}% vs mês anterior</span>"
    txt += f". Confirmações sem rastreamento: <b>{m_atual:,}</b>"
    if m_ant > 0:
        var2 = round((m_atual - m_ant)/m_ant*100, 1); sinal2 = "▲" if var2 > 0 else "▼"; cor2 = "color:#ef4444" if var2 > 0 else "color:#22c55e"
        txt += f" <span style='{cor2}'>{sinal2} {abs(var2)}%</span>"
    txt += ". <b>100% dos casos são de prestadores terceirizados.</b>"
    return txt

def comentario_gre():
    if not gre_pivot: return ""
    melhor = None; pior = None
    for gre, dados in gre_pivot.items():
        vals = [dados.get(m,{}).get('pct',0) for m in MESES_COLS if m in dados]
        if len(vals) < 2: continue
        ultimo = vals[-1]
        if melhor is None or ultimo > melhor[1]: melhor = (gre, ultimo)
        if pior is None or ultimo < pior[1]: pior = (gre, ultimo)
    txt = ""
    if melhor: txt += f"Melhor índice atual: <b>{melhor[0]}</b> com {melhor[1]}% de rastreamento. "
    if pior: txt += f"Pior índice atual: <b>{pior[0]}</b> com {pior[1]}%. "
    txt += "A tendência de queda no Q3/2026 é generalizada — investigar causas comuns (calendário escolar, resistência ou problema técnico)."
    return txt

def comentario_contratos():
    n = len(df_contratos) if not df_contratos.empty else 0
    total_risco = 184493 + 199506
    return (f"<b>{n} contratos ativos sem operação nos últimos 30 dias.</b> Valor diário estimado em risco: <b>R$ {fmt(total_risco)}</b> "
            f"(veículos que nunca rodaram + parados há +90 dias com contrato ativo). Recomendação: solicitar comprovação de operação ou suspender pagamento até regularização.")

def comentario_combustivel():
    if not comb_gre_pivot: return ""
    maior_gre = max(comb_gre_pivot.items(), key=lambda x: sum(x[1].get(m,{}).get('gasto',0) for m in MESES_COMB), default=(None,{}))[0]
    if not maior_gre: return ""
    dados = comb_gre_pivot[maior_gre]; total = sum(dados.get(m,{}).get('gasto',0) for m in MESES_COMB)
    pico_mes = max(MESES_COMB, key=lambda m: dados.get(m,{}).get('gasto',0)); pico_val = dados.get(pico_mes,{}).get('gasto',0)
    return (f"GRE com maior gasto de combustível: <b>{maior_gre}</b> — R$ {fmt(total)} no período. "
            f"Pico em {MESES_COMB_NOMES.get(pico_mes,'')}: R$ {fmt(pico_val)}. Verificar se o volume de escalas justifica o consumo ou se há abastecimentos sem execução de rota.")

cidade_top = df_bonificacao_cidade['cidade'].iloc[0] if not df_bonificacao_cidade.empty else '—'
gre_top = df_bonificacao_gre['gre'].iloc[0] if not df_bonificacao_gre.empty else '—'
n_mot_bonif = len(df_bonificacao_mot) if not df_bonificacao_mot.empty else 0

def html_bonif_mot():
    if df_bonificacao_mot.empty: return "<tr><td colspan='10'>Sem dados</td></tr>"
    h = ""
    for i, (_, r) in enumerate(df_bonificacao_mot.iterrows()):
        score = float(r.get('score') or 0); pct_r = float(r.get('pct_rastreado') or 0); pct_s = float(r.get('pct_suspeitas') or 0)
        cor_score = "color:#22c55e;font-weight:700" if score >= 70 else ("color:#f59e0b;font-weight:700" if score >= 50 else "color:#ef4444")
        medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"#{i+1}"))
        h += f"<tr><td style='text-align:center;font-weight:700'>{medal}</td><td><b>{r['motorista']}</b></td><td>{r['empresa']}</td><td>{r.get('cidade','')}</td><td>{r.get('gre','')}</td>"
        h += f"<td style='text-align:center'>{int(r.get('total_escalas',0)):,}</td><td style='text-align:center;{cor_pct(pct_r)}'>{pct_r}%</td>"
        h += f"<td style='text-align:center'>{int(r.get('suspeitas',0))}</td><td style='text-align:center;{'color:#ef4444' if pct_s > 5 else ''}'>{pct_s}%</td><td style='text-align:center;{cor_score}'>{score}</td></tr>"
    return h

def html_bonif_gre():
    if df_bonificacao_gre.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for i, (_, r) in enumerate(df_bonificacao_gre.iterrows()):
        score = float(r.get('score') or 0); pct_r = float(r.get('pct_rastreado') or 0)
        cor_score = "color:#22c55e;font-weight:700" if score >= 50 else ("color:#f59e0b" if score >= 30 else "color:#ef4444")
        medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"#{i+1}"))
        h += f"<tr><td style='text-align:center'>{medal}</td><td><b>{r['gre']}</b></td><td>{r.get('fiscal','—')}</td>"
        h += f"<td style='text-align:center'>{int(r.get('motoristas',0))}</td><td style='text-align:center;{cor_pct(pct_r)}'>{pct_r}%</td>"
        h += f"<td style='text-align:center;{'color:#ef4444' if float(r.get('pct_suspeitas',0))>5 else ''}'>{r.get('pct_suspeitas',0)}%</td><td style='text-align:center;{cor_score}'>{score}</td></tr>"
    return h

def html_bonif_cidade():
    if df_bonificacao_cidade.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for i, (_, r) in enumerate(df_bonificacao_cidade.iterrows()):
        score = float(r.get('score') or 0); pct_r = float(r.get('pct_rastreado') or 0)
        cor_score = "color:#22c55e;font-weight:700" if score >= 50 else ("color:#f59e0b" if score >= 30 else "color:#ef4444")
        medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"#{i+1}"))
        h += f"<tr><td style='text-align:center'>{medal}</td><td><b>{r['cidade']}</b></td><td style='text-align:center'>{int(r.get('motoristas',0))}</td>"
        h += f"<td style='text-align:center'>{int(r.get('total_escalas',0)):,}</td><td style='text-align:center;{cor_pct(pct_r)}'>{pct_r}%</td>"
        h += f"<td style='text-align:center;{'color:#ef4444' if float(r.get('pct_suspeitas',0))>5 else ''}'>{r.get('pct_suspeitas',0)}%</td><td style='text-align:center;{cor_score}'>{score}</td></tr>"
    return h

def comentario_executivo():
    if exec_total == 0:
        return "<b>Nenhuma rota encontrada</b> no mês atual com os filtros padrão."
    return (
        f"<b>{exec_total:,} ocorrências analisadas</b> · "
        f"<b>{exec_conc:,} concluídas</b> · "
        f"<b>{exec_nao:,} não executadas</b> · "
        f"<b>{exec_and:,} em andamento</b> · "
        f"assiduidade <b>{exec_pct_assid}%</b> · "
        f"extras <b>{exec_extras:,}</b> · "
        f"KM executado <b>{fmt(exec_km)} km</b>."
    )

# ─── FUNÇÕES HTML — GERENTE DE CONTRATOS ────────────────────────────────────

def html_gc_frota_status():
    if df_gc_frota_status.empty:
        return "<tr><td colspan='9'>Sem dados</td></tr>"
    h = ""
    tipos_nice = {
        'FROTA_PROPRIA':'🚗 Frota Própria',
        'FROTA_TERCEIRIZADA':'🤝 Terceirizada',
        'FROTA_PARCEIRO':'🤝 Parceiro',
        'FROTA_LOCADA':'🏷️ Locada',
        'SEM TIPO':'❓ Sem tipo'
    }
    for _, r in df_gc_frota_status.iterrows():
        tipo = tipos_nice.get(r['tipo'], str(r['tipo']))
        ociosos = int(r.get('ociosos_com_contrato') or 0)
        sem_contrato = int(r.get('sem_contrato') or 0)
        inativos_contrato = int(r.get('inativos_com_contrato') or 0)
        cor_ociosos = "color:#ef4444;font-weight:700" if ociosos > 10 else "color:#f59e0b"
        cor_sem = "color:#38bdf8;font-weight:700" if sem_contrato > 0 else ""
        cor_inat = "color:#ef4444;font-weight:700" if inativos_contrato > 0 else "color:#64748b"
        h += f"<tr><td><b>{tipo}</b></td><td style='text-align:center'>{int(r.get('total',0)):,}</td>"
        h += f"<td style='text-align:center;color:#22c55e;font-weight:700'>{int(r.get('ativos',0)):,}</td>"
        h += f"<td style='text-align:center'>{int(r.get('inativos',0)):,}</td>"
        h += f"<td style='text-align:center;color:#38bdf8;font-weight:700'>{int(r.get('em_operacao',0)):,}</td>"
        h += f"<td style='text-align:center;{cor_ociosos}'>{ociosos:,}</td>"
        h += f"<td style='text-align:center'>{int(r.get('com_contrato',0)):,}</td>"
        h += f"<td style='text-align:center;{cor_sem}'>{sem_contrato:,}</td>"
        h += f"<td style='text-align:center;{cor_inat}'>{inativos_contrato:,}</td></tr>"
    return h


def html_gc_gap_gre():
    if df_gc_gap_gre.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for _, r in df_gc_gap_gre.iterrows():
        sit = r.get('situacao','')
        cores_sit = {'SOBRECARGA':'color:#ef4444;font-weight:700','FROTA OCIOSA':'color:#f59e0b;font-weight:700','LIMITE':'color:#f97316;font-weight:700','EQUILIBRADO':'color:#22c55e','SEM FROTA':'color:#a78bfa;font-weight:700'}
        cor = cores_sit.get(sit, '')
        h += f"<tr><td><b>{r.get('gre','—')}</b></td><td style='text-align:center'>{int(r.get('frota_ativa',0))}</td>"
        h += f"<td style='text-align:center;color:#38bdf8;font-weight:700'>{int(r.get('frota_operando',0))}</td>"
        h += f"<td style='text-align:center'>{int(r.get('escalas_30d',0)):,}</td>"
        h += f"<td style='text-align:center'>{int(r.get('veiculos_usados',0))}</td>"
        h += f"<td style='text-align:center'>{r.get('utilizacao_pct',0)}%</td>"
        h += f"<td style='{cor}'>{sit}</td></tr>"
    return h


def html_gc_custo_tipo():
    if df_gc_custo_tipo.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    h = ""
    tipos_nice = {'FROTA_PROPRIA':'🚗 Própria','FROTA_TERCEIRIZADA':'🤝 Terceirizada','FROTA_PARCEIRO':'🤝 Parceiro','FROTA_LOCADA':'🏷️ Locada'}
    for _, r in df_gc_custo_tipo.iterrows():
        tipo = tipos_nice.get(r['tipo'], r['tipo'])
        custo_esc = float(r.get('custo_por_escala') or 0)
        cor_custo = "color:#22c55e" if custo_esc < 500 else ("color:#f59e0b" if custo_esc < 800 else "color:#ef4444;font-weight:700")
        h += f"<tr><td><b>{tipo}</b></td><td style='text-align:center'>{int(r.get('media_escalas',0)):,}</td>"
        h += f"<td style='text-align:center'>{int(r.get('media_veiculos',0))}</td>"
        h += f"<td style='text-align:right;color:#38bdf8;font-weight:700'>R$ {fmt(r.get('media_custo_mensal',0))}</td>"
        h += f"<td style='text-align:right;{cor_custo}'>R$ {fmt(custo_esc)}</td>"
        h += f"<td style='text-align:right'>R$ {fmt(r.get('custo_por_veiculo',0))}</td></tr>"
    return h


def html_gc_rank_terceiros_quantidade():
    if df_gc_rank_terceiros.empty:
        return "<tr><td colspan='4'>Sem dados</td></tr>"
    h = ""
    for i, (_, r) in enumerate(df_gc_rank_terceiros.sort_values(['contratos_rota','valor_diaria_dia'], ascending=[False,False]).head(10).iterrows()):
        medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"#{i+1}"))
        h += f"<tr><td style='text-align:center;font-weight:700'>{medal}</td><td><b>{r.get('fornecedor','SEM FORNECEDOR')}</b></td><td style='text-align:center'>{int(r.get('contratos_rota',0)):,}</td><td style='text-align:center'>{int(r.get('veiculos',0)):,}</td></tr>"
    return h


def html_gc_rank_terceiros_valor():
    if df_gc_rank_terceiros.empty:
        return "<tr><td colspan='5'>Sem dados</td></tr>"
    base = df_gc_rank_terceiros.sort_values(['valor_diaria_dia','contratos_rota'], ascending=[False,False]).head(10)
    h = ""
    for i, (_, r) in enumerate(base.iterrows()):
        medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"#{i+1}"))
        h += f"<tr><td style='text-align:center;font-weight:700'>{medal}</td><td><b>{r.get('fornecedor','SEM FORNECEDOR')}</b></td><td style='text-align:center'>{int(r.get('qtd_diaria',0)):,}</td><td style='text-align:right;color:#ef4444;font-weight:700'>R$ {fmt(r.get('valor_diaria_dia',0))}</td><td style='text-align:center'>/ dia</td></tr>"
    return h


def html_gc_sem_placa():
    if df_gc_sem_placa.empty:
        return "<tr><td colspan='9'>Nenhum contrato rota ativo sem placa vinculada.</td></tr>"
    h = ""
    for _, r in df_gc_sem_placa.iterrows():
        modal = str(r.get('modalidade_pagamento','') or '—')
        val = float(r.get('valor_unitario') or 0)
        unidade = '/dia' if modal == 'DIARIA' else '/mês' if modal == 'MENSAL' else ''
        h += f"<tr><td><b>#{r.get('contrato_rota_id','—')}</b></td><td style='text-align:center'>#{r.get('contrato_id','—')}</td><td>{r.get('gre','—')}</td><td>{r.get('fornecedor','—')}</td><td>{modal}</td><td style='text-align:right'>R$ {fmt(val)}{unidade}</td><td>{str(r.get('data_inicio',''))[:10] if r.get('data_inicio') else '—'}</td><td>{str(r.get('data_fim',''))[:10] if r.get('data_fim') else '—'}</td><td style='color:#a78bfa;font-weight:700'>SEM PLACA</td></tr>"
    return h


def html_gc_inativos_contrato():
    if df_gc_inativos_contrato.empty: return "<tr><td colspan='11'>Nenhum veículo inativo com contrato ativo.</td></tr>"
    h = ""
    for _, r in df_gc_inativos_contrato.iterrows():
        status = str(r.get('veiculo_status',''))
        cor = 'color:#ef4444;font-weight:700' if status == 'I' else 'color:#f59e0b;font-weight:700'
        tipo = str(r.get('tipo_frota','SEM TIPO') or 'SEM TIPO').replace('FROTA_','')
        modal = r.get('modalidade_pagamento','—') or '—'
        val = float(r.get('valor_unitario') or 0)
        unidade = '/dia' if modal == 'DIARIA' else '/mês' if modal == 'MENSAL' else ''
        h += f"<tr><td style='{cor}'><b>{r.get('placa','—')}</b></td><td>{r.get('modelo','—')}</td><td>{r.get('gre','—')}</td>"
        h += f"<td>{r.get('fornecedor','—')}</td><td>{tipo}</td><td style='{cor}'>{r.get('alerta','')}</td>"
        h += f"<td style='text-align:center'>#{r.get('contrato_id','—')}</td><td style='text-align:center'>#{r.get('contrato_rota_id','—')}</td>"
        h += f"<td>{modal}</td><td style='text-align:right'>R$ {fmt(val)}{unidade}</td><td>{str(r.get('data_fim',''))[:10] if r.get('data_fim') else '—'}</td></tr>"
    return h


def html_gc_ociosa():
    if df_gc_ociosa_contrato.empty: return "<tr><td colspan='9'>Nenhuma frota ativa com contrato e sem operação nos últimos 30 dias.</td></tr>"
    h = ""
    for _, r in df_gc_ociosa_contrato.iterrows():
        dias = int(r.get('dias_parado') or 0)
        risco = float(r.get('valor_risco_acumulado') or 0)
        cor_dias = "color:#ef4444;font-weight:700" if dias > 90 else ("color:#f97316;font-weight:700" if dias > 60 else "color:#f59e0b")
        tipo = str(r.get('tipo','SEM TIPO') or 'SEM TIPO').replace('FROTA_','')
        modal = r.get('modalidade_pagamento','—') or '—'
        val = float(r.get('valor_unitario') or 0)
        unidade = '/dia' if modal == 'DIARIA' else '/mês' if modal == 'MENSAL' else ''
        h += f"<tr><td>{r.get('gre','—')}</td><td><b>{r.get('placa','—')}</b></td><td>{r.get('modelo','—')}</td><td>{tipo}</td><td>{r.get('fornecedor','—')}</td>"
        h += f"<td>{modal}</td><td style='text-align:right'>R$ {fmt(val)}{unidade}</td><td style='text-align:center;{cor_dias}'>{dias:,} dias</td>"
        h += f"<td style='text-align:right;color:#ef4444;font-weight:700'>R$ {fmt(risco)}</td></tr>"
    return h


def html_gc_demanda():
    if df_gc_demanda_diaria.empty: return "<tr><td colspan='9'>Sem dados</td></tr>"
    h = ""
    for _, r in df_gc_demanda_diaria.iterrows():
        media = float(r.get('media_escalas_dia') or 0)
        cor_media = "color:#ef4444;font-weight:700" if media > 50 else ("color:#f59e0b" if media > 30 else "color:#22c55e")
        h += f"<tr><td><b>{r.get('gre','—')}</b></td><td style='text-align:center'>{int(r.get('dias_com_escala',0))}</td>"
        h += f"<td style='text-align:center'>{int(r.get('total_escalas',0)):,}</td><td style='text-align:center;{cor_media}'>{media}</td>"
        h += f"<td style='text-align:center'>{int(r.get('veiculos_distintos',0))}</td><td style='text-align:center'>{int(r.get('veic_proprios',0))}</td>"
        h += f"<td style='text-align:center'>{int(r.get('veic_terceirizados',0))}</td><td style='text-align:center'>{int(r.get('veic_parceiros',0))}</td><td style='text-align:center'>{int(r.get('veic_locados',0))}</td></tr>"
    return h


def html_gc_historico():
    if df_gc_historico.empty:
        return "<tr><td colspan='3'>Sem dados</td></tr>"
    h = ""
    nomes = {'2026-01':'Jan/26','2026-02':'Fev/26','2026-03':'Mar/26','2026-04':'Abr/26','2026-05':'Mai/26','2026-06':'Jun/26','2026-07':'Jul/26','2026-08':'Ago/26','2026-09':'Set/26','2026-10':'Out/26','2026-11':'Nov/26','2026-12':'Dez/26'}
    anterior = None
    for _, r in df_gc_historico.iterrows():
        mes_raw = str(r.get('mes',''))
        mes = nomes.get(mes_raw, mes_raw or '—')
        qtd = int(r.get('contratos_ativos',0) or 0)
        variacao = '—' if anterior is None else f"{qtd-anterior:+d}"
        cor = 'color:#22c55e;font-weight:700' if anterior is not None and qtd > anterior else ('color:#ef4444;font-weight:700' if anterior is not None and qtd < anterior else 'color:#94a3b8')
        h += f"<tr><td><b>{mes}</b></td><td style='text-align:center;color:#38bdf8;font-weight:700'>{qtd:,}</td><td style='text-align:center;{cor}'>{variacao}</td></tr>"
        anterior = qtd
    return h


def _gc_date_str(v):
    if v is None:
        return ''
    return str(v)[:10]


def _gc_num(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _gc_int(v):
    try:
        return int(v or 0)
    except Exception:
        return 0


def _gc_mes_nome(ym):
    nomes = {
        '01':'Jan','02':'Fev','03':'Mar','04':'Abr','05':'Mai','06':'Jun',
        '07':'Jul','08':'Ago','09':'Set','10':'Out','11':'Nov','12':'Dez'
    }
    parts = str(ym).split('-')
    return f"{nomes.get(parts[1], parts[1] if len(parts)>1 else ym)}/{parts[0][-2:]}" if len(parts) > 1 else str(ym)


def _gc_fmt_data(data_iso):
    try:
        y,m,d = [int(x) for x in str(data_iso)[:10].split('-')]
        return f"{d:02d}/{m:02d}/{y}"
    except Exception:
        return str(data_iso)


# Monta os consolidados operacionais para o calendário financeiro.
gc_oper_dia = {}
if not df_gc_operacao_diaria.empty:
    for _, r in df_gc_operacao_diaria.iterrows():
        data_iso = _gc_date_str(r.get('data'))
        gc_oper_dia[data_iso] = {
            'execucoes': _gc_int(r.get('execucoes')),
            'contratos': _gc_int(r.get('contratos_rota_executados')),
            'rotas': _gc_int(r.get('rotas_viagens')),
            'motoristas': _gc_int(r.get('motoristas')),
            'veiculos': _gc_int(r.get('veiculos')),
            'concluidas': _gc_int(r.get('concluidas')),
            'em_andamento': _gc_int(r.get('em_andamento')),
        }

gc_oper_mes = {}
if not df_gc_operacao_mensal.empty:
    for _, r in df_gc_operacao_mensal.iterrows():
        mes_iso = _gc_date_str(r.get('mes'))[:7]
        gc_oper_mes[mes_iso] = {
            'execucoes': _gc_int(r.get('execucoes')),
            'contratos': _gc_int(r.get('contratos_rota_executados')),
            'rotas': _gc_int(r.get('rotas_viagens')),
            'motoristas': _gc_int(r.get('motoristas')),
            'veiculos': _gc_int(r.get('veiculos')),
            'concluidas': _gc_int(r.get('concluidas')),
            'em_andamento': _gc_int(r.get('em_andamento')),
        }

# Monta o calendário mensal/dia a partir dos dados reais consultados no banco.
gc_pag_dia = {}
if not df_gc_pagamento_diario.empty:
    for _, r in df_gc_pagamento_diario.iterrows():
        data_iso = _gc_date_str(r.get('data'))
        gc_pag_dia[data_iso] = {
            'contratos': _gc_int(r.get('contratos_rota_diaria')),
            'valor': _gc_num(r.get('valor_diarias')),
        }

gc_pag_mensal = {}
if not df_gc_pagamento_mensal.empty:
    for _, r in df_gc_pagamento_mensal.iterrows():
        mes_iso = _gc_date_str(r.get('mes'))[:7]
        gc_pag_mensal[mes_iso] = {
            'contratos': _gc_int(r.get('contratos_mensais_executados')),
            'valor': _gc_num(r.get('valor_mensal')),
        }

gc_pag_detalhes = {}
if not df_gc_pagamento_detalhe.empty:
    for _, r in df_gc_pagamento_detalhe.iterrows():
        data_iso = _gc_date_str(r.get('data'))
        gc_pag_detalhes.setdefault(data_iso, []).append({
            'contrato_rota': _gc_int(r.get('contrato_rota_id')),
            'contrato_mestre': _gc_int(r.get('contrato_id')),
            'fornecedor': str(r.get('fornecedor') or 'SEM FORNECEDOR'),
            'gre': str(r.get('gre') or 'SEM GRE'),
            'motoristas': str(r.get('motoristas') or 'SEM MOTORISTA'),
            'placas': str(r.get('placas') or 'SEM PLACA'),
            'rotas': str(r.get('rotas') or 'SEM ROTA'),
            'execucoes': _gc_int(r.get('execucoes')),
            'valor': _gc_num(r.get('valor_diaria')),
        })

# Meses do calendário: Jan/2026 até o mês atual da execução do RPA.
_gc_hoje = datetime.now().date()
gc_cal_meses = []
for ano in range(2026, _gc_hoje.year + 1):
    m_ini = 1
    m_fim = _gc_hoje.month if ano == _gc_hoje.year else 12
    for mes_num in range(m_ini, m_fim + 1):
        ym = f"{ano:04d}-{mes_num:02d}"
        dias = []
        ultimo_dia = calendar.monthrange(ano, mes_num)[1]
        limite_dia = _gc_hoje.day if (ano == _gc_hoje.year and mes_num == _gc_hoje.month) else ultimo_dia
        total_diarias = 0.0
        total_contratos_diaria = 0
        dias_com_operacao = 0
        for d in range(1, limite_dia + 1):
            data_iso = f"{ano:04d}-{mes_num:02d}-{d:02d}"
            info = gc_pag_dia.get(data_iso, {'contratos':0,'valor':0.0})
            oper = gc_oper_dia.get(data_iso, {'execucoes':0,'contratos':0,'rotas':0,'motoristas':0,'veiculos':0,'concluidas':0,'em_andamento':0})
            tem = oper['execucoes'] > 0
            if tem:
                dias_com_operacao += 1
                total_diarias += info['valor']
                total_contratos_diaria += info['contratos']
            dias.append({
                'data': data_iso,
                'label': _gc_fmt_data(data_iso),
                'execucoes': oper['execucoes'],
                'contratos_executados': oper['contratos'],
                'rotas': oper['rotas'],
                'motoristas': oper['motoristas'],
                'veiculos': oper['veiculos'],
                'concluidas': oper.get('concluidas',0),
                'em_andamento': oper.get('em_andamento',0),
                'contratos_diaria': info['contratos'],
                'valor': info['valor'],
                'detalhes': gc_pag_detalhes.get(data_iso, []),
            })
        mens = gc_pag_mensal.get(ym, {'contratos':0,'valor':0.0})
        oper_mes = gc_oper_mes.get(ym, {'execucoes':0,'contratos':0,'rotas':0,'motoristas':0,'veiculos':0,'concluidas':0,'em_andamento':0})
        dias_com_valor = [d for d in dias if d['valor'] > 0]
        maior_dia = max(dias_com_valor, key=lambda d: d['valor'], default={'data':'—','label':'—','valor':0.0,'contratos':0})
        menor_dia = min(dias_com_valor, key=lambda d: d['valor'], default={'data':'—','label':'—','valor':0.0,'contratos':0})
        gc_cal_meses.append({
            'ym': ym,
            'nome': _gc_mes_nome(ym),
            'dias': dias,
            'dias_com_operacao': dias_com_operacao,
            'execucoes': oper_mes['execucoes'],
            'contratos_rota_executados': oper_mes['contratos'],
            'rotas_viagens': oper_mes['rotas'],
            'motoristas': oper_mes['motoristas'],
            'veiculos': oper_mes['veiculos'],
            'concluidas': oper_mes.get('concluidas',0),
            'em_andamento': oper_mes.get('em_andamento',0),
            'contratos_rota_diaria': total_contratos_diaria,
            'valor_diarias': total_diarias,
            'contratos_mensais': mens['contratos'],
            'valor_mensal': mens['valor'],
            'total_previsto': total_diarias + mens['valor'],
            'maior_dia': maior_dia,
            'menor_dia': menor_dia,
        })


def html_gc_pagamento_calendario():
    if not gc_cal_meses:
        return "<div class='info'>Sem dados de execução para montar o calendário financeiro.</div>"

    h = ""
    for mes in reversed(gc_cal_meses):
        aberto = ' open' if mes['ym'] == gc_cal_meses[-1]['ym'] else ''
        h += f"""
        <details class='gc-month'{aberto}>
          <summary>
            <span class='gc-month-title'>📅 {mes['nome']}</span>
            <span class='gc-month-metrics'>
              <span>{mes['execucoes']:,} execuções</span>
              <span>{mes['contratos_rota_executados']:,} Contratos Rota</span>
              <span>{mes['dias_com_operacao']} dias c/ operação</span>
              <span>{mes['concluidas']:,} concluídas · {mes['em_andamento']:,} em andamento</span>
              <strong>R$ {fmt(mes['total_previsto'])}</strong>
            </span>
          </summary>
          <div class='gc-month-body'>
            <div class='gc-month-cards'>
              <div class='gc-mini'><label>Execuções válidas</label><b>{mes['execucoes']:,}</b><span>início registrado · não anuladas</span></div>
              <div class='gc-mini'><label>Contratos Rota executados</label><b>{mes['contratos_rota_executados']:,}</b><span>distintos no mês</span></div>
              <div class='gc-mini'><label>Diárias computadas</label><b>R$ {fmt(mes['valor_diarias'])}</b><span>{mes['contratos_rota_diaria']:,} Contratos Rota-dia</span></div>
              <div class='gc-mini'><label>Mensalidades computadas</label><b>R$ {fmt(mes['valor_mensal'])}</b><span>{mes['contratos_mensais']:,} Contratos Rota com execução</span></div>
              <div class='gc-mini gc-mini-total'><label>Já computado a pagar</label><b>R$ {fmt(mes['total_previsto'])}</b><span>execução real registrada no mês</span></div>
            </div>
            <div class='gc-day-list'>
        """
        for dia in mes['dias']:
            zero = dia['execucoes'] == 0
            cls = ' gc-day-zero' if zero else ''
            h += f"""
              <details class='gc-day{cls}'>
                <summary>
                  <span class='gc-day-date'>{dia['label']}</span>
                  <span class='gc-day-count'>
                    <b>{dia['execucoes']:,}</b> execuções válidas · <b>{dia['contratos_executados']:,}</b> Contratos Rota ·
                    <b>{dia['contratos_diaria']:,}</b> diárias · <b>{dia['veiculos']:,}</b> veículos
                  </span>
                  <strong class='gc-day-value'>{'—' if zero else 'R$ '+fmt(dia['valor'])}</strong>
                </summary>
            """
            if zero:
                h += "<div class='gc-day-empty'>Nenhuma execução válida registrada para este dia (início de execução não preenchido ou registro inexistente).</div>"
            else:
                h += f"""
                  <div class='gc-day-detail'>
                    <div class='gc-day-stats'>
                      <span><b>Execuções válidas:</b> {dia['execucoes']:,}</span>
                      <span><b>Contratos Rota executados:</b> {dia['contratos_executados']:,}</span>
                      <span><b>Concluídas:</b> {dia['concluidas']:,}</span>
                      <span><b>Em andamento:</b> {dia['em_andamento']:,}</span>
                      <span><b>Rotas/viagens:</b> {dia['rotas']:,}</span>
                      <span><b>Motoristas:</b> {dia['motoristas']:,}</span>
                      <span><b>Veículos:</b> {dia['veiculos']:,}</span>
                      <span><b>Diárias faturáveis:</b> {dia['contratos_diaria']:,}</span>
                      <span><b>Já computado em diárias:</b> R$ {fmt(dia['valor'])}</span>
                    </div>
                    <div class='gc-day-note'>
                      <b>Regra de pagamento:</b> para DIÁRIA, o valor é computado uma única vez por <b>Contrato Rota + dia</b> com execução real.
                      O mesmo Contrato Rota pode estar em várias rotas/viagens e várias escalas no dia sem duplicar a diária.
                    </div>
                    <div class='tw'>
                      <table>
                        <thead><tr><th>Contrato Rota</th><th>Contrato Mestre</th><th>Fornecedor</th><th>GRE</th><th>Motorista(s)</th><th>Placa(s)</th><th>Execuções</th><th style='text-align:right'>Valor da Diária</th></tr></thead>
                        <tbody>
                """
                for det in dia['detalhes']:
                    h += f"<tr><td><b>#{det['contrato_rota']}</b></td><td>#{det['contrato_mestre']}</td><td>{det['fornecedor']}</td><td>{det['gre']}</td><td>{det['motoristas']}</td><td>{det['placas']}</td><td style='text-align:center'>{det['execucoes']}</td><td style='text-align:right;color:#38bdf8;font-weight:700'>R$ {fmt(det['valor'])}</td></tr>"
                if not dia['detalhes']:
                    h += "<tr><td colspan='8'>Detalhamento das diárias não disponível.</td></tr>"
                h += """
                        </tbody>
                      </table>
                    </div>
                  </div>
                """
            h += "</details>"
        h += """
            </div>
          </div>
        </details>
        """
    return h



# Valor já computado a pagar no mês corrente, baseado somente em execução real.
gc_pag_atual = gc_cal_meses[-1] if gc_cal_meses else {
    'nome': 'Mês atual', 'valor_diarias': 0.0, 'valor_mensal': 0.0, 'total_previsto': 0.0,
    'execucoes': 0, 'concluidas': 0, 'em_andamento': 0, 'contratos_rota_diaria': 0, 'contratos_mensais': 0
}
gc_pag_atual_diarias = float(gc_pag_atual.get('valor_diarias', 0.0) or 0.0)
gc_pag_atual_mensal = float(gc_pag_atual.get('valor_mensal', 0.0) or 0.0)
gc_pag_atual_total = float(gc_pag_atual.get('total_previsto', 0.0) or 0.0)
gc_pag_atual_execucoes = int(gc_pag_atual.get('execucoes', 0) or 0)
gc_pag_atual_concluidas = int(gc_pag_atual.get('concluidas', 0) or 0)
gc_pag_atual_andamento = int(gc_pag_atual.get('em_andamento', 0) or 0)

# ─── APOIO DO PAINEL EXECUTIVO ───────────────────────────────────────────────
# Histórico mensal do valor já computado: diárias deduplicadas por DATA + CONTRATO ROTA
# mais mensalidades deduplicadas por MÊS + CONTRATO ROTA.
exec_pag_hist = {}
if not df_gc_pagamento_diario.empty:
    for _, r in df_gc_pagamento_diario.iterrows():
        ym = _gc_date_str(r.get('data'))[:7]
        exec_pag_hist[ym] = exec_pag_hist.get(ym, 0.0) + _gc_num(r.get('valor_diarias'))
if not df_gc_pagamento_mensal.empty:
    for _, r in df_gc_pagamento_mensal.iterrows():
        ym = _gc_date_str(r.get('mes'))[:7]
        exec_pag_hist[ym] = exec_pag_hist.get(ym, 0.0) + _gc_num(r.get('valor_mensal'))

exec_pago_meses = [exec_pag_hist.get(m,0.0) for m in meses_ev]

# Resumo diário atual: últimos 10 dias com registro até hoje.
exec_dias_recentes = []
if gc_oper_dia:
    ultimas = sorted(gc_oper_dia.keys())[-10:]
    for data_iso in ultimas:
        op = gc_oper_dia[data_iso]
        pg = gc_pag_dia.get(data_iso, {'valor':0.0,'contratos':0})
        exec_dias_recentes.append({
            'data': _gc_fmt_data(data_iso),
            'execucoes': op.get('execucoes',0),
            'rotas': op.get('rotas',0),
            'contratos': op.get('contratos',0),
            'concluidas': op.get('concluidas',0),
            'andamento': op.get('em_andamento',0),
            'valor': pg.get('valor',0.0),
        })

# Previsão de fechamento: estimativa, não compromisso contratual.
# Usa a média dos dias úteis com valor real já computado no mês atual e projeta
# apenas os dias úteis restantes. A mensalidade potencial vem dos contratos mensais ativos.
_hoje_exec = datetime.now().date()
_atual_ym = _hoje_exec.strftime('%Y-%m')
_valores_uteis = []
if _atual_ym in exec_pag_hist or gc_pag_dia:
    for d in range(1, _hoje_exec.day + 1):
        dd = date(_hoje_exec.year, _hoje_exec.month, d)
        if dd.weekday() < 5:
            info = gc_pag_dia.get(dd.isoformat())
            if info and float(info.get('valor',0) or 0) > 0:
                _valores_uteis.append(float(info.get('valor',0) or 0))
_media_dia_exec = sum(_valores_uteis)/len(_valores_uteis) if _valores_uteis else 0.0
_dias_uteis_restantes = 0
for d in range(_hoje_exec.day + 1, calendar.monthrange(_hoje_exec.year, _hoje_exec.month)[1] + 1):
    if date(_hoje_exec.year, _hoje_exec.month, d).weekday() < 5:
        _dias_uteis_restantes += 1
_mensal_ativo_geral = float(df_gc_mensal_ativo_geral.iloc[0].get('valor_mensal_ativo',0) or 0) if not df_gc_mensal_ativo_geral.empty else 0.0
# A previsão final é: diárias já computadas + média real dos dias úteis restantes
# + a base mensal potencial ativa (sem somar duas vezes o que já foi computado).
_g_previsao_final = (
    float(gc_pag_atual_diarias)
    + (_media_dia_exec * _dias_uteis_restantes)
    + max(float(gc_pag_atual_mensal), _mensal_ativo_geral)
)
exec_previsao_final = max(_g_previsao_final, float(gc_pag_atual_total))
gc_previsao_fechamento = exec_previsao_final
gc_exec_contratos_mes = exec_contratos
gc_exec_validas_mes = exec_total

def comentario_gc_pagamento_calendario():
    if not gc_cal_meses:
        return "Sem dados de pagamento por execução."
    atual = gc_cal_meses[-1]
    meses_com_valor = [m for m in gc_cal_meses if m['total_previsto'] > 0]
    if not meses_com_valor:
        return "Não houve execução faturável registrada no período analisado."
    maior = max(meses_com_valor, key=lambda x: x['total_previsto'])
    menor = min(meses_com_valor, key=lambda x: x['total_previsto'])
    return (
        f"<b>Leitura operacional-financeira:</b> {atual['nome']} registra <b>{atual['execucoes']:,} execuções válidas</b> (início registrado e não anuladas) e <b>{atual['contratos_rota_executados']:,} Contratos Rota distintos</b> no mês, gerando <b>R$ {fmt(atual['total_previsto'])}</b> já computados a pagar. "
        f"O maior valor computado do período é <b>{maior['nome']}</b> (R$ {fmt(maior['total_previsto'])}). "
        f"No mês com menor valor computado observado, <b>{menor['nome']}</b>, foram computados R$ {fmt(menor['total_previsto'])}. "
        f"No detalhe diário, cada <b>Contrato Rota</b> conta apenas uma vez por dia na modalidade DIARIA, mesmo que o mesmo contrato esteja em várias rotas/viagens e várias escalas."
    )

# ─── COMENTÁRIOS AUTOMÁTICOS — GERENTE DE CONTRATOS ─────────────────────────

def comentario_gc_frota_analise():
    if df_gc_frota_geral.empty:
        return "Não foi possível obter a situação da frota no banco."
    r = df_gc_frota_geral.iloc[0]
    ativa = int(r.get('frota_ativa',0) or 0)
    oper = int(r.get('em_operacao',0) or 0)
    ociosa = int(r.get('ociosa_com_contrato',0) or 0)
    disp = int(r.get('disponivel_sem_contrato',0) or 0)
    inat = int(r.get('inativos_com_contrato',0) or 0)
    propria_contrato = int(r.get('propria_com_contrato',0) or 0)
    propria_sem = int(r.get('propria_sem_contrato',0) or 0)
    locada = int(r.get('ativa_locada',0) or 0)
    if ativa <= 0:
        return "<b style='color:#ef4444'>ATENÇÃO:</b> a consulta retornou zero veículos ativos."
    utiliz = round(oper / ativa * 100, 1)
    p_oci = round(ociosa / ativa * 100, 1)
    partes = [f"<b>Frota ativa:</b> {ativa:,} veículos; <b>em operação:</b> {oper:,} ({utiliz}%)."]
    partes.append(f"<b>Ociosa com contrato:</b> {ociosa:,} ({p_oci}%). É o grupo que merece revisão de alocação e pagamento.")
    partes.append(f"<b>Frota comercial disponível:</b> {disp:,}. Considera somente veículos ativos <b>terceirizados + locados</b> sem contrato vigente; não inclui frota própria ou parceira.")
    if inat > 0:
        partes.append(f"<b style='color:#ef4444'>Alerta crítico:</b> {inat:,} veículo(s) inativo(s) possuem contrato ativo. Isso deve ser tratado antes de qualquer renovação ou nova contratação.")
    if propria_contrato > 0:
        partes.append(f"<b style='color:#f59e0b'>Frota própria com contrato:</b> {propria_contrato:,} veículo(s). Como a frota própria não deveria depender de contrato, esse vínculo precisa ser auditado.")
    partes.append(f"<b>Frota própria sem contrato:</b> {propria_sem:,}; <b>locada ativa:</b> {locada:,}. Locada permanece em análise separada dos terceirizados.")
    return "<br>".join(partes)


def comentario_gc_financeiro():
    if df_gc_financeiro.empty:
        return "Não foi possível calcular a previsão financeira dos terceirizados."
    r = df_gc_financeiro.iloc[0]
    qd = int(r.get('qtd_diaria',0) or 0)
    vd = float(r.get('valor_diaria_dia',0) or 0)
    qm = int(r.get('qtd_mensal',0) or 0)
    vm = float(r.get('valor_mensal',0) or 0)
    qn = int(r.get('qtd_nao_identificado',0) or 0)
    vn = float(r.get('valor_nao_identificado',0) or 0)
    estimado_mes_diarias = vd * 22
    total_mes = estimado_mes_diarias + vm
    partes = [f"<b>Terceirizados — diária:</b> {qd:,} contratos rota · <b>R$ {fmt(vd)}/dia</b> · referência de <b>R$ {fmt(estimado_mes_diarias)}/mês</b> em 22 dias úteis."]
    partes.append(f"<b>Terceirizados — mensal:</b> {qm:,} contratos rota · <b>R$ {fmt(vm)}/mês</b>.")
    partes.append(f"<b>Previsão mensal combinada de terceiros:</b> <b style='color:#38bdf8'>R$ {fmt(total_mes)}</b>.")
    if qn > 0:
        partes.append(f"<b style='color:#f59e0b'>Não classificados:</b> {qn:,} itens · R$ {fmt(vn)}. Permanecem fora da previsão até a classificação correta.")
    return "<br>".join(partes)


def comentario_gc_locada():
    if df_gc_fin_locada.empty:
        return "Nenhum item de frota locada encontrado."
    r = df_gc_fin_locada.iloc[0]
    qd = int(r.get('qtd_diaria',0) or 0); vd = float(r.get('valor_diaria_dia',0) or 0)
    qm = int(r.get('qtd_mensal',0) or 0); vm = float(r.get('valor_mensal',0) or 0)
    return f"<b>Locada:</b> {int(r.get('itens_ativos',0) or 0)} item(ns) ativo(s) · {qd} diária(s) em R$ {fmt(vd)}/dia e {qm} mensal(is) em R$ {fmt(vm)}/mês. Mantida separada dos terceirizados para não misturar modelos contratuais."


def comentario_gc_historico():
    if df_gc_historico.empty:
        return "Sem histórico suficiente para análise."
    vals = [int(v or 0) for v in df_gc_historico['contratos_ativos'].tolist()]
    if not vals: return "Sem histórico suficiente para análise."
    atual = vals[-1]; inicio = vals[0]; delta = atual - inicio
    if delta > 0:
        return f"O estoque de contratos mestres em vigência passou de <b>{inicio:,}</b> para <b>{atual:,}</b> no período, alta líquida de <b>{delta:,}</b> contratos."
    if delta < 0:
        return f"O estoque de contratos mestres em vigência passou de <b>{inicio:,}</b> para <b>{atual:,}</b>, redução líquida de <b>{abs(delta):,}</b> contratos."
    return f"O estoque de contratos mestres em vigência permaneceu em <b>{atual:,}</b> entre o primeiro e o último mês disponível."


def comentario_gc_geral():
    if df_gc_resumo.empty or df_gc_frota_geral.empty:
        return "Não foi possível consolidar a análise gerencial."
    cr = df_gc_resumo.iloc[0]; fr = df_gc_frota_geral.iloc[0]
    contratos = int(cr.get('contratos_ativos',0) or 0)
    rotas = int(cr.get('contratos_rota_ativos',0) or 0)
    ativa = int(fr.get('frota_ativa',0) or 0)
    oper = int(fr.get('em_operacao',0) or 0)
    ociosa = int(fr.get('ociosa_com_contrato',0) or 0)
    inat = int(fr.get('inativos_com_contrato',0) or 0)
    propria = int(fr.get('propria_com_contrato',0) or 0)
    vd = float(df_gc_financeiro.iloc[0].get('valor_diaria_dia',0) or 0) if not df_gc_financeiro.empty else 0
    vm = float(df_gc_financeiro.iloc[0].get('valor_mensal',0) or 0) if not df_gc_financeiro.empty else 0
    total_ref = vd*22 + vm
    utiliz = round(oper/ativa*100,1) if ativa else 0
    partes = [f"<b>{contratos:,} contratos mestres ativos</b> controlam <b>{rotas:,} contratos rota</b> ativos. A frota ativa é de <b>{ativa:,}</b> veículos, com <b>{oper:,}</b> em operação nos últimos 30 dias ({utiliz}%)."]
    if ociosa:
        partes.append(f"Há <b style='color:#f59e0b'>{ociosa:,} veículos ativos com contrato e sem operação recente</b>; esse é o principal ponto de revisão de utilização e pagamento.")
    if inat:
        partes.append(f"Há <b style='color:#ef4444'>{inat:,} veículos inativos com contrato ativo</b>; isso é uma inconsistência contratual prioritária.")
    if propria:
        partes.append(f"Existem <b style='color:#f59e0b'>{propria:,} veículos de frota própria com contrato ativo</b>; esse vínculo deve ser auditado separadamente.")
    partes.append(f"A referência mensal dos terceiros é <b>R$ {fmt(total_ref)}</b> (22 dias úteis para diárias + mensalidades). Frota locada permanece fora desse cálculo para análise específica.")
    return "<br>".join(partes)


def comentario_gc_recomendacao():
    partes = []
    if not df_gc_inativos_contrato.empty:
        partes.append(f"<b style='color:#ef4444'>1. Corrigir {len(df_gc_inativos_contrato)} vínculo(s) de veículo inativo com contrato ativo.</b>")
    if not df_gc_frota_geral.empty:
        r = df_gc_frota_geral.iloc[0]
        ociosa = int(r.get('ociosa_com_contrato',0) or 0)
        if ociosa:
            partes.append(f"<b>2. Auditar {ociosa:,} veículo(s) ocioso(s) com contrato</b> antes de ampliar a frota.")
        propria = int(r.get('propria_com_contrato',0) or 0)
        if propria:
            partes.append(f"<b>3. Revisar {propria:,} vínculo(s) de frota própria com contrato</b> para eliminar custo contratual indevido.")
    if not df_gc_sem_placa.empty:
        itens = len(df_gc_sem_placa)
        if itens:
            partes.append(f"<b>4. Regularizar {itens:,} contrato(s) rota ativo(s) sem placa</b> antes de considerar o item regularizado para operação.")
    partes.append("<b>5. Manter frota locada separada dos terceirizados</b> e comparar seu custo com a alternativa de frota própria/terceirizada.")
    return "<br><br>".join(partes)


def comentario_gc_custo():
    if df_gc_custo_tipo.empty:
        return "Sem base suficiente para comparação de custo."
    melhor = df_gc_custo_tipo.loc[df_gc_custo_tipo['custo_por_escala'].idxmin()]
    pior = df_gc_custo_tipo.loc[df_gc_custo_tipo['custo_por_escala'].idxmax()]
    txt = f"<b>Menor custo estimado por escala:</b> {str(melhor['tipo']).replace('FROTA_','')} — R$ {fmt(melhor['custo_por_escala'])}/escala. "
    txt += f"<b>Maior custo:</b> {str(pior['tipo']).replace('FROTA_','')} — R$ {fmt(pior['custo_por_escala'])}/escala."
    return txt

# ─── KPIs GERENTE DE CONTRATOS ──────────────────────────────────────────────
gc_total = int(df_gc_resumo['contratos_ativos'].iloc[0]) if not df_gc_resumo.empty else 0
gc_itens_ativos = int(df_gc_resumo['contratos_rota_ativos'].iloc[0]) if not df_gc_resumo.empty else 0

gc_fin_qd = int(df_gc_financeiro['qtd_diaria'].iloc[0]) if not df_gc_financeiro.empty else 0
gc_fin_vd = float(df_gc_financeiro['valor_diaria_dia'].iloc[0]) if not df_gc_financeiro.empty else 0
gc_fin_qm = int(df_gc_financeiro['qtd_mensal'].iloc[0]) if not df_gc_financeiro.empty else 0
gc_fin_vm = float(df_gc_financeiro['valor_mensal'].iloc[0]) if not df_gc_financeiro.empty else 0
gc_fin_qn = int(df_gc_financeiro['qtd_nao_identificado'].iloc[0]) if not df_gc_financeiro.empty else 0
gc_fin_vn = float(df_gc_financeiro['valor_nao_identificado'].iloc[0]) if not df_gc_financeiro.empty else 0
gc_fin_ref_mes = gc_fin_vd * 22
gc_fin_total_mes = gc_fin_ref_mes + gc_fin_vm

gc_loc_qd = int(df_gc_fin_locada['qtd_diaria'].iloc[0]) if not df_gc_fin_locada.empty else 0
gc_loc_vd = float(df_gc_fin_locada['valor_diaria_dia'].iloc[0]) if not df_gc_fin_locada.empty else 0
gc_loc_qm = int(df_gc_fin_locada['qtd_mensal'].iloc[0]) if not df_gc_fin_locada.empty else 0
gc_loc_vm = float(df_gc_fin_locada['valor_mensal'].iloc[0]) if not df_gc_fin_locada.empty else 0

gc_sem_placa = len(df_gc_sem_placa) if not df_gc_sem_placa.empty else 0

gc_rank_fornecedores = len(df_gc_rank_terceiros) if not df_gc_rank_terceiros.empty else 0

gc_inat_contrato = len(df_gc_inativos_contrato) if not df_gc_inativos_contrato.empty else 0

gc_propria_com_contrato = int(df_gc_resumo['veic_proprios_com_contrato'].iloc[0]) if not df_gc_resumo.empty else 0

gc_locada_com_contrato = int(df_gc_resumo['veic_locados_com_contrato'].iloc[0]) if not df_gc_resumo.empty else 0

_frota_geral = df_gc_frota_geral.iloc[0] if not df_gc_frota_geral.empty else {}
gc_frota_total = int(_frota_geral.get('frota_total',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_ativa = int(_frota_geral.get('frota_ativa',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_operando = int(_frota_geral.get('em_operacao',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_ociosa = int(_frota_geral.get('ociosa_com_contrato',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_sem_contrato = int(_frota_geral.get('disponivel_sem_contrato',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_inat_contrato = int(_frota_geral.get('inativos_com_contrato',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_propria = int(_frota_geral.get('ativa_propria',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_terc = int(_frota_geral.get('ativa_terceirizada',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_parceiro = int(_frota_geral.get('ativa_parceiro',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_frota_locada = int(_frota_geral.get('ativa_locada',0) or 0) if hasattr(_frota_geral,'get') else 0
gc_propria_sem_contrato = int(_frota_geral.get('propria_sem_contrato',0) or 0) if hasattr(_frota_geral,'get') else 0

gc_risco_ocioso = float(df_gc_ociosa_contrato['valor_risco_acumulado'].sum()) if not df_gc_ociosa_contrato.empty else 0

gc_custo_medio = round(df_gc_custo_tipo['custo_por_escala'].mean(),2) if not df_gc_custo_tipo.empty else 0

gc_hist_meses = df_gc_historico['mes'].tolist() if not df_gc_historico.empty else []
gc_hist_ativos = [int(v or 0) for v in df_gc_historico['contratos_ativos'].tolist()] if not df_gc_historico.empty else []

gc_demanda_tipos = {'Própria':0,'Terceirizada':0,'Parceiro':0,'Locada':0}
if not df_gc_demanda_diaria.empty:
    gc_demanda_tipos['Própria'] = int(df_gc_demanda_diaria['veic_proprios'].sum())
    gc_demanda_tipos['Terceirizada'] = int(df_gc_demanda_diaria['veic_terceirizados'].sum())
    gc_demanda_tipos['Parceiro'] = int(df_gc_demanda_diaria['veic_parceiros'].sum())
    gc_demanda_tipos['Locada'] = int(df_gc_demanda_diaria['veic_locados'].sum())

gc_frota_tipos = {'Própria':gc_frota_propria,'Terceirizada':gc_frota_terc,'Parceiro':gc_frota_parceiro,'Locada':gc_frota_locada}
gc_gap_counts = df_gc_gap_gre['situacao'].value_counts().to_dict() if not df_gc_gap_gre.empty else {}

# ─── HTML FINAL ─────────────────────────────────────────────────────────────
gerado = datetime.now().strftime("%d/%m/%Y %H:%M")

html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Torre de Controle | Fiscalização de Rotas — Piauí</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#0b0f1a;--s1:#131929;--s2:#1a2236;--bd:#1e2d45;--tx:#e2e8f0;--mt:#64748b;
--ac:#38bdf8;--ok:#22c55e;--wn:#f59e0b;--cr:#ef4444;--or:#f97316;--pu:#a78bfa;}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--tx);font-size:13px}}
.hdr{{background:var(--s1);border-bottom:1px solid var(--bd);padding:12px 24px;
  display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}}
.hdr h1{{font-size:15px;font-weight:700;color:var(--ac)}}
.hdr .meta{{font-size:11px;color:var(--mt)}}
.nav{{display:flex;gap:2px;padding:10px 24px 0;background:var(--s1);border-bottom:2px solid var(--bd);overflow-x:auto}}
.nav button{{background:none;border:none;color:var(--mt);padding:10px 14px;cursor:pointer;
  font-size:12px;font-weight:600;border-bottom:2px solid transparent;margin-bottom:-2px;
  white-space:nowrap;transition:.15s}}
.nav button.active{{color:var(--ac);border-bottom-color:var(--ac)}}
.nav button:hover:not(.active){{color:var(--tx)}}
.tab{{display:none;padding:16px 24px}}
.tab.active{{display:block}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:16px}}
.kpi{{background:var(--s1);border:1px solid var(--bd);border-radius:8px;padding:14px}}
.kpi label{{font-size:10px;color:var(--mt);text-transform:uppercase;letter-spacing:.5px;font-weight:700;display:block}}
.kpi .v{{font-size:22px;font-weight:700;margin-top:4px}}
.kpi .sub{{font-size:10px;color:var(--mt);margin-top:2px}}
.v-ok{{color:var(--ok)}}.v-wn{{color:var(--wn)}}.v-cr{{color:var(--cr)}}.v-ac{{color:var(--ac)}}
.card{{background:var(--s1);border:1px solid var(--bd);border-radius:8px;padding:16px;margin-bottom:14px}}
.card h3{{font-size:12px;font-weight:700;color:var(--ac);margin-bottom:12px;
  padding-bottom:8px;border-bottom:1px solid var(--bd)}}
.card p.desc{{font-size:11px;color:var(--mt);margin-bottom:10px;line-height:1.6;
  padding:8px;background:var(--bg);border-radius:4px;border-left:3px solid var(--bd)}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.g3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}}
@media(max-width:900px){{.g2,.g3{{grid-template-columns:1fr}}}}
.tw{{overflow-x:auto;max-height:440px;overflow-y:auto}}
table{{width:100%;border-collapse:collapse;font-size:12px}}
th{{background:var(--bg);color:var(--ac);padding:9px 8px;border-bottom:2px solid var(--bd);
  position:sticky;top:0;text-align:left;font-size:11px;font-weight:700;white-space:nowrap}}
td{{padding:8px;border-bottom:1px solid var(--bd);vertical-align:middle}}
tr:hover{{background:var(--s2)}}
.src{{width:100%;padding:8px 10px;background:var(--bg);border:1px solid var(--bd);
  color:var(--tx);border-radius:6px;margin-bottom:10px;font-size:12px;outline:none}}
.src:focus{{border-color:var(--ac)}}
.tag{{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap}}
.badge-ok{{background:rgba(34,197,94,.12);color:var(--ok)}}
.badge-warn{{background:rgba(245,158,11,.12);color:var(--wn)}}
.badge-crit{{background:rgba(239,68,68,.12);color:var(--cr)}}
.badge-zero{{background:rgba(167,139,250,.12);color:var(--pu)}}
.badge-stab{{background:rgba(56,189,248,.1);color:var(--ac)}}
.badge-nd{{background:rgba(100,116,139,.1);color:var(--mt)}}
.alerta{{background:rgba(239,68,68,.07);border:1px solid rgba(239,68,68,.25);
  border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:12px;color:#fca5a5;line-height:1.6}}
.alerta b{{color:var(--cr)}}
.info{{background:rgba(56,189,248,.07);border:1px solid rgba(56,189,248,.2);
  border-radius:6px;padding:10px 14px;margin-bottom:14px;font-size:12px;color:#7dd3fc;line-height:1.6}}
canvas{{max-height:270px}}

.gc-payment-card summary{{list-style:none;cursor:pointer}}
.gc-payment-card summary::-webkit-details-marker{{display:none}}
.gc-month{{border:1px solid var(--bd);border-radius:8px;background:var(--bg);margin-bottom:10px;overflow:hidden}}
.gc-month>summary{{padding:12px 14px;display:flex;justify-content:space-between;align-items:center;gap:12px;background:var(--s1);border-bottom:1px solid var(--bd)}}
.gc-month[open]>summary{{border-bottom-color:var(--bd)}}
.gc-month-title{{font-size:13px;font-weight:700;color:var(--ac)}}
.gc-month-metrics{{display:flex;gap:14px;align-items:center;color:var(--mt);font-size:11px;flex-wrap:wrap;justify-content:flex-end}}
.gc-month-metrics strong{{color:var(--tx);font-size:13px}}
.gc-month-body{{padding:12px}}
.gc-month-cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:12px}}
.gc-mini{{background:var(--s1);border:1px solid var(--bd);border-radius:6px;padding:10px}}
.gc-mini label{{display:block;font-size:10px;color:var(--mt);text-transform:uppercase;font-weight:700}}
.gc-mini b{{display:block;font-size:17px;margin:4px 0;color:var(--tx)}}
.gc-mini span{{font-size:10px;color:var(--mt)}}
.gc-mini-total{{border-left:3px solid var(--ac)}}
.gc-day{{border-top:1px solid var(--bd)}}
.gc-day:first-child{{border-top:0}}
.gc-day>summary{{display:grid;grid-template-columns:120px 1fr 160px;gap:10px;padding:9px 10px;align-items:center;cursor:pointer;color:var(--tx);background:rgba(255,255,255,.01)}}
.gc-day>summary:hover{{background:var(--s2)}}
.gc-day-date{{font-weight:700}}
.gc-day-count{{color:var(--mt);font-size:11px}}
.gc-day-value{{text-align:right;color:#38bdf8}}
.gc-day-zero>summary{{color:#64748b}}
.gc-day-zero .gc-day-value{{color:#334155}}
.gc-day-detail{{padding:0 10px 10px}}
.gc-day-note{{font-size:10px;color:var(--mt);padding:8px;background:var(--s1);border-left:3px solid var(--wn);margin-bottom:8px}}
.gc-day-stats{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}}
.gc-day-stats span{{font-size:10px;color:var(--mt);background:var(--s1);border:1px solid var(--bd);padding:5px 7px;border-radius:5px}}
.gc-day-stats b{{color:var(--tx)}}
.gc-day-empty{{padding:8px 10px 12px;color:var(--mt);font-size:11px}}
@media(max-width:900px){{.gc-month-cards{{grid-template-columns:1fr}}.gc-month>summary{{align-items:flex-start;flex-direction:column}}.gc-month-metrics{{justify-content:flex-start}}.gc-day>summary{{grid-template-columns:1fr auto}}.gc-day-count{{grid-column:1}}.gc-day-value{{grid-column:2;grid-row:1 / span 2;align-self:center}}}}

.legenda-cores{{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px;font-size:10px}}
.lc{{padding:2px 8px;border-radius:3px;font-weight:700}}
.lc-cr{{background:rgba(239,68,68,.2);color:var(--cr)}}
.lc-or{{background:rgba(249,115,22,.2);color:var(--or)}}
.lc-wn{{background:rgba(245,158,11,.2);color:var(--wn)}}
.lc-ok{{background:rgba(34,197,94,.2);color:var(--ok)}}
.lc-nd{{background:rgba(100,116,139,.2);color:var(--mt)}}
.gc-rec{{background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);border-radius:6px;padding:12px 14px;margin-bottom:14px;font-size:12px;color:#86efac;line-height:1.7}}
.gc-rec b{{color:var(--ok)}}
.gc-rec .item{{margin-bottom:6px;padding-left:16px;position:relative}}
.gc-rec .item::before{{content:'▸';position:absolute;left:0;color:var(--ok)}}
.rank-table td{{padding:7px 8px}}
.gc-analysis{{border-color:rgba(56,189,248,.35)}}
.filter-box{{background:var(--s1);border:1px solid var(--bd);border-radius:8px;padding:12px;margin-bottom:14px}}
.filter-title{{font-size:11px;font-weight:700;color:var(--ac);margin-bottom:10px}}
.filter-grid{{display:grid;grid-template-columns:repeat(5,minmax(130px,1fr));gap:8px}}
.filter-item label{{display:block;font-size:9px;color:var(--mt);font-weight:700;margin-bottom:4px}}
.filter-item select{{width:100%;padding:8px 9px;border-radius:6px;border:1px solid var(--bd);background:var(--bg);color:var(--tx);font-size:11px;outline:none}}
.filter-item select:focus{{border-color:var(--ac)}}
.exec-coverage{{display:inline-flex;gap:6px;align-items:center;padding:8px 10px;border:1px solid var(--bd);background:var(--bg);border-radius:6px;font-size:11px}}
.exec-coverage b{{color:var(--ac);font-size:14px}}
@media(max-width:1100px){{.filter-grid{{grid-template-columns:repeat(3,minmax(130px,1fr))}}}}
@media(max-width:700px){{.filter-grid{{grid-template-columns:1fr 1fr}}}}

.gc-analysis .desc{{margin-top:8px}}
</style>
</head>
<body>
<div class="hdr">
  <h1>🛡️ Torre de Controle — Fiscalização de Rotas Escolares | Piauí</h1>
  <div class="meta">Atualizado em {gerado} &nbsp;·&nbsp; Fonte: Banco de dados operacional</div>
</div>
<div class="nav">
  <button class="active" onclick="tab('t1',this)">📊 Painel Executivo</button>
  <button onclick="tab('t2',this)">📍 Regionais (GRE)</button>
  <button onclick="tab('t3',this)">🏙️ Cidades</button>
  <button onclick="tab('t4',this)">⚠️ Rotas Suspeitas</button>
  <button onclick="tab('t5',this)">📋 Contratos</button>
  <button onclick="tab('t6',this)">🚌 Frota</button>
  <button onclick="tab('t7',this)">👤 Motoristas</button>
  <button onclick="tab('t8',this)">🧠 Prioridades</button>
  <button onclick="tab('t9',this)">🏆 Bonificação</button>
  <button onclick="tab('t10',this)">⛽ Combustível</button>
  <button onclick="tab('t11',this)">📑 Gerente Contratos</button>
</div>

<!-- ABA 1: PAINEL EXECUTIVO -->
<div id="t1" class="tab active">
  <div class="info">
    <b>📌 Painel Operacional de Rotas:</b>
    acompanha <b>rotas planejadas/analisadas × execução real</b>.
    <b>Concluída</b> = início + fim registrados.
    <b>Não Executada</b> = sem início.
    <b>Em andamento</b> = início sem fim.
    Registros anulados ficam fora da análise.
  </div>

  <div class="filter-box">
    <div class="filter-title">🔎 FILTROS OPERACIONAIS</div>
    <div class="filter-grid">
      <div class="filter-item"><label>PERÍODO</label><select id="fx_periodo">
        <option value="current" selected>MÊS ATUAL</option>
        <option value="year">ANO 2026</option>
        <option value="last30">ÚLTIMOS 30 DIAS</option>
      </select></div>
      <div class="filter-item"><label>TIPO</label><select id="fx_tipo">
        <option value="" selected>TODOS</option>
        <option value="RR">REGULARES</option>
        <option value="EX">EXTRAS</option>
        <option value="OUTROS">OUTROS</option>
      </select></div>
      <div class="filter-item"><label>TURNO</label><select id="fx_turno">{exec_html_options(_exec_vals['turno'])}</select></div>
      <div class="filter-item"><label>DIREÇÃO</label><select id="fx_direcao">{exec_html_options(_exec_vals['direcao'])}</select></div>
      <div class="filter-item"><label>GRE</label><select id="fx_gre">{exec_html_options(_exec_vals['gre'])}</select></div>
      <div class="filter-item"><label>CIDADE</label><select id="fx_cidade">{exec_html_options(_exec_vals['cidade'])}</select></div>
      <div class="filter-item"><label>FISCAL</label><select id="fx_fiscal">{exec_html_options(_exec_vals['fiscal'])}</select></div>
      <div class="filter-item"><label>REGIÃO</label><select id="fx_regiao">
        <option value="" selected>TODAS</option><option value="CAPITAL">CAPITAL</option><option value="INTERIOR">INTERIOR</option>
      </select></div>
      <div class="filter-item"><label>FORNECEDOR</label><select id="fx_fornecedor">{exec_html_options(_exec_vals['fornecedor'])}</select></div>
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi"><label>Total Analisado</label><div class="v v-ac" id="x_total">{exec_total:,}</div><div class="sub">rotas não anuladas</div></div>
    <div class="kpi"><label>Concluído</label><div class="v v-ok" id="x_conc">{exec_conc:,}</div><div class="sub">início + fim</div></div>
    <div class="kpi"><label>Não Executado</label><div class="v v-cr" id="x_nao">{exec_nao:,}</div><div class="sub">sem início</div></div>
    <div class="kpi"><label>Assiduidade</label><div class="v v-ok" id="x_assid">{exec_pct_assid}%</div><div class="sub">concluído / analisado</div></div>
    <div class="kpi"><label>Volume Extras</label><div class="v v-wn" id="x_extra">{exec_extras:,}</div><div class="sub">tipo EX</div></div>
    <div class="kpi"><label>KM Executado</label><div class="v v-ac" id="x_km">{fmt(exec_km)} km</div><div class="sub">execução iniciada</div></div>
    <div class="kpi"><label>Em Andamento</label><div class="v v-wn" id="x_and">{exec_and:,}</div><div class="sub">início sem fim</div></div>
  </div>

  <div class="card gc-analysis">
    <h3>👤 Performance Campo</h3>
    <p class="desc" id="exec_analysis" style="border-left-color:var(--ac)">{comentario_executivo()}</p>
    <div class="exec-coverage">📊 <span>Cobertura geral:</span> <b id="x_cov">{exec_pct_assid}%</b></div>
  </div>

  <div class="g2">
    <div class="card"><h3>📈 Histórico de Rotas — Planejadas x Concluídas x Não Executadas</h3><p class="desc">Histórico mensal de 2026. A análise não usa a tabela de contratos.</p><canvas id="c_exec_hist"></canvas></div>
    <div class="card"><h3>📊 Assiduidade Mensal</h3><p class="desc">Concluídas ÷ total analisado.</p><canvas id="c_exec_assid"></canvas></div>
  </div>

  <div class="card"><h3>📏 KM Executado por Mês</h3><canvas id="c_exec_km"></canvas></div>

  <div class="g2">
    <div class="card"><h3>🏆 Ranking de Responsáveis — Performance Campo</h3><p class="desc">Top por assiduidade, respeitando os filtros selecionados.</p>
      <div class="tw"><table id="t_exec_fiscal"><thead><tr><th>Pos</th><th>Responsável</th><th>GRE</th><th>Total</th><th>Concl.</th><th>Assid.</th></tr></thead><tbody></tbody></table></div>
    </div>
    <div class="card"><h3>📈 Visão Detalhada de Assiduidade: Top 5</h3><canvas id="c_exec_topfiscal"></canvas></div>
  </div>

  <div class="card"><h3>👥 Motoristas — Vínculo com Veículo</h3>
    <div class="g3" style="margin-bottom:12px">
      <div class="kpi"><label>Mot.</label><div class="v v-ac" id="x_mot">0</div></div>
      <div class="kpi"><label>Vei.</label><div class="v v-ok" id="x_mot_vei">0</div></div>
      <div class="kpi"><label>Sem Vei.</label><div class="v v-wn" id="x_mot_sem">0</div></div>
    </div>
    <div class="tw"><table id="t_exec_vinculo"><thead><tr><th>Regional (GRE)</th><th>Mot.</th><th>Com V.</th><th>Sem V.</th></tr></thead><tbody></tbody></table></div>
    <div class="info" style="margin-top:10px" id="x_multi_gre">✅ Nenhum motorista em mais de uma GRE.</div>
  </div>

  <div class="g2">
    <div class="card"><h3>🏆 Rotas por Regional (GRE)</h3><div class="tw"><table id="t_exec_gre"><thead><tr><th>Pos</th><th>Regional</th><th>Total</th><th>Ok</th><th>Assid.</th></tr></thead><tbody></tbody></table></div></div>
    <div class="card"><h3>🏙️ Rotas por Município</h3><div class="tw"><table id="t_exec_city"><thead><tr><th>Pos</th><th>Cidade</th><th>Total</th><th>Ok</th><th>Assid.</th></tr></thead><tbody></tbody></table></div></div>
  </div>

  <div class="g2">
    <div class="card"><h3>📏 KM Executado por GRE</h3><div class="tw"><table id="t_exec_km_gre"><thead><tr><th>Pos</th><th>GRE</th><th>KM Exec.</th></tr></thead><tbody></tbody></table></div></div>
    <div class="card"><h3>📏 KM Executado por Município</h3><div class="tw"><table id="t_exec_km_city"><thead><tr><th>Pos</th><th>Município</th><th>KM Exec.</th></tr></thead><tbody></tbody></table></div></div>
  </div>

  <div class="card"><h3>🏆 Rotas Concluídas por Município</h3><div class="tw"><table id="t_exec_city_conc"><thead><tr><th>Pos</th><th>Município</th><th>Concluídas</th></tr></thead><tbody></tbody></table></div></div>

  <div class="card"><h3>⚠️ Municípios Ofensores — Não Executadas</h3><p class="desc">Ordenado pelo volume de não executadas.</p><div class="tw"><table id="t_exec_off"><thead><tr><th>Pos</th><th>Cidade</th><th>Total</th><th>Não Ex.</th><th>Assid.</th></tr></thead><tbody></tbody></table></div></div>

  <div class="card"><h3>🏅 Ranking Municípios — Assiduidade</h3><div class="tw"><table id="t_exec_city_assid"><thead><tr><th>Pos</th><th>Cidade</th><th>Total</th><th>Ok</th><th>Assid.</th></tr></thead><tbody></tbody></table></div></div>

  <div class="g2">
    <div class="card"><h3>🚛 Tipologia de Frota</h3><div class="tw"><table id="t_exec_frota"><thead><tr><th>Categoria / Regional</th><th>Rotas</th><th>Vei.</th></tr></thead><tbody></tbody></table></div></div>
    <div class="card"><h3>🤝 Fornecedores</h3><div class="tw"><table id="t_exec_fornecedor"><thead><tr><th>Fornecedor</th><th>Rotas</th><th>Ok</th><th>Assid.</th></tr></thead><tbody></tbody></table></div></div>
  </div>

  <div class="card"><h3>📝 Ocorrências por Fiscal</h3><p class="desc">Registros com observação preenchida.</p><div class="tw"><table id="t_exec_ocorr"><thead><tr><th>Fiscal</th><th>GRE</th><th>Ocorrências</th></tr></thead><tbody></tbody></table></div></div>

  <div class="card"><h3>📱 Análise de Tecnologia (Origem Localização)</h3><p class="desc">Motoristas únicos. Via App usa <b>via_app=true</b>; Via Link/Outro usa <b>via_app=false</b>. Taxa de abertura = motoristas com início / motoristas analisados.</p>
    <div class="tw"><table id="t_exec_tec"><thead><tr><th>Fiscal</th><th>GRE</th><th>Cidade</th><th>Motorista</th><th>Total Mots.</th><th>Mots. OK</th><th>Via App</th><th>Via Link/Outro</th><th>% App</th><th>% Abertura</th></tr></thead><tbody></tbody></table></div>
  </div>
</div>

<!-- ABA 2: REGIONAIS (GRE) -->
<div id="t2" class="tab">
  <div class="info">
    <b>📌 Como ler:</b> Cada linha é uma Regional de Ensino (GRE). As colunas mostram o % de escalas com rastreamento ativo mês a mês. <b>Verde</b> = acima de 50%. <b>Laranja</b> = entre 15-50%. <b>Vermelho</b> = abaixo de 15%. A tendência compara o último mês com o anterior.
  </div>
  <div class="legenda-cores">
    <span class="lc lc-cr">0-14%: Crítico</span>
    <span class="lc lc-or">15-29%: Baixo</span>
    <span class="lc lc-wn">30-49%: Moderado</span>
    <span class="lc lc-ok">50%+: Adequado</span>
  </div>
  <div class="card">
    <h3>📊 Evolução do Rastreamento por Regional — Abr a Ago/2026</h3>
    <p class="desc" style="border-left-color:var(--ac)">{comentario_gre()}</p>
    <div class="tw">
      <table>
        <thead><tr>
          <th>Regional (GRE)</th><th style="text-align:center">Total Esc.</th>
          <th style="text-align:center">Abr/26</th><th style="text-align:center">Mai/26</th>
          <th style="text-align:center">Jun/26</th><th style="text-align:center">Jul/26</th>
          <th style="text-align:center">Ago/26</th>
          <th style="text-align:center">Sem Rast.</th>
          <th style="text-align:center">Suspeitas</th>
          <th>Tendência</th>
        </tr></thead>
        <tbody>{html_gre_pivo()}</tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <h3>📉 % Rastreamento por GRE — Evolução Mensal (Abr-Ago/2026)</h3>
    <canvas id="c_gre"></canvas>
  </div>
</div>

<!-- ABA 3: CIDADES -->
<div id="t3" class="tab">
  <div class="info">
    <b>📌 Como ler:</b> Cada linha é um município. As colunas mostram o % de escalas com rastreamento por mês. A coluna <b>Situação</b> classifica automaticamente com base na evolução. <b>Rotas Suspeitas</b> = total de rotas com duração menor que 10 minutos no período. Cidades ordenadas pela prioridade de atenção (pior primeiro).
  </div>
  <div class="legenda-cores">
    <span class="lc lc-cr">0%: Sem registro</span>
    <span class="lc lc-or">1-14%: Crítico</span>
    <span class="lc lc-wn">15-29%: Baixo</span>
    <span class="lc lc-ok">50%+: Adequado</span>
  </div>
  <div class="card">
    <h3>🏙️ Rastreamento por Cidade — Histórico Mensal Abr a Ago/2026</h3>
    <p class="desc" style="border-left-color:var(--cr)">{comentario_cidades()}</p>
    <input class="src" id="s_cid" oninput="fil('s_cid','t_cid')" placeholder="Filtrar por cidade...">
    <div class="tw">
      <table id="t_cid">
        <thead><tr>
          <th>Cidade</th><th style="text-align:center">Total</th>
          <th style="text-align:center">Abr/26</th><th style="text-align:center">Mai/26</th>
          <th style="text-align:center">Jun/26</th><th style="text-align:center">Jul/26</th>
          <th style="text-align:center">Ago/26</th>
          <th style="text-align:center">Suspeitas</th>
          <th>Situação</th><th style="text-align:right">Score</th>
        </tr></thead>
        <tbody>{html_pivo()}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ABA 4: ROTAS SUSPEITAS -->
<div id="t4" class="tab">
  <div class="alerta">
    <b>⚠️ O que é uma Rota Suspeita?</b> Qualquer escala com início e fim de execução registrados, mas com duração menor que 10 minutos. Uma rota escolar real leva no mínimo 20-30 minutos. Rotas concluídas em menos de 10 minutos indicam abertura e fechamento irregular para registrar execução sem realizar a rota. <b>100% dos casos identificados são de prestadores terceirizados.</b>
  </div>
  <div class="card"><h3>📉 Evolução Mensal — Rotas Suspeitas e Sem Rastreamento</h3><p class="desc" style="border-left-color:var(--cr)">{comentario_fraude()}</p><canvas id="c_fr"></canvas></div>
  <div class="g2">
    <div class="card">
      <h3>🏢 Empresas com Maior % de Rotas Suspeitas</h3>
      <p class="desc">Empresas ordenadas pelo percentual de rotas suspeitas sobre o total de escalas. Percentual acima de 20% é considerado crítico e requer ação contratual imediata.</p>
      <div class="tw">
        <table>
          <thead><tr><th>Empresa</th><th>Mot.</th><th>Total Esc.</th><th>Suspeitas</th><th>%</th><th>Sem Rast.</th></tr></thead>
          <tbody>{html_fraude_emp()}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>👤 Motoristas com Maior % de Rotas Suspeitas</h3>
      <p class="desc">Motoristas com pelo menos 10 escalas no período. Percentual acima de 20% em vermelho.</p>
      <input class="src" id="s_fm" oninput="fil('s_fm','t_fm')" placeholder="Buscar motorista...">
      <div class="tw">
        <table id="t_fm">
          <thead><tr><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>GRE</th><th>Suspeitas</th><th>%</th><th>Sem Rast.</th></tr></thead>
          <tbody>{html_fraude_mot()}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 5: CONTRATOS -->
<div id="t5" class="tab">
  <div class="alerta">
    <b>⚠️ Contratos sem Operação:</b> Veículos com contrato ativo mas sem motorista associado e zero escalas nos últimos 30 dias. O valor informado é o valor diário do contrato — cada dia sem execução representa esse valor em risco de pagamento sem prestação de serviço.
  </div>
  <div class="g2">
    <div class="card"><h3>📈 Total de Escalas com Contrato — Abr a Ago/2026</h3><canvas id="c_ct2"></canvas></div>
    <div class="card"><h3>📊 Escalas com Contrato: Total vs Sem Rastreamento vs Anuladas</h3><canvas id="c_ct3"></canvas></div>
  </div>
  <div class="card">
    <h3>🌙 Contratos com Turno Noite — Risco de Pagamento em Sábado sem Aula</h3>
    <p class="desc">
      <b>Sábado à noite é excepcionalmente raro ter aulas.</b> Contratos com turno Noite ativo em sábados representam risco de pagamento indevido — especialmente quando o mesmo contrato cobre Noite + outro turno, pois o prestador recebe a diária completa ao executar qualquer turno. A coluna <b>Turnos do Contrato</b> mostra todas as combinações do item. <b>Valor Pago Est.</b> = sábados executados × valor diário do contrato. Solução: rever contratos com turno Noite para excluir sábados ou exigir comprovação de aula.
    </p>
    <div class="tw">
      <table>
        <thead><tr>
          <th>GRE</th><th>Placa</th><th>Fornecedor</th>
          <th style="text-align:right">Valor/Dia</th>
          <th>Turnos do Contrato</th>
          <th style="text-align:center">Sáb. Noite 2026</th>
          <th style="text-align:center">Executados</th>
          <th style="text-align:center">Manuais s/GPS</th>
          <th style="text-align:right">Valor Pago Est.</th>
        </tr></thead>
        <tbody>{html_contratos_noite()}</tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <h3>🚨 Veículos em Contrato Ativo sem Motorista (Zero Escalas em 30 dias)</h3>
    <p class="desc" style="border-left-color:var(--cr)">{comentario_contratos()}</p>
    <input class="src" id="s_ct" oninput="fil('s_ct','t_ct')" placeholder="Filtrar por GRE, placa...">
    <div class="tw">
      <table id="t_ct">
        <thead><tr><th>Regional</th><th>Placa</th><th style="text-align:center">Nº Contrato</th><th style="text-align:center">Item</th><th>Valor/Dia</th><th>Turno</th><th>Situação do Veículo</th><th style="text-align:center">Esc. 30d</th></tr></thead>
        <tbody>{html_contratos()}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ABA 6: FROTA -->
<div id="t6" class="tab">
  <div class="alerta">
    <b>🚨 Frota sem operação com contrato ativo:</b>
    338 veículos nunca registraram rota = <b>R$ 184.493/dia em risco</b>.
    359 veículos parados há +90 dias com contrato ativo = <b>R$ 199.506/dia em risco</b>.
    Total: <b>R$ 383.999/dia</b> — aproximadamente <b>R$ 8,4 milhões/mês</b> em contratos sem execução correspondente.
  </div>
  <div class="g3">
    <div class="kpi"><label>Nunca Registraram Rota</label><div class="v v-cr">511 veíc.</div><div class="sub">77% frota terceirizada</div></div>
    <div class="kpi"><label>Parados há +90 dias</label><div class="v v-cr">268 veíc.</div><div class="sub">64% frota própria</div></div>
    <div class="kpi"><label>Valor Diário em Risco</label><div class="v v-cr">R$ 383.999</div><div class="sub">~R$ 8,4M/mês</div></div>
  </div>
  <div class="g2">
    <div class="card">
      <h3>🅿️ Situação da Frota Ativa por Tempo sem Operação</h3>
      <p class="desc">Classificação de todos os veículos com status ativo pelo tempo desde a última rota registrada.</p>
      <div class="tw">
        <table>
          <thead><tr><th>Situação</th><th style="text-align:center">Total</th><th style="text-align:center">Própria</th><th style="text-align:center">Terceirizada</th><th style="text-align:center">Parceiro</th></tr></thead>
          <tbody>{html_frota_parada()}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>💸 Veículos c/ Contrato Ativo que Nunca Registraram Rota</h3>
      <p class="desc">Veículos em contrato ativo sem nenhuma escala no histórico. Valor diário sendo pago sem prestação de serviço.</p>
      <input class="src" id="s_fn" oninput="fil('s_fn','t_fn')" placeholder="Filtrar placa, fornecedor...">
      <div class="tw">
        <table id="t_fn">
          <thead><tr><th>Placa</th><th>Modelo</th><th>Fornecedor</th><th>GRE</th><th>Valor/Dia</th><th>Contrato Início</th></tr></thead>
          <tbody>{html_frota_nunca()}</tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="info">
    <b>📌 Licenciamento Vencido</b> = veículo com ano de licenciamento anterior a 2026. Veículo com licenciamento vencido não deveria estar em operação de transporte escolar. <b>Com Multas</b> = registro de multa ativa no cadastro do veículo.
  </div>
  <div class="card">
    <h3>📄 Situação Documental da Frota por Fornecedor</h3>
    <input class="src" id="s_fr" oninput="fil('s_fr','t_fr')" placeholder="Filtrar fornecedor...">
    <div class="tw">
      <table id="t_fr">
        <thead><tr><th>Fornecedor</th><th style="text-align:center">Total</th><th style="text-align:center">Ativos</th><th style="text-align:center">Inativos</th><th>Lic. Vencido</th><th style="text-align:center">Lic. OK</th><th style="text-align:center">C/ Multas</th></tr></thead>
        <tbody>{html_frota()}</tbody>
      </table>
    </div>
  </div>
  <div class="g2">
    <div class="card">
      <h3>🔧 Manutenção por Fornecedor (2026)</h3>
      <p class="desc"><b>Chamados Abertos</b> = aguardando solução. <b>Em Oficina</b> = veículo parado para conserto. <b>Média de Dias</b> = tempo médio entre abertura do chamado e entrega do veículo.</p>
      <div class="tw">
        <table>
          <thead><tr><th>Fornecedor</th><th>Chamados</th><th>Abertos</th><th>Oficina</th><th>Veíc.</th><th>Média Dias</th></tr></thead>
          <tbody>{''.join([f"<tr><td><b>{r['fornecedor']}</b></td><td>{int(r.get('chamados',0))}</td><td style='{'color:#ef4444;font-weight:700' if int(r.get('abertos',0))>5 else ''}'>{int(r.get('abertos',0))}</td><td>{int(r.get('oficina',0))}</td><td>{int(r.get('veiculos',0))}</td><td>{r.get('media_dias',0)} dias</td></tr>" for _,r in df_manut_forn.iterrows()]) if not df_manut_forn.empty else "<tr><td colspan='6'>Sem dados</td></tr>"}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>🚗 Veículos com Mais Chamados de Manutenção (2026)</h3>
      <p class="desc"><b>Falha Humana</b> = manutenção causada por conduta do motorista (diagnosticada pela oficina).</p>
      <div class="tw">
        <table>
          <thead><tr><th>Placa</th><th>Modelo</th><th style="text-align:center">Ano</th><th>Fornecedor</th><th>GRE</th><th style="text-align:center">Chamados</th><th style="text-align:center">Abertos</th><th style="text-align:center">Falha Hum.</th><th style="text-align:center">Média Dias</th><th style="text-align:right">Custo Total 2026</th></tr></thead>
          <tbody>{''.join([f"<tr><td><b>{r['placa']}</b></td><td>{r.get('modelo','')}</td><td style='text-align:center'>{int(r.get('ano',0)) if r.get('ano') else '—'}</td><td>{r['fornecedor']}</td><td>{r.get('gre','')}</td><td style='text-align:center'>{int(r.get('chamados',0))}</td><td style='text-align:center;{'color:#ef4444' if int(r.get('abertos',0))>3 else ''}'>{int(r.get('abertos',0))}</td><td style='text-align:center;{'color:#ef4444' if int(r.get('falha_hum',0))>0 else ''}'>{int(r.get('falha_hum',0))}</td><td style='text-align:center'>{r.get('media_dias',0)}d</td><td style='text-align:right;color:#ef4444;font-weight:700'>R$ {fmt(r.get('custo_total',0))}</td></tr>" for _,r in df_veic_prob.iterrows()]) if not df_veic_prob.empty else "<tr><td colspan='10'>Sem dados</td></tr>"}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 7: MOTORISTAS -->
<div id="t7" class="tab">
  <div class="card">
    <h3>👤 Motoristas — % Com Rastreamento (piores primeiro, desde Abr/2026)</h3>
    <p class="desc">Motoristas com pelo menos 20 escalas no período. <b>% Com Rastreamento</b> = proporção de escalas registradas via app ou link. Abaixo de 20% em vermelho, 20-50% em laranja, acima de 50% em verde. <b>Rotas Suspeitas</b> = duração menor que 10 minutos. <b>Sem Rastreamento</b> = confirmação manual.</p>
    <input class="src" id="s_mt" oninput="fil('s_mt','t_mt')" placeholder="Buscar motorista, cidade, empresa, GRE...">
    <div class="tw">
      <table id="t_mt">
        <thead><tr><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>GRE</th><th>Escalas</th><th>% Rastreado</th><th>Rotas Suspeitas</th><th>Sem Rastreamento</th></tr></thead>
        <tbody>{html_mot()}</tbody>
      </table>
    </div>
  </div>
  <div class="g2">
    <div class="card">
      <h3>🔧 Motoristas que Mais Geram Chamados de Manutenção</h3>
      <div class="tw">
        <table>
          <thead><tr><th>Motorista</th><th>Empresa</th><th>GRE</th><th>Chamados</th><th>Falha Humana</th><th>Em Aberto</th></tr></thead>
          <tbody>{''.join([f"<tr><td><b>{r['nome']}</b></td><td>{r['empresa']}</td><td>{r.get('gre','')}</td><td>{int(r.get('chamados',0))}</td><td style='{'color:#ef4444;font-weight:700' if int(r.get('falha_hum',0))>0 else ''}'>{int(r.get('falha_hum',0))}</td><td>{int(r.get('abertos',0))}</td></tr>" for _,r in df_mot_chamados.iterrows()]) if not df_mot_chamados.empty else "<tr><td colspan='6'>Sem dados</td></tr>"}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>⛽ Consumo de Combustível por Motorista (2026)</h3>
      <p class="desc"><b>R$/Escala</b> = custo médio de combustível por escala executada. Útil para identificar consumo desproporcional.</p>
      <div class="tw">
        <table>
          <thead><tr><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>Litros</th><th>Gasto R$</th><th>Escalas</th><th>R$/Escala</th></tr></thead>
          <tbody>{html_abast()}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 8: PRIORIDADES -->
<div id="t8" class="tab">
  <div class="info">
    <b>🧠 Como funciona o Score de Prioridade:</b> Calculado automaticamente combinando quatro fatores: <b>índice atual de rastreamento</b> (peso 50%) + <b>queda em relação ao mês anterior</b> (peso 30%) + <b>% de rotas suspeitas</b> (peso 20%). Quanto maior o score, maior a urgência de intervenção. A <b>Ação Recomendada</b> é gerada automaticamente com base na situação classificada.
  </div>
  <div class="card">
    <h3>🎯 Ranking de Prioridade de Intervenção — Por Cidade (Abr-Ago/2026)</h3>
    <div class="tw">
      <table>
        <thead><tr>
          <th style="text-align:center">#</th><th>Cidade</th><th style="text-align:center">Total Esc.</th>
          <th style="text-align:center">Abr/26</th><th style="text-align:center">Mai/26</th>
          <th style="text-align:center">Jun/26</th><th style="text-align:center">Jul/26</th>
          <th style="text-align:center">Ago/26</th>
          <th>Situação</th><th>Ação Recomendada</th>
        </tr></thead>
        <tbody>{html_insights()}</tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <h3>👮 Desempenho por Fiscal Responsável — Abr-Ago/2026</h3>
    <p class="desc"><b>Abr-Jun/26</b> = % de rastreamento no segundo trimestre. <b>Jul-Ago/26</b> = % atual. A tendência mostra se a área do fiscal está melhorando ou piorando. <b>Rotas Suspeitas</b> e <b>Sem Rastreamento</b> são totais acumulados desde abril.</p>
    <div class="tw">
      <table>
        <thead><tr><th>Regional (GRE)</th><th>Fiscal Responsável</th><th style="text-align:center">Total Esc.</th><th style="text-align:center">Abr-Jun/26</th><th style="text-align:center">Jul-Ago/26</th><th style="text-align:center">Rotas Suspeitas</th><th style="text-align:center">Sem Rastreamento</th></tr></thead>
        <tbody>{html_fiscal()}</tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <h3>📊 Diagnóstico Geral: Prestadores vs Frota Própria</h3>
    <p class="desc" style="border-left-color:var(--cr)">
      <b style="color:var(--cr)">100% das irregularidades identificadas são de prestadores terceirizados.</b> Motoristas da frota própria (sem vínculo com fornecedor) apresentam irregularidade próxima de zero. Isso indica que o problema não é operacional — é estrutural no modelo de terceirização.<br><br>
      <b style="color:var(--wn)">Empresas com maior risco imediato:</b> J COUTINHO DE SOUSA FILHO (97% de rotas suspeitas) · ANTONIO CARLOS REIS SARAIVA (74%) · INES DE SALES RESENDE (59%).<br><br>
      <b style="color:var(--ac)">Recomendação estratégica:</b> Incluir cláusula contratual vinculando pagamento ao índice mínimo de rastreamento (sugerido: 60%). Prestadores abaixo desse índice por dois meses consecutivos devem receber notificação formal com prazo de 30 dias para adequação, seguida de processo de glosa caso não haja melhora.
    </p>
  </div>
</div>

<!-- ABA 9: BONIFICAÇÃO -->
<div id="t9" class="tab">
  <div class="info">
    <b>📌 Como funciona o Score de Bonificação:</b> Calculado por motorista desde Abr/2026 combinando dois fatores: <b>% de rastreamento</b> (peso positivo) e <b>% de rotas suspeitas</b> (peso negativo, conta dobrado). Fórmula: Score = % Rastreado − (% Suspeitas × 2). Score 70+ = excelente · 50-69 = bom · abaixo de 50 = atenção. Mínimo de 30 escalas no período para entrar no ranking. <b>Combustível:</b> dado em revisão — valores inconsistentes identificados no banco de origem.
  </div>
  <div class="g3">
    <div class="kpi"><label>🏆 Top Cidade</label><div class="v v-ok" style="font-size:16px">{cidade_top}</div><div class="sub">maior score médio de bonificação</div></div>
    <div class="kpi"><label>🏆 Top GRE</label><div class="v v-ok" style="font-size:16px">{gre_top}</div><div class="sub">maior score médio de bonificação</div></div>
    <div class="kpi"><label>Motoristas no Ranking</label><div class="v">{n_mot_bonif}</div><div class="sub">com mín. 30 escalas em Abr-Ago/26</div></div>
  </div>
  <div class="card">
    <h3>🏆 Ranking de Motoristas — Melhores Índices Operacionais (Abr-Ago/2026)</h3>
    <p class="desc">Motoristas com maior score de bonificação. São referências de boa prática operacional que podem servir de modelo para treinamentos e incentivos.</p>
    <input class="src" id="s_bon" oninput="fil('s_bon','t_bon')" placeholder="Buscar motorista, cidade, GRE...">
    <div class="tw">
      <table id="t_bon">
        <thead><tr>
          <th style="text-align:center">#</th><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>GRE</th>
          <th style="text-align:center">Escalas</th><th style="text-align:center">% Rastreado</th>
          <th style="text-align:center">Suspeitas</th><th style="text-align:center">% Suspeitas</th><th style="text-align:center">Score</th>
        </tr></thead>
        <tbody>{html_bonif_mot()}</tbody>
      </table>
    </div>
  </div>
  <div class="g2">
    <div class="card">
      <h3>🏆 Ranking por GRE — Score Médio de Bonificação</h3>
      <p class="desc">Regionais ordenadas pelo score médio de bonificação de seus motoristas. A coluna <b>Fiscal</b> é responsável pela área.</p>
      <div class="tw">
        <table>
          <thead><tr>
            <th style="text-align:center">#</th><th>GRE</th><th>Fiscal</th>
            <th style="text-align:center">Motoristas</th><th style="text-align:center">% Rastreado</th>
            <th style="text-align:center">% Suspeitas</th><th style="text-align:center">Score</th>
          </tr></thead>
          <tbody>{html_bonif_gre()}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>🏆 Ranking por Cidade — Score Médio de Bonificação</h3>
      <p class="desc">Cidades ordenadas pelo score médio de bonificação. Cidades no topo são referência de boa adesão ao rastreamento.</p>
      <input class="src" id="s_bcid" oninput="fil('s_bcid','t_bcid')" placeholder="Filtrar cidade...">
      <div class="tw">
        <table id="t_bcid">
          <thead><tr>
            <th style="text-align:center">#</th><th>Cidade</th>
            <th style="text-align:center">Motoristas</th><th style="text-align:center">Escalas</th>
            <th style="text-align:center">% Rastreado</th><th style="text-align:center">% Suspeitas</th><th style="text-align:center">Score</th>
          </tr></thead>
          <tbody>{html_bonif_cidade()}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 10: COMBUSTÍVEL -->
<div id="t10" class="tab">
  <div class="info">
    <b>📌 Como ler:</b> Gasto de combustível cruzado com escalas executadas no mesmo mês. <b>R$/Escala</b> = eficiência real do combustível por rota executada. Valores altos de R$/Escala em meses com poucas escalas indicam abastecimento sem operação proporcional. <b>Dados validados:</b> filtro de 0-500 litros e R$ 0-5.000 por abastecimento.
  </div>
  <div class="card">
    <h3>📊 Análise Automática</h3>
    <p class="desc" style="border-left-color:var(--ac)">{comentario_combustivel()}</p>
  </div>
  <div class="card">
    <h3>⛽ Gasto de Combustível por Regional — Mensal (2026)</h3>
    <p class="desc">Valores em vermelho = acima de R$ 20 milhões/mês · Laranja = R$ 10-20 milhões · Verde = abaixo de R$ 10 milhões.</p>
    <div class="tw">
      <table>
        <thead><tr>
          <th>Regional (GRE)</th><th>Fiscal</th>
          <th style="text-align:right">Fev/26</th><th style="text-align:right">Mar/26</th><th style="text-align:right">Abr/26</th>
          <th style="text-align:right">Mai/26</th><th style="text-align:right">Jun/26</th><th style="text-align:right">Jul/26</th><th style="text-align:right">Ago/26</th>
          <th style="text-align:right;color:#38bdf8">Total</th>
        </tr></thead>
        <tbody>{html_comb_gre_pivo()}</tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <h3>📊 Total Geral de Combustível — Mensal (2026)</h3>
    <p class="desc">Total consolidado de todos os abastecimentos do período, incluindo todas as GREs. Referência para confronto com o sistema operacional. <b>Convênio ProFrotas</b> = abastecimentos registrados via sistema ProFrotas (id_profrotas preenchido).</p>
    <div class="tw">
      <table>
        <thead><tr>
          <th>Mês</th><th style="text-align:center">Lançamentos</th><th style="text-align:right">Litros</th><th style="text-align:right">Valor Total</th><th style="text-align:center">Convênio ProFrotas</th>
        </tr></thead>
        <tbody>{html_comb_total()}</tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <h3>🏢 Gasto de Combustível por Empresa — Mensal (2026)</h3>
    <p class="desc">Top 20 empresas por gasto acumulado. Vermelho = acima de R$ 5 milhões/mês · Laranja = R$ 1-5 milhões · Verde = abaixo de R$ 1 milhão. Coluna <b>Total</b> = acumulado Fev-Ago/2026.</p>
    <div class="tw">
      <table>
        <thead><tr>
          <th>Empresa</th><th style="text-align:center">Mot.</th>
          <th style="text-align:right">Fev/26</th><th style="text-align:right">Mar/26</th><th style="text-align:right">Abr/26</th>
          <th style="text-align:right">Mai/26</th><th style="text-align:right">Jun/26</th><th style="text-align:right">Jul/26</th><th style="text-align:right">Ago/26</th>
          <th style="text-align:right;color:#38bdf8">Total</th>
        </tr></thead>
        <tbody>{html_comb_emp_pivo()}</tbody>
      </table>
    </div>
  </div>
  <div class="card">
    <h3>👤 Gasto de Combustível por Motorista — Mensal (2026)</h3>
    <p class="desc">Top 30 motoristas por gasto acumulado (excluindo motoristas sem escalas). Vermelho = acima de R$ 1,5 milhão/mês · <b>R$/Escala</b> em vermelho = acima de R$ 8.000 (alto custo por rota). Quanto menor o R$/Escala, mais eficiente o motorista.</p>
    <input class="src" id="s_cm" oninput="fil('s_cm','t_cm')" placeholder="Buscar motorista, empresa, cidade...">
    <div class="tw">
      <table id="t_cm">
        <thead><tr>
          <th style="text-align:center">#</th><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>GRE</th>
          <th style="text-align:right">Fev/26</th><th style="text-align:right">Mar/26</th><th style="text-align:right">Abr/26</th>
          <th style="text-align:right">Mai/26</th><th style="text-align:right">Jun/26</th><th style="text-align:right">Jul/26</th><th style="text-align:right">Ago/26</th>
          <th style="text-align:right;color:#38bdf8">Total</th><th style="text-align:right">R$/Escala</th>
        </tr></thead>
        <tbody>{html_comb_mot_pivo()}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ABA 11: GERENTE DE CONTRATOS -->
<div id="t11" class="tab">
  <div class="info">
    <b>📌 Painel do Gerente de Contratos:</b> visão consolidada de <b>contratos mestres</b>, <b>contratos rota</b>, frota, pagamento e inconsistências. <b>Contratos a vencer foram retirados deste painel.</b>
  </div>

  <div class="kpi-grid">
    <div class="kpi"><label>Contratos Mestres Ativos</label><div class="v v-ac">{gc_total:,}</div><div class="sub">carteira ativa</div></div>
    <div class="kpi"><label>Contratos Rota Ativos</label><div class="v v-ac">{gc_itens_ativos:,}</div><div class="sub">unidades contratuais</div></div>
    <div class="kpi"><label>Contratos Rota c/ Execução</label><div class="v v-ok">{gc_exec_contratos_mes:,}</div><div class="sub">no mês atual</div></div>
    <div class="kpi"><label>Já Computado a Pagar</label><div class="v v-ac">R$ {fmt(gc_pag_atual_total)}</div><div class="sub">execução real até hoje</div></div>
    <div class="kpi"><label>Previsão de Fechamento</label><div class="v v-ac">R$ {fmt(gc_previsao_fechamento)}</div><div class="sub">estimativa do mês</div></div>
    <div class="kpi"><label>Frota Total Ativa</label><div class="v v-ok">{gc_frota_ativa:,}</div><div class="sub">status A no cadastro</div></div>
    <div class="kpi"><label>Frota em Operação</label><div class="v v-ok">{gc_frota_operando:,}</div><div class="sub">execução real nos últimos 30 dias</div></div>
    <div class="kpi"><label>Frota Ociosa c/ Contrato</label><div class="v {'v-cr' if gc_frota_ociosa>20 else 'v-wn'}">{gc_frota_ociosa:,}</div><div class="sub">ativa + contrato + sem execução</div></div>
    <div class="kpi"><label>Inativos c/ Contrato</label><div class="v v-cr">{gc_frota_inat_contrato:,}</div><div class="sub">inconsistência contratual</div></div>
    <div class="kpi"><label>Frota Comercial Disponível</label><div class="v v-ac">{gc_frota_sem_contrato:,}</div><div class="sub">terceirizados + locados</div></div>
  </div>

  <div class="g2">
    <div class="kpi"><label>Terceiros — Diária</label><div class="v v-wn">R$ {fmt(gc_fin_vd)}</div><div class="sub">{gc_fin_qd:,} contratos rota · valor/dia</div></div>
    <div class="kpi"><label>Terceiros — Mensal</label><div class="v v-wn">R$ {fmt(gc_fin_vm)}</div><div class="sub">{gc_fin_qm:,} contratos rota · valor/mês</div></div>
  </div>

  <div class="g2">
    <div class="kpi"><label>Frota Própria c/ Contrato</label><div class="v {'v-cr' if gc_propria_com_contrato>0 else 'v-ok'}">{gc_propria_com_contrato:,}</div><div class="sub">vínculo que deve ser auditado</div></div>
    <div class="kpi"><label>Frota Locada c/ Contrato</label><div class="v v-wn">{gc_locada_com_contrato:,}</div><div class="sub">analisada separadamente</div></div>
  </div>

  <div class="card gc-analysis">
    <h3>🧠 ANÁLISE GERENCIAL — LEITURA EXECUTIVA</h3>
    <p class="desc" style="border-left-color:var(--ac)">{comentario_gc_geral()}</p>
    <p class="desc" style="border-left-color:var(--wn)">{comentario_gc_frota_analise()}</p>
    <p class="desc" style="border-left-color:var(--pu)">{comentario_gc_financeiro()}</p>
    <p class="desc" style="border-left-color:#f97316">{comentario_gc_locada()}</p>
  </div>

  <div class="gc-rec">
    <b>🧠 PRIORIDADES GERENCIAIS:</b><br><br>
    {comentario_gc_recomendacao()}
  </div>

  <div class="g2">
    <div class="card">
      <h3>🚌 Frota Ativa por Tipo — Operação, Contrato e Disponibilidade</h3>
      <p class="desc">
        <b>Em Operação</b> = veículo ativo com execução real (início registrado) nos últimos 30 dias.
        <b>Ocioso c/ Contrato</b> = ativo, contrato vigente e sem execução real nos últimos 30 dias.
        <b>S/ Contrato</b> = ativo no cadastro sem contrato vigente. O card superior de disponibilidade comercial considera somente <b>terceirizados + locados</b>; frota própria e parceira são analisadas separadamente.
      </p>
      <div class="tw">
        <table>
          <thead><tr><th>Tipo</th><th>Total</th><th>Ativos</th><th>Inativos</th><th>Operando</th><th>Ociosos c/ Contrato</th><th>C/ Contrato</th><th>S/ Contrato</th><th>Inativos c/ Contrato</th></tr></thead>
          <tbody>{html_gc_frota_status()}</tbody>
        </table>
      </div>
      <div style="margin-top:12px;height:220px"><canvas id="c_gc_frota"></canvas></div>
    </div>

    <div class="card">
      <h3>💰 Compromisso Financeiro dos Terceirizados</h3>
      <p class="desc">Os valores abaixo consideram somente <b>contratos rota ATIVOS</b>, dentro de <b>contratos mestres ATIVOS</b>, e somente veículos classificados como <b>FROTA_TERCEIRIZADA</b>. O valor de diária é uma referência contratual; o <b>Já Computado a Pagar</b> usa exclusivamente execução real.</p>
      <table>
        <thead><tr><th>Modalidade</th><th style="text-align:center">Contratos Rota</th><th style="text-align:right">Valor</th><th>Referência</th></tr></thead>
        <tbody>
          <tr><td><b>DIÁRIA</b></td><td style="text-align:center">{gc_fin_qd:,}</td><td style="text-align:right;color:#f59e0b;font-weight:700">R$ {fmt(gc_fin_vd)}</td><td>por dia</td></tr>
          <tr><td><b>MENSAL</b></td><td style="text-align:center">{gc_fin_qm:,}</td><td style="text-align:right;color:#f59e0b;font-weight:700">R$ {fmt(gc_fin_vm)}</td><td>por mês</td></tr>
          <tr style="background:#0f172a;border-top:2px solid #334155"><td><b>PREVISÃO MENSAL</b></td><td></td><td style="text-align:right;color:#38bdf8;font-weight:700">R$ {fmt(gc_fin_total_mes)}</td><td>22 dias + mensal</td></tr>
        </tbody>
      </table>
      <p class="desc" style="border-left-color:#f97316;margin-top:12px"><b>Locada separada:</b> {gc_loc_qd} diária(s) = R$ {fmt(gc_loc_vd)}/dia · {gc_loc_qm} mensal(is) = R$ {fmt(gc_loc_vm)}/mês.</p>
    </div>
  </div>

  <div class="card gc-payment-card">
    <h3>💳 Pagamento Computado pela Execução — Mês → Dias → Contratos Rota</h3>
    <p class="desc" style="border-left-color:var(--ac)">{comentario_gc_pagamento_calendario()}</p>
    <p class="desc" style="border-left-color:var(--wn)">
      <b>Como calcular:</b> a operação diária vem diretamente de <b>rotas_escalarota</b>. DIÁRIA = 1 valor por <b>Contrato Rota + dia</b> com pelo menos uma execução real (início registrado) e não anulada. MENSAL = 1 valor por <b>Contrato Rota + mês</b> com pelo menos uma execução real e não anulada. O mesmo Contrato Rota pode aparecer em várias rotas/viagens e várias escalas, mas <b>não multiplica o valor da diária</b>. O calendário mostra a valor <b>já computado com base na execução efetivamente registrada</b>; não é uma projeção fixa de 22 dias.
    </p>
    {html_gc_pagamento_calendario()}
  </div>

  <div class="card">
    <h3>📈 Evolução da Quantidade de Contratos Mestres Ativos — 2026</h3>
    <p class="desc" style="border-left-color:var(--ac)">{comentario_gc_historico()}</p>
    <div class="tw">
      <table>
        <thead><tr><th>Mês</th><th style="text-align:center">Contratos Mestres em Vigência</th><th style="text-align:center">Variação</th></tr></thead>
        <tbody>{html_gc_historico()}</tbody>
      </table>
    </div>
    <div style="margin-top:12px;height:220px"><canvas id="c_gc_hist"></canvas></div>
  </div>

  <div class="card">
    <h3>🚨 Veículos Inativos com Contratos Ativos — Prioridade de Auditoria</h3>
    <p class="desc" style="border-left-color:var(--cr)">
      Este é um indicador específico de inconsistência: o veículo está <b>inativo (status I/S)</b>, mas existe <b>contrato mestre ativo + contrato rota ativo</b> vinculado a ele. Esses casos devem ser validados antes de renovação, pagamento ou nova contratação.
    </p>
    <input class="src" id="s_gc_i" oninput="fil('s_gc_i','t_gc_i')" placeholder="Filtrar placa, GRE, fornecedor, contrato...">
    <div class="tw">
      <table id="t_gc_i">
        <thead><tr><th>Placa</th><th>Modelo</th><th>GRE</th><th>Fornecedor</th><th>Tipo Frota</th><th>Alerta</th><th>Contrato</th><th>Contrato Rota</th><th>Modalidade</th><th>Valor</th><th>Vencimento</th></tr></thead>
        <tbody>{html_gc_inativos_contrato()}</tbody>
      </table>
    </div>
  </div>

  <div class="g2">
    <div class="card">
      <h3>📊 Demanda vs Oferta por GRE (Últimos 30 Dias)</h3>
      <p class="desc"><b>Frota Ativa</b> = veículos ativos no cadastro. <b>Frota Operando</b> = ativos com escala nos últimos 30 dias. <b>Veículos Usados</b> = distintos que apareceram nas escalas. A situação orienta redistribuição ou reforço de frota.</p>
      <div class="tw">
        <table>
          <thead><tr><th>GRE</th><th>Frota Ativa</th><th>Operando</th><th>Escalas 30d</th><th>Veíc. Usados</th><th>Utilização</th><th>Situação</th></tr></thead>
          <tbody>{html_gc_gap_gre()}</tbody>
        </table>
      </div>
      <div style="margin-top:12px;height:220px"><canvas id="c_gc_gap"></canvas></div>
    </div>

    <div class="card">
      <h3>📈 Demanda Diária Média por GRE (Últimos 30 Dias)</h3>
      <div class="tw">
        <table>
          <thead><tr><th>GRE</th><th>Dias</th><th>Total Escalas</th><th>Média/Dia</th><th>Veíc. Total</th><th>Próprios</th><th>Terc.</th><th>Parc.</th><th>Locados</th></tr></thead>
          <tbody>{html_gc_demanda()}</tbody>
        </table>
      </div>
      <div style="margin-top:12px;height:220px"><canvas id="c_gc_demanda"></canvas></div>
    </div>
  </div>

  <div class="card">
    <h3>🚨 Frota Ociosa com Contrato Ativo (Parada +30 dias)</h3>
    <p class="desc">Somente veículos <b>ativos + contrato ativo + sem execução real nos últimos 30 dias</b>. O quadro não inclui a frota disponível sem contrato. Para contratos mensais, o risco acumulado é rateado proporcionalmente por 30 dias.</p>
    <input class="src" id="s_gc_o" oninput="fil('s_gc_o','t_gc_o')" placeholder="Filtrar por GRE, placa, fornecedor...">
    <div class="tw">
      <table id="t_gc_o">
        <thead><tr><th>GRE</th><th>Placa</th><th>Modelo</th><th>Tipo</th><th>Fornecedor</th><th>Modalidade</th><th>Valor</th><th>Dias Parado</th><th>Risco Acumulado</th></tr></thead>
        <tbody>{html_gc_ociosa()}</tbody>
      </table>
    </div>
  </div>

  <div class="g2">
    <div class="card">
      <h3>🏢 Terceirizados — Maior Quantidade de Contratos Rota</h3>
      <p class="desc">Ranking dos fornecedores terceirizados com maior quantidade de <b>Contratos Rota ativos</b>. Considera somente itens ativos, dentro de contratos mestres ativos, vinculados a veículos classificados como <b>FROTA_TERCEIRIZADA</b>.</p>
      <div class="tw">
        <table>
          <thead><tr><th>#</th><th>Fornecedor</th><th style="text-align:center">Contratos Rota</th><th style="text-align:center">Veículos</th></tr></thead>
          <tbody>{html_gc_rank_terceiros_quantidade()}</tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h3>💰 Terceirizados — Maior Compromisso Diário</h3>
      <p class="desc">Ranking pelo valor contratado em <b>diárias</b>. Mostra onde está concentrado o maior compromisso financeiro diário com os terceirizados.</p>
      <div class="tw">
        <table>
          <thead><tr><th>#</th><th>Fornecedor</th><th style="text-align:center">Rotas Diárias</th><th style="text-align:right">Valor Diário</th><th></th></tr></thead>
          <tbody>{html_gc_rank_terceiros_valor()}</tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>🚨 Contratos Rota Ativos sem Placa Vinculada</h3>
    <p class="desc" style="border-left-color:#a78bfa">Existem <b>{gc_sem_placa:,}</b> contratos rota ativos sem placa vinculada. Esses itens devem ser regularizados ou justificados antes de serem considerados plenamente aptos para operação.</p>
    <input class="src" id="s_gc_p" oninput="fil('s_gc_p','t_gc_p')" placeholder="Filtrar contrato, GRE, fornecedor...">
    <div class="tw">
      <table id="t_gc_p">
        <thead><tr><th>Contrato Rota</th><th style="text-align:center">Contrato Mestre</th><th>GRE</th><th>Fornecedor</th><th>Modalidade</th><th style="text-align:right">Valor</th><th>Início</th><th>Fim</th><th>Situação</th></tr></thead>
        <tbody>{html_gc_sem_placa()}</tbody>
      </table>
    </div>
  </div>
</div>

<script>
function tab(id,btn){{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
function fil(sid,tid){{
  const v=document.getElementById(sid).value.toLowerCase();
  document.getElementById(tid).querySelectorAll('tbody tr').forEach(r=>{{
    r.style.display=r.innerText.toLowerCase().includes(v)?'':'none';
  }});
}}

const C={{
  line:(id,labels,datasets)=>new Chart(document.getElementById(id),{{
    type:'line',
    data:{{labels,datasets}},
    options:{{
      responsive:true,
      plugins:{{legend:{{labels:{{color:'#94a3b8',font:{{size:11}}}}}}}},
      scales:{{
        x:{{ticks:{{color:'#64748b',font:{{size:10}}}}}},
        y:{{ticks:{{color:'#64748b',font:{{size:10}}}}}}
      }}
    }}
  }}),
  bar:(id,labels,datasets)=>new Chart(document.getElementById(id),{{
    type:'bar',
    data:{{labels,datasets}},
    options:{{
      responsive:true,
      plugins:{{legend:{{labels:{{color:'#94a3b8',font:{{size:11}}}}}}}},
      scales:{{
        x:{{ticks:{{color:'#64748b',font:{{size:10}}}}}},
        y:{{ticks:{{color:'#64748b',font:{{size:10}}}}}}
      }}
    }}
  }}),
  pie:(id,labels,data,colors)=>new Chart(document.getElementById(id),{{
    type:'doughnut',
    data:{{labels,datasets:[{{data,backgroundColor:colors,borderWidth:0}}]}},
    options:{{
      responsive:true,
      plugins:{{legend:{{position:'right',labels:{{color:'#94a3b8',font:{{size:11}}}}}}}}
    }}
  }})
}};

// ─── PAINEL EXECUTIVO — FILTROS E RENDERIZAÇÃO ─────────────────────────────
const execRows = {jd(exec_data)};
const execToday = '{exec_today_iso}';
const execCurrentYM = execToday.slice(0,7);

function exEsc(v){{
  return String(v??'').replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}})[m]);
}}
function exPct(v){{ return Number(v||0).toLocaleString('pt-BR',{{minimumFractionDigits:1,maximumFractionDigits:1}})+'%'; }}
function exNum(v){{ return Number(v||0).toLocaleString('pt-BR'); }}
function exKm(v){{ return Number(v||0).toLocaleString('pt-BR',{{minimumFractionDigits:1,maximumFractionDigits:1}}); }}

function exDate(s){{ return new Date(s+'T00:00:00'); }}
function exPeriodMatch(r,p){{
  if(p==='year') return true;
  if(p==='current') return r.d.slice(0,7)===execCurrentYM;
  if(p==='last30'){{
    const d=exDate(r.d); const t=exDate(execToday); const ini=new Date(t); ini.setDate(ini.getDate()-30);
    return d>=ini && d<=t;
  }}
  return true;
}}
function exTypeMatch(r,v){{
  if(!v) return true;
  const t=String(r.t||'').toUpperCase();
  if(v==='RR') return t==='RR';
  if(v==='EX') return t==='EX';
  if(v==='OUTROS') return !['RR','EX'].includes(t);
  return true;
}}
function exRows(){{
  const p=document.getElementById('fx_periodo').value;
  const f={{
    tipo:document.getElementById('fx_tipo').value,
    turno:document.getElementById('fx_turno').value,
    direcao:document.getElementById('fx_direcao').value,
    gre:document.getElementById('fx_gre').value,
    cidade:document.getElementById('fx_cidade').value,
    fiscal:document.getElementById('fx_fiscal').value,
    regiao:document.getElementById('fx_regiao').value,
    fornecedor:document.getElementById('fx_fornecedor').value
  }};
  return execRows.filter(r=>{{
    if(!exPeriodMatch(r,p) || !exTypeMatch(r,f.tipo)) return false;
    if(f.turno && r.s!==f.turno) return false;
    if(f.direcao && r.di!==f.direcao) return false;
    if(f.gre && r.g!==f.gre) return false;
    if(f.cidade && r.c!==f.cidade) return false;
    if(f.fiscal && r.f!==f.fiscal) return false;
    if(f.regiao && r.rg!==f.regiao) return false;
    if(f.fornecedor && r.p!==f.fornecedor) return false;
    return true;
  }});
}}
function exGroup(rows,key){{
  const m=new Map();
  rows.forEach(r=>{{
    const k=r[key]||'SEM DADO';
    if(!m.has(k))m.set(k,{{nome:k,total:0,ok:0,nao:0,km:0,veic:new Set(),motor:new Set()}});
    const o=m.get(k); o.total++;
    if(r.i&&r.z)o.ok++;
    if(!r.i)o.nao++;
    if(r.i)o.km+=Number(r.k||0);
    if(r.v)o.veic.add(r.v);
    if(r.m)o.motor.add(r.m);
  }});
  return [...m.values()];
}}
function exAssid(o){{ return o.total?o.ok/o.total*100:0; }}
function exTable(id, html, colspan){{
  document.querySelector('#'+id+' tbody').innerHTML=html||`<tr><td colspan="${{colspan}}">Sem dados para os filtros selecionados.</td></tr>`;
}}
function exTr(a){{ return '<tr>'+a.map(v=>'<td>'+v+'</td>').join('')+'</tr>'; }}

let exCharts=[];
function exDestroy(){{ exCharts.forEach(c=>{{try{{c.destroy()}}catch(e){{}}}}); exCharts=[]; }}

function exRender(){{
  const rows=exRows();
  const total=rows.length;
  const conc=rows.filter(r=>r.i&&r.z).length;
  const and=rows.filter(r=>r.i&&!r.z).length;
  const nao=rows.filter(r=>!r.i).length;
  const started=rows.filter(r=>r.i);
  const assid=total?conc/total*100:0;
  const extra=rows.filter(r=>String(r.t).toUpperCase()==='EX').length;
  const km=rows.reduce((s,r)=>s+(r.i?Number(r.k||0):0),0);

  document.getElementById('x_total').textContent=exNum(total);
  document.getElementById('x_conc').textContent=exNum(conc);
  document.getElementById('x_nao').textContent=exNum(nao);
  document.getElementById('x_assid').textContent=exPct(assid);
  document.getElementById('x_extra').textContent=exNum(extra);
  document.getElementById('x_km').textContent=exKm(km)+' km';
  document.getElementById('x_and').textContent=exNum(and);
  document.getElementById('x_cov').textContent=exPct(assid);

  document.getElementById('exec_analysis').innerHTML =
    `<b>${{exNum(total)}} ocorrências analisadas</b> · <b>${{exNum(conc)}} concluídas</b> · `+
    `<b>${{exNum(nao)}} não executadas</b> · <b>${{exNum(and)}} em andamento</b> · `+
    `assiduidade <b>${{exPct(assid)}}</b> · extras <b>${{exNum(extra)}}</b> · `+
    `KM executado <b>${{exKm(km)}} km</b>`;

  exRenderFiscal(rows);
  exRenderGre(rows);
  exRenderCity(rows);
  exRenderKm(rows);
  exRenderFrota(rows);
  exRenderFornecedor(rows);
  exRenderOcorr(rows);
  exRenderTec(rows);
  exRenderVinculo(rows);
  exRenderCharts(rows);
}}
function exRenderFiscal(rows){{
  const m=new Map();
  rows.forEach(r=>{{
    const k=(r.f||'SEM FISCAL')+'||'+(r.g||'SEM GRE');
    if(!m.has(k))m.set(k,{{f:r.f,g:r.g,total:0,ok:0}});
    const o=m.get(k);o.total++;if(r.i&&r.z)o.ok++;
  }});
  const a=[...m.values()].map(o=>({{...o,ass:o.total?o.ok/o.total*100:0}})).sort((x,y)=>y.ass-x.ass||y.total-x.total);
  exTable('t_exec_fiscal',a.slice(0,30).map((o,i)=>exTr(['<b>#'+(i+1)+'</b>',exEsc(o.f),exEsc(o.g),exNum(o.total),exNum(o.ok),exPct(o.ass)])).join(''),6);
}}
function exRenderGre(rows){{
  const a=exGroup(rows,'g').map(o=>({{...o,ass:exAssid(o)}})).sort((x,y)=>y.total-x.total);
  exTable('t_exec_gre',a.slice(0,30).map((o,i)=>exTr(['<b>#'+(i+1)+'</b>',exEsc(o.nome),exNum(o.total),exNum(o.ok),exPct(o.ass)])).join(''),5);
}}
function exRenderCity(rows){{
  const a=exGroup(rows,'c').map(o=>({{...o,ass:exAssid(o)}})).sort((x,y)=>y.total-x.total);
  exTable('t_exec_city',a.slice(0,40).map((o,i)=>exTr(['<b>#'+(i+1)+'</b>',exEsc(o.nome),exNum(o.total),exNum(o.ok),exPct(o.ass)])).join(''),5);
  const conc=[...a].sort((x,y)=>y.ok-x.ok);
  exTable('t_exec_city_conc',conc.slice(0,40).map((o,i)=>exTr(['<b>#'+(i+1)+'</b>',exEsc(o.nome),exNum(o.ok)])).join(''),3);
  const ass=[...a].filter(o=>o.total>=10).sort((x,y)=>y.ass-x.ass);
  exTable('t_exec_city_assid',ass.slice(0,40).map((o,i)=>exTr(['<b>#'+(i+1)+'</b>',exEsc(o.nome),exNum(o.total),exNum(o.ok),exPct(o.ass)])).join(''),5);
}}
function exRenderKm(rows){{
  const a=exGroup(rows,'g').sort((x,y)=>y.km-x.km);
  exTable('t_exec_km_gre',a.slice(0,30).map((o,i)=>exTr(['<b>#'+(i+1)+'</b>',exEsc(o.nome),exKm(o.km)+' km'])).join(''),3);
  const b=exGroup(rows,'c').sort((x,y)=>y.km-x.km);
  exTable('t_exec_km_city',b.slice(0,40).map((o,i)=>exTr(['<b>#'+(i+1)+'</b>',exEsc(o.nome),exKm(o.km)+' km'])).join(''),3);
}}
function exRenderFrota(rows){{
  const m=new Map();
  rows.forEach(r=>{{
    const k=(r.ft||'SEM TIPO')+'||'+(r.g||'SEM GRE');
    if(!m.has(k))m.set(k,{{tipo:r.ft,gre:r.g,rotas:0,veic:new Set()}});
    const o=m.get(k);o.rotas++;if(r.v)o.veic.add(r.v);
  }});
  const a=[...m.values()].sort((x,y)=>y.rotas-x.rotas);
  exTable('t_exec_frota',a.slice(0,50).map(o=>exTr([exEsc(o.tipo+' / '+o.gre),exNum(o.rotas),exNum(o.veic.size)])).join(''),3);
}}
function exRenderFornecedor(rows){{
  const a=exGroup(rows,'p').map(o=>({{...o,ass:exAssid(o)}})).sort((x,y)=>y.total-x.total);
  exTable('t_exec_fornecedor',a.slice(0,40).map(o=>exTr([exEsc(o.nome),exNum(o.total),exNum(o.ok),exPct(o.ass)])).join(''),4);
}}
function exRenderOcorr(rows){{
  const m=new Map();
  rows.forEach(r=>{{ if(!r.o)return; const k=(r.f||'SEM FISCAL')+'||'+(r.g||'SEM GRE'); m.set(k,(m.get(k)||0)+1); }});
  const a=[...m.entries()].map(([k,v])=>{{const q=k.split('||');return{{f:q[0],g:q[1],n:v}}}}).sort((x,y)=>y.n-x.n);
  exTable('t_exec_ocorr',a.slice(0,40).map(o=>exTr([exEsc(o.f),exEsc(o.g),exNum(o.n)])).join(''),3);
}}
function exRenderTec(rows){{
  const m=new Map();
  rows.forEach(r=>{{
    const k=[r.f,r.g,r.c,r.m].join('||');
    if(!m.has(k))m.set(k,{{f:r.f,g:r.g,c:r.c,m:r.m,total:0,start:false,concl:false,app:false,link:false}});
    const o=m.get(k);o.total++;if(r.i)o.start=true;if(r.i&&r.z)o.concl=true;if(r.i&&r.a===true)o.app=true;if(r.i&&r.a===false)o.link=true;
  }});
  const a=[...m.values()].map(o=>({{...o,pctApp:o.concl?(o.app?100:0):0,pctOpen:o.total?(o.start?100:0):0}})).sort((x,y)=>y.total-x.total);
  exTable('t_exec_tec',a.slice(0,100).map(o=>exTr([exEsc(o.f),exEsc(o.g),exEsc(o.c),'<b>'+exEsc(o.m)+'</b>',exNum(o.total),o.concl?'1':'0',o.app?'1':'0',o.link?'1':'0',exPct(o.pctApp),exPct(o.pctOpen)])).join(''),10);
}}
function exRenderVinculo(rows){{
  const mm=new Map(), gps=new Map(), allMot=new Set(), allV=new Set(), allS=new Set();
  rows.forEach(r=>{{
    const g=r.g||'SEM GRE', mot=r.m||'SEM MOTORISTA';
    if(!mm.has(g))mm.set(g,{{mot:new Set(),vei:new Set(),sem:new Set()}});
    const o=mm.get(g);o.mot.add(mot);
    if(r.v && r.v!=='SEM PLACA')o.vei.add(mot);else o.sem.add(mot);
    allMot.add(mot); if(r.v&&r.v!=='SEM PLACA')allV.add(mot);else allS.add(mot);
    if(!gps.has(mot))gps.set(mot,new Set());gps.get(mot).add(g);
  }});
  document.getElementById('x_mot').textContent=exNum(allMot.size);
  document.getElementById('x_mot_vei').textContent=exNum(allV.size);
  document.getElementById('x_mot_sem').textContent=exNum(allS.size);
  const a=[...mm.entries()].sort((x,y)=>y[1].mot.size-x[1].mot.size);
  exTable('t_exec_vinculo',a.map(([g,o])=>exTr([exEsc(g),exNum(o.mot.size),exNum(o.vei.size),exNum(o.sem.size)])).join(''),4);
  const multi=[...gps.entries()].filter(([_,s])=>s.size>1);
  const el=document.getElementById('x_multi_gre');
  if(multi.length){{el.className='alerta';el.innerHTML='<b>⚠️ Motoristas em mais de uma GRE:</b> '+multi.slice(0,10).map(([m,s])=>exEsc(m)+' ('+[...s].map(exEsc).join(', ')+')').join(' · ');}}
  else{{el.className='info';el.innerHTML='✅ Nenhum motorista em mais de uma GRE.';}}
}}
function exRenderCharts(rows){{
  exDestroy();
  const byM=new Map();
  rows.forEach(r=>{{
    const m=r.d.slice(0,7);if(!byM.has(m))byM.set(m,{{total:0,conc:0,nao:0,km:0}});
    const o=byM.get(m);o.total++;if(r.i&&r.z)o.conc++;if(!r.i)o.nao++;if(r.i)o.km+=Number(r.k||0);
  }});
  let ms=[...byM.keys()].sort();
  if(document.getElementById('fx_periodo').value==='current' && !ms.length)ms=[execCurrentYM];
  const monthNames=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
  const labels=ms.map(m=>{{const [y,mo]=m.split('-');return monthNames[Number(mo)-1]+'/'+y.slice(2)}});

  exCharts.push(new Chart(document.getElementById('c_exec_hist'),{{type:'line',data:{{labels,datasets:[
    {{label:'Planejadas / Analisadas',data:ms.map(m=>byM.get(m)?.total||0),tension:.25}},
    {{label:'Concluídas',data:ms.map(m=>byM.get(m)?.conc||0),tension:.25}},
    {{label:'Não Executadas',data:ms.map(m=>byM.get(m)?.nao||0),tension:.25}}
  ]}},options:{{responsive:true}}}}));
  exCharts.push(new Chart(document.getElementById('c_exec_assid'),{{type:'line',data:{{labels,datasets:[{{label:'Assiduidade %',data:ms.map(m=>{{const o=byM.get(m);return o&&o.total?Number((o.conc/o.total*100).toFixed(1)):0}}),tension:.25}}]}},options:{{responsive:true,scales:{{y:{{beginAtZero:true,max:100}}}}}}}}));
  exCharts.push(new Chart(document.getElementById('c_exec_km'),{{type:'bar',data:{{labels,datasets:[{{label:'KM Executado',data:ms.map(m=>Number((byM.get(m)?.km||0).toFixed(1)))}}]}},options:{{responsive:true}}}}));
}}

['fx_periodo','fx_tipo','fx_turno','fx_direcao','fx_gre','fx_cidade','fx_fiscal','fx_regiao','fx_fornecedor'].forEach(id=>document.getElementById(id).addEventListener('change',exRender));
exRender();

// ─── GRÁFICOS GERENTE DE CONTRATOS ─────────────────────────────────────────

// Frota por tipo (doughnut)
const frotaLabels = {jd(list(gc_frota_tipos.keys()))};
const frotaData = {jd(list(gc_frota_tipos.values()))};
C.pie('c_gc_frota', frotaLabels, frotaData, ['#22c55e','#f59e0b','#a78bfa','#38bdf8']);

// Custo por tipo (bar)
const custoLabels = {jd(df_gc_custo_tipo['tipo'].tolist() if not df_gc_custo_tipo.empty else [])};
const custoData = {jd([float(v) for v in df_gc_custo_tipo['custo_por_escala'].tolist()] if not df_gc_custo_tipo.empty else [])};
C.bar('c_gc_custo', custoLabels.map(l=>l.replace('FROTA_','')), [{{label:'R$/Escala',data:custoData,backgroundColor:['rgba(34,197,94,.4)','rgba(245,158,11,.4)','rgba(167,139,250,.4)'],borderColor:['#22c55e','#f59e0b','#a78bfa'],borderWidth:1}}]);

// Gap por situação (bar horizontal via bar com indexAxis)
const gapLabels = {jd(list(gc_gap_counts.keys()))};
const gapData = {jd(list(gc_gap_counts.values()))};
new Chart(document.getElementById('c_gc_gap'), {{
  type:'bar',
  data:{{labels:gapLabels,datasets:[{{label:'GREs',data:gapData,backgroundColor:gapLabels.map(l=>{{const c={{'SOBRECARGA':'#ef4444','FROTA OCIOSA':'#f59e0b','LIMITE':'#f97316','EQUILIBRADO':'#22c55e','SEM FROTA':'#a78bfa'}};return c[l]||'#64748b';}}),borderWidth:0}}]}},
  options:{{indexAxis:'y',responsive:true,plugins:{{legend:{{display:false}}}},scales:{{x:{{ticks:{{color:'#64748b'}}}},y:{{ticks:{{color:'#94a3b8'}}}}}}}}
}});

// Demanda diária (bar)
const demLabels = {jd(df_gc_demanda_diaria['gre'].tolist() if not df_gc_demanda_diaria.empty else [])};
const demData = {jd([float(v) for v in df_gc_demanda_diaria['media_escalas_dia'].tolist()] if not df_gc_demanda_diaria.empty else [])};
C.bar('c_gc_demanda', demLabels, [{{label:'Média Escalas/Dia',data:demData,backgroundColor:'rgba(56,189,248,.35)',borderColor:'#38bdf8',borderWidth:1}}]);

// Histórico contratação (line)
const histM = {jd(gc_hist_meses)};
const histA = {jd(gc_hist_ativos)};
C.line('c_gc_hist', histM, [
  {{label:'Contratos Ativos',data:histA,borderColor:'#38bdf8',backgroundColor:'rgba(56,189,248,.08)',fill:true,tension:.3}}
]);
</script>
</body>
</html>"""

with open("index.html","w",encoding="utf-8") as f:
    f.write(html)
print(f"✅ index.html gerado — {len(html):,} bytes")
