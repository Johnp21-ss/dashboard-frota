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

# 1. Totalizadores (KPIs Gerais)
kpi_query = """
SELECT 
    (SELECT COUNT(*) FROM airbyte.veiculos_veiculo WHERE status = 'ATIVO') as veiculos_ativos,
    (SELECT COUNT(*) FROM airbyte.motoristas_motorista WHERE status = 'ATIVO') as motoristas_ativos,
    (SELECT COALESCE(SUM(litros), 0) FROM airbyte.abastecimentos_abastecimento) as total_litros,
    (SELECT COALESCE(SUM(km_executado), 0) FROM airbyte.rotas_escalarota WHERE anulada = false) as total_km,
    (SELECT COUNT(*) FROM airbyte.ordens_chamado WHERE status = 'EM_ABERTO') as manutençoes_abertas
"""
df_kpi = pd.read_sql(kpi_query, conn)

# 2. Desempenho por GRE (Escalas vs Anulações)
gre_query = """
SELECT 
    COALESCE(g.nome, 'Sem GRE') as gre,
    COUNT(e.id) as total_escalas,
    SUM(CASE WHEN e.anulada = true THEN 1 ELSE 0 END) as anuladas
FROM airbyte.rotas_escalarota e
JOIN airbyte.rotas_rota r ON e.rota_id = r.id
LEFT JOIN airbyte.escolas_gre g ON r.gre_id = g.id
GROUP BY g.nome
ORDER BY total_escalas DESC
LIMIT 8;
"""
df_gre = pd.read_sql(gre_query, conn)

# 3. Consumo por Fornecedor
fornecedor_query = """
SELECT 
    COALESCE(f.nome, 'Direto/Próprio') as fornecedor,
    ROUND(SUM(a.litros)::numeric, 2) as total_litros
FROM airbyte.abastecimentos_abastecimento a
LEFT JOIN airbyte.motoristas_fornecedor f ON a.fornecedor_id = f.id
GROUP BY f.nome
ORDER BY total_litros DESC
LIMIT 8;
"""
df_fornecedor = pd.read_sql(fornecedor_query, conn)

# 4. Auditoria Consumo x KM (Ofensores L/KM)
ofensores_query = """
WITH abs AS (
    SELECT veiculo_id, SUM(litros) as litros FROM airbyte.abastecimentos_abastecimento GROUP BY veiculo_id
),
km AS (
    SELECT veiculo_id, SUM(km_executado) as km FROM airbyte.rotas_escalarota WHERE anulada = false GROUP BY veiculo_id
)
SELECT 
    v.placa,
    COALESCE(a.litros, 0) as litros,
    COALESCE(k.km, 0) as km_rodado,
    CASE WHEN COALESCE(k.km, 0) > 0 THEN ROUND((COALESCE(a.litros, 0) / k.km)::numeric, 2) ELSE 0 END as media_l_km
FROM airbyte.veiculos_veiculo v
JOIN abs a ON v.id = a.veiculo_id
LEFT JOIN km k ON v.id = k.veiculo_id
WHERE a.litros > 0
ORDER BY media_l_km DESC
LIMIT 10;
"""
df_ofensores = pd.read_sql(ofensores_query, conn)

conn.close()

# Estruturação Tabela Ofensores
linhas_ofensores = ""
for _, row in df_ofensores.iterrows():
    linhas_ofensores += f"""
    <tr>
        <td><b>{row['placa']}</b></td>
        <td>{row['litros']:,.2f} L</td>
        <td>{row['km_rodado']:,.2f} KM</td>
        <td><span style="color:#f87171; font-weight:bold;">{row['media_l_km']} L/KM</span></td>
    </tr>
    """

# HTML Template
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Torre de Controle & Governança de Frota</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 24px; }}
        h1 {{ font-size: 22px; font-weight: 700; color: #38bdf8; margin-bottom: 20px; }}
        
        .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card-kpi {{ background: #1e293b; padding: 18px; border-radius: 10px; border: 1px solid #334155; }}
        .card-kpi p {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; }}
        .card-kpi h2 {{ font-size: 24px; color: #f8fafc; margin-top: 6px; }}

        .grid-charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; margin-bottom: 24px; }}
        .card-chart {{ background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; }}
        .card-chart h3 {{ font-size: 15px; margin-bottom: 14px; color: #cbd5e1; }}
        
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; margin-top: 10px; }}
        th {{ background: #0f172a; color: #94a3b8; padding: 10px; border-bottom: 1px solid #334155; }}
        td {{ padding: 10px; border-bottom: 1px solid #334155; }}
    </style>
</head>
<body>
    <h1>Torre de Controle | Governança Integrada de Frota</h1>

    <div class="grid-kpi">
        <div class="card-kpi"><p>Veículos Ativos</p><h2>{int(df_kpi['veiculos_ativos'].iloc[0])}</h2></div>
        <div class="card-kpi"><p>Motoristas Ativos</p><h2>{int(df_kpi['motoristas_ativos'].iloc[0])}</h2></div>
        <div class="card-kpi"><p>Total Litros Abastecidos</p><h2>{float(df_kpi['total_litros'].iloc[0]):,.0f} L</h2></div>
        <div class="card-kpi"><p>KM Executado</p><h2>{float(df_kpi['total_km'].iloc[0]):,.0f} KM</h2></div>
        <div class="card-kpi"><p>Manutenções Abertas</p><h2>{int(df_kpi['manutençoes_abertas'].iloc[0])}</h2></div>
    </div>

    <div class="grid-charts">
        <div class="card-chart">
            <h3>Execução de Escalada de Rotas por GRE</h3>
            <canvas id="chartGre"></canvas>
        </div>
        <div class="card-chart">
            <h3>Volume de Abastecimento por Fornecedor (Litros)</h3>
            <canvas id="chartFornecedor"></canvas>
        </div>
    </div>

    <div class="card-chart">
        <h3>Auditoria de Consumo: Veículos Ofensores (Maior Razão Litros/KM)</h3>
        <table>
            <thead>
                <tr>
                    <th>Placa</th>
                    <th>Litros Abastecidos</th>
                    <th>KM Executado</th>
                    <th>Média (L/KM)</th>
                </tr>
            </thead>
            <tbody>
                {linhas_ofensores}
            </tbody>
        </table>
    </div>

    <script>
        new Chart(document.getElementById('chartGre').getContext('2d'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(df_gre['gre'].tolist())},
                datasets: [
                    {{ label: 'Escalas Realizadas', data: {json.dumps(df_gre['total_escalas'].tolist())}, backgroundColor: '#38bdf8' }},
                    {{ label: 'Anuladas', data: {json.dumps(df_gre['anuladas'].tolist())}, backgroundColor: '#ef4444' }}
                ]
            }},
            options: {{ responsive: true }}
        }});

        new Chart(document.getElementById('chartFornecedor').getContext('2d'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(df_fornecedor['fornecedor'].tolist())},
                datasets: [{{ label: 'Litros', data: {json.dumps(df_fornecedor['total_litros'].tolist())}, backgroundColor: '#f59e0b' }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
        }});
    </script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
