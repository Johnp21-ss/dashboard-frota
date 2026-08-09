import psycopg2
import pandas as pd
import json

# Configurações de conexão com o banco PostgreSQL / Supabase
HOST = "aws-0-sa-east-1.pooler.supabase.com"
PORT = 5432
DATABASE = "postgres"
USER = "analista_bi.cuofycgznnbtpotybpuu"     # Substitua pelo seu usuário do banco
PASSWORD = "marvao#37m"   # Substitua pela sua senha do banco

try:
    conn = psycopg2.connect(
        host=HOST, port=PORT, database=DATABASE, user=USER, password=PASSWORD
    )
except Exception as e:
    print(f"Erro ao conectar ao banco Supabase: {e}")
    raise e

def safe_read(query, default_df):
    try:
        return pd.read_sql(query, conn)
    except Exception as err:
        print(f"Erro na execução da consulta: {err}")
        return default_df

# -------------------------------------------------------------
# 1. ABA 1: VISÃO MACRO & KPIS GLOBAIS
# -------------------------------------------------------------
df_kpi = safe_read("""
SELECT 
    (SELECT COUNT(*) FROM airbyte.veiculos_veiculo WHERE status = 'ATIVO') as veiculos_ativos,
    (SELECT COUNT(*) FROM airbyte.motoristas_motorista WHERE status = 'ATIVO') as motoristas_ativos,
    (SELECT COALESCE(SUM(litros), 0) FROM airbyte.abastecimentos_abastecimento) as total_litros,
    (SELECT COALESCE(SUM(valor_total), 0) FROM airbyte.abastecimentos_abastecimento) as total_gasto_combustivel,
    (SELECT COALESCE(SUM(km_executado), 0) FROM airbyte.rotas_escalarota WHERE anulada = false) as total_km,
    (SELECT COUNT(*) FROM airbyte.ordens_chamado WHERE status = 'EM_ABERTO') as manutençoes_abertas
""", pd.DataFrame([{
    'veiculos_ativos': 0, 'motoristas_ativos': 0, 'total_litros': 0, 
    'total_gasto_combustivel': 0, 'total_km': 0, 'manutençoes_abertas': 0
}]))

df_macro_km = safe_read("""
SELECT 
    TO_CHAR(data, 'YYYY-MM') as mes,
    SUM(km_executado) as km_total
FROM airbyte.rotas_escalarota
WHERE anulada = false AND data IS NOT NULL
GROUP BY TO_CHAR(data, 'YYYY-MM')
ORDER BY mes DESC
LIMIT 6;
""", pd.DataFrame([{'mes': '2026-01', 'km_total': 0}]))

# -------------------------------------------------------------
# 2. ABA 2: GOVERNANÇA POR GRE / REGIONAL
# -------------------------------------------------------------
df_gre = safe_read("""
SELECT 
    g.nome as gre,
    COUNT(DISTINCT r.id) as total_rotas,
    COUNT(DISTINCT m.id) as total_motoristas,
    COUNT(DISTINCT e.id) as total_escalas,
    SUM(CASE WHEN e.anulada = true THEN 1 ELSE 0 END) as rotas_anuladas,
    COALESCE(SUM(e.km_executado), 0) as km_total
FROM airbyte.escolas_gre g
LEFT JOIN airbyte.rotas_rota r ON r.gre_id = g.id
LEFT JOIN airbyte.motoristas_motorista m ON m.gre_id = g.id
LEFT JOIN airbyte.rotas_escalarota e ON e.rota_id = r.id
GROUP BY g.nome
ORDER BY total_escalas DESC;
""", pd.DataFrame())

# -------------------------------------------------------------
# 3. ABA 3: GESTÃO DE FORNECEDORES & CONTRATOS
# -------------------------------------------------------------
df_fornecedores = safe_read("""
SELECT 
    f.nome as fornecedor,
    COUNT(DISTINCT v.id) as total_veiculos,
    COUNT(DISTINCT m.id) as total_motoristas,
    COALESCE(SUM(a.litros), 0) as total_litros,
    COALESCE(SUM(a.valor_total), 0) as custo_combustivel
FROM airbyte.motoristas_fornecedor f
LEFT JOIN airbyte.veiculos_veiculo v ON v.fornecedor_id = f.id
LEFT JOIN airbyte.motoristas_motorista m ON m.fornecedor_id = f.id
LEFT JOIN airbyte.abastecimentos_abastecimento a ON a.fornecedor_id = f.id
GROUP BY f.nome
ORDER BY total_litros DESC;
""", pd.DataFrame())

# -------------------------------------------------------------
# 4. ABA 4: AUDITORIA DE MOTORISTAS & ROTAS (GPS VS PLANEJADO)
# -------------------------------------------------------------
df_motoristas = safe_read("""
SELECT 
    m.nome as motorista,
    COALESCE(g.nome, 'N/A') as gre,
    COALESCE(f.nome, 'Direto') as fornecedor,
    COUNT(e.id) as total_escalas,
    SUM(CASE WHEN e.anulada = true THEN 1 ELSE 0 END) as anuladas,
    COALESCE(SUM(e.km_planejado), 0) as km_planejado,
    COALESCE(SUM(e.km_executado), 0) as km_executado,
    CASE 
        WHEN SUM(e.km_planejado) > 0 
        THEN ROUND(((SUM(e.km_executado) - SUM(e.km_planejado)) / SUM(e.km_planejado) * 100)::numeric, 2)
        ELSE 0 
    END as desvio_pct
FROM airbyte.motoristas_motorista m
LEFT JOIN airbyte.escolas_gre g ON m.gre_id = g.id
LEFT JOIN airbyte.motoristas_fornecedor f ON m.fornecedor_id = f.id
LEFT JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
GROUP BY m.nome, g.nome, f.nome
ORDER BY km_executado DESC
LIMIT 50;
""", pd.DataFrame())

# -------------------------------------------------------------
# 5. ABA 5: MANUTENÇÃO & DISPONIBILIDADE (Com orcamento em Texto)
# -------------------------------------------------------------
df_manutencao = safe_read("""
SELECT 
    v.placa,
    COALESCE(c.tipo_manutencao, 'Preventiva') as tipo_manutencao,
    c.status,
    c.descricao,
    c.orcamento::text as orcamento,
    c.falha_humana
FROM airbyte.ordens_chamado c
JOIN airbyte.veiculos_veiculo v ON c.veiculo_id = v.id
ORDER BY c.emissao DESC
LIMIT 50;
""", pd.DataFrame())

df_manutencao_chart = safe_read("""
SELECT 
    COALESCE(tipo_manutencao, 'Geral') as tipo,
    COUNT(*) as qtd
FROM airbyte.ordens_chamado
GROUP BY tipo_manutencao
ORDER BY qtd DESC;
""", pd.DataFrame())

conn.close()

# -------------------------------------------------------------
# MONTAGEM DA INTERFACE DASHBOARD (HTML / SPA)
# -------------------------------------------------------------
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Torre de Controle | Governança de Frota</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
        
        .header {{ margin-bottom: 20px; border-bottom: 1px solid #1e293b; padding-bottom: 10px; }}
        h1 {{ font-size: 22px; color: #38bdf8; }}
        
        .nav-tabs {{ display: flex; gap: 8px; border-bottom: 2px solid #334155; margin-bottom: 20px; overflow-x: auto; }}
        .tab-btn {{ background: #1e293b; color: #94a3b8; border: none; padding: 12px 20px; border-radius: 8px 8px 0 0; cursor: pointer; font-weight: 600; font-size: 13px; whitespace: nowrap; }}
        .tab-btn.active {{ background: #0284c7; color: #fff; }}
        .tab-btn:hover:not(.active) {{ background: #334155; color: #f8fafc; }}
        
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .card-kpi {{ background: #1e293b; padding: 16px; border-radius: 10px; border: 1px solid #334155; }}
        .card-kpi p {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; }}
        .card-kpi h2 {{ font-size: 22px; color: #f8fafc; margin-top: 4px; }}

        .card-box {{ background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; margin-bottom: 20px; }}
        .search-input {{ width: 100%; padding: 10px; background: #0f172a; border: 1px solid #334155; color: #fff; border-radius: 6px; margin-bottom: 14px; font-size: 13px; outline: none; }}
        .search-input:focus {{ border-color: #38bdf8; }}

        .table-responsive {{ overflow-x: auto; max-height: 500px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }}
        th {{ background: #0f172a; color: #38bdf8; padding: 10px; border-bottom: 2px solid #334155; position: sticky; top: 0; }}
        td {{ padding: 10px; border-bottom: 1px solid #334155; }}
        tr:hover {{ background: #334155; }}
        .badge-danger {{ color: #ef4444; font-weight: bold; }}
        .badge-success {{ color: #22c55e; font-weight: bold; }}
    </style>
</head>
<body>

    <div class="header">
        <h1>Torre de Controle | Governança Integrada de Frota</h1>
    </div>

    <!-- Navegação Ramificada -->
    <div class="nav-tabs">
        <button class="tab-btn active" onclick="switchTab('tab-1')">Aba 1: Visão Macro</button>
        <button class="tab-btn" onclick="switchTab('tab-2')">Aba 2: Governança por GRE</button>
        <button class="tab-btn" onclick="switchTab('tab-3')">Aba 3: Fornecedores & Contratos</button>
        <button class="tab-btn" onclick="switchTab('tab-4')">Aba 4: Auditoria Motoristas & Rotas</button>
        <button class="tab-btn" onclick="switchTab('tab-5')">Aba 5: Manutenção & Chamados</button>
    </div>

    <!-- ABA 1: VISÃO MACRO -->
    <div id="tab-1" class="tab-content active">
        <div class="grid-kpi">
            <div class="card-kpi"><p>Veículos Ativos</p><h2>{int(df_kpi['veiculos_ativos'].iloc[0]) if not df_kpi.empty else 0}</h2></div>
            <div class="card-kpi"><p>Motoristas Ativos</p><h2>{int(df_kpi['motoristas_ativos'].iloc[0]) if not df_kpi.empty else 0}</h2></div>
            <div class="card-kpi"><p>Total Litros</p><h2>{float(df_kpi['total_litros'].iloc[0]):,.0f} L</h2></div>
            <div class="card-kpi"><p>Gasto Combustível</p><h2>R$ {float(df_kpi['total_gasto_combustivel'].iloc[0]):,.2f}</h2></div>
            <div class="card-kpi"><p>KM Executado</p><h2>{float(df_kpi['total_km'].iloc[0]):,.0f} KM</h2></div>
            <div class="card-kpi"><p>Manutenções Abertas</p><h2>{int(df_kpi['manutençoes_abertas'].iloc[0]) if not df_kpi.empty else 0}</h2></div>
        </div>
        <div class="card-box">
            <h3>Evolução Mensal de Quilometragem Executada</h3>
            <canvas id="chartMacroKm" style="max-height: 250px;"></canvas>
        </div>
    </div>

    <!-- ABA 2: GOVERNANÇA POR GRE -->
    <div id="tab-2" class="tab-content">
        <div class="card-box">
            <h3>Resumo por Gerência Regional de Ensino (GRE)</h3>
            <input type="text" id="searchGre" class="search-input" onkeyup="filterTable('searchGre', 'tableGre')" placeholder="Buscar por GRE...">
            <div class="table-responsive">
                <table id="tableGre">
                    <thead><tr><th>GRE</th><th>Rotas Mapeadas</th><th>Motoristas Alocados</th><th>Escalas Executadas</th><th>Anuladas</th><th>KM Total</th></tr></thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['gre']}</b></td><td>{r['total_rotas']}</td><td>{r['total_motoristas']}</td><td>{r['total_escalas']}</td><td class='badge-danger'>{r['rotas_anuladas']}</td><td>{r['km_total']:,.1f} KM</td></tr>" for _, r in df_gre.iterrows()]) if not df_gre.empty else "<tr><td colspan='6'>Nenhum registro encontrado.</td></tr>"}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ABA 3: FORNECEDORES -->
    <div id="tab-3" class="tab-content">
        <div class="card-box">
            <h3>Gestão de Terceirizados & Fornecedores</h3>
            <input type="text" id="searchForn" class="search-input" onkeyup="filterTable('searchForn', 'tableForn')" placeholder="Buscar Fornecedor...">
            <div class="table-responsive">
                <table id="tableForn">
                    <thead><tr><th>Fornecedor</th><th>Veículos Vinculados</th><th>Motoristas Vinculados</th><th>Litros Abastecidos</th><th>Custo Combustível</th></tr></thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['fornecedor']}</b></td><td>{r['total_veiculos']}</td><td>{r['total_motoristas']}</td><td>{r['total_litros']:,.2f} L</td><td>R$ {r['custo_combustivel']:,.2f}</td></tr>" for _, r in df_fornecedores.iterrows()]) if not df_fornecedores.empty else "<tr><td colspan='5'>Nenhum registro encontrado.</td></tr>"}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ABA 4: AUDITORIA MOTORISTAS -->
    <div id="tab-4" class="tab-content">
        <div class="card-box">
            <h3>Auditoria de Performance: KM GPS vs. Planejado</h3>
            <input type="text" id="searchMot" class="search-input" onkeyup="filterTable('searchMot', 'tableMot')" placeholder="Buscar Motorista, GRE ou Fornecedor...">
            <div class="table-responsive">
                <table id="tableMot">
                    <thead><tr><th>Motorista</th><th>GRE</th><th>Fornecedor</th><th>Viagens Realizadas</th><th>Anuladas</th><th>KM Planejado</th><th>KM GPS</th><th>Desvio (%)</th></tr></thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['motorista']}</b></td><td>{r['gre']}</td><td>{r['fornecedor']}</td><td>{r['total_escalas']}</td><td class='badge-danger'>{r['anuladas']}</td><td>{r['km_planejado']:,.1f} KM</td><td>{r['km_executado']:,.1f} KM</td><td class='{'badge-danger' if r['desvio_pct'] > 10 else 'badge-success'}'>{r['desvio_pct']}%</td></tr>" for _, r in df_motoristas.iterrows()]) if not df_motoristas.empty else "<tr><td colspan='8'>Nenhum registro encontrado.</td></tr>"}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ABA 5: MANUTENÇÃO -->
    <div id="tab-5" class="tab-content">
        <div class="card-box">
            <h3>Ordens de Serviço e Chamados de Manutenção</h3>
            <input type="text" id="searchMan" class="search-input" onkeyup="filterTable('searchMan', 'tableMan')" placeholder="Buscar Placa ou Descrição...">
            <div class="table-responsive">
                <table id="tableMan">
                    <thead><tr><th>Placa</th><th>Tipo Manutenção</th><th>Status</th><th>Descrição / Ocorrência</th><th>Registro / Data</th><th>Falha Humana</th></tr></thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['placa']}</b></td><td>{r['tipo_manutencao']}</td><td>{r['status']}</td><td>{r['descricao']}</td><td>{r['orcamento'] if r['orcamento'] else '-'}</td><td>{'SIM' if r['falha_humana'] else 'NÃO'}</td></tr>" for _, r in df_manutencao.iterrows()]) if not df_manutencao.empty else "<tr><td colspan='6'>Nenhum registro encontrado.</td></tr>"}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
        }}

        function filterTable(inputId, tableId) {{
            let filter = document.getElementById(inputId).value.toLowerCase();
            let rows = document.getElementById(tableId).getElementsByTagName("tr");
            for (let i = 1; i < rows.length; i++) {{
                let text = rows[i].innerText.toLowerCase();
                rows[i].style.display = text.indexOf(filter) > -1 ? "" : "none";
            }}
        }}

        new Chart(document.getElementById('chartMacroKm').getContext('2d'), {{
            type: 'line',
            data: {{
                labels: {json.dumps(df_macro_km['mes'].tolist()[::-1] if not df_macro_km.empty else [])},
                datasets: [{{
                    label: 'KM Executado',
                    data: {json.dumps(df_macro_km['km_total'].tolist()[::-1] if not df_macro_km.empty else [])},
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    fill: true,
                    tension: 0.3
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
