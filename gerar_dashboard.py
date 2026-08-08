import psycopg2
import pandas as pd
import json

# Credenciais de conexão
HOST = "aws-0-sa-east-1.pooler.supabase.com"
PORT = 5432
DATABASE = "postgres"
USER = "analista_bi.cuofycgznnbtpotybpuu"
PASSWORD = "marvao#37m"

conn = psycopg2.connect(
    host=HOST,
    port=PORT,
    database=DATABASE,
    user=USER,
    password=PASSWORD
)

# 1. Totalizadores (KPIs)
kpi_query = """
SELECT 
    (SELECT COUNT(*) FROM airbyte.veiculos_veiculo) as total_veiculos,
    (SELECT COUNT(*) FROM airbyte.motoristas_motorista) as total_motoristas,
    (SELECT COALESCE(SUM(litros), 0) FROM airbyte.abastecimentos_abastecimento) as total_litros,
    (SELECT COALESCE(SUM(km_executado), 0) FROM airbyte.rotas_escalarota WHERE anulada = false) as total_km
"""
df_kpi = pd.read_sql(kpi_query, conn)

# 2. Execução de Rotas por Motorista (Top 10 KM)
rotas_query = """
SELECT 
    m.nome as motorista,
    COALESCE(SUM(e.km_executado), 0) as total_km
FROM airbyte.rotas_escalarota e
JOIN airbyte.motoristas_motorista m ON e.motorista_id = m.id
WHERE e.anulada = false
GROUP BY m.nome
ORDER BY total_km DESC
LIMIT 10;
"""
df_rotas = pd.read_sql(rotas_query, conn)

# 3. Abastecimento por Veículo (Top 10 Litros)
abs_query = """
SELECT 
    v.placa,
    COALESCE(SUM(a.litros), 0) as total_litros
FROM airbyte.abastecimentos_abastecimento a
JOIN airbyte.veiculos_veiculo v ON a.veiculo_id = v.id
GROUP BY v.placa
ORDER BY total_litros DESC
LIMIT 10;
"""
df_abs = pd.read_sql(abs_query, conn)

conn.close()

# Dados para o HTML
totais = {
    "veiculos": int(df_kpi['total_veiculos'].iloc[0]),
    "motoristas": int(df_kpi['total_motoristas'].iloc[0]),
    "litros": round(float(df_kpi['total_litros'].iloc[0]), 2),
    "km": round(float(df_kpi['total_km'].iloc[0]), 2)
}

rotas_labels = df_rotas['motorista'].tolist()
rotas_valores = df_rotas['total_km'].tolist()

abs_labels = df_abs['placa'].tolist()
abs_valores = df_abs['total_litros'].tolist()

# Template do Dashboard
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Dashboard de Operações de Frota</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 24px; }}
        h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 20px; color: #38bdf8; }}
        
        .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card-kpi {{ background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; }}
        .card-kpi p {{ font-size: 13px; color: #94a3b8; text-transform: uppercase; font-weight: 600; }}
        .card-kpi h2 {{ font-size: 28px; color: #f8fafc; margin-top: 8px; }}

        .grid-charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; }}
        .card-chart {{ background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; }}
        .card-chart h3 {{ font-size: 16px; margin-bottom: 16px; color: #cbd5e1; }}
    </style>
</head>
<body>
    <h1>Monitoramento Integrado de Frota & Operações</h1>

    <div class="grid-kpi">
        <div class="card-kpi">
            <p>Veículos Cadastrados</p>
            <h2>{totais['veiculos']}</h2>
        </div>
        <div class="card-kpi">
            <p>Motoristas Ativos</p>
            <h2>{totais['motoristas']}</h2>
        </div>
        <div class="card-kpi">
            <p>Total Litros Abastecidos</p>
            <h2>{totais['litros']:,} L</h2>
        </div>
        <div class="card-kpi">
            <p>Total KM Executado</p>
            <h2>{totais['km']:,} KM</h2>
        </div>
    </div>

    <div class="grid-charts">
        <div class="card-chart">
            <h3>Top 10 Motoristas por KM Executado</h3>
            <canvas id="chartRotas"></canvas>
        </div>
        <div class="card-chart">
            <h3>Top 10 Veículos por Consumo (Litros)</h3>
            <canvas id="chartAbastecimentos"></canvas>
        </div>
    </div>

    <script>
        // Gráfico de Rotas
        new Chart(document.getElementById('chartRotas').getContext('2d'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(rotas_labels)},
                datasets: [{{
                    label: 'KM Rodado',
                    data: {json.dumps(rotas_valores)},
                    backgroundColor: '#38bdf8'
                }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
        }});

        // Gráfico de Abastecimentos
        new Chart(document.getElementById('chartAbastecimentos').getContext('2d'), {{
            type: 'bar',
            data: {{
                labels: {json.dumps(abs_labels)},
                datasets: [{{
                    label: 'Litros',
                    data: {json.dumps(abs_valores)},
                    backgroundColor: '#f59e0b'
                }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
        }});
    </script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
