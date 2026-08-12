import psycopg2
import pandas as pd
import json
import re
from datetime import datetime

HOST = "aws-0-sa-east-1.pooler.supabase.com"
PORT = 5432
DATABASE = "postgres"
USER = "analista_bi.cuofycgznnbtpotybpuu"
PASSWORD = "marvao#37m"

try:
    conn = psycopg2.connect(host=HOST, port=PORT, database=DATABASE, user=USER, password=PASSWORD)
    print("Conectado ao banco com sucesso.")
except Exception as e:
    print(f"Erro ao conectar: {e}")
    raise e

def safe_read(query, default=None):
    try:
        return pd.read_sql(query, conn)
    except Exception as err:
        print(f"Erro na query: {err}")
        return pd.DataFrame() if default is None else default

def jdumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)

def fmt_br(v):
    try: return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "0,00"

def badge(valor, limiar_verde=70, limiar_amarelo=40):
    try:
        v = float(valor)
        if v >= limiar_verde: return "badge-ok"
        elif v >= limiar_amarelo: return "badge-warn"
        else: return "badge-crit"
    except: return "badge-crit"

def tendencia(q2, q3):
    try:
        diff = float(q3) - float(q2)
        if diff >= 5: return ("⬆️", "EVOLUINDO", "status-ok")
        elif diff <= -5: return ("⬇️", "REGREDINDO", "status-crit")
        else: return ("➡️", "ESTÁVEL", "status-warn")
    except: return ("❓", "S/DADOS", "status-nd")

# ─────────────────────────────────────────────
# 1. PAINEL EXECUTIVO — KPIs
# ─────────────────────────────────────────────
df_kpi = safe_read("""
SELECT
    COUNT(*) as total_escalas,
    COUNT(*) FILTER (WHERE via_app = true) as via_app,
    COUNT(*) FILTER (WHERE via_app = false AND confirmado_manualmente = true) as manual_sem_gps,
    COUNT(*) FILTER (WHERE anulada = true) as anuladas,
    COUNT(*) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) as fraude_tempo
FROM airbyte.rotas_escalarota
WHERE data >= DATE_TRUNC('month', CURRENT_DATE)
""")

df_kpi_contratos = safe_read("""
SELECT COUNT(DISTINCT ci.id) as contratos_sem_operacao
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c ON ci.contrato_id = c.id
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
LEFT JOIN airbyte.motoristas_motorista m ON m.veiculo_id = v.id AND m.status = 'A'
WHERE c.status = 'A' AND ci.status = 'ATIVO' AND m.id IS NULL
""")

df_kpi_manut = safe_read("""
SELECT
    COUNT(*) FILTER (WHERE status = 'CA') as em_aberto,
    COUNT(*) FILTER (WHERE status = 'CO') as em_oficina
FROM airbyte.ordens_chamado
WHERE emissao >= '2026-01-01'
""")

df_evolucao = safe_read("""
SELECT
    TO_CHAR(data, 'YYYY-MM') as mes,
    COUNT(*) as total,
    COUNT(*) FILTER (WHERE via_app = true) as via_app,
    COUNT(*) FILTER (WHERE via_app = false AND confirmado_manualmente = true) as manual_gps,
    COUNT(*) FILTER (WHERE anulada = true) as anuladas,
    COUNT(*) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) as fraude_tempo
FROM airbyte.rotas_escalarota
WHERE data >= '2026-01-01' AND data IS NOT NULL
GROUP BY TO_CHAR(data, 'YYYY-MM')
ORDER BY mes
""")

# ─────────────────────────────────────────────
# 2. ASSIDUIDADE POR GRE
# ─────────────────────────────────────────────
df_gre_assid = safe_read("""
SELECT
    g.nome as gre,
    COUNT(e.id) as total_escalas,
    COUNT(e.id) FILTER (WHERE e.via_app = true) as via_app,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as manual_gps,
    COUNT(e.id) FILTER (WHERE e.anulada = true) as anuladas,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true) * 100.0 / NULLIF(COUNT(e.id),0),1) as pct_app,
    -- Q2 vs Q3
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data BETWEEN '2026-04-01' AND '2026-06-30')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data BETWEEN '2026-04-01' AND '2026-06-30'),0),1) as pct_q2,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data >= '2026-07-01')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-07-01'),0),1) as pct_q3
FROM airbyte.rotas_escalarota e
JOIN airbyte.rotas_rota r ON r.id = e.rota_id
JOIN airbyte.escolas_gre g ON g.id = r.gre_id
WHERE e.data >= '2026-01-01'
GROUP BY g.nome
ORDER BY pct_app ASC
""")

df_gre_mensal = safe_read("""
SELECT
    g.nome as gre,
    TO_CHAR(e.data, 'YYYY-MM') as mes,
    COUNT(e.id) as total,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true) * 100.0 / NULLIF(COUNT(e.id),0),1) as pct_app
FROM airbyte.rotas_escalarota e
JOIN airbyte.rotas_rota r ON r.id = e.rota_id
JOIN airbyte.escolas_gre g ON g.id = r.gre_id
WHERE e.data >= '2026-01-01'
GROUP BY g.nome, TO_CHAR(e.data, 'YYYY-MM')
ORDER BY g.nome, mes
""")

# ─────────────────────────────────────────────
# 3. CIDADES QUE NÃO REGISTRAM
# ─────────────────────────────────────────────
df_cidades = safe_read("""
SELECT
    m.cidade,
    COUNT(DISTINCT m.id) as motoristas,
    COUNT(e.id) as total_escalas,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true) * 100.0 / NULLIF(COUNT(e.id),0),1) as pct_app,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data BETWEEN '2026-04-01' AND '2026-06-30')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data BETWEEN '2026-04-01' AND '2026-06-30'),0),1) as pct_q2,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data >= '2026-07-01')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-07-01'),0),1) as pct_q3,
    ROUND(COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
        AND e.data >= '2026-01-01'
    ) * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-01-01'),0),1) as pct_fraude,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true AND e.data >= '2026-01-01') as manuais_gps
FROM airbyte.motoristas_motorista m
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE m.status = 'A' AND m.cidade IS NOT NULL AND e.data >= '2026-01-01'
GROUP BY m.cidade
HAVING COUNT(e.id) >= 100
ORDER BY pct_q3 ASC, pct_fraude DESC
LIMIT 30
""")

# ─────────────────────────────────────────────
# 4. FRAUDE & IRREGULARIDADE
# ─────────────────────────────────────────────
df_fraude_mensal = safe_read("""
SELECT
    TO_CHAR(data, 'YYYY-MM') as mes,
    COUNT(*) FILTER (WHERE inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL) as com_horario,
    COUNT(*) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) as menos_10min,
    COUNT(*) FILTER (WHERE via_app = false AND confirmado_manualmente = true) as manuais_gps,
    ROUND(COUNT(*) FILTER (WHERE
        inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (fim_execucao::timestamp - inicio_execucao::timestamp))/60 < 10
    ) * 100.0 / NULLIF(COUNT(*) FILTER (WHERE inicio_execucao IS NOT NULL AND fim_execucao IS NOT NULL),0),2) as pct_fraude
FROM airbyte.rotas_escalarota
WHERE data >= '2026-01-01'
GROUP BY TO_CHAR(data, 'YYYY-MM')
ORDER BY mes
""")

df_fraude_empresas = safe_read("""
SELECT
    COALESCE(f.nome, 'SEM FORNECEDOR') as empresa,
    COUNT(DISTINCT m.id) as motoristas,
    COUNT(e.id) as total_escalas,
    COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) as fraude_tempo,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as manuais_gps,
    ROUND(COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) * 100.0 / NULLIF(COUNT(e.id),0),2) as pct_fraude
FROM airbyte.motoristas_fornecedor f
JOIN airbyte.motoristas_motorista m ON m.fornecedor_id = f.id
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE e.data >= '2026-01-01' AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL
GROUP BY f.nome
HAVING COUNT(e.id) >= 20
ORDER BY pct_fraude DESC
LIMIT 15
""")

df_fraude_motoristas = safe_read("""
SELECT
    m.nome as motorista,
    COALESCE(f.nome, 'PRÓPRIO') as empresa,
    m.cidade,
    g.nome as gre,
    COUNT(e.id) as total_escalas,
    COUNT(e.id) FILTER (WHERE
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) as fraude_tempo,
    ROUND(COUNT(e.id) FILTER (WHERE
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) * 100.0 / NULLIF(COUNT(e.id),0),1) as pct_fraude,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as manuais_gps
FROM airbyte.motoristas_motorista m
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status = 'A' AND e.data >= '2026-01-01'
    AND e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL
GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COUNT(e.id) >= 10
ORDER BY pct_fraude DESC
LIMIT 20
""")

# ─────────────────────────────────────────────
# 5. CONTRATOS VS EXECUÇÃO
# ─────────────────────────────────────────────
df_contratos_risco = safe_read("""
SELECT
    ci.id as item_contrato,
    g.nome as gre,
    ci.valor_unitario,
    v.placa,
    v.status as status_veiculo,
    COALESCE(ct.nome, 'Não def.') as turno,
    (SELECT COUNT(*) FROM airbyte.rotas_escalarota e2
     WHERE e2.veiculo_id = v.id AND e2.data >= CURRENT_DATE - INTERVAL '30 days'
     AND e2.anulada = false) as escalas_30d
FROM airbyte.contratos_itemcontrato ci
JOIN airbyte.contratos_contrato c ON ci.contrato_id = c.id
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = ci.veiculo_id
LEFT JOIN airbyte.motoristas_motorista m ON m.veiculo_id = v.id AND m.status = 'A'
LEFT JOIN airbyte.contratos_itemcontrato_turnos cit ON cit.itemcontrato_id = ci.id
LEFT JOIN airbyte.contratos_turno ct ON ct.id = cit.turno_id
LEFT JOIN airbyte.escolas_gre g ON g.id = ci.gre_id
WHERE c.status = 'A' AND ci.status = 'ATIVO' AND m.id IS NULL
ORDER BY ci.valor_unitario DESC
LIMIT 50
""")

df_contratos_mensal = safe_read("""
SELECT
    TO_CHAR(e.data, 'YYYY-MM') as mes,
    COUNT(e.id) as escalas_com_contrato,
    COUNT(e.id) FILTER (WHERE e.anulada = true) as anuladas,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as manuais
FROM airbyte.rotas_escalarota e
WHERE e.contrato_rota_id IS NOT NULL AND e.data >= '2026-01-01'
GROUP BY TO_CHAR(e.data, 'YYYY-MM')
ORDER BY mes
""")

# ─────────────────────────────────────────────
# 6. FROTA & DOCUMENTAÇÃO
# ─────────────────────────────────────────────
df_frota_doc = safe_read("""
SELECT
    COALESCE(f.nome, 'SEM FORNECEDOR') as fornecedor,
    COUNT(DISTINCT v.id) as total_veiculos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'A') as ativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.status = 'I') as inativos,
    COUNT(DISTINCT v.id) FILTER (WHERE v.multas = true) as com_multas,
    COUNT(DISTINCT v.id) FILTER (WHERE v.licenciamento::int < 2026) as lic_vencido,
    COUNT(DISTINCT v.id) FILTER (WHERE v.licenciamento::int >= 2026) as lic_ok
FROM airbyte.motoristas_fornecedor f
JOIN airbyte.veiculos_veiculo v ON v.fornecedor_id = f.id
WHERE v.licenciamento IS NOT NULL
GROUP BY f.nome
HAVING COUNT(DISTINCT v.id) >= 2
ORDER BY lic_vencido DESC
LIMIT 15
""")

df_veiculos_problema = safe_read("""
SELECT
    v.placa,
    v.modelo,
    v.tipo_contrato_locacao,
    COALESCE(f.nome, 'SEM FORNECEDOR') as fornecedor,
    g.nome as gre,
    COUNT(c.id) as total_chamados,
    COUNT(c.id) FILTER (WHERE c.status = 'CA') as em_aberto,
    COUNT(c.id) FILTER (WHERE c.falha_humana = true) as falha_humana,
    ROUND(AVG(
        CASE WHEN c.entrega IS NOT NULL AND c.emissao IS NOT NULL
        THEN EXTRACT(EPOCH FROM (c.entrega - c.emissao))/86400 END
    )::numeric, 1) as media_dias_parado
FROM airbyte.veiculos_veiculo v
JOIN airbyte.ordens_chamado c ON c.veiculo_id = v.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = v.gre_id
WHERE c.emissao >= '2026-01-01'
GROUP BY v.placa, v.modelo, v.tipo_contrato_locacao, f.nome, g.nome
HAVING COUNT(c.id) >= 5
ORDER BY total_chamados DESC
LIMIT 15
""")

df_manut_fornecedor = safe_read("""
SELECT
    COALESCE(f.nome, 'SEM FORNECEDOR') as fornecedor,
    COUNT(DISTINCT c.id) as total_chamados,
    COUNT(DISTINCT c.id) FILTER (WHERE c.status = 'CA') as em_aberto,
    COUNT(DISTINCT c.id) FILTER (WHERE c.status = 'CO') as em_oficina,
    COUNT(DISTINCT c.veiculo_id) as veiculos_afetados,
    ROUND(AVG(
        CASE WHEN c.entrega IS NOT NULL AND c.emissao IS NOT NULL
        THEN EXTRACT(EPOCH FROM (c.entrega - c.emissao))/86400 END
    )::numeric, 1) as media_dias_parado
FROM airbyte.ordens_chamado c
JOIN airbyte.veiculos_veiculo v ON v.id = c.veiculo_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = v.fornecedor_id
WHERE c.emissao >= '2026-01-01'
GROUP BY f.nome
ORDER BY em_aberto DESC, total_chamados DESC
LIMIT 12
""")

# ─────────────────────────────────────────────
# 7. MOTORISTAS & EMPRESAS
# ─────────────────────────────────────────────
df_motoristas_rank = safe_read("""
SELECT
    m.nome as motorista,
    COALESCE(f.nome, 'PRÓPRIO') as empresa,
    m.cidade,
    g.nome as gre,
    COUNT(e.id) as total_escalas,
    COUNT(e.id) FILTER (WHERE e.via_app = true) as via_app,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true) * 100.0 / NULLIF(COUNT(e.id),0),1) as pct_app,
    COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
    ) as fraude_tempo,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true) as manuais_gps
FROM airbyte.motoristas_motorista m
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status = 'A' AND e.data >= '2026-01-01'
GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COUNT(e.id) >= 20
ORDER BY pct_app ASC
LIMIT 30
""")

df_motoristas_chamados = safe_read("""
SELECT
    m.nome as motorista,
    COALESCE(f.nome, 'PRÓPRIO') as empresa,
    g.nome as gre,
    COUNT(c.id) as total_chamados,
    COUNT(c.id) FILTER (WHERE c.falha_humana = true) as falha_humana,
    COUNT(c.id) FILTER (WHERE c.status = 'CA') as em_aberto
FROM airbyte.ordens_chamado c
JOIN airbyte.motoristas_motorista m ON m.id = c.motorista_id
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE c.emissao >= '2026-01-01'
GROUP BY m.nome, f.nome, g.nome
HAVING COUNT(c.id) >= 3
ORDER BY total_chamados DESC
LIMIT 15
""")

df_abastecimento_motorista = safe_read("""
SELECT
    m.nome as motorista,
    COALESCE(f.nome, 'PRÓPRIO') as empresa,
    m.cidade,
    g.nome as gre,
    COUNT(DISTINCT a.id) as abastecimentos,
    COALESCE(SUM(a.litros), 0) as total_litros,
    COALESCE(SUM(a.valor_total), 0) as total_gasto,
    COUNT(DISTINCT e.id) as escalas_executadas,
    CASE WHEN COUNT(DISTINCT e.id) > 0
        THEN ROUND(COALESCE(SUM(a.valor_total),0) / COUNT(DISTINCT e.id), 2)
        ELSE 0
    END as custo_por_escala
FROM airbyte.motoristas_motorista m
LEFT JOIN airbyte.abastecimentos_abastecimento a ON a.motorista_id = m.id
    AND a.datetime_abastecimento >= '2026-01-01'
    AND a.litros <= 1000
LEFT JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
    AND e.data >= '2026-01-01' AND e.anulada = false
LEFT JOIN airbyte.motoristas_fornecedor f ON f.id = m.fornecedor_id
LEFT JOIN airbyte.escolas_gre g ON g.id = m.gre_id
WHERE m.status = 'A'
GROUP BY m.nome, f.nome, m.cidade, g.nome
HAVING COALESCE(SUM(a.litros), 0) > 0 AND COALESCE(SUM(a.litros), 0) <= 50000
ORDER BY total_gasto DESC
LIMIT 20
""")

# ─────────────────────────────────────────────
# 8. INSIGHTS — SCORE DE GARGALO
# ─────────────────────────────────────────────
df_insights_cidade = safe_read("""
SELECT
    m.cidade,
    COUNT(DISTINCT m.id) as motoristas,
    COUNT(e.id) as total_escalas,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data BETWEEN '2026-04-01' AND '2026-06-30')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data BETWEEN '2026-04-01' AND '2026-06-30'),0),1) as pct_q2,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data >= '2026-07-01')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-07-01'),0),1) as pct_q3,
    ROUND(COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
        AND e.data >= '2026-01-01'
    ) * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-01-01'),0),1) as pct_fraude,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true
        AND e.data >= '2026-01-01') as manuais_gps
FROM airbyte.motoristas_motorista m
JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
WHERE m.status = 'A' AND m.cidade IS NOT NULL AND e.data >= '2026-01-01'
GROUP BY m.cidade
HAVING COUNT(e.id) >= 100
ORDER BY pct_q3 ASC
LIMIT 30
""")

df_insights_fiscal = safe_read("""
SELECT
    g.nome as gre,
    func.nome as fiscal,
    COUNT(e.id) as total_escalas,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true) * 100.0 / NULLIF(COUNT(e.id),0),1) as pct_app,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data BETWEEN '2026-04-01' AND '2026-06-30')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data BETWEEN '2026-04-01' AND '2026-06-30'),0),1) as pct_q2,
    ROUND(COUNT(e.id) FILTER (WHERE e.via_app = true AND e.data >= '2026-07-01')
        * 100.0 / NULLIF(COUNT(e.id) FILTER (WHERE e.data >= '2026-07-01'),0),1) as pct_q3,
    COUNT(e.id) FILTER (WHERE
        e.inicio_execucao IS NOT NULL AND e.fim_execucao IS NOT NULL AND
        EXTRACT(EPOCH FROM (e.fim_execucao::timestamp - e.inicio_execucao::timestamp))/60 < 10
        AND e.data >= '2026-01-01'
    ) as fraude_tempo,
    COUNT(e.id) FILTER (WHERE e.via_app = false AND e.confirmado_manualmente = true
        AND e.data >= '2026-01-01') as manuais_gps
FROM airbyte.rotas_escalarota e
JOIN airbyte.rotas_rota r ON r.id = e.rota_id
JOIN airbyte.escolas_gre g ON g.id = r.gre_id
LEFT JOIN airbyte.motoristas_funcionario func ON func.id = g.fiscal_responsavel_id
WHERE e.data >= '2026-01-01'
GROUP BY g.nome, func.nome
ORDER BY pct_q3 ASC
""")

conn.close()
print("Queries executadas. Gerando HTML...")

# ─────────────────────────────────────────────
# CALCULAR SCORES DE GARGALO
# ─────────────────────────────────────────────
def calcular_score(pct_q3, pct_q2, pct_fraude, manuais, total):
    try:
        p3 = float(pct_q3) if pct_q3 is not None else 0
        p2 = float(pct_q2) if pct_q2 is not None else 0
        fr = float(pct_fraude) if pct_fraude is not None else 0
        mn = float(manuais) if manuais is not None else 0
        tot = float(total) if total is not None else 1
        score = (100 - p3) * 0.4 + max(0, p2 - p3) * 0.3 + fr * 0.2 + (mn / tot * 100) * 0.1
        return round(score, 1)
    except:
        return 0

def classificar(pct_q2, pct_q3, pct_fraude):
    try:
        q2, q3 = float(pct_q2 or 0), float(pct_q3 or 0)
        fr = float(pct_fraude or 0)
        diff = q3 - q2
        if q3 == 0 and q2 == 0: return ("⚫", "NUNCA ADERIU", "class-nunca")
        if q3 == 0 and q2 > 0: return ("🔴", "REGREDIU TOTAL", "class-crit")
        if diff <= -10: return ("🔴", "REGREDINDO", "class-crit")
        if diff <= -5: return ("🟠", "ATENÇÃO", "class-warn")
        if diff >= 5: return ("🟢", "EVOLUINDO", "class-ok")
        if q3 >= 50: return ("🟢", "ESTÁVEL BOM", "class-ok")
        return ("🟡", "ESTÁVEL BAIXO", "class-warn")
    except:
        return ("❓", "S/DADOS", "class-nd")

rows_insights = []
if not df_insights_cidade.empty:
    for _, r in df_insights_cidade.iterrows():
        score = calcular_score(r.get('pct_q3'), r.get('pct_q2'), r.get('pct_fraude'), r.get('manuais_gps'), r.get('total_escalas'))
        icon, status, cls = classificar(r.get('pct_q2'), r.get('pct_q3'), r.get('pct_fraude'))
        rows_insights.append({
            'cidade': r['cidade'],
            'motoristas': r['motoristas'],
            'total_escalas': r['total_escalas'],
            'pct_q2': r.get('pct_q2') or 0,
            'pct_q3': r.get('pct_q3') or 0,
            'pct_fraude': r.get('pct_fraude') or 0,
            'manuais_gps': r.get('manuais_gps') or 0,
            'score': score,
            'icon': icon,
            'status': status,
            'cls': cls
        })
    rows_insights.sort(key=lambda x: -x['score'])

# ─────────────────────────────────────────────
# PREPARAR DADOS PARA GRÁFICOS
# ─────────────────────────────────────────────
meses = df_evolucao['mes'].tolist() if not df_evolucao.empty else []
ev_total = df_evolucao['total'].tolist() if not df_evolucao.empty else []
ev_app = df_evolucao['via_app'].tolist() if not df_evolucao.empty else []
ev_fraude = df_evolucao['fraude_tempo'].tolist() if not df_evolucao.empty else []
ev_manual = df_evolucao['manual_gps'].tolist() if not df_evolucao.empty else []

ev_pct_app = []
ev_pct_fraude = []
for i, row in df_evolucao.iterrows():
    tot = row['total'] or 1
    with_h = row.get('via_app') or 0
    frd = row.get('fraude_tempo') or 0
    ev_pct_app.append(round(with_h / tot * 100, 1))
    ev_pct_fraude.append(round(frd / tot * 100, 2))

kpi_total = int(df_kpi['total_escalas'].iloc[0]) if not df_kpi.empty else 0
kpi_app = int(df_kpi['via_app'].iloc[0]) if not df_kpi.empty else 0
kpi_manual = int(df_kpi['manual_sem_gps'].iloc[0]) if not df_kpi.empty else 0
kpi_fraude = int(df_kpi['fraude_tempo'].iloc[0]) if not df_kpi.empty else 0
kpi_contratos = int(df_kpi_contratos['contratos_sem_operacao'].iloc[0]) if not df_kpi_contratos.empty else 0
kpi_manut_aberto = int(df_kpi_manut['em_aberto'].iloc[0]) if not df_kpi_manut.empty else 0
kpi_manut_oficina = int(df_kpi_manut['em_oficina'].iloc[0]) if not df_kpi_manut.empty else 0
kpi_pct_app = round(kpi_app / max(kpi_total, 1) * 100, 1)
kpi_pct_fraude = round(kpi_fraude / max(kpi_total, 1) * 100, 2)

# ─────────────────────────────────────────────
# GERAR LINHAS DAS TABELAS
# ─────────────────────────────────────────────
def rows_gre(df):
    if df.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        q2, q3 = r.get('pct_q2') or 0, r.get('pct_q3') or 0
        icon, _, _ = tendencia(q2, q3)
        b = badge(r.get('pct_app') or 0)
        html += f"""<tr>
            <td><b>{r['gre']}</b></td>
            <td>{int(r['total_escalas']):,}</td>
            <td><span class="tag {b}">{r.get('pct_app') or 0}%</span></td>
            <td>{r.get('pct_q2') or 0}%</td>
            <td>{r.get('pct_q3') or 0}% {icon}</td>
            <td>{int(r.get('manual_gps') or 0):,}</td>
            <td>{int(r.get('anuladas') or 0):,}</td>
        </tr>"""
    return html

def rows_cidades(df):
    if df.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        icon, status, cls = classificar(r.get('pct_q2'), r.get('pct_q3'), r.get('pct_fraude'))
        html += f"""<tr>
            <td><b>{r['cidade']}</b></td>
            <td>{int(r['motoristas'])}</td>
            <td>{int(r['total_escalas']):,}</td>
            <td>{r.get('pct_q2') or 0}%</td>
            <td>{r.get('pct_q3') or 0}%</td>
            <td class="{'text-red' if float(r.get('pct_fraude') or 0) > 5 else ''}">{r.get('pct_fraude') or 0}%</td>
            <td>{int(r.get('manuais_gps') or 0):,}</td>
            <td><span class="tag {cls.replace('class-','badge-')}">{icon} {status}</span></td>
        </tr>"""
    return html

def rows_fraude_emp(df):
    if df.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        pct = float(r.get('pct_fraude') or 0)
        cls = "text-red" if pct > 20 else ("text-orange" if pct > 10 else "")
        html += f"""<tr>
            <td><b>{r['empresa']}</b></td>
            <td>{int(r['motoristas'])}</td>
            <td>{int(r['total_escalas']):,}</td>
            <td class="{cls}">{int(r.get('fraude_tempo') or 0):,}</td>
            <td class="{cls}">{r.get('pct_fraude') or 0}%</td>
            <td>{int(r.get('manuais_gps') or 0):,}</td>
        </tr>"""
    return html

def rows_fraude_mot(df):
    if df.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        pct = float(r.get('pct_fraude') or 0)
        cls = "text-red" if pct > 20 else ""
        html += f"""<tr>
            <td><b>{r['motorista']}</b></td>
            <td>{r['empresa']}</td>
            <td>{r['cidade']}</td>
            <td>{r['gre']}</td>
            <td>{int(r.get('fraude_tempo') or 0)}</td>
            <td class="{cls}">{r.get('pct_fraude') or 0}%</td>
            <td>{int(r.get('manuais_gps') or 0)}</td>
        </tr>"""
    return html

def rows_contratos(df):
    if df.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    # deduplicar por item_contrato (pode aparecer em múltiplos turnos)
    seen = set()
    html = ""
    for _, r in df.iterrows():
        key = str(r['item_contrato'])
        if key in seen: continue
        seen.add(key)
        sv = "🔴 INATIVO" if r.get('status_veiculo') == 'I' else "🟡 SEM MOTORISTA"
        html += f"""<tr>
            <td>{r['gre']}</td>
            <td>{r.get('placa','—')}</td>
            <td>R$ {fmt_br(r.get('valor_unitario',0))}/dia</td>
            <td>{r.get('turno','—')}</td>
            <td><span class="tag badge-crit">{sv}</span></td>
            <td>{int(r.get('escalas_30d',0))}</td>
        </tr>"""
    return html

def rows_frota_doc(df):
    if df.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        tot = max(int(r.get('total_veiculos') or 1), 1)
        pct_v = round(int(r.get('lic_vencido') or 0) / tot * 100)
        cls = "text-red" if pct_v > 50 else ("text-orange" if pct_v > 20 else "")
        html += f"""<tr>
            <td><b>{r['fornecedor']}</b></td>
            <td>{int(r.get('total_veiculos') or 0)}</td>
            <td>{int(r.get('ativos') or 0)}</td>
            <td>{int(r.get('inativos') or 0)}</td>
            <td class="{cls}">{int(r.get('lic_vencido') or 0)} ({pct_v}%)</td>
            <td>{int(r.get('lic_ok') or 0)}</td>
            <td>{int(r.get('com_multas') or 0)}</td>
        </tr>"""
    return html

def rows_veiculos_prob(df):
    if df.empty: return "<tr><td colspan='9'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        html += f"""<tr>
            <td><b>{r['placa']}</b></td>
            <td>{r['modelo']}</td>
            <td>{r['fornecedor']}</td>
            <td>{r['gre']}</td>
            <td>{int(r.get('total_chamados') or 0)}</td>
            <td class="{'text-red' if int(r.get('em_aberto') or 0) > 3 else ''}">{int(r.get('em_aberto') or 0)}</td>
            <td>{int(r.get('falha_humana') or 0)}</td>
            <td>{r.get('media_dias_parado') or 0} dias</td>
        </tr>"""
    return html

def rows_motoristas(df):
    if df.empty: return "<tr><td colspan='8'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        pct = float(r.get('pct_app') or 0)
        cls = badge(pct)
        html += f"""<tr>
            <td><b>{r['motorista']}</b></td>
            <td>{r['empresa']}</td>
            <td>{r['cidade']}</td>
            <td>{r['gre']}</td>
            <td>{int(r.get('total_escalas') or 0):,}</td>
            <td><span class="tag {cls}">{pct}%</span></td>
            <td class="{'text-red' if int(r.get('fraude_tempo') or 0) > 5 else ''}">{int(r.get('fraude_tempo') or 0)}</td>
            <td>{int(r.get('manuais_gps') or 0)}</td>
        </tr>"""
    return html

def rows_abast(df):
    if df.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        html += f"""<tr>
            <td><b>{r['motorista']}</b></td>
            <td>{r['empresa']}</td>
            <td>{r['cidade']}</td>
            <td>{r['gre']}</td>
            <td>{int(r.get('abastecimentos') or 0)}</td>
            <td>{fmt_br(r.get('total_litros',0))} L</td>
            <td>R$ {fmt_br(r.get('total_gasto',0))}</td>
            <td>{int(r.get('escalas_executadas') or 0):,}</td>
            <td>R$ {fmt_br(r.get('custo_por_escala',0))}</td>
        </tr>"""
    return html

def rows_mot_chamados(df):
    if df.empty: return "<tr><td colspan='6'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        html += f"""<tr>
            <td><b>{r['motorista']}</b></td>
            <td>{r['empresa']}</td>
            <td>{r['gre']}</td>
            <td>{int(r.get('total_chamados') or 0)}</td>
            <td class="{'text-red' if int(r.get('falha_humana') or 0) > 0 else ''}">{int(r.get('falha_humana') or 0)}</td>
            <td>{int(r.get('em_aberto') or 0)}</td>
        </tr>"""
    return html

def rows_insights_table(rows):
    if not rows: return "<tr><td colspan='8'>Sem dados</td></tr>"
    html = ""
    for i, r in enumerate(rows[:20]):
        acao = {
            'NUNCA ADERIU': 'Notificação formal ao fornecedor + visita do coordenador',
            'REGREDIU TOTAL': 'Visita imediata + relatório ao gestor regional',
            'REGREDINDO': 'Reunião com fiscal responsável + prazo de 15 dias',
            'ATENÇÃO': 'Monitoramento semanal + cobrança ao fiscal',
            'EVOLUINDO': 'Manter pressão, reconhecer melhora',
            'ESTÁVEL BAIXO': 'Plano de ação com metas mensais',
            'ESTÁVEL BOM': 'Monitoramento padrão',
        }.get(r['status'], 'Avaliar caso a caso')
        html += f"""<tr>
            <td><b>#{i+1}</b></td>
            <td><b>{r['cidade']}</b></td>
            <td>{int(r['motoristas'])}</td>
            <td>{int(r['total_escalas']):,}</td>
            <td>{r['pct_q2']}%</td>
            <td>{r['pct_q3']}%</td>
            <td><span class="tag {r['cls'].replace('class-','badge-')}">{r['icon']} {r['status']}</span></td>
            <td style="font-size:11px">{acao}</td>
        </tr>"""
    return html

def rows_insights_fiscal(df):
    if df.empty: return "<tr><td colspan='7'>Sem dados</td></tr>"
    html = ""
    for _, r in df.iterrows():
        q2, q3 = float(r.get('pct_q2') or 0), float(r.get('pct_q3') or 0)
        icon, _, _ = tendencia(q2, q3)
        b = badge(q3)
        html += f"""<tr>
            <td><b>{r['gre']}</b></td>
            <td>{r.get('fiscal') or '—'}</td>
            <td>{int(r.get('total_escalas') or 0):,}</td>
            <td>{q2}%</td>
            <td><span class="tag {b}">{q3}% {icon}</span></td>
            <td>{int(r.get('fraude_tempo') or 0):,}</td>
            <td>{int(r.get('manuais_gps') or 0):,}</td>
        </tr>"""
    return html

# ─────────────────────────────────────────────
# HTML
# ─────────────────────────────────────────────
gerado_em = datetime.now().strftime("%d/%m/%Y %H:%M")

html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Torre de Controle | Fiscalização de Rotas — Piauí</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{
  --bg: #0b0f1a;
  --surface: #131929;
  --surface2: #1a2236;
  --border: #1e2d45;
  --text: #e2e8f0;
  --muted: #64748b;
  --accent: #38bdf8;
  --ok: #22c55e;
  --warn: #f59e0b;
  --crit: #ef4444;
  --orange: #f97316;
  --purple: #a78bfa;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); font-size: 13px; }}
.header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 14px 24px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 100; }}
.header h1 {{ font-size: 16px; font-weight: 700; color: var(--accent); letter-spacing: 0.5px; }}
.header .meta {{ font-size: 11px; color: var(--muted); }}
.nav {{ display: flex; gap: 4px; padding: 12px 24px 0; background: var(--surface); border-bottom: 2px solid var(--border); overflow-x: auto; }}
.nav button {{ background: none; border: none; color: var(--muted); padding: 10px 16px; cursor: pointer; font-size: 12px; font-weight: 600; border-bottom: 2px solid transparent; margin-bottom: -2px; white-space: nowrap; transition: .2s; }}
.nav button.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
.nav button:hover:not(.active) {{ color: var(--text); }}
.tab {{ display: none; padding: 20px 24px; }}
.tab.active {{ display: block; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }}
.kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
.kpi label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; }}
.kpi .val {{ font-size: 26px; font-weight: 700; color: var(--text); margin-top: 4px; }}
.kpi .val.ok {{ color: var(--ok); }}
.kpi .val.warn {{ color: var(--warn); }}
.kpi .val.crit {{ color: var(--crit); }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px; margin-bottom: 16px; }}
.card h3 {{ font-size: 13px; font-weight: 700; color: var(--accent); margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
.grid3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }}
@media(max-width: 900px) {{ .grid2, .grid3 {{ grid-template-columns: 1fr; }} }}
.tbl-wrap {{ overflow-x: auto; max-height: 420px; overflow-y: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th {{ background: var(--bg); color: var(--accent); padding: 10px 8px; border-bottom: 2px solid var(--border); position: sticky; top: 0; text-align: left; font-size: 11px; font-weight: 700; white-space: nowrap; }}
td {{ padding: 9px 8px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
tr:hover {{ background: var(--surface2); }}
.search {{ width: 100%; padding: 8px 12px; background: var(--bg); border: 1px solid var(--border); color: var(--text); border-radius: 6px; margin-bottom: 12px; font-size: 12px; outline: none; }}
.search:focus {{ border-color: var(--accent); }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 700; }}
.badge-ok {{ background: rgba(34,197,94,.15); color: var(--ok); }}
.badge-warn {{ background: rgba(245,158,11,.15); color: var(--warn); }}
.badge-crit {{ background: rgba(239,68,68,.15); color: var(--crit); }}
.badge-nd {{ background: rgba(100,116,139,.15); color: var(--muted); }}
.badge-nunca {{ background: rgba(167,139,250,.15); color: var(--purple); }}
.text-red {{ color: var(--crit); font-weight: 700; }}
.text-orange {{ color: var(--orange); font-weight: 700; }}
.alert-box {{ background: rgba(239,68,68,.08); border: 1px solid rgba(239,68,68,.3); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; font-size: 12px; color: #fca5a5; }}
.alert-box b {{ color: var(--crit); }}
.score-bar {{ display: inline-block; height: 6px; border-radius: 3px; background: var(--crit); margin-left: 8px; vertical-align: middle; }}
canvas {{ max-height: 280px; }}
.legenda {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 12px; font-size: 11px; color: var(--muted); }}
.legenda span {{ display: flex; align-items: center; gap: 4px; }}
.legenda i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; }}
</style>
</head>
<body>

<div class="header">
  <h1>🛡️ Torre de Controle | Fiscalização de Rotas — Piauí</h1>
  <div class="meta">Gerado em {gerado_em} &nbsp;|&nbsp; Dados: Supabase/Airbyte</div>
</div>

<div class="nav">
  <button class="active" onclick="tab('t1',this)">📊 Painel Executivo</button>
  <button onclick="tab('t2',this)">📍 Assiduidade GRE</button>
  <button onclick="tab('t3',this)">🏙️ Cidades</button>
  <button onclick="tab('t4',this)">⚠️ Fraude</button>
  <button onclick="tab('t5',this)">📋 Contratos</button>
  <button onclick="tab('t6',this)">🚌 Frota</button>
  <button onclick="tab('t7',this)">👤 Motoristas</button>
  <button onclick="tab('t8',this)">🧠 Insights</button>
</div>

<!-- ABA 1: PAINEL EXECUTIVO -->
<div id="t1" class="tab active">
  <div class="kpi-grid">
    <div class="kpi"><label>Escalas no Mês</label><div class="val">{kpi_total:,}</div></div>
    <div class="kpi"><label>Via App</label><div class="val {'ok' if kpi_pct_app >= 50 else 'warn' if kpi_pct_app >= 30 else 'crit'}">{kpi_pct_app}%</div></div>
    <div class="kpi"><label>Manuais s/ GPS</label><div class="val warn">{kpi_manual:,}</div></div>
    <div class="kpi"><label>Fraude Tempo (&lt;10min)</label><div class="val crit">{kpi_fraude:,} ({kpi_pct_fraude}%)</div></div>
    <div class="kpi"><label>Contratos s/ Operação</label><div class="val crit">{kpi_contratos}</div></div>
    <div class="kpi"><label>Chamados Abertos</label><div class="val warn">{kpi_manut_aberto}</div></div>
    <div class="kpi"><label>Veíc. em Oficina</label><div class="val warn">{kpi_manut_oficina}</div></div>
  </div>

  <div class="grid2">
    <div class="card">
      <h3>📈 Evolução Mensal de Escalas (2026)</h3>
      <canvas id="chart_esc"></canvas>
    </div>
    <div class="card">
      <h3>📱 % Via App vs % Fraude de Tempo</h3>
      <canvas id="chart_pct"></canvas>
    </div>
  </div>

  <div class="grid2">
    <div class="card">
      <h3>🚨 Manuais s/ GPS por Mês</h3>
      <canvas id="chart_manual"></canvas>
    </div>
    <div class="card">
      <h3>📋 Escalas com Contrato por Mês</h3>
      <canvas id="chart_contrato"></canvas>
    </div>
  </div>
</div>

<!-- ABA 2: ASSIDUIDADE GRE -->
<div id="t2" class="tab">
  <div class="card">
    <h3>📊 Evolução % Via App por GRE (2026)</h3>
    <canvas id="chart_gre"></canvas>
  </div>
  <div class="card">
    <h3>📋 Desempenho por GRE — Q2 vs Q3/2026</h3>
    <input class="search" id="s_gre" oninput="fil('s_gre','tbl_gre')" placeholder="Filtrar GRE...">
    <div class="tbl-wrap">
      <table id="tbl_gre">
        <thead><tr><th>GRE</th><th>Escalas</th><th>% App</th><th>Q2/2026</th><th>Q3/2026</th><th>Manuais s/GPS</th><th>Anuladas</th></tr></thead>
        <tbody>{rows_gre(df_gre_assid)}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ABA 3: CIDADES -->
<div id="t3" class="tab">
  <div class="alert-box">
    <b>⚠️ Atenção:</b> Cidades abaixo classificadas por situação de registro via app.
    Regressão = índice Q3 menor que Q2. "Nunca aderiu" = 0% em ambos os trimestres.
  </div>
  <div class="card">
    <h3>🏙️ Cidades — Registro via App e Fraude de Tempo</h3>
    <input class="search" id="s_cid" oninput="fil('s_cid','tbl_cid')" placeholder="Filtrar cidade...">
    <div class="tbl-wrap">
      <table id="tbl_cid">
        <thead><tr><th>Cidade</th><th>Mot.</th><th>Escalas</th><th>Q2 App%</th><th>Q3 App%</th><th>Fraude%</th><th>Manuais</th><th>Situação</th></tr></thead>
        <tbody>{rows_cidades(df_cidades)}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ABA 4: FRAUDE -->
<div id="t4" class="tab">
  <div class="card">
    <h3>📉 Evolução Mensal — Fraude de Tempo e Manuais s/ GPS</h3>
    <canvas id="chart_fraude"></canvas>
  </div>
  <div class="grid2">
    <div class="card">
      <h3>🏢 Empresas com Maior % Fraude de Tempo</h3>
      <div class="tbl-wrap">
        <table id="tbl_femp">
          <thead><tr><th>Empresa</th><th>Mot.</th><th>Escalas</th><th>Fraude</th><th>%</th><th>Manuais</th></tr></thead>
          <tbody>{rows_fraude_emp(df_fraude_empresas)}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>👤 Motoristas com Maior % Fraude de Tempo</h3>
      <input class="search" id="s_fmot" oninput="fil('s_fmot','tbl_fmot')" placeholder="Buscar...">
      <div class="tbl-wrap">
        <table id="tbl_fmot">
          <thead><tr><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>GRE</th><th>Fraudes</th><th>%</th><th>Manuais</th></tr></thead>
          <tbody>{rows_fraude_mot(df_fraude_motoristas)}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 5: CONTRATOS -->
<div id="t5" class="tab">
  <div class="alert-box">
    <b>🚨 Contratos Ativos sem Operação:</b> Veículos com contrato ativo mas SEM motorista associado
    e ZERO escalas nos últimos 30 dias. Cada linha representa valor diário em risco de pagamento sem execução.
  </div>
  <div class="grid2">
    <div class="card">
      <h3>📋 Escalas com Contrato — Evolução Mensal</h3>
      <canvas id="chart_cont2"></canvas>
    </div>
    <div class="card">
      <h3>📊 Distribuição: Total vs Manuais vs Anuladas</h3>
      <canvas id="chart_cont3"></canvas>
    </div>
  </div>
  <div class="card">
    <h3>⚠️ Contratos Ativos sem Motorista (Zero Escalas em 30 dias)</h3>
    <input class="search" id="s_cont" oninput="fil('s_cont','tbl_cont')" placeholder="Filtrar GRE, placa...">
    <div class="tbl-wrap">
      <table id="tbl_cont">
        <thead><tr><th>GRE</th><th>Placa</th><th>Valor/Dia</th><th>Turno</th><th>Situação</th><th>Escalas 30d</th></tr></thead>
        <tbody>{rows_contratos(df_contratos_risco)}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- ABA 6: FROTA -->
<div id="t6" class="tab">
  <div class="card">
    <h3>📄 Documentação por Fornecedor — Licenciamento e Multas</h3>
    <input class="search" id="s_frota" oninput="fil('s_frota','tbl_frota')" placeholder="Filtrar fornecedor...">
    <div class="tbl-wrap">
      <table id="tbl_frota">
        <thead><tr><th>Fornecedor</th><th>Total</th><th>Ativos</th><th>Inativos</th><th>Lic. Vencido</th><th>Lic. OK (2026)</th><th>C/ Multas</th></tr></thead>
        <tbody>{rows_frota_doc(df_frota_doc)}</tbody>
      </table>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <h3>🔧 Manutenção por Fornecedor (2026)</h3>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Fornecedor</th><th>Chamados</th><th>Abertos</th><th>Oficina</th><th>Veíc.</th><th>Média Dias</th></tr></thead>
          <tbody>{''.join([f"<tr><td><b>{r['fornecedor']}</b></td><td>{int(r.get('total_chamados',0))}</td><td class='{'text-red' if int(r.get('em_aberto',0))>5 else ''}'>{int(r.get('em_aberto',0))}</td><td>{int(r.get('em_oficina',0))}</td><td>{int(r.get('veiculos_afetados',0))}</td><td>{r.get('media_dias_parado',0)}</td></tr>" for _,r in df_manut_fornecedor.iterrows()]) if not df_manut_fornecedor.empty else "<tr><td colspan='6'>Sem dados</td></tr>"}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>🚗 Veículos com Mais Chamados (2026)</h3>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Placa</th><th>Fornecedor</th><th>GRE</th><th>Chamados</th><th>Abertos</th><th>Falha Hum.</th><th>Média Dias</th></tr></thead>
          <tbody>{rows_veiculos_prob(df_veiculos_problema)}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 7: MOTORISTAS -->
<div id="t7" class="tab">
  <div class="card">
    <h3>👤 Motoristas — Ranking por % Via App (piores primeiro)</h3>
    <input class="search" id="s_mot" oninput="fil('s_mot','tbl_mot')" placeholder="Buscar motorista, cidade, empresa...">
    <div class="tbl-wrap">
      <table id="tbl_mot">
        <thead><tr><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>GRE</th><th>Escalas</th><th>% App</th><th>Fraude Tempo</th><th>Manuais s/GPS</th></tr></thead>
        <tbody>{rows_motoristas(df_motoristas_rank)}</tbody>
      </table>
    </div>
  </div>
  <div class="grid2">
    <div class="card">
      <h3>🔧 Motoristas que Mais Geram Chamados</h3>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Motorista</th><th>Empresa</th><th>GRE</th><th>Chamados</th><th>Falha Hum.</th><th>Abertos</th></tr></thead>
          <tbody>{rows_mot_chamados(df_motoristas_chamados)}</tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <h3>⛽ Motoristas — Consumo de Combustível (2026)</h3>
      <div class="tbl-wrap">
        <table id="tbl_abast">
          <thead><tr><th>Motorista</th><th>Empresa</th><th>Cidade</th><th>GRE</th><th>Abast.</th><th>Litros</th><th>Gasto R$</th><th>Escalas</th><th>R$/Escala</th></tr></thead>
          <tbody>{rows_abast(df_abastecimento_motorista)}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ABA 8: INSIGHTS -->
<div id="t8" class="tab">
  <div class="alert-box">
    <b>🧠 Inteligência Operacional:</b> Score de Gargalo calculado por cidade combinando: 
    baixo índice de app (40%), regressão Q2→Q3 (30%), fraude de tempo (20%) e manuais sem GPS (10%).
    Quanto maior o score, maior a prioridade de intervenção.
  </div>

  <div class="card">
    <h3>🎯 Ranking de Prioridade de Intervenção — Cidades</h3>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>#</th><th>Cidade</th><th>Mot.</th><th>Escalas</th><th>Q2 App%</th><th>Q3 App%</th><th>Situação</th><th>Ação Recomendada</th></tr></thead>
        <tbody>{rows_insights_table(rows_insights)}</tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h3>👮 Desempenho por Fiscal Responsável</h3>
    <div class="tbl-wrap">
      <table>
        <thead><tr><th>GRE</th><th>Fiscal</th><th>Escalas</th><th>Q2 App%</th><th>Q3 App%</th><th>Fraudes Tempo</th><th>Manuais s/GPS</th></tr></thead>
        <tbody>{rows_insights_fiscal(df_insights_fiscal)}</tbody>
      </table>
    </div>
  </div>

  <div class="card">
    <h3>📊 Comparativo Prestadores vs Próprios</h3>
    <div class="grid3" style="text-align:center; padding: 8px 0;">
      <div class="kpi"><label>Escalas Prestadores</label><div class="val">113.005</div></div>
      <div class="kpi"><label>Fraude de Tempo</label><div class="val crit">7.871 (6,97%)</div></div>
      <div class="kpi"><label>Manuais s/ GPS</label><div class="val warn">5.165</div></div>
    </div>
    <div style="margin-top:12px; padding: 12px; background: var(--bg); border-radius: 8px; font-size: 12px; color: var(--muted); line-height: 1.8;">
      <b style="color:var(--crit)">100% das irregularidades são de PRESTADORES.</b>
      Motoristas próprios (sem fornecedor_id) apresentam irregularidade próxima de zero.
      Isso indica que o modelo de terceirização carece de mecanismos de controle mais rígidos.<br><br>
      <b style="color:var(--warn)">Empresas críticas:</b> J COUTINHO DE SOUSA FILHO (96,94% fraude), 
      ANTONIO CARLOS REIS SARAIVA (75,74%), INES DE SALES RESENDE (59,35%).<br><br>
      <b style="color:var(--accent)">Recomendação estratégica:</b> Implantação de cláusula de glosa contratual 
      vinculada ao índice de execução via app. Prestadores abaixo de 50% em dois meses consecutivos 
      devem receber notificação formal com prazo de adequação de 30 dias.
    </div>
  </div>
</div>

<script>
function tab(id, btn) {{
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}

function fil(inputId, tableId) {{
  const v = document.getElementById(inputId).value.toLowerCase();
  document.getElementById(tableId).querySelectorAll('tbody tr').forEach(r => {{
    r.style.display = r.innerText.toLowerCase().includes(v) ? '' : 'none';
  }});
}}

const meses = {jdumps(meses)};
const ev_total = {jdumps(ev_total)};
const ev_app = {jdumps(ev_app)};
const ev_fraude = {jdumps(ev_fraude)};
const ev_manual = {jdumps(ev_manual)};
const ev_pct_app = {jdumps(ev_pct_app)};
const ev_pct_fraude = {jdumps(ev_pct_fraude)};

const opts = {{ responsive: true, plugins: {{ legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }} }}, scales: {{ x: {{ ticks: {{ color: '#64748b' }} }}, y: {{ ticks: {{ color: '#64748b' }} }} }} }};

new Chart(document.getElementById('chart_esc'), {{ type: 'bar', data: {{
  labels: meses,
  datasets: [
    {{ label: 'Total Escalas', data: ev_total, backgroundColor: 'rgba(56,189,248,.3)', borderColor: '#38bdf8', borderWidth: 1 }},
    {{ label: 'Via App', data: ev_app, backgroundColor: 'rgba(34,197,94,.3)', borderColor: '#22c55e', borderWidth: 1 }}
  ]
}}, options: opts }});

new Chart(document.getElementById('chart_pct'), {{ type: 'line', data: {{
  labels: meses,
  datasets: [
    {{ label: '% Via App', data: ev_pct_app, borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,.1)', fill: true, tension: 0.3 }},
    {{ label: '% Fraude Tempo', data: ev_pct_fraude, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,.1)', fill: true, tension: 0.3 }}
  ]
}}, options: opts }});

new Chart(document.getElementById('chart_manual'), {{ type: 'bar', data: {{
  labels: meses,
  datasets: [{{ label: 'Manuais s/ GPS', data: ev_manual, backgroundColor: 'rgba(245,158,11,.4)', borderColor: '#f59e0b', borderWidth: 1 }}]
}}, options: opts }});

const cont_meses = {jdumps(df_contratos_mensal['mes'].tolist() if not df_contratos_mensal.empty else [])};
const cont_total = {jdumps(df_contratos_mensal['escalas_com_contrato'].tolist() if not df_contratos_mensal.empty else [])};
const cont_anuladas = {jdumps(df_contratos_mensal['anuladas'].tolist() if not df_contratos_mensal.empty else [])};
const cont_manuais = {jdumps(df_contratos_mensal['manuais'].tolist() if not df_contratos_mensal.empty else [])};

new Chart(document.getElementById('chart_cont2'), {{ type: 'line', data: {{
  labels: cont_meses,
  datasets: [{{ label: 'Escalas c/ Contrato', data: cont_total, borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,.1)', fill: true, tension: 0.3 }}]
}}, options: opts }});

new Chart(document.getElementById('chart_cont3'), {{ type: 'bar', data: {{
  labels: cont_meses,
  datasets: [
    {{ label: 'Total', data: cont_total, backgroundColor: 'rgba(56,189,248,.3)', borderColor: '#38bdf8', borderWidth: 1 }},
    {{ label: 'Manuais', data: cont_manuais, backgroundColor: 'rgba(245,158,11,.4)', borderColor: '#f59e0b', borderWidth: 1 }},
    {{ label: 'Anuladas', data: cont_anuladas, backgroundColor: 'rgba(239,68,68,.3)', borderColor: '#ef4444', borderWidth: 1 }}
  ]
}}, options: opts }});

const fraude_meses = {jdumps(df_fraude_mensal['mes'].tolist() if not df_fraude_mensal.empty else [])};
const fraude_vals = {jdumps(df_fraude_mensal['menos_10min'].tolist() if not df_fraude_mensal.empty else [])};
const manual_vals = {jdumps(df_fraude_mensal['manuais_gps'].tolist() if not df_fraude_mensal.empty else [])};

new Chart(document.getElementById('chart_fraude'), {{ type: 'line', data: {{
  labels: fraude_meses,
  datasets: [
    {{ label: 'Fraude Tempo (<10min)', data: fraude_vals, borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,.1)', fill: true, tension: 0.3 }},
    {{ label: 'Manuais s/ GPS', data: manual_vals, borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,.1)', fill: true, tension: 0.3 }}
  ]
}}, options: opts }});

// Gráfico GRE mensal
const gre_data = {jdumps(df_gre_mensal.to_dict('records') if not df_gre_mensal.empty else [])};
const gre_meses_u = [...new Set(gre_data.map(r => r.mes))].sort();
const gre_nomes = [...new Set(gre_data.map(r => r.gre))];
const cores = ['#38bdf8','#22c55e','#f59e0b','#ef4444','#a78bfa','#f97316','#06b6d4','#84cc16','#ec4899','#14b8a6'];
const gre_datasets = gre_nomes.map((gre, i) => {{
  const mapa = {{}};
  gre_data.filter(r => r.gre === gre).forEach(r => mapa[r.mes] = r.pct_app);
  return {{ label: gre, data: gre_meses_u.map(m => mapa[m] || 0), borderColor: cores[i % cores.length], backgroundColor: 'transparent', tension: 0.3 }};
}});
new Chart(document.getElementById('chart_gre'), {{ type: 'line', data: {{ labels: gre_meses_u, datasets: gre_datasets }}, options: opts }});
</script>
</body>
</html>"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ index.html gerado com sucesso ({len(html):,} bytes)")
