import psycopg2
import pandas as pd
import json

HOST = "aws-0-sa-east-1.pooler.supabase.com"
PORT = 5432
DATABASE = "postgres"
USER = "analista_bi.cuofycgznnbtpotybpuu"
PASSWORD = "marvao#37m"

conn = psycopg2.connect(
    host=HOST, port=PORT, database=DATABASE, user=USER, password=PASSWORD
)

# 1. KPIs Gerais de Governança
kpi_query = """
SELECT 
    (SELECT COUNT(*) FROM airbyte.veiculos_veiculo WHERE status = 'ATIVO') as veiculos_ativos,
    (SELECT COUNT(*) FROM airbyte.motoristas_motorista WHERE status = 'ATIVO') as motoristas_ativos,
    (SELECT COUNT(DISTINCT fornecedor_id) FROM airbyte.motoristas_fornecedor) as fornecedores_ativos,
    (SELECT COALESCE(SUM(litros), 0) FROM airbyte.abastecimentos_abastecimento WHERE created_at >= CURRENT_DATE - INTERVAL '30 days') as litros_30d,
    (SELECT COALESCE(SUM(km_executado), 0) FROM airbyte.rotas_escalarota WHERE anulada = false AND data >= CURRENT_DATE - INTERVAL '30 days') as km_30d
"""
df_kpi = pd.read_sql(kpi_query, conn)

# 2. Custo e Volume por Fornecedor (Abastecimentos / Terceiros)
fornecedor_query = """
SELECT 
    f.nome as fornecedor,
    ROUND(SUM(a.litros)::numeric, 2) as total_litros,
    COUNT(a.id) as qtd_abastecimentos
FROM airbyte.abastecimentos_abastecimento a
JOIN airbyte.motoristas_fornecedor f ON a.fornecedor_id = f.id
WHERE a.created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY f.nome
ORDER BY total_litros DESC
LIMIT 8;
"""
df_fornecedor = pd.read_sql(fornecedor_query, conn)

# 3. Assiduidade e Execução de Rotas por Unidade/GRE
rotas_unidade_query = """
SELECT 
    g.nome as unidade,
    COUNT(e.id) as total_escalas,
    SUM(CASE WHEN e.anulada = true THEN 1 ELSE 0 END) as rotas_anuladas,
    ROUND(SUM(e.km_executado)::numeric, 2) as km_realizado
FROM airbyte.rotas_escalarota e
JOIN airbyte.rotas_rota r ON e.rota_id = r.id
LEFT JOIN airbyte.escolas_gre g ON r.gre_id = g.id
WHERE e.data >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY g.nome
ORDER BY total_escalas DESC
LIMIT 10;
"""
df_rotas_unidade = pd.read_sql(rotas_unidade_query, conn)

# 4. Auditoria de Abastecimento x KM Executado por Veículo (Ranking Ofensores)
ofensores_query = """
WITH abastecimentos_30d AS (
    SELECT veiculo_id, SUM(litros) as litros FROM airbyte.abastecimentos_abastecimento 
    WHERE created_at >= CURRENT_DATE - INTERVAL '30 days' GROUP BY veiculo_id
),
km_30d AS (
    SELECT veiculo_id, SUM(km_executado) as km FROM airbyte.rotas_escalarota 
    WHERE anulada = false AND data >= CURRENT_DATE - INTERVAL '30 days' GROUP BY veiculo_id
)
SELECT 
    v.placa,
    COALESCE(a.litros, 0) as litros,
    COALESCE(k.km, 0) as km_rodado,
    CASE WHEN COALESCE(k.km, 0) > 0 THEN ROUND((COALESCE(a.litros, 0) / k.km)::numeric, 3) ELSE 0 END as litros_por_km
FROM airbyte.veiculos_veiculo v
LEFT JOIN abastecimentos_30d a ON v.id = a.veiculo_id
LEFT JOIN km_30d k ON v.id = k.veiculo_id
WHERE a.litros > 0
ORDER BY litros_por_km DESC
LIMIT 10;
"""
df_ofensores = pd.read_sql(ofensores_query, conn)

conn.close()

# HTML com Filtros e Estrutura de Governança
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Torre de Controle & Governança de Frota</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 24px; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }}
        h1 {{ font-size: 22px; font-weight: 700; color: #38bdf8; }}
        
        .filters {{ display: flex; gap: 12px; background: #1e293b; padding: 12px 16px; border-radius: 8px; border: 1px solid #334155; }}
        .filters select, .filters input {{ background: #0f172a; color: #fff; border: 1px solid #475569; padding: 6px 12px; border-radius: 6px; font-size: 13px; }}

        .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card-kpi {{ background: #1e293b; padding: 16px; border-radius: 10px; border: 1px solid #334155; }}
        .card-kpi p {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; }}
        .card-kpi h2 {{ font-size: 24px; color: #f8fafc; margin-top: 6px; }}

        .grid-charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(450px, 1fr)); gap: 20px; margin-bottom: 24px; }}
        .card-chart {{ background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; }}
        .card-chart h3 {{ font-size: 15px; margin-bottom: 14px; color: #cbd5e1; }}
        
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
        th {{ background: #0f172a; color: #94a3b8; padding: 10px; border-bottom: 1px solid #334155; }}
        td {{ padding: 10px; border-bottom: 1px solid #334155; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Torre de Controle | Governança de Frota & Rotas</h1>
        <div class="filters">
            <select id="filtroPeriodo">
                <option value="30">Últimos 30 dias</option>
                <option value="60">Últimos 60 dias</option>
                <option value="90">Últimos 90 dias</option>
            </select>
        </div>
    </div>

    <div class="grid-kpi">
        <div class="card-kpi"><p>Veículos Ativos</p><h2>{int(df_kpi['veiculos_ativos'].iloc[0])}</h2></div>
        <div class="card-kpi"><p>Motoristas Ativos</p><h2>{int(df_kpi['motoristas_ativos'].iloc[0])}</h2></div>
        <div class="card-kpi"><p>Fornecedores</p><h2>{int(df_kpi['fornecedores_ativos'].iloc[0])}</h2></div>
        <div class="card-kpi"><p>Consumo (30d)</p><h2>{float(df_kpi['litros_30d'].iloc[0]):,.0f} L</h2></div>
        <div class="card-kpi"><p>Distância (30d)</p><h2>{float(df_kpi['km_30d'].iloc[0]):,.0f} KM</h2></div>
    </div>

    <div class="grid-charts">
        <div class="card-chart">
            <h3>Consumo de Combustível por Fornecedor (Litros)</h3>
            <canvas id="chartFornecedores"></canvas>
        </div>
        <div class="card-chart">
            <h3>Execução de Escalada de Rotas por Regional/GRE</h3>
            <canvas id="chartRotasUnidades"></canvas>
        </div>
    </div>

    <div class="card-chart">
        <h3>Auditoria de Eficiência: Top Veículos com Maior Razão (Litros / KM Rodado)</h3>
        <table>
            <thead>
                <tr>
                    <th>Placa</th>
                    <th>Litros Abastecidos</th>
                    <th>KM Executado</th>
                    <th>Razão (L/KM)</th>
                </tr>
            </thead>
            <tbody>
                {''.join([f"<tr><td><b>{row['placa']}</b></td><td>{row['litros']} L</td><td>{row['km_rodado']} KM</td><td><span style='color:#f87171;'>{row['litros_por_km']}</span></td></tr>" for _, row in df_ofensores.iterrows()])}
            </tbody>
        </table>
    </div>

    <script>
        new Chart(document.getElementById('chartFornecedores').getContext('2d'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(df_fornecedor['fornecedor'].tolist())},
                datasets: [{{ label: 'Litros', data: {json.dumps(df_fornecedor['total_litros'].tolist())}, backgroundColor: '#f59e0b' }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
        }});

        new Chart(document.getElementById('chartRotasUnidades').getContext('2d'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(df_rotas_unidade['unidade'].tolist())},
                datasets: [
                    {{ label: 'Escalas Realizadas', data: {json.dumps(df_rotas_unidade['total_escalas'].tolist())}, backgroundColor: '#38bdf8' }},
                    {{ label: 'Rotas Anuladas', data: {json.dumps(df_rotas_unidade['rotas_anuladas'].tolist())}, backgroundColor: '#ef4444' }}
                ]
            }},
            options: {{ responsive: true }}
        }});
    </script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
