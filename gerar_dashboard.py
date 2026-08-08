import psycopg2
import pandas as pd
import json

# Credenciais de conexão
HOST = "aws-0-sa-east-1.pooler.supabase.com"
PORT = 5432
DATABASE = "postgres"
USER = "analista_bi.cuofycgznnbtpotybpuu"  # Substitua pelo seu usuário
PASSWORD = "marvao#37m"  # Substitua pela sua senha

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

# 2. Execução por Motorista (Top 10 KM Executado)
rotas_query = """
SELECT 
    COALESCE(m.nome, 'Não informado') as motorista,
    COALESCE(SUM(e.km_executado), 0) as total_km
FROM airbyte.rotas_escalarota e
LEFT JOIN airbyte.motoristas_motorista m ON e.motorista_id = m.id
WHERE e.anulada = false
GROUP BY m.nome
ORDER BY total_km DESC
LIMIT 10;
"""
df_rotas = pd.read_sql(rotas_query, conn)

# 3. Abastecimento por Veículo (Top 10 Litros)
abs_query = """
SELECT 
    COALESCE(v.placa, 'Sem Placa') as placa,
    COALESCE(SUM(a.litros), 0) as total_litros
FROM airbyte.abastecimentos_abastecimento a
LEFT JOIN airbyte.veiculos_veiculo v ON a.veiculo_id = v.id
GROUP BY v.placa
ORDER BY total_litros DESC
LIMIT 10;
"""
df_abs = pd.read_sql(abs_query, conn)

# 4. Auditoria Eficiência (Litros por KM - Top Ofensores)
ofensores_query = """
WITH abs_30 AS (
    SELECT veiculo_id, SUM(litros) as litros 
    FROM airbyte.abastecimentos_abastecimento 
    GROUP BY veiculo_id
),
km_30 AS (
    SELECT veiculo_id, SUM(km_executado) as km 
    FROM airbyte.rotas_escalarota 
    WHERE anulada = false 
    GROUP BY veiculo_id
)
SELECT 
    v.placa,
    COALESCE(a.litros, 0) as litros,
    COALESCE(k.km, 0) as km_rodado,
    CASE 
        WHEN COALESCE(k.km, 0) > 0 THEN ROUND((COALESCE(a.litros, 0) / k.km)::numeric, 2) 
        ELSE 0 
    END as litros_por_km
FROM airbyte.veiculos_veiculo v
JOIN abs_30 a ON v.id = a.veiculo_id
LEFT JOIN km_30 k ON v.id = k.veiculo_id
WHERE a.litros > 0
ORDER BY litros_por_km DESC
LIMIT 10;
"""
df_ofensores = pd.read_sql(ofensores_query, conn)

conn.close()

# Extração dos dados
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

# Construção da tabela de ofensores
linhas_ofensores = ""
for _, row in df_ofensores.iterrows():
    linhas_ofensores += f"""
    <tr>
        <td><b>{row['placa']}</b></td>
        <td>{row['litros']:,.2f} L</td>
        <td>{row['km_rodado']:,.2f} KM</td>
        <td><span style="color:#f87171; font-weight: bold;">{row['litros_por_km']} L/KM</span></td>
    </tr>
    """

# HTML Final
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Painel Integrado de Governança de Frota</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 24px; }}
        h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 20px; color: #38bdf8; }}
        
        .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card-kpi {{ background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; }}
        .card-kpi p {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; font-weight: 700; }}
        .card-kpi h2 {{ font-size: 26px; color: #f8fafc; margin-top: 8px; }}

        .grid-charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; margin-bottom: 24px; }}
        .card-chart {{ background: #1e293b; padding: 20px; border-radius: 12px; border: 1px solid #334155; }}
        .card-chart h3 {{ font-size: 16px; margin-bottom: 16px; color: #cbd5e1; }}

        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 14px; margin-top: 8px; }}
        th {{ background: #0f172a; color: #94a3b8; padding: 12px; border-bottom: 1px solid #334155; }}
        td {{ padding: 12px; border-bottom: 1px solid #334155; }}
    </style>
</head>
<body>
    <h1>Torre de Controle & Governança de Frota</h1>

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
            <p>Total Abastecido</p>
            <h2>{totais['litros']:,} L</h2>
        </div>
        <div class="card-kpi">
            <p>Total KM Rodado</p>
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

    <div class="card-chart">
        <h3>Auditoria de Consumo: Veículos com Maior Discrepância (Litros por KM)</h3>
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
