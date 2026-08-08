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

# 1. KPIs Globais
df_kpi = pd.read_sql("""
SELECT 
    (SELECT COUNT(*) FROM airbyte.veiculos_veiculo WHERE status = 'ATIVO') as veiculos_ativos,
    (SELECT COUNT(*) FROM airbyte.motoristas_motorista WHERE status = 'ATIVO') as motoristas_ativos,
    (SELECT COALESCE(SUM(litros), 0) FROM airbyte.abastecimentos_abastecimento) as total_litros,
    (SELECT COALESCE(SUM(km_executado), 0) FROM airbyte.rotas_escalarota WHERE anulada = false) as total_km,
    (SELECT COUNT(*) FROM airbyte.ordens_chamado WHERE status = 'EM_ABERTO') as manutençoes_abertas
""", conn)

# 2. Detalhamento por GRE / Regional
df_gre = pd.read_sql("""
SELECT 
    COALESCE(g.nome, 'Não Atribuído') as gre,
    COUNT(DISTINCT r.id) as total_rotas,
    COUNT(DISTINCT e.id) as total_escalas,
    SUM(CASE WHEN e.anulada = true THEN 1 ELSE 0 END) as rotas_anuladas,
    COALESCE(SUM(e.km_executado), 0) as km_total
FROM airbyte.escolas_gre g
LEFT JOIN airbyte.rotas_rota r ON r.gre_id = g.id
LEFT JOIN airbyte.rotas_escalarota e ON e.rota_id = r.id
GROUP BY g.nome
ORDER BY total_escalas DESC;
""", conn)

# 3. Detalhamento por Fornecedor
df_fornecedores = pd.read_sql("""
SELECT 
    COALESCE(f.nome, 'Próprio / Direto') as fornecedor,
    COUNT(DISTINCT v.id) as total_veiculos,
    COUNT(DISTINCT m.id) as total_motoristas,
    COALESCE(SUM(a.litros), 0) as total_litros,
    COALESCE(SUM(a.valor_total), 0) as custo_total
FROM airbyte.motoristas_fornecedor f
LEFT JOIN airbyte.veiculos_veiculo v ON v.fornecedor_id = f.id
LEFT JOIN airbyte.motoristas_motorista m ON m.fornecedor_id = f.id
LEFT JOIN airbyte.abastecimentos_abastecimento a ON a.fornecedor_id = f.id
GROUP BY f.nome
ORDER BY total_litros DESC;
""", conn)

# 4. Detalhamento por Motorista & Rotas
df_motoristas = pd.read_sql("""
SELECT 
    m.nome as motorista,
    COALESCE(g.nome, 'N/A') as gre,
    COALESCE(f.nome, 'Direto') as fornecedor,
    COUNT(e.id) as total_viagens,
    SUM(CASE WHEN e.anulada = true THEN 1 ELSE 0 END) as anuladas,
    COALESCE(SUM(e.km_executado), 0) as km_executado
FROM airbyte.motoristas_motorista m
LEFT JOIN airbyte.escolas_gre g ON m.gre_id = g.id
LEFT JOIN airbyte.motoristas_fornecedor f ON m.fornecedor_id = f.id
LEFT JOIN airbyte.rotas_escalarota e ON e.motorista_id = m.id
GROUP BY m.nome, g.nome, f.nome
ORDER BY km_executado DESC
LIMIT 50;
""", conn)

# 5. Detalhamento Manutenção e Chamados
df_manutencao = pd.read_sql("""
SELECT 
    v.placa,
    c.tipo_manutencao,
    c.status,
    c.descricao,
    c.orcamento,
    c.falha_humana
FROM airbyte.ordens_chamado c
JOIN airbyte.veiculos_veiculo v ON c.veiculo_id = v.id
ORDER BY c.emissao DESC
LIMIT 50;
""", conn)

conn.close()

# Estruturação HTML com NAVEGAÇÃO POR ABAS (SPA)
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Torre de Controle | Governança Ramificada</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
        
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }}
        h1 {{ font-size: 22px; color: #38bdf8; }}
        
        /* Menu por Abas */
        .nav-tabs {{ display: flex; gap: 8px; border-bottom: 2px solid #334155; margin-bottom: 20px; }}
        .tab-btn {{ background: #1e293b; color: #94a3b8; border: none; padding: 12px 20px; border-radius: 8px 8px 0 0; cursor: pointer; font-weight: 600; font-size: 14px; transition: 0.2s; }}
        .tab-btn.active {{ background: #0284c7; color: #fff; }}
        .tab-btn:hover:not(.active) {{ background: #334155; color: #f8fafc; }}
        
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 20px; }}
        .card-kpi {{ background: #1e293b; padding: 16px; border-radius: 10px; border: 1px solid #334155; }}
        .card-kpi p {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; }}
        .card-kpi h2 {{ font-size: 24px; color: #f8fafc; margin-top: 4px; }}

        .card-box {{ background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; margin-bottom: 20px; }}
        
        /* Filtros e Busca */
        .search-input {{ width: 100%; padding: 10px 14px; background: #0f172a; border: 1px solid #334155; color: #fff; border-radius: 6px; margin-bottom: 14px; font-size: 14px; }}

        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
        th {{ background: #0f172a; color: #38bdf8; padding: 12px; border-bottom: 2px solid #334155; position: sticky; top: 0; }}
        td {{ padding: 10px; border-bottom: 1px solid #334155; }}
        tr:hover {{ background: #334155; }}
        .badge-danger {{ color: #ef4444; font-weight: bold; }}
        .badge-success {{ color: #22c55e; font-weight: bold; }}
    </style>
</head>
<body>

    <div class="header">
        <h1>Torre de Controle de Frota | Sistema de Governança Integrado</h1>
    </div>

    <!-- Navegação Principais Ramificações -->
    <div class="nav-tabs">
        <button class="tab-btn active" onclick="switchTab('tab-macro')">Visão Geral Macro</button>
        <button class="tab-btn" onclick="switchTab('tab-gre')">Ramificação por GRE</button>
        <button class="tab-btn" onclick="switchTab('tab-fornecedores')">Fornecedores & Terceiros</button>
        <button class="tab-btn" onclick="switchTab('tab-motoristas')">Motoristas & Operação</button>
        <button class="tab-btn" onclick="switchTab('tab-manutencao')">Manutenção & Chamados</button>
    </div>

    <!-- ABA 1: VISÃO MACRO -->
    <div id="tab-macro" class="tab-content active">
        <div class="grid-kpi">
            <div class="card-kpi"><p>Veículos Ativos</p><h2>{int(df_kpi['veiculos_ativos'].iloc[0])}</h2></div>
            <div class="card-kpi"><p>Motoristas Ativos</p><h2>{int(df_kpi['motoristas_ativos'].iloc[0])}</h2></div>
            <div class="card-kpi"><p>Litros Abastecidos</p><h2>{float(df_kpi['total_litros'].iloc[0]):,.0f} L</h2></div>
            <div class="card-kpi"><p>KM Executado</p><h2>{float(df_kpi['total_km'].iloc[0]):,.0f} KM</h2></div>
            <div class="card-kpi"><p>Manutenções Abertas</p><h2>{int(df_kpi['manutençoes_abertas'].iloc[0])}</h2></div>
        </div>
        <div class="card-box">
            <h3>Visão Geral da Operação</h3>
            <p style="color: #94a3b8; margin-top: 8px;">Selecione uma das abas acima para navegar pelas ramificações e detalhar informações por Regional (GRE), Fornecedor, Motorista ou Ordens de Serviço.</p>
        </div>
    </div>

    <!-- ABA 2: REGIONAIS (GRE) -->
    <div id="tab-gre" class="tab-content">
        <div class="card-box">
            <h3>Detalhamento por Gerência Regional (GRE)</h3>
            <input type="text" id="searchGre" class="search-input" onkeyup="filterTable('searchGre', 'tableGre')" placeholder="Buscar por GRE...">
            <table id="tableGre">
                <thead>
                    <tr><th>GRE / Regional</th><th>Total Rotas</th><th>Escalas Executadas</th><th>Escalas Anuladas</th><th>KM Total</th></tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td><b>{r['gre']}</b></td><td>{r['total_rotas']}</td><td>{r['total_escalas']}</td><td class='badge-danger'>{r['rotas_anuladas']}</td><td>{r['km_total']:,.1f} KM</td></tr>" for _, r in df_gre.iterrows()])}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ABA 3: FORNECEDORES -->
    <div id="tab-fornecedores" class="tab-content">
        <div class="card-box">
            <h3>Desempenho e Custos por Fornecedor / Terceirizado</h3>
            <input type="text" id="searchForn" class="search-input" onkeyup="filterTable('searchForn', 'tableForn')" placeholder="Buscar por Fornecedor...">
            <table id="tableForn">
                <thead>
                    <tr><th>Fornecedor</th><th>Veículos Vinculados</th><th>Motoristas</th><th>Total Litros</th><th>Custo Total (R$)</th></tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td><b>{r['fornecedor']}</b></td><td>{r['total_veiculos']}</td><td>{r['total_motoristas']}</td><td>{r['total_litros']:,.2f} L</td><td>R$ {r['custo_total']:,.2f}</td></tr>" for _, r in df_fornecedores.iterrows()])}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ABA 4: MOTORISTAS -->
    <div id="tab-motoristas" class="tab-content">
        <div class="card-box">
            <h3>Performance Individual dos Motoristas</h3>
            <input type="text" id="searchMot" class="search-input" onkeyup="filterTable('searchMot', 'tableMot')" placeholder="Buscar por Motorista, GRE ou Fornecedor...">
            <table id="tableMot">
                <thead>
                    <tr><th>Motorista</th><th>GRE</th><th>Fornecedor</th><th>Viagens Executadas</th><th>Viagens Anuladas</th><th>KM Executado</th></tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td><b>{r['motorista']}</b></td><td>{r['gre']}</td><td>{r['fornecedor']}</td><td>{r['total_viagens']}</td><td class='badge-danger'>{r['anuladas']}</td><td>{r['km_executado']:,.1f} KM</td></tr>" for _, r in df_motoristas.iterrows()])}
                </tbody>
            </table>
        </div>
    </div>

    <!-- ABA 5: MANUTENÇÃO -->
    <div id="tab-manutencao" class="tab-content">
        <div class="card-box">
            <h3>Ordens de Serviço e Chamados de Manutenção</h3>
            <input type="text" id="searchMan" class="search-input" onkeyup="filterTable('searchMan', 'tableMan')" placeholder="Buscar por Placa ou Diagnóstico...">
            <table id="tableMan">
                <thead>
                    <tr><th>Placa</th><th>Tipo</th><th>Status</th><th>Descrição</th><th>Orçamento (R$)</th><th>Falha Humana</th></tr>
                </thead>
                <tbody>
                    {''.join([f"<tr><td><b>{r['placa']}</b></td><td>{r['tipo_manutencao']}</td><td>{r['status']}</td><td>{r['descricao']}</td><td>R$ {r['orcamento'] if r['orcamento'] else 0:,.2f}</td><td>{'SIM' if r['falha_humana'] else 'NÃO'}</td></tr>" for _, r in df_manutencao.iterrows()])}
                </tbody>
            </table>
        </div>
    </div>

    <script>
        // Alternar entre Abas
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
        }}

        // Filtro de Busca Dinâmico nas Tabelas
        function filterTable(inputId, tableId) {{
            let input = document.getElementById(inputId);
            let filter = input.value.toLowerCase();
            let rows = document.getElementById(tableId).getElementsByTagName("tr");
            
            for (let i = 1; i < rows.length; i++) {{
                let cells = rows[i].getElementsByTagName("td");
                let match = false;
                for (let j = 0; j < cells.length; j++) {{
                    if (cells[j] && cells[j].innerText.toLowerCase().indexOf(filter) > -1) {{
                        match = true;
                        break;
                    }}
                }}
                rows[i].style.display = match ? "" : "none";
            }}
        }}
    </script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
