import psycopg2
import pandas as pd
import json

# Credenciais de Conexão
HOST = "aws-0-sa-east-1.pooler.supabase.com"
PORT = 5432
DATABASE = "postgres"
USER = "analista_bi.cuofycgznnbtpotybpuu"     # Substitua pelo seu usuário real
PASSWORD = "marvao#37m"   # Substitua pela sua senha real

conn = psycopg2.connect(
    host=HOST, port=PORT, database=DATABASE, user=USER, password=PASSWORD
)

# -------------------------------------------------------------
# 1. ABA 1: VISÃO MACRO & KPIS GLOBAIS
# -------------------------------------------------------------
df_kpi = pd.read_sql("""
SELECT 
    (SELECT COUNT(*) FROM airbyte.veiculos_veiculo WHERE status = 'ATIVO') as veiculos_ativos,
    (SELECT COUNT(*) FROM airbyte.motoristas_motorista WHERE status = 'ATIVO') as motoristas_ativos,
    (SELECT COALESCE(SUM(litros), 0) FROM airbyte.abastecimentos_abastecimento) as total_litros,
    (SELECT COALESCE(SUM(valor_total), 0) FROM airbyte.abastecimentos_abastecimento) as total_gasto_combustivel,
    (SELECT COALESCE(SUM(km_executado), 0) FROM airbyte.rotas_escalarota WHERE anulada = false) as total_km,
    (SELECT COUNT(*) FROM airbyte.ordens_chamado WHERE status = 'EM_ABERTO') as manutençoes_abertas
""", conn)

# Gráfico Macro: KM Executado por Mês/Período
df_macro_km = pd.read_sql("""
SELECT 
    TO_CHAR(data, 'YYYY-MM') as mes,
    SUM(km_executado) as km_total
FROM airbyte.rotas_escalarota
WHERE anulada = false AND data IS NOT NULL
GROUP BY TO_CHAR(data, 'YYYY-MM')
ORDER BY mes DESC
LIMIT 6;
""", conn)

# -------------------------------------------------------------
# 2. ABA 2: GOVERNANÇA POR GRE / REGIONAL
# -------------------------------------------------------------
df_gre = pd.read_sql("""
SELECT 
    COALESCE(g.nome, 'Não Atribuído') as gre,
    COUNT(DISTINCT r.id) as total_rotas,
    COUNT(DISTINCT re.escola_id) as total_escolas,
    COUNT(DISTINCT m.id) as total_motoristas,
    COUNT(DISTINCT e.id) as total_escalas,
    SUM(CASE WHEN e.anulada = true THEN 1 ELSE 0 END) as rotas_anuladas,
    COALESCE(SUM(e.km_executado), 0) as km_total
FROM airbyte.escolas_gre g
LEFT JOIN airbyte.rotas_rota r ON r.gre_id = g.id
LEFT JOIN airbyte.rotas_rota_escolas re ON re.rota_id = r.id
LEFT JOIN airbyte.motoristas_motorista m ON m.gre_id = g.id
LEFT JOIN airbyte.rotas_escalarota e ON e.rota_id = r.id
GROUP BY g.nome
ORDER BY total_escalas DESC;
""", conn)

# -------------------------------------------------------------
# 3. ABA 3: GESTÃO DE FORNECEDORES & CONTRATOS
# -------------------------------------------------------------
df_fornecedores = pd.read_sql("""
SELECT 
    COALESCE(f.nome, 'Frota Própria / Direto') as fornecedor,
    COUNT(DISTINCT v.id) as total_veiculos,
    COUNT(DISTINCT m.id) as total_motoristas,
    COALESCE(SUM(a.litros), 0) as total_litros,
    COALESCE(SUM(a.valor_total), 0) as custo_combustivel,
    COALESCE(SUM(v.valor_locacao), 0) as custo_locacao_estimado
FROM airbyte.motoristas_fornecedor f
LEFT JOIN airbyte.veiculos_veiculo v ON v.fornecedor_id = f.id
LEFT JOIN airbyte.motoristas_motorista m ON m.fornecedor_id = f.id
LEFT JOIN airbyte.abastecimentos_abastecimento a ON a.fornecedor_id = f.id
GROUP BY f.nome
ORDER BY total_litros DESC;
""", conn)

# -------------------------------------------------------------
# 4. ABA 4: AUDITORIA DE MOTORISTAS & ROTAS (GPS vs PLANEJADO)
# -------------------------------------------------------------
df_motoristas = pd.read_sql("""
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
LIMIT 100;
""", conn)

# -------------------------------------------------------------
# 5. ABA 5: MANUTENÇÃO & DISPONIBILIDADE
# -------------------------------------------------------------
df_manutencao = pd.read_sql("""
SELECT 
    v.placa,
    c.tipo_manutencao,
    c.status,
    c.descricao,
    c.diagnostico,
    COALESCE(c.orcamento, 0) as orcamento,
    c.falha_humana,
    c.emissao
FROM airbyte.ordens_chamado c
JOIN airbyte.veiculos_veiculo v ON c.veiculo_id = v.id
ORDER BY c.emissao DESC
LIMIT 100;
""", conn)

# Gráfico de Tipos de Manutenção
df_manutencao_chart = pd.read_sql("""
SELECT 
    COALESCE(tipo_manutencao, 'Não Especificado') as tipo,
    COUNT(*) as qtd
FROM airbyte.ordens_chamado
GROUP BY tipo_manutencao
ORDER BY qtd DESC;
""", conn)

conn.close()

# -------------------------------------------------------------
# CONSTRUÇÃO DO DASHBOARD HTML INTERATIVO (SPA)
# -------------------------------------------------------------
html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Torre de Controle & Governança de Frota</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; }}
        
        .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 1px solid #1e293b; padding-bottom: 16px; }}
        h1 {{ font-size: 22px; font-weight: 700; color: #38bdf8; }}
        .sub-header {{ font-size: 13px; color: #94a3b8; }}

        /* Menu de Navegação em Abas */
        .nav-tabs {{ display: flex; gap: 8px; border-bottom: 2px solid #334155; margin-bottom: 24px; overflow-x: auto; }}
        .tab-btn {{ background: #1e293b; color: #94a3b8; border: none; padding: 12px 20px; border-radius: 8px 8px 0 0; cursor: pointer; font-weight: 600; font-size: 13px; transition: 0.2s; whitespace: nowrap; }}
        .tab-btn.active {{ background: #0284c7; color: #ffffff; border-bottom: 2px solid #38bdf8; }}
        .tab-btn:hover:not(.active) {{ background: #334155; color: #f8fafc; }}
        
        .tab-content {{ display: none; }}
        .tab-content.active {{ display: block; }}

        /* Grid de KPIs */
        .grid-kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card-kpi {{ background: #1e293b; padding: 18px; border-radius: 10px; border: 1px solid #334155; }}
        .card-kpi p {{ font-size: 11px; color: #94a3b8; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; }}
        .card-kpi h2 {{ font-size: 24px; color: #f8fafc; margin-top: 6px; font-weight: 700; }}

        /* Containers de Conteúdo e Tabelas */
        .card-box {{ background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; margin-bottom: 24px; }}
        .card-box h3 {{ font-size: 16px; color: #cbd5e1; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }}

        /* Input de Pesquisa Rápida */
        .search-input {{ width: 100%; padding: 10px 14px; background: #0f172a; border: 1px solid #334155; color: #fff; border-radius: 6px; margin-bottom: 16px; font-size: 13px; outline: none; }}
        .search-input:focus {{ border-color: #38bdf8; }}

        /* Tabelas Estilizadas */
        .table-responsive {{ overflow-x: auto; max-height: 500px; overflow-y: auto; }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
        th {{ background: #0f172a; color: #38bdf8; padding: 12px; border-bottom: 2px solid #334155; position: sticky; top: 0; z-index: 10; font-weight: 600; }}
        td {{ padding: 12px; border-bottom: 1px solid #334155; color: #e2e8f0; }}
        tr:hover {{ background: #334155; }}
        
        /* Badges de Destaque */
        .badge-danger {{ color: #ef4444; font-weight: 700; }}
        .badge-warning {{ color: #f59e0b; font-weight: 700; }}
        .badge-success {{ color: #22c55e; font-weight: 700; }}
        
        .grid-charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 20px; margin-bottom: 24px; }}
    </style>
</head>
<body>

    <div class="header">
        <div>
            <h1>Torre de Controle | Governança Integrada de Frota</h1>
            <div class="sub-header">Painel Unificado de Monitoramento Operacional, Custos e Compliance</div>
        </div>
    </div>

    <!-- Navegação por Abas -->
    <div class="nav-tabs">
        <button class="tab-btn active" onclick="switchTab('tab-1')">Aba 1: Visão Macro & KPIs</button>
        <button class="tab-btn" onclick="switchTab('tab-2')">Aba 2: Governança por GRE</button>
        <button class="tab-btn" onclick="switchTab('tab-3')">Aba 3: Fornecedores & Contratos</button>
        <button class="tab-btn" onclick="switchTab('tab-4')">Aba 4: Auditoria Motoristas & Rotas</button>
        <button class="tab-btn" onclick="switchTab('tab-5')">Aba 5: Manutenção & Disponibilidade</button>
    </div>

    <!-- ABA 1: VISÃO MACRO -->
    <div id="tab-1" class="tab-content active">
        <div class="grid-kpi">
            <div class="card-kpi"><p>Veículos Ativos</p><h2>{int(df_kpi['veiculos_ativos'].iloc[0])}</h2></div>
            <div class="card-kpi"><p>Motoristas Ativos</p><h2>{int(df_kpi['motoristas_ativos'].iloc[0])}</h2></div>
            <div class="card-kpi"><p>Total Litros Abastecidos</p><h2>{float(df_kpi['total_litros'].iloc[0]):,.0f} L</h2></div>
            <div class="card-kpi"><p>Gasto Combustível</p><h2>R$ {float(df_kpi['total_gasto_combustivel'].iloc[0]):,.2f}</h2></div>
            <div class="card-kpi"><p>KM Executado</p><h2>{float(df_kpi['total_km'].iloc[0]):,.0f} KM</h2></div>
            <div class="card-kpi"><p>Manutenções Abertas</p><h2>{int(df_kpi['manutençoes_abertas'].iloc[0])}</h2></div>
        </div>

        <div class="card-box">
            <h3>Evolução Mensal de Quilometragem Executada (KM)</h3>
            <canvas id="chartMacroKm" style="max-height: 280px;"></canvas>
        </div>
    </div>

    <!-- ABA 2: GOVERNANÇA POR GRE -->
    <div id="tab-2" class="tab-content">
        <div class="card-box">
            <h3>Detalhamento por Gerência Regional de Ensino (GRE)</h3>
            <input type="text" id="searchGre" class="search-input" onkeyup="filterTable('searchGre', 'tableGre')" placeholder="Filtrar por nome da GRE...">
            <div class="table-responsive">
                <table id="tableGre">
                    <thead>
                        <tr>
                            <th>Regional (GRE)</th>
                            <th>Escolas Atendidas</th>
                            <th>Rotas Mapeadas</th>
                            <th>Motoristas Alocados</th>
                            <th>Escalas Executadas</th>
                            <th>Rotas Anuladas</th>
                            <th>KM Executado</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['gre']}</b></td><td>{r['total_escolas']}</td><td>{r['total_rotas']}</td><td>{r['total_motoristas']}</td><td>{r['total_escalas']}</td><td class='badge-danger'>{r['rotas_anuladas']}</td><td>{r['km_total']:,.1f} KM</td></tr>" for _, r in df_gre.iterrows()])}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ABA 3: FORNECEDORES & CONTRATOS -->
    <div id="tab-3" class="tab-content">
        <div class="card-box">
            <h3>Acompanhamento por Fornecedor & Empresas Terceirizadas</h3>
            <input type="text" id="searchForn" class="search-input" onkeyup="filterTable('searchForn', 'tableForn')" placeholder="Filtrar por Fornecedor...">
            <div class="table-responsive">
                <table id="tableForn">
                    <thead>
                        <tr>
                            <th>Fornecedor</th>
                            <th>Frota Alocada</th>
                            <th>Motoristas Vinculados</th>
                            <th>Consumo Combustível (L)</th>
                            <th>Custo Combustível (R$)</th>
                            <th>Locação Estimada (R$)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['fornecedor']}</b></td><td>{r['total_veiculos']}</td><td>{r['total_motoristas']}</td><td>{r['total_litros']:,.2f} L</td><td class='badge-warning'>R$ {r['custo_combustivel']:,.2f}</td><td>R$ {r['custo_locacao_estimado']:,.2f}</td></tr>" for _, r in df_fornecedores.iterrows()])}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ABA 4: AUDITORIA MOTORISTAS & ROTAS -->
    <div id="tab-4" class="tab-content">
        <div class="card-box">
            <h3>Auditoria de Performance: KM GPS vs. Planejado & Rotas Anuladas</h3>
            <input type="text" id="searchMot" class="search-input" onkeyup="filterTable('searchMot', 'tableMot')" placeholder="Buscar Motorista, GRE ou Fornecedor...">
            <div class="table-responsive">
                <table id="tableMot">
                    <thead>
                        <tr>
                            <th>Motorista</th>
                            <th>GRE</th>
                            <th>Fornecedor</th>
                            <th>Viagens Realizadas</th>
                            <th>Viagens Anuladas</th>
                            <th>KM Planejado</th>
                            <th>KM Executado (GPS)</th>
                            <th>Desvio (%)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['motorista']}</b></td><td>{r['gre']}</td><td>{r['fornecedor']}</td><td>{r['total_escalas']}</td><td class='badge-danger'>{r['anuladas']}</td><td>{r['km_planejado']:,.1f} KM</td><td>{r['km_executado']:,.1f} KM</td><td class='{'badge-danger' if r['desvio_pct'] > 10 else 'badge-success'}'>{r['desvio_pct']}%</td></tr>" for _, r in df_motoristas.iterrows()])}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ABA 5: MANUTENÇÃO & DISPONIBILIDADE -->
    <div id="tab-5" class="tab-content">
        <div class="grid-charts">
            <div class="card-box">
                <h3>Ocorrências por Tipo de Manutenção</h3>
                <canvas id="chartManutencao" style="max-height: 250px;"></canvas>
            </div>
        </div>
        <div class="card-box">
            <h3>Chamados e Ordens de Serviço Recentes</h3>
            <input type="text" id="searchMan" class="search-input" onkeyup="filterTable('searchMan', 'tableMan')" placeholder="Buscar por Placa, Diagnóstico ou Status...">
            <div class="table-responsive">
                <table id="tableMan">
                    <thead>
                        <tr>
                            <th>Placa</th>
                            <th>Tipo Manutenção</th>
                            <th>Status</th>
                            <th>Descrição / Ocorrência</th>
                            <th>Diagnóstico</th>
                            <th>Orçamento (R$)</th>
                            <th>Falha Humana</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join([f"<tr><td><b>{r['placa']}</b></td><td>{r['tipo_manutencao']}</td><td><span class='badge-warning'>{r['status']}</span></td><td>{r['descricao']}</td><td>{r['diagnostico']}</td><td>R$ {r['orcamento']:,.2f}</td><td class='{'badge-danger' if r['falha_humana'] else ''}'>{'SIM' if r['falha_humana'] else 'NÃO'}</td></tr>" for _, r in df_manutencao.iterrows()])}
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        // Função de Troca de Abas
        function switchTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
        }}

        // Função de Filtro de Busca nas Tabelas
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

        // Gráfico Macro (KM Executado)
        new Chart(document.getElementById('chartMacroKm').getContext('2d'), {{
            type: 'line',
            data: {{
                labels: {json.dumps(df_macro_km['mes'].tolist()[::-1])},
                datasets: [{{
                    label: 'KM Executado',
                    data: {json.dumps(df_macro_km['km_total'].tolist()[::-1])},
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    fill: true,
                    tension: 0.3
                }}]
            }},
            options: {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }}
        }});

        // Gráfico de Tipos de Manutenção
        new Chart(document.getElementById('chartManutencao').getContext('2d'), {{
            type: 'doughnut',
            data: {{
                labels: {json.dumps(df_manutencao_chart['tipo'].tolist())},
                datasets: [{{
                    data: {json.dumps(df_manutencao_chart['qtd'].tolist())},
                    backgroundColor: ['#ef4444', '#f59e0b', '#38bdf8', '#10b981', '#8b5cf6']
                }}]
            }},
            options: {{ responsive: true }}
        }});
    </script>
</body>
</html>
"""

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_content)
