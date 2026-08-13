import psycopg2
import pandas as pd
import json
from datetime import datetime

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

# KPIs executivos
df_kpi = safe_read("""
SELECT
    COUNT(*) as total_escalas,
    COUNT(*) FILTER (WHERE via_app = true) as rastreado,
    COUNT(*) FILTER (WHERE via_app = false AND confirmado_manualmente = true) as sem_rastreamento,
    COUNT(*) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) as suspeitas
FROM airbyte.rotas_escalarota
WHERE data >= DATE_TRUNC('month', CURRENT_DATE)
""", pd.DataFrame([{'total_escalas':0,'rastreado':0,'sem_rastreamento':0,'suspeitas':0}]))

df_kpi_extra = safe_read("""
SELECT
    (SELECT COUNT(DISTINCT ci.id) FROM airbyte.contratos_itemcontrato ci
     JOIN airbyte.contratos_contrato c ON ci.contrato_id = c.id
     LEFT JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
     LEFT JOIN airbyte.motoristas_motorista m ON m.veiculo_id = v.id AND m.status = 'A'
     WHERE c.status = 'A' AND ci.status = 'ATIVO' AND m.id IS NULL) as contratos_risco,
    (SELECT COUNT(*) FROM airbyte.ordens_chamado WHERE status = 'CA' AND emissao >= '2026-01-01') as chamados_abertos,
    (SELECT COUNT(*) FROM airbyte.ordens_chamado WHERE status = 'CO' AND emissao >= '2026-01-01') as em_oficina
""", pd.DataFrame([{'contratos_risco':0,'chamados_abertos':0,'em_oficina':0}]))

# Evolução mensal geral
df_evolucao = safe_read("""
SELECT
    TO_CHAR(data,'YYYY-MM') as mes,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE via_app = true) as rastreado,
    COUNT(*) FILTER (WHERE via_app = false AND confirmado_manualmente = true) as sem_rast,
    COUNT(*) FILTER (WHERE anulada = true) as anuladas,
    COUNT(*) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) as suspeitas
FROM airbyte.rotas_escalarota
WHERE data >= '2026-01-01' AND data IS NOT NULL
GROUP BY TO_CHAR(data,'YYYY-MM')
ORDER BY mes
""")

# Histórico mensal por cidade (PIVÔ)
df_cidade_hist = safe_read("""
SELECT
    m.cidade,
    TO_CHAR(e.data,'YYYY-MM') as mes,
    COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE e.via_app = true) as rastreado,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0),1) as pct,
    COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) as suspeitas,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast
FROM airbyte.motoristas_motorista m
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE m.status = 'A' AND m.cidade IS NOT NULL
  AND e.data >= '2026-04-01'
GROUP BY m.cidade, TO_CHAR(e.data,'YYYY-MM')
HAVING COUNT(e.id) >= 30
ORDER BY m.cidade, mes
""")

# Histórico mensal por GRE (apenas a partir de abr/2026)
df_gre_hist = safe_read("""
SELECT
    g.nome as gre,
    TO_CHAR(e.data,'YYYY-MM') as mes,
    COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE e.via_app = true) as rastreado,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true)*100.0/NULLIF(COUNT(e.id),0),1) as pct,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast,
    COUNT(e.id) FILTER (WHERE anulada = true) as anuladas,
    COUNT(e.id) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) as suspeitas
FROM airbyte.rotas_escalarota e
JOIN airbyte.rotas_rota r ON r.id = e.rota_id
JOIN airbyte.escolas_gre g ON g.id = r.gre_id
WHERE e.data >= '2026-04-01'
  AND g.nome NOT IN ('ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','TESTE','SEMEC - SUDESTE')
GROUP BY g.nome, TO_CHAR(e.data,'YYYY-MM')
ORDER BY g.nome, mes
""")

# Fraude mensal
df_fraude_mensal = safe_read("""
SELECT
    TO_CHAR(data,'YYYY-MM') as mes,
    COUNT(*) FILTER (WHERE inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL) as com_horario,
    COUNT(*) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) as suspeitas,
    COUNT(*) FILTER (WHERE via_app = false AND confirmado_manualmente = true) as sem_rast
FROM airbyte.rotas_escalarota
WHERE data >= '2026-01-01'
GROUP BY TO_CHAR(data,'YYYY-MM') ORDER BY mes
""")

# Empresas com fraude
df_fraude_emp = safe_read("""
SELECT
    COALESCE(f.nome,'SEM FORNECEDOR') as empresa,
    COUNT(DISTINCT m.id) as motoristas,
    COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) as suspeitas,
    ROUND(COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    )*100.0/NULLIF(COUNT(e.id),0),1) as pct_susp,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast
FROM airbyte.motoristas_fornecedor f
JOIN airbyte.motoristas_motorista m ON m.fornecedor_id = f.id
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE e.data >= '2026-01-01'
  AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL
GROUP BY f.nome HAVING COUNT(e.id) >= 20
ORDER BY pct_susp DESC LIMIT 15
""")

# Motoristas com fraude
df_fraude_mot = safe_read("""
SELECT
    m.nome as motorista,
    COALESCE(f.nome,'PRÓPRIO') as empresa,
    m.cidade, g.nome as gre,
    COUNT(e.id) as total,
    COUNT(e.id) FILTER (WHERE
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) as suspeitas,
    ROUND(COUNT(e.id) FILTER (WHERE
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    )*100.0/NULLIF(COUNT(e.id),0),1) as pct_susp,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as sem_rast
FROM airbyte.motoristas_motorista m
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status = 'A' AND e.data >= '2026-01-01'
  AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL
GROUP BY m.nome, f.nome, m.cidade, g.nome HAVING COUNT(e.id) >= 10
ORDER BY pct_susp DESC LIMIT 20
""")

# Contratos sem operação
df_contratos = safe_read("""
SELECT DISTINCT ON (ci.id)
    ci.id as item, g.nome as gre, ci.valor_unitario,
    v.placa, v.status as sv,
    COALESCE(ct.nome,'Não definido') as turno,
    (SELECT COUNT(*) FROM airbyte.rotas_escalarota e2
     WHERE e2.veiculo_id = v.id AND e2.data >= CURRENT_DATE - INTERVAL '30 days'
     AND e2.anulada = false) as esc30d
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c ON ci.contrato_id = c.id
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
LEFT JOIN airbyte.motoristas_motorista m ON m.veiculo_id = v.id AND m.status = 'A'
LEFT JOIN airbyte.contratos_itemcontrato_turnos cit ON cit.itemcontrato_id = ci.id
LEFT JOIN airbyte.contratos_turno ct ON ct.id = cit.turno_id
LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
WHERE c.status = 'A' AND ci.status = 'ATIVO' AND m.id IS NULL
ORDER BY ci.id, ci.valor_unitario DESC
LIMIT 60
""")

df_cont_mensal = safe_read("""
SELECT TO_CHAR(data,'YYYY-MM') as mes,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE anulada=true) as anuladas,
    COUNT(*) FILTER (WHERE via_app=false AND confirmado_manualmente=true) as sem_rast
FROM airbyte.rotas_escalarota
WHERE contrato_rota_id IS NOT NULL AND data >= '2026-04-01'
GROUP BY TO_CHAR(data,'YYYY-MM') ORDER BY mes
""")

# Frota documentação
df_frota = safe_read("""
SELECT COALESCE(f.nome,'SEM FORNECEDOR') as fornecedor,
    COUNT(DISTINCT v.id) as total,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status='A') as ativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status='I') as inativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.multas=true) as multas,
    COUNT(DISTINCT v.id) FILTER (WHERE v.licenciamento::int < 2026) as lic_venc,
    COUNT(DISTINCT v.id) FILTER (WHERE v.licenciamento::int >= 2026) as lic_ok
FROM airbyte.motoristas_fornecedor f
JOIN airbyte.veiculos_veiculo v ON v.fornecedor_id = f.id
WHERE v.licenciamento IS NOT NULL
GROUP BY f.nome HAVING COUNT(DISTINCT v.id) >= 2
ORDER BY lic_venc DESC LIMIT 15
""")

df_manut_forn = safe_read("""
SELECT COALESCE(f.nome,'SEM FORNECEDOR') as fornecedor,
    COUNT(DISTINCT c.id) as chamados,
    COUNT(DISTINCT c.id) FILTER (WHERE c.status='CA') as abertos,
    COUNT(DISTINCT c.id) FILTER (WHERE c.status='CO') as oficina,
    COUNT(DISTINCT c.veiculo_id) as veiculos,
    ROUND(AVG(CASE WHEN c.entrega IS NOT NULL AND c.emissao IS NOT NULL
        THEN EXTRACT(EPOCH FROM (c.entrega - c.emissao))/86400 END)::numeric,1) as media_dias
FROM airbyte.ordens_chamado c
JOIN airbyte.veiculos_veiculo v ON v.id = c.veiculo_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
WHERE c.emissao >= '2026-01-01'
GROUP BY f.nome ORDER BY abertos DESC, chamados DESC LIMIT 12
""")

df_veic_prob = safe_read("""
SELECT v.placa, v.modelo, COALESCE(f.nome,'SEM FORN') as fornecedor,
    g.nome as gre,
    COUNT(c.id) as chamados,
    COUNT(c.id) FILTER (WHERE c.status='CA') as abertos,
    COUNT(c.id) FILTER (WHERE c.falha_humana=true) as falha_hum,
    ROUND(AVG(CASE WHEN c.entrega IS NOT NULL AND c.emissao IS NOT NULL
        THEN EXTRACT(EPOCH FROM (c.entrega - c.emissao))/86400 END)::numeric,1) as media_dias
FROM airbyte.veiculos_veiculo v
JOIN airbyte.ordens_chamado c ON c.veiculo_id = v.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = v.gre_id
WHERE c.emissao >= '2026-01-01'
GROUP BY v.placa, v.modelo, f.nome, g.nome
HAVING COUNT(c.id) >= 5 ORDER BY chamados DESC LIMIT 15
""")

# Motoristas
df_mot_rank = safe_read("""
SELECT m.nome, COALESCE(f.nome,'PRÓPRIO') as empresa, m.cidade, g.nome as gre,
    COUNT(e.id) as total,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app=true)*100.0/NULLIF(COUNT(e.id),0),1) as pct_rast,
    COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) as suspeitas,
    COUNT(e.id) FILTER (WHERE e.via_app=false AND e.confirmado_manualmente=true) as sem_rast
FROM airbyte.motoristas_motorista m
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status='A' AND e.data >= '2026-04-01'
GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COUNT(e.id) >= 20
ORDER BY pct_rast ASC LIMIT 30
""")

df_mot_chamados = safe_read("""
SELECT m.nome, COALESCE(f.nome,'PRÓPRIO') as empresa, g.nome as gre,
    COUNT(c.id) as chamados,
    COUNT(c.id) FILTER (WHERE c.falha_humana=true) as falha_hum,
    COUNT(c.id) FILTER (WHERE c.status='CA') as abertos
FROM airbyte.ordens_chamado c
JOIN airbyte.motoristas_motorista m ON m.id = c.motorista_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE c.emissao >= '2026-01-01'
GROUP BY m.nome, f.nome, g.nome HAVING COUNT(c.id) >= 3
ORDER BY chamados DESC LIMIT 15
""")

df_abast = safe_read("""
SELECT m.nome, COALESCE(f.nome,'PRÓPRIO') as empresa, m.cidade, g.nome as gre,
    COUNT(DISTINCT a.id) as abast,
    COALESCE(SUM(a.litros),0) as litros,
    COALESCE(SUM(a.valor_total),0) as gasto,
    COUNT(DISTINCT e.id) as escalas,
    CASE WHEN COUNT(DISTINCT e.id) > 0
        THEN ROUND(COALESCE(SUM(a.valor_total),0)/COUNT(DISTINCT e.id),2) ELSE 0
    END as rs_escala
FROM airbyte.motoristas_motorista m
LEFT JOIN airbyte.abastecimentos_abastecimento a ON a.motorista_id = m.id
    AND a.datetime_abastecimento >= '2026-01-01' AND a.litros <= 1000
LEFT JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
    AND e.data >= '2026-01-01' AND e.anulada = false
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status='A'
GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COALESCE(SUM(a.litros),0) BETWEEN 1 AND 50000
ORDER BY gasto DESC LIMIT 20
""")

# Fiscal
df_fiscal = safe_read("""
SELECT g.nome as gre, func.nome as fiscal,
    COUNT(e.id) as total,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app=true AND e.data BETWEEN '2026-04-01' AND '2026-06-30')
        *100.0/NULLIF(COUNT(e.id) FILTER (WHERE e.data BETWEEN '2026-04-01' AND '2026-06-30'),0),1) as pct_q2,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app=true AND e.data >= '2026-07-01')
        *100.0/NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-07-01'),0),1) as pct_q3,
    COUNT(e.id) FILTER (WHERE e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL
        AND EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
        AND e.data >= '2026-04-01') as suspeitas,
    COUNT(e.id) FILTER (WHERE e.via_app=false AND e.confirmado_manualmente=true
        AND e.data >= '2026-04-01') as sem_rast
FROM airbyte.rotas_escalarota e
JOIN airbyte.rotas_rota r ON r.id = e.rota_id
JOIN airbyte.escolas_gre g ON g.id = r.gre_id
LEFT JOIN airbyte.motoristas_funcionario func ON func.id = g.fiscal_responsavel_id
WHERE e.data >= '2026-04-01'
  AND g.nome NOT IN ('ADMINISTRATIVO','LOGISTICA CAPITAL','LOGISTICA INTERIOR','TESTE','SEMEC - SUDESTE')
GROUP BY g.nome, func.nome ORDER BY pct_q3 ASC
""")

conn.close()
print("✅ Queries concluídas. Processando...")

# ─── PROCESSAR PIVÔ DE CIDADES ─────────────────────────────────────────────
pivot = {}  # cidade -> {mes -> {total, pct, suspeitas, sem_rast}}
if not df_cidade_hist.empty:
    for _, r in df_cidade_hist.iterrows():
        c = r['cidade']
        m = r['mes']
        if c not in pivot: pivot[c] = {}
        pivot[c][m] = {
            'total': int(r['total']),
            'pct': float(r['pct'] or 0),
            'suspeitas': int(r['suspeitas'] or 0),
            'sem_rast': int(r['sem_rast'] or 0)
        }

# Calcular scores e tendências por cidade
cidade_scores = []
for cidade, dados in pivot.items():
    vals = [dados.get(m, {}).get('pct') for m in MESES_COLS]
    total_geral = sum(dados.get(m, {}).get('total', 0) for m in MESES_COLS)
    total_susp = sum(dados.get(m, {}).get('suspeitas', 0) for m in MESES_COLS)
    total_sem = sum(dados.get(m, {}).get('sem_rast', 0) for m in MESES_COLS)
    v_clean = [x for x in vals if x is not None]
    score = score_gargalo(v_clean, total_susp, total_geral)
    icon, status, cls = tendencia(v_clean)
    cidade_scores.append({
        'cidade': cidade, 'vals': vals, 'total': total_geral,
        'suspeitas': total_susp, 'sem_rast': total_sem,
        'score': score, 'icon': icon, 'status': status, 'cls': cls
    })
cidade_scores.sort(key=lambda x: -x['score'])

# ─── GERAR HTML DA TABELA PIVÔ ─────────────────────────────────────────────
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
        h += f"<tr><td><b>{r['cidade']}</b></td>"
        h += f"<td style='text-align:center'>{r['total']:,}</td>"
        for pct in r['vals']:
            if pct is None:
                h += "<td style='text-align:center;color:#334155'>—</td>"
            else:
                h += f"<td style='text-align:center;{cor_pct(pct)}'>{pct}%</td>"
        h += f"<td style='text-align:center'>{r['suspeitas']:,}</td>"
        h += f"<td><span class='tag {cls_status(r['cls'])}'>{r['icon']} {r['status']}</span></td>"
        h += f"<td style='text-align:right;color:#64748b;font-size:11px'>{r['score']}</td></tr>"
    return h

# Tabela pivô de GREs
gre_pivot = {}
if not df_gre_hist.empty:
    for _, r in df_gre_hist.iterrows():
        g = r['gre']; m = r['mes']
        if g not in gre_pivot: gre_pivot[g] = {}
        gre_pivot[g][m] = {
            'total': int(r['total']), 'pct': float(r['pct'] or 0),
            'sem_rast': int(r['sem_rast'] or 0), 'suspeitas': int(r['suspeitas'] or 0),
            'anuladas': int(r['anuladas'] or 0)
        }

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
            if pct is None: h += "<td style='text-align:center;color:#334155'>—</td>"
            else: h += f"<td style='text-align:center;{cor_pct(pct)}'>{pct}%</td>"
        h += f"<td style='text-align:center'>{sem_rast:,}</td>"
        h += f"<td style='text-align:center;color:#f97316'>{suspeitas:,}</td>"
        h += f"<td><span class='tag {cls_status(cls)}'>{icon} {status}</span></td></tr>"
    return h

# ─── FUNÇÕES DE TABELAS ─────────────────────────────────────────────────────
def fmt(v):
    try: return f"{float(v):,.2f}".replace(",","X").replace(".",",").replace("X",".")
    except: return "0,00"

def html_fraude_emp():
    if df_fraude_emp.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    h = ""
    for _, r in df_fraude_emp.iterrows():
        pct = float(r.get('pct_susp') or 0)
        cls = "color:#ef4444;font-weight:700" if pct > 20 else ("color:#f97316" if pct > 10 else "")
        h += f"<tr><td><b>{r['empresa']}</b></td><td>{int(r['motoristas'])}</td>"
        h += f"<td>{int(r['total']):,}</td><td>{int(r.get('suspeitas',0)):,}</td>"
        h += f"<td style='{cls}'>{pct}%</td><td>{int(r.get('sem_rast',0)):,}</td></tr>"
    return h

def html_fraude_mot():
    if df_fraude_mot.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for _, r in df_fraude_mot.iterrows():
        pct = float(r.get('pct_susp') or 0)
        cls = "color:#ef4444;font-weight:700" if pct > 20 else ""
        h += f"<tr><td><b>{r['motorista']}</b></td><td>{r['empresa']}</td>"
        h += f"<td>{r.get('cidade','')}</td><td>{r.get('gre','')}</td>"
        h += f"<td>{int(r.get('suspeitas',0))}</td><td style='{cls}'>{pct}%</td>"
        h += f"<td>{int(r.get('sem_rast',0))}</td></tr>"
    return h

def html_contratos():
    if df_contratos.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    h = ""
    for _, r in df_contratos.iterrows():
        sv = "🔴 INATIVO" if r.get('sv') == 'I' else "🟡 SEM MOTORISTA"
        cor = "color:#ef4444" if r.get('sv') == 'I' else "color:#f59e0b"
        h += f"<tr><td>{r.get('gre','—')}</td><td><b>{r.get('placa','—')}</b></td>"
        h += f"<td>R$ {fmt(r.get('valor_unitario',0))}/dia</td><td>{r.get('turno','—')}</td>"
        h += f"<td style='{cor}'>{sv}</td><td style='text-align:center'>{int(r.get('esc30d',0))}</td></tr>"
    return h

def html_frota():
    if df_frota.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for _, r in df_frota.iterrows():
        tot = max(int(r.get('total',1)),1)
        pct_v = round(int(r.get('lic_venc',0))/tot*100)
        cls = "color:#ef4444;font-weight:700" if pct_v > 50 else ("color:#f97316" if pct_v > 20 else "")
        h += f"<tr><td><b>{r['fornecedor']}</b></td><td>{int(r.get('total',0))}</td>"
        h += f"<td>{int(r.get('ativos',0))}</td><td>{int(r.get('inativos',0))}</td>"
        h += f"<td style='{cls}'>{int(r.get('lic_venc',0))} ({pct_v}%)</td>"
        h += f"<td>{int(r.get('lic_ok',0))}</td><td>{int(r.get('multas',0))}</td></tr>"
    return h

def html_mot():
    if df_mot_rank.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    h = ""
    for _, r in df_mot_rank.iterrows():
        pct = float(r.get('pct_rast') or 0)
        cls = "color:#ef4444;font-weight:700" if pct < 20 else ("color:#f59e0b" if pct < 50 else "color:#22c55e")
        h += f"<tr><td><b>{r['nome']}</b></td><td>{r['empresa']}</td>"
        h += f"<td>{r.get('cidade','')}</td><td>{r.get('gre','')}</td>"
        h += f"<td>{int(r.get('total',0)):,}</td><td style='{cls}'>{pct}%</td>"
        h += f"<td style='{'color:#ef4444' if int(r.get('suspeitas',0))>5 else ''}'>{int(r.get('suspeitas',0))}</td>"
        h += f"<td>{int(r.get('sem_rast',0))}</td></tr>"
    return h

def html_abast():
    if df_abast.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    h = ""
    for _, r in df_abast.iterrows():
        h += f"<tr><td><b>{r['nome']}</b></td><td>{r['empresa']}</td>"
        h += f"<td>{r.get('cidade','')}</td><td>{r.get('gre','')}</td>"
        h += f"<td>{fmt(r.get('litros',0))} L</td><td>R$ {fmt(r.get('gasto',0))}</td>"
        h += f"<td>{int(r.get('escalas',0)):,}</td><td>R$ {fmt(r.get('rs_escala',0))}</td></tr>"
    return h

def html_fiscal():
    if df_fiscal.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    h = ""
    for _, r in df_fiscal.iterrows():
        q2 = float(r.get('pct_q2') or 0); q3 = float(r.get('pct_q3') or 0)
        icon, _, cls = tendencia([q2, q3])
        cls_badge = cls_status(cls)
        h += f"<tr><td><b>{r['gre']}</b></td><td>{r.get('fiscal','—')}</td>"
        h += f"<td style='text-align:center'>{int(r.get('total',0)):,}</td>"
        h += f"<td style='text-align:center;{cor_pct(q2)}'>{q2}%</td>"
        h += f"<td style='text-align:center'><span class='tag {cls_badge}'>{q3}% {icon}</span></td>"
        h += f"<td style='text-align:center;color:#f97316'>{int(r.get('suspeitas',0)):,}</td>"
        h += f"<td style='text-align:center'>{int(r.get('sem_rast',0)):,}</td></tr>"
    return h

def html_insights():
    if not cidade_scores: return "<tr><td colspan='9'>Sem dados</td></tr>"
    h = ""
    acoes = {
        'SEM REGISTRO': 'Notificação formal ao fornecedor + visita do coordenador com prazo de 15 dias',
        'REGREDIU TOTAL': 'Visita imediata + relatório ao gestor regional + prazo de regularização',
        'EM QUEDA FORTE': 'Reunião urgente com o fiscal responsável + cobrança formal',
        'EM QUEDA': 'Reunião com fiscal + prazo de 15 dias para recuperação',
        'ATENÇÃO': 'Monitoramento semanal + cobrança ao fiscal responsável',
        'MELHORANDO': 'Manter pressão. Reconhecer melhora na próxima reunião',
        'LEVE MELHORA': 'Continuar monitorando. Meta: superar 50% até fim do trimestre',
        'ESTÁVEL': 'Monitoramento padrão mensal',
    }
    for i, r in enumerate(cidade_scores[:25]):
        acao = acoes.get(r['status'], 'Avaliar individualmente')
        h += f"<tr><td style='text-align:center;font-weight:700'>#{i+1}</td>"
        h += f"<td><b>{r['cidade']}</b></td><td style='text-align:center'>{r['total']:,}</td>"
        for pct in r['vals']:
            if pct is None: h += "<td style='text-align:center;color:#334155'>—</td>"
            else: h += f"<td style='text-align:center;{cor_pct(pct)}'>{pct}%</td>"
        h += f"<td><span class='tag {cls_status(r[\"cls\"])}'>{r['icon']} {r['status']}</span></td>"
        h += f"<td style='font-size:11px;color:#94a3b8'>{acao}</td></tr>"
    return h

# ─── KPIs ───────────────────────────────────────────────────────────────────
kpi_total = int(df_kpi['total_escalas'].iloc[0]) if not df_kpi.empty else 0
kpi_rast = int(df_kpi['rastreado'].iloc[0]) if not df_kpi.empty else 0
kpi_sem = int(df_kpi['sem_rastreamento'].iloc[0]) if not df_kpi.empty else 0
kpi_susp = int(df_kpi['suspeitas'].iloc[0]) if not df_kpi.empty else 0
kpi_pct = round(kpi_rast/max(kpi_total,1)*100,1)
kpi_pct_susp = round(kpi_susp/max(kpi_total,1)*100,2)
kpi_cont = int(df_kpi_extra['contratos_risco'].iloc[0]) if not df_kpi_extra.empty else 0
kpi_ch = int(df_kpi_extra['chamados_abertos'].iloc[0]) if not df_kpi_extra.empty else 0
kpi_of = int(df_kpi_extra['em_oficina'].iloc[0]) if not df_kpi_extra.empty else 0

# Dados gráficos
meses_ev = df_evolucao['mes'].tolist() if not df_evolucao.empty else []
ev_tot = df_evolucao['total'].tolist() if not df_evolucao.empty else []
ev_rast = df_evolucao['rastreado'].tolist() if not df_evolucao.empty else []
ev_susp = df_evolucao['suspeitas'].tolist() if not df_evolucao.empty else []
ev_sem = df_evolucao['sem_rast'].tolist() if not df_evolucao.empty else []
ev_pct_rast = [round(n(r)/max(n(t),1)*100,1) for r,t in zip(ev_rast,ev_tot)]
ev_pct_susp = [round(n(s)/max(n(t),1)*100,2) for s,t in zip(ev_susp,ev_tot)]

cont_m = df_cont_mensal['mes'].tolist() if not df_cont_mensal.empty else []
cont_t = df_cont_mensal['total'].tolist() if not df_cont_mensal.empty else []
cont_a = df_cont_mensal['anuladas'].tolist() if not df_cont_mensal.empty else []
cont_s = df_cont_mensal['sem_rast'].tolist() if not df_cont_mensal.empty else []

fr_m = df_fraude_mensal['mes'].tolist() if not df_fraude_mensal.empty else []
fr_s = df_fraude_mensal['suspeitas'].tolist() if not df_fraude_mensal.empty else []
fr_sr = df_fraude_mensal['sem_rast'].tolist() if not df_fraude_mensal.empty else []

gerado = datetime.now().strftime("%d/%m/%Y %H:%M")

# ─── HTML FINAL ─────────────────────────────────────────────────────────────
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
.v-ok{{color:var(--ok)}}.v-wn{{color:var(--wn)}}.v-cr{{color:var(--cr)}}
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
.legenda-cores{{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:10px;font-size:10px}}
.lc{{padding:2px 8px;border-radius:3px;font-weight:700}}
.lc-cr{{background:rgba(239,68,68,.2);color:var(--cr)}}
.lc-or{{background:rgba(249,115,22,.2);color:var(--or)}}
.lc-wn{{background:rgba(245,158,11,.2);color:var(--wn)}}
.lc-ok{{background:rgba(34,197,94,.2);color:var(--ok)}}
.lc-nd{{background:rgba(100,116,139,.2);color:var(--mt)}}
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
</div>

<!-- ABA 1: PAINEL EXECUTIVO -->
<div id="t1" class="tab active">
  <div class="info">
    <b>📌 Como ler este painel:</b>
    <b>Com Rastreamento</b> = rota registrada via app ou link (GPS ativo).
    <b>Sem Rastreamento</b> = confirmada manualmente, sem GPS.
    <b>Rota Suspeita</b> = duração menor que 10 minutos (impossível para uma rota real).
  </div>
  <div class="kpi-grid">
    <div class="kpi"><label>Escalas no Mês Atual</label><div class="v">{kpi_total:,}</div></div>
    <div class="kpi"><label>Com Rastreamento</label><div class="v {'v-ok' if kpi_pct>=50 else 'v-wn' if kpi_pct>=30 else 'v-cr'}">{kpi_pct}%</div><div class="sub">{kpi_rast:,} escalas</div></div>
    <div class="kpi"><label>Sem Rastreamento</label><div class="v v-wn">{kpi_sem:,}</div><div class="sub">confirmadas manualmente</div></div>
    <div class="kpi"><label>Rotas Suspeitas (&lt;10min)</label><div class="v v-cr">{kpi_susp:,}</div><div class="sub">{kpi_pct_susp}% do total</div></div>
    <div class="kpi"><label>Contratos sem Operação</label><div class="v v-cr">{kpi_cont}</div><div class="sub">veículos sem motorista</div></div>
    <div class="kpi"><label>Chamados em Aberto</label><div class="v v-wn">{kpi_ch:,}</div></div>
    <div class="kpi"><label>Veículos em Oficina</label><div class="v v-wn">{kpi_of}</div></div>
  </div>
  <div class="g2">
    <div class="card"><h3>📈 Total de Escalas vs Rastreadas por Mês (2026)</h3><canvas id="c_esc"></canvas></div>
    <div class="card"><h3>📱 % Com Rastreamento vs % Rotas Suspeitas</h3><canvas id="c_pct"></canvas></div>
  </div>
  <div class="g2">
    <div class="card"><h3>🚫 Sem Rastreamento por Mês</h3><canvas id="c_sem"></canvas></div>
    <div class="card"><h3>📋 Escalas com Contrato por Mês</h3><canvas id="c_cont"></canvas></div>
  </div>
</div>

<!-- ABA 2: REGIONAIS (GRE) -->
<div id="t2" class="tab">
  <div class="info">
    <b>📌 Como ler:</b> Cada linha é uma Regional de Ensino (GRE). As colunas mostram o % de escalas
    com rastreamento ativo mês a mês. <b>Verde</b> = acima de 50%. <b>Laranja</b> = entre 15-50%.
    <b>Vermelho</b> = abaixo de 15%. A tendência compara o último mês com o anterior.
  </div>
  <div class="legenda-cores">
    <span class="lc lc-cr">0-14%: Crítico</span>
    <span class="lc lc-or">15-29%: Baixo</span>
    <span class="lc lc-wn">30-49%: Moderado</span>
    <span class="lc lc-ok">50%+: Adequado</span>
  </div>
  <div class="card">
    <h3>📊 Evolução do Rastreamento por Regional — Abr a Ago/2026</h3>
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
    <b>📌 Como ler:</b> Cada linha é um município. As colunas mostram o % de escalas com rastreamento
    por mês. A coluna <b>Situação</b> classifica automaticamente com base na evolução.
    <b>Rotas Suspeitas</b> = total de rotas com duração menor que 10 minutos no período.
    Cidades ordenadas pela prioridade de atenção (pior primeiro).
  </div>
  <div class="legenda-cores">
    <span class="lc lc-cr">0%: Sem registro</span>
    <span class="lc lc-or">1-14%: Crítico</span>
    <span class="lc lc-wn">15-29%: Baixo</span>
    <span class="lc lc-ok">50%+: Adequado</span>
  </div>
  <div class="card">
    <h3>🏙️ Rastreamento por Cidade — Histórico Mensal Abr a Ago/2026</h3>
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
    <b>⚠️ O que é uma Rota Suspeita?</b> Qualquer escala com início e fim de execução registrados,
    mas com duração menor que 10 minutos. Uma rota escolar real leva no mínimo 20-30 minutos.
    Rotas concluídas em menos de 10 minutos indicam abertura e fechamento irregular para registrar execução sem realizar a rota.
    <b>100% dos casos identificados são de prestadores terceirizados.</b>
  </div>
  <div class="card"><h3>📉 Evolução Mensal — Rotas Suspeitas e Sem Rastreamento</h3><canvas id="c_fr"></canvas></div>
  <div class="g2">
    <div class="card">
      <h3>🏢 Empresas com Maior % de Rotas Suspeitas</h3>
      <p class="desc">Empresas ordenadas pelo percentual de rotas suspeitas sobre o total de escalas.
      Percentual acima de 20% é considerado crítico e requer ação contratual imediata.</p>
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
    <b>⚠️ Contratos sem Operação:</b> Veículos com contrato ativo mas sem motorista associado
    e zero escalas nos últimos 30 dias. O valor informado é o valor diário do contrato —
    cada dia sem execução representa esse valor em risco de pagamento sem prestação de serviço.
  </div>
  <div class="g2">
    <div class="card"><h3>📈 Total de Escalas com Contrato — Abr a Ago/2026</h3><canvas id="c_ct2"></canvas></div>
    <div class="card"><h3>📊 Escalas com Contrato: Total vs Sem Rastreamento vs Anuladas</h3><canvas id="c_ct3"></canvas></div>
  </div>
  <div class="card">
    <h3>🚨 Veículos em Contrato Ativo sem Motorista (Zero Escalas em 30 dias)</h3>
    <input class="src" id="s_ct" oninput="fil('s_ct','t_ct')" placeholder="Filtrar por GRE, placa...">
    <div class="tw">
      <table id="t_ct">
        <thead><tr><th>Regional</th><th>Placa</th><th>Valor/Dia</th><th>Turno</th><th>Situação do Veículo</th><th style="text-align:center">Esc. 30d</th></tr></thead>
        <tbody>{html_contratos()}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ABA 6: FROTA -->
<div id="t6" class="tab">
  <div class="info">
    <b>📌 Licenciamento Vencido</b> = veículo com ano de licenciamento anterior a 2026.
    Veículo com licenciamento vencido não deveria estar em operação de transporte escolar.
    <b>Com Multas</b> = registro de multa ativa no cadastro do veículo.
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
      <p class="desc"><b>Chamados Abertos</b> = aguardando solução. <b>Em Oficina</b> = veículo parado para conserto.
      <b>Média de Dias</b> = tempo médio entre abertura do chamado e entrega do veículo.</p>
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
          <thead><tr><th>Placa</th><th>Fornecedor</th><th>GRE</th><th>Chamados</th><th>Abertos</th><th>Falha Hum.</th><th>Média Dias</th></tr></thead>
          <tbody>{''.join([f"<tr><td><b>{r['placa']}</b></td><td>{r['fornecedor']}</td><td>{r.get('gre','')}</td><td>{int(r.get('chamados',0))}</td><td style='{'color:#ef4444' if int(r.get('abertos',0))>3 else ''}'>{int(r.get('abertos',0))}</td><td style='{'color:#ef4444' if int(r.get('falha_hum',0))>0 else ''}'>{int(r.get('falha_hum',0))}</td><td>{r.get('media_dias',0)} dias</td></tr>" for _,r in df_veic_prob.iterrows()]) if not df_veic_prob.empty else "<tr><td colspan='7'>Sem dados</td></tr>"}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 7: MOTORISTAS -->
<div id="t7" class="tab">
  <div class="card">
    <h3>👤 Motoristas — % Com Rastreamento (piores primeiro, desde Abr/2026)</h3>
    <p class="desc">Motoristas com pelo menos 20 escalas no período. <b>% Com Rastreamento</b> = proporção de escalas
    registradas via app ou link. Abaixo de 20% em vermelho, 20-50% em laranja, acima de 50% em verde.
    <b>Rotas Suspeitas</b> = duração menor que 10 minutos. <b>Sem Rastreamento</b> = confirmação manual.</p>
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
    <b>🧠 Como funciona o Score de Prioridade:</b>
    Calculado automaticamente combinando quatro fatores:
    <b>índice atual de rastreamento</b> (peso 50%) +
    <b>queda em relação ao mês anterior</b> (peso 30%) +
    <b>% de rotas suspeitas</b> (peso 20%).
    Quanto maior o score, maior a urgência de intervenção. A <b>Ação Recomendada</b>
    é gerada automaticamente com base na situação classificada.
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
    <p class="desc">
      <b>Abr-Jun/26</b> = % de rastreamento no segundo trimestre.
      <b>Jul-Ago/26</b> = % atual. A tendência mostra se a área do fiscal está melhorando ou piorando.
      <b>Rotas Suspeitas</b> e <b>Sem Rastreamento</b> são totais acumulados desde abril.
    </p>
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
      <b style="color:var(--cr)">100% das irregularidades identificadas são de prestadores terceirizados.</b>
      Motoristas da frota própria (sem vínculo com fornecedor) apresentam irregularidade próxima de zero.
      Isso indica que o problema não é operacional — é estrutural no modelo de terceirização.<br><br>
      <b style="color:var(--wn)">Empresas com maior risco imediato:</b>
      J COUTINHO DE SOUSA FILHO (97% de rotas suspeitas) · ANTONIO CARLOS REIS SARAIVA (74%) · INES DE SALES RESENDE (59%).<br><br>
      <b style="color:var(--ac)">Recomendação estratégica:</b>
      Incluir cláusula contratual vinculando pagamento ao índice mínimo de rastreamento (sugerido: 60%).
      Prestadores abaixo desse índice por dois meses consecutivos devem receber notificação formal
      com prazo de 30 dias para adequação, seguida de processo de glosa caso não haja melhora.
    </p>
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
    type:'line',data:{{labels,datasets}},
    options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#94a3b8',font:{{size:11}}}}}}}},
      scales:{{x:{{ticks:{{color:'#64748b',font:{{size:10}}}}}},y:{{ticks:{{color:'#64748b',font:{{size:10}}}}}}}}}}
  }}),
  bar:(id,labels,datasets)=>new Chart(document.getElementById(id),{{
    type:'bar',data:{{labels,datasets}},
    options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#94a3b8',font:{{size:11}}}}}}}},
      scales:{{x:{{ticks:{{color:'#64748b',font:{{size:10}}}}}},y:{{ticks:{{color:'#64748b',font:{{size:10}}}}}}}}}}
  }})
}};

const m={jd(meses_ev)},tot={jd(ev_tot)},rast={jd(ev_rast)},
      pct_r={jd(ev_pct_rast)},pct_s={jd(ev_pct_susp)},sem_r={jd(ev_sem)};

C.bar('c_esc',m,[
  {{label:'Total',data:tot,backgroundColor:'rgba(56,189,248,.25)',borderColor:'#38bdf8',borderWidth:1}},
  {{label:'Com Rastreamento',data:rast,backgroundColor:'rgba(34,197,94,.3)',borderColor:'#22c55e',borderWidth:1}}
]);
C.line('c_pct',m,[
  {{label:'% Com Rastreamento',data:pct_r,borderColor:'#22c55e',backgroundColor:'rgba(34,197,94,.08)',fill:true,tension:.3}},
  {{label:'% Rotas Suspeitas',data:pct_s,borderColor:'#ef4444',backgroundColor:'rgba(239,68,68,.08)',fill:true,tension:.3}}
]);
C.bar('c_sem',m,[{{label:'Sem Rastreamento',data:sem_r,backgroundColor:'rgba(245,158,11,.35)',borderColor:'#f59e0b',borderWidth:1}}]);

const cm={jd(cont_m)},ct={jd(cont_t)},ca={jd(cont_a)},cs={jd(cont_s)};
C.line('c_ct2',cm,[{{label:'Escalas c/ Contrato',data:ct,borderColor:'#a78bfa',backgroundColor:'rgba(167,139,250,.08)',fill:true,tension:.3}}]);
C.bar('c_ct3',cm,[
  {{label:'Total',data:ct,backgroundColor:'rgba(56,189,248,.25)',borderColor:'#38bdf8',borderWidth:1}},
  {{label:'Sem Rastreamento',data:cs,backgroundColor:'rgba(245,158,11,.35)',borderColor:'#f59e0b',borderWidth:1}},
  {{label:'Anuladas',data:ca,backgroundColor:'rgba(239,68,68,.25)',borderColor:'#ef4444',borderWidth:1}}
]);
C.line('c_fr',{jd(fr_m)},[
  {{label:'Rotas Suspeitas (<10min)',data:{jd(fr_s)},borderColor:'#ef4444',backgroundColor:'rgba(239,68,68,.08)',fill:true,tension:.3}},
  {{label:'Sem Rastreamento',data:{jd(fr_sr)},borderColor:'#f59e0b',backgroundColor:'rgba(245,158,11,.08)',fill:true,tension:.3}}
]);

// Gráfico GRE
const gd={jd(df_gre_hist.to_dict('records') if not df_gre_hist.empty else [])};
const gmu=[...new Set(gd.map(r=>r.mes))].sort();
const gns=[...new Set(gd.map(r=>r.gre))];
const cs2=['#38bdf8','#22c55e','#f59e0b','#ef4444','#a78bfa','#f97316','#06b6d4','#84cc16','#ec4899','#14b8a6'];
C.line('c_gre',gmu,gns.map((g,i)=>{{
  const mp={{}};
  gd.filter(r=>r.gre===g).forEach(r=>mp[r.mes]=r.pct);
  return{{label:g,data:gmu.map(m=>mp[m]||0),borderColor:cs2[i%cs2.length],backgroundColor:'transparent',tension:.3,borderWidth:2}};
}}));
</script>
</body>
</html>"""

