import psycopg2
import pandas as pd
import json

# Conexão direta com as credenciais do DBeaver
conn = psycopg2.connect(
    host="aws-0-sa-east-1.pooler.supabase.com",
    port=5432,
    database="postgres",
    user="analista_bi.cuofycgznnbtpotybpuu",
    password="marvao#37m"
)

# Consulta SQL puxando as colunas necessárias
query = "SELECT * FROM airbyte.rotas_rota LIMIT 500;"
df = pd.read_sql(query, conn)
conn.close()

# Converte os dados para JSON para injetar no Chart.js
dados_json = df.to_json(orient="records")

# Estrutura da página HTML interativa
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Painel de Monitoramento de Frota</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{ font-family: sans-serif; background-color: #121212; color: #fff; padding: 20px; }}
        .card {{ background: #1e1e1e; padding: 20px; border-radius: 8px; margin-top: 20px; }}
    </style>
</head>
<body>
    <h1>Painel de Frota & Rotas</h1>
    <div class="card">
        <canvas id="graficoFrota"></canvas>
    </div>
    <script>
        const dados = {dados_json};
        console.log("Dados do banco:", dados);
        // Estrutura de visualização pronta
    </script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
