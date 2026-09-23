"""Componente financeiro incorporado ao gerador; somente consultas de leitura."""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo


def carregar_centro(conn, inicio):
    from psycopg2.extras import RealDictCursor
    consultas = {
        'frota': '''SELECT id, placa, status, tipo_contrato_locacao
                    FROM airbyte.veiculos_veiculo''',
        'manutencao': '''SELECT DISTINCT veiculo_id FROM airbyte.ordens_chamado
                         WHERE status = 'CO' AND veiculo_id IS NOT NULL''',
        'contratos': '''SELECT c.id, c.status, c.data_inicio, c.data_fim,
            COALESCE(f.nome,'SEM PRESTADOR') AS prestador
            FROM airbyte.contratos_contrato c
            LEFT JOIN airbyte.motoristas_fornecedor f ON f.id=c.fornecedor_id
            WHERE c.data_inicio <= CURRENT_DATE
              AND (c.data_fim IS NULL OR c.data_fim >= %s::date)
              AND c.status IN ('A','I')''',
        'itens': '''SELECT id, contrato_id, status, modalidade_pagamento,
            valor_unitario, veiculo_id FROM airbyte.contratos_itemcontrato''',
        'escalas': '''SELECT e.id, e.data::date AS data, e.tipo_rota,
            e.contrato_rota_id, e.veiculo_execucao_id,
            e.inicio_execucao IS NOT NULL AS iniciou,
            e.fim_execucao IS NOT NULL AS terminou,
            e.km_executado, e.observacao,
            COALESCE(r.nome,'SEM ROTA') AS rota,
            COALESCE(v.placa,'SEM VEÍCULO REGISTRADO') AS placa,
            COALESCE(m.nome,'SEM MOTORISTA') AS motorista
            FROM airbyte.rotas_escalarota e
            LEFT JOIN airbyte.rotas_rota r ON r.id=e.rota_id
            LEFT JOIN airbyte.veiculos_veiculo v ON v.id=e.veiculo_execucao_id
            LEFT JOIN airbyte.motoristas_motorista m ON m.id=e.motorista_id
            WHERE e.data >= %s::date AND e.data < CURRENT_DATE + INTERVAL '1 day'
              AND e.anulada=false''',
        # Inclui contratos antigos para identificar conflitos fora da janela de vigência.
        'vinculos': '''SELECT c.id, c.status, c.data_inicio, c.data_fim,
            COALESCE(f.nome,'SEM PRESTADOR') AS prestador
            FROM airbyte.contratos_contrato c
            LEFT JOIN airbyte.motoristas_fornecedor f ON f.id=c.fornecedor_id''',
    }
    dados = {}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        for nome, sql in consultas.items():
            cur.execute(sql, (inicio,) if '%s' in sql else None)
            dados[nome] = [dict(r) for r in cur.fetchall()]
    dados['inicio'] = inicio
    dados['hoje'] = datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
    dados['atualizado'] = datetime.now(ZoneInfo('America/Sao_Paulo')).isoformat(timespec='seconds')
    return dados


def preparar_financeiro(dados):
    """Dias elegíveis por contrato; composição não verificável fica sem valor automático."""
    contratos = {str(c['id']): c for c in dados['vinculos']}
    itens = {str(i['id']): i for i in dados['itens']}
    grupos = {}
    for i in dados['itens']:
        grupos.setdefault(str(i['contrato_id']), []).append(i)
    for c in dados['vinculos']:
        membros = grupos.get(str(c['id']), [])
        # Encerramento de itens não tem vigência própria disponível.
        # Nunca presumir que todos os itens encerrados eram simultaneamente devidos.
        c['composicao_pendente'] = (not membros or any(
            i['status'] != 'ATIVO' or i['valor_unitario'] is None
            or i['modalidade_pagamento'] not in ('DIARIA', 'MENSAL')
            for i in membros))
        c['diaria'] = sum(float(i['valor_unitario'] or 0) for i in membros
                          if i['modalidade_pagamento'] == 'DIARIA' and i['status'] == 'ATIVO')
        c['mensal'] = sum(float(i['valor_unitario'] or 0) for i in membros
                          if i['modalidade_pagamento'] == 'MENSAL' and i['status'] == 'ATIVO')
        c['tem_diaria'] = any(i['modalidade_pagamento'] == 'DIARIA' for i in membros)
        c['tem_mensal'] = any(i['modalidade_pagamento'] == 'MENSAL' for i in membros)
    dias = {}
    for e in dados['escalas']:
        i = itens.get(str(e['contrato_rota_id']))
        c = contratos.get(str(i['contrato_id'])) if i else None
        e['contrato_id'] = c['id'] if c else None
        d = str(e['data'])[:10]
        # Extras seguem fila de lançamento manual e não liberam diária automática.
        if not (c and e['tipo_rota'] == 'RR' and e['iniciou'] and e['terminou']):
            continue
        if not c['data_inicio'] or d < str(c['data_inicio'])[:10]:
            continue
        if c['data_fim'] and d > str(c['data_fim'])[:10]:
            continue
        if c['status'] not in ('A','I') or not c['tem_diaria']:
            continue
        chave = (str(c['id']), d)
        dias[chave] = {'data': d, 'contrato_id': c['id'],
                       'valor': None if c['composicao_pendente'] else c['diaria']}
    dados['diarias'] = list(dias.values())
    # Usa os mesmos objetos enriquecidos.
    dados['contratos'] = [contratos[str(c['id'])] for c in dados['contratos']]
    return dados


def componente(dados):
    payload = json.dumps(dados, ensure_ascii=False, default=str, allow_nan=False)
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return TEMPLATE.replace('__DADOS__', payload)


TEMPLATE = r'''
<style>
#ct{--bg:#091522;--panel:#122432;--line:#2a4357;--ink:#eaf3fa;--muted:#9bb1c2;color:var(--ink);background:var(--bg);padding:26px;font:14px system-ui,sans-serif;border-bottom:4px solid #22ba9b}
#ct *{box-sizing:border-box}#ct h1{margin:0;font-size:26px}#ct h2{font-size:15px;text-transform:uppercase;margin:0 0 16px}#ct p{color:var(--muted);line-height:1.6}#ct .ct-head,#ct .ct-filters{display:flex;gap:16px;flex-wrap:wrap;align-items:end;justify-content:space-between}#ct .ct-filters{justify-content:start;margin:20px 0}#ct label{display:grid;gap:6px;color:var(--muted);font-size:12px}#ct input,#ct select,#ct button{background:#183144;color:var(--ink);border:1px solid #476275;padding:10px;border-radius:7px;font:inherit}#ct button{cursor:pointer;background:#087e73}#ct button:focus-visible,#ct input:focus-visible,#ct select:focus-visible{outline:3px solid #47bfff;outline-offset:2px}#ct .ct-contract-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:14px}#ct .ct-contract-cards strong{font-size:32px}#ct .ct-contract-cards .ct-base{padding-top:12px;border-top:1px solid var(--line);display:block}#ct .ct-kpis{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:14px}#ct .ct-card{background:var(--panel);border:1px solid var(--line);border-radius:13px;padding:18px;min-width:0}#ct .ct-kpi strong{display:block;font-size:clamp(22px,2.5vw,36px);font-weight:500;margin:12px 0;overflow-wrap:anywhere}#ct .ct-kpi span{font-size:12px;color:var(--muted)}#ct .ct-kpi:nth-child(4){background:#123e3d;border-color:#239a86}#ct .ct-main{display:grid;grid-template-columns:3fr 1fr;gap:14px;margin-top:16px}#ct .ct-bottom{display:grid;grid-template-columns:2fr 1.3fr 1fr;gap:14px;margin-top:16px}#ct .ct-scroll{overflow:auto;max-height:430px}#ct table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:12px}#ct th,#ct td{padding:11px 10px;border-bottom:1px solid var(--line);text-align:left}#ct th{color:#c6d9e7;background:#183043;position:sticky;top:0}#ct .ct-badge{display:inline-block;padding:4px 8px;border-radius:5px;background:#1b6759}#ct .ct-warn{background:#725326}#ct .ct-alert{padding:12px;background:#53282e;border:1px solid #94505b;border-radius:8px;margin-bottom:10px;line-height:1.6}#ct .ct-note{font-size:12px}#ct .ct-bar{margin:12px 0}#ct .ct-bar label{display:flex;justify-content:space-between;margin-bottom:5px}#ct .ct-bar i{display:block;height:12px;background:#18a6e5;border-radius:4px}#ct .ct-plot{width:100%;height:180px}#ct details{margin-top:16px}#ct summary{cursor:pointer;font-weight:600;padding:10px 0}#ct [hidden]{display:none!important}#ct .ct-error{color:#ffb9b9}#ct .ct-status{font-size:12px;color:#76dcca}#ct .ct-tabs{display:flex;gap:10px;margin-top:18px;flex-wrap:wrap}#ct .ct-muted{color:var(--muted)}@media(max-width:1000px){#ct .ct-kpis{grid-template-columns:repeat(2,1fr)}#ct .ct-main,#ct .ct-bottom{grid-template-columns:1fr}}@media(max-width:600px){#ct{padding:14px}#ct .ct-contract-cards{grid-template-columns:1fr}#ct .ct-kpis{grid-template-columns:1fr}#ct h1{font-size:22px}}
</style>
<section id="ct" aria-label="Control Tower financeiro">
<div class="ct-head"><div><div class="ct-status">LOG-PI / CONTROL TOWER</div><h1>Contratos e demandas extras</h1></div><div id="ct-update" class="ct-muted"></div></div>
<div class="ct-filters"><label>Consulta<select id="ct-mode"><option value="month">Mês e ano</option><option value="range">Período personalizado</option></select></label><label id="ct-month-wrap">Mês<input id="ct-month" type="month"></label><label id="ct-start-wrap" hidden>Data inicial<input id="ct-start" type="date"></label><label id="ct-end-wrap" hidden>Data final<input id="ct-end" type="date"></label><button id="ct-apply" type="button">Aplicar período</button></div>
<p id="ct-period" role="status"></p><p id="ct-error" class="ct-error" role="alert"></p>
<div class="ct-kpis" id="ct-kpis"></div>
<div class="ct-main"><article class="ct-card"><h2>Rotas e diárias — últimos 3 dias do período</h2><div class="ct-scroll" id="ct-recent"></div></article><aside class="ct-card"><h2>Alertas de operação</h2><div id="ct-alerts"></div></aside></div>
<div class="ct-bottom"><article class="ct-card"><h2>Diárias acumuladas no período</h2><div id="ct-trend"></div><p class="ct-note">Mensalidades são integrais por competência e aparecem separadas abaixo. Orçamento não informado.</p></article><article class="ct-card"><h2>Valor apurado por prestador</h2><div id="ct-suppliers"></div></article><article class="ct-card"><h2>Veículos com registro no período</h2><div id="ct-fleet"></div><p class="ct-note">Não representa disponibilidade ou estado de manutenção.</p></article></div>
<p class="ct-note">Valores apurados com o cadastro disponível, não comprovam pagamento. Contratos com itens encerrados, suspensos ou incompletos ficam pendentes de conferência da composição, sem valor automático. Histórico de alterações dos valores não disponível.</p>
<details open class="ct-card"><summary>Composição financeira — diárias e mensalidades</summary><div id="ct-finance" class="ct-scroll"></div></details>
<details open class="ct-card"><summary>Conflitos de execução após encerramento</summary><div id="ct-conflicts" class="ct-scroll"></div></details>
<details open class="ct-card"><summary>Demandas extras — EX, AB, AP e SA</summary><p id="ct-extra-summary"></p><p class="ct-note">Tipo informado pelo motorista. Início registrado conta como concluída para controle de extras. Valores aguardam lançamento pelo coordenador e não entram automaticamente na apuração.</p><div id="ct-extras" class="ct-scroll"></div></details>
<div class="ct-bottom"><article class="ct-card"><h2>Vínculo da frota ativa — cadastro atual</h2><div id="ct-fleet-pie"></div></article><article class="ct-card"><h2>Ativos e inativos — cadastro atual</h2><div id="ct-fleet-status"></div></article><article class="ct-card"><h2>Veículos em manutenção — cadastro atual</h2><div id="ct-maintenance"></div><p class="ct-note">Critério herdado do painel anterior: chamado com status CO (oficina). Veículos distintos, mesmo com vários chamados. Não somar manutenção a ativos/inativos.</p></article></div><p class="ct-note">Os gráficos de cadastro da frota refletem a última atualização e não variam com o período. Não há histórico cadastral disponível.</p>
</section>
<script type="application/json" id="ct-data">__DADOS__</script>
<script>
(()=>{'use strict';
const D=JSON.parse(document.getElementById('ct-data').textContent),$=id=>document.getElementById(id), money=v=>v===null?'A conferir':Number(v).toLocaleString('pt-BR',{style:'currency',currency:'BRL'}),esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),day=v=>String(v||'').slice(0,10),br=v=>v?day(v).split('-').reverse().join('/'):'—';
const C=new Map(D.vinculos.map(c=>[String(c.id),c])),I=new Map(D.itens.map(i=>[String(i.id),i])), vehicleContracts=new Map();
D.itens.forEach(i=>{if(i.veiculo_id!=null){const k=String(i.veiculo_id);if(!vehicleContracts.has(k))vehicleContracts.set(k,new Set());vehicleContracts.get(k).add(String(i.contrato_id));}});
const overlap=(c,a,b)=>c.data_inicio&&day(c.data_inicio)<=b&&(!c.data_fim||day(c.data_fim)>=a),valid=(c,d)=>overlap(c,d,d),extra=e=>['EX','AB','AP','SA'].includes(e.tipo_rota),sum=a=>a.reduce((s,x)=>s+Number(x||0),0), table=(id,heads,rows)=>{$(id).innerHTML='<table><thead><tr>'+heads.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+(rows.length?rows.map(r=>'<tr>'+r.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join(''):'<tr><td colspan="'+heads.length+'">Nenhum registro no período.</td></tr>')+'</tbody></table>';};
function months(a,b){const out=[];let m=a.slice(0,7);while(m<=b.slice(0,7)){out.push(m);const [y,n]=m.split('-').map(Number);m=n===12?`${y+1}-01`:`${y}-${String(n+1).padStart(2,'0')}`;}return out;}
function last(m){const [y,n]=m.split('-').map(Number);return m+'-'+new Date(Date.UTC(y,n,0)).getUTCDate();}
function render(){let a,b;if($('ct-mode').value==='month'){const m=$('ct-month').value;if(!m){$('ct-error').textContent='Selecione um mês.';return;}a=m+'-01';b=last(m);}else{a=$('ct-start').value;b=$('ct-end').value;}
if(!a||!b||a>b||a<D.inicio||b>D.hoje||a>D.hoje){if($('ct-mode').value==='month'&&a>=D.inicio&&a<=D.hoje&&b>D.hoje)b=D.hoje;else{$('ct-error').textContent='Escolha um intervalo válido entre '+br(D.inicio)+' e '+br(D.hoje)+'.';return;}}
$('ct-error').textContent='';$('ct-period').textContent='Período: '+br(a)+' a '+br(b)+'. Dados carregados até '+br(D.hoje)+'. Trocar datas não consulta o banco novamente.';
const rows=D.escalas.filter(e=>day(e.data)>=a&&day(e.data)<=b),regular=rows.filter(e=>e.tipo_rota==='RR'),extras=rows.filter(e=>extra(e)&&e.iniciou),ds=D.diarias.filter(d=>d.data>=a&&d.data<=b),active=D.contratos.filter(c=>overlap(c,a,b));
const ms=[];for(const m of months(a,b))for(const c of D.contratos){if(c.tem_mensal&&overlap(c,m+'-01',last(m)))ms.push({mes:m,c,valor:c.composicao_pendente?null:c.mensal});}
const dv=sum(ds.map(d=>d.valor)),mv=sum(ms.map(m=>m.valor)),pending=ds.filter(d=>d.valor===null).length+ms.filter(m=>m.valor===null).length;
const activeIds=new Set(active.map(c=>String(c.id)));
const activeItems=[...new Map(D.itens.filter(i=>activeIds.has(String(i.contrato_id))&&i.status==='ATIVO').map(i=>[String(i.id),i])).values()];
const dailyItems=activeItems.filter(i=>i.modalidade_pagamento==='DIARIA'),monthlyItems=activeItems.filter(i=>i.modalidade_pagamento==='MENSAL');
const estimate=(items,unit)=>'Estimado: '+money(sum(items.map(i=>i.valor_unitario)))+' / '+unit+(items.some(i=>i.valor_unitario==null)?' · parcial: há valores não informados':'');
const cards=[['CONTRATOS COM VIGÊNCIA',active.length,'Contratos principais no período'],['CONTRATOS-ROTA ATIVOS · DIÁRIA',dailyItems.length,estimate(dailyItems,'dia')+' — se todos executarem'],['CONTRATOS-ROTA ATIVOS · LOCAÇÃO',monthlyItems.length,estimate(monthlyItems,'mês')+' — modalidade MENSAL'],['ROTAS RR SEM / COM CONCLUSÃO',regular.filter(e=>!(e.iniciou&&e.terminou)).length+' / '+regular.filter(e=>e.iniciou&&e.terminou).length,'Sem conclusão inclui ausência de registro'],['DIÁRIAS ELEGÍVEIS',ds.length,'Uma por contrato e data'],['VALOR APURADO'+(pending?' · PARCIAL':''),money(dv+mv),pending+' parcelas aguardando conferência'],['PREVISÃO DO FECHAMENTO','A definir','Calendário futuro de atendimento não informado']];
$('ct-kpis').innerHTML=cards.map(c=>'<article class="ct-card ct-kpi"><span>'+esc(c[0])+'</span><strong>'+esc(c[1])+'</strong><span>'+esc(c[2])+'</span></article>').join('');
const cutoff=new Date(b+'T12:00:00Z');cutoff.setUTCDate(cutoff.getUTCDate()-2);const low=cutoff.toISOString().slice(0,10);const dailyKeys=new Map(ds.map(d=>[String(d.contrato_id)+'|'+d.data,d]));
table('ct-recent',['Prestador / contrato','Rota','Data','Placa','Motorista','Registro','Diária do contrato'],rows.filter(e=>e.tipo_rota==='RR'&&C.has(String(e.contrato_id))&&day(e.data)>=low).map(e=>{const c=C.get(String(e.contrato_id)),d=dailyKeys.get(String(e.contrato_id)+'|'+day(e.data));return[c?c.prestador+' / #'+c.id:'Sem contrato',e.rota,br(e.data),e.placa,e.motorista,e.iniciou?(e.terminou?'Concluída':'Sem encerramento'):'Sem início',d?'Elegível — ver composição':'Sem diária apurada'];}));
const conflicts=new Map();rows.filter(e=>e.iniciou).forEach(e=>{const c=C.get(String(e.contrato_id));if(!c?.data_fim||day(e.data)<=day(c.data_fim))return;const k=String(c.id);if(!conflicts.has(k))conflicts.set(k,{c,days:new Set(),n:0,done:0,first:day(e.data),last:day(e.data)});const x=conflicts.get(k);x.days.add(day(e.data));x.n++;x.done+=e.terminou?1:0;x.first=x.first<day(e.data)?x.first:day(e.data);x.last=x.last>day(e.data)?x.last:day(e.data);});
const cf=[...conflicts.values()].sort((x,y)=>y.days.size-x.days.size),gap=x=>Math.round((Date.parse(x.last)-Date.parse(day(x.c.data_fim)))/86400000);
table('ct-conflicts',['Contrato','Prestador','Encerramento','Primeira no período','Última no período','Dias com execução','Dias após encerramento','Iniciadas','Com início e fim'],cf.map(x=>[x.c.id,x.c.prestador,br(x.c.data_fim),br(x.first),br(x.last),x.days.size,gap(x),x.n,x.done]));
$('ct-alerts').innerHTML=(cf.slice(0,3).map(x=>'<div class="ct-alert"><b>Contrato #'+esc(x.c.id)+'</b><br>'+x.days.size+' dias com execução após encerramento.<br>Última: '+gap(x)+' dias depois.</div>').join('')||'<p>Sem conflito de encerramento registrado no período.</p>')+'<p>'+extras.length+' extras aguardam valor.</p><p>'+pending+' parcelas têm composição a conferir.</p>';
const byContract=new Map();ds.forEach(d=>{const c=C.get(String(d.contrato_id));const k=String(c.id);if(!byContract.has(k))byContract.set(k,{c,days:0,total:0,pending:false});const o=byContract.get(k);o.days++;o.pending||=d.valor===null;o.total+=d.valor||0;});
table('ct-finance',['Contrato','Prestador','Modalidade','Dias / competência','Valor apurado','Base'],[...[...byContract.values()].map(x=>[x.c.id,x.c.prestador,'DIÁRIA',x.days+' dias',money(x.pending?null:x.total),x.pending?'Composição histórica a conferir':'Cadastro disponível']),...ms.map(x=>[x.c.id,x.c.prestador,'MENSAL',x.mes,money(x.valor),x.valor===null?'Composição histórica a conferir':'Integral, sem depender de execução'])]);
const names={EX:'Extracurricular',AB:'Abastecimento',AP:'Apoio',SA:'Saída antecipada'};
table('ct-extras',['Data','ID','Placa','Motorista','Tipo informado','Contratos pelo veículo','Sinalização','Encerramento','KM registrado','Observação','Valor'],extras.map(e=>{const candidates=[...(vehicleContracts.get(String(e.veiculo_execucao_id))||[])].map(id=>C.get(id)).filter(Boolean),v=candidates.filter(c=>valid(c,day(e.data))),old=candidates.filter(c=>c.data_fim&&day(c.data_fim)<day(e.data));return[br(e.data),e.id,e.placa,e.motorista,names[e.tipo_rota],(v.length?v:old).map(c=>'#'+c.id).join(', ')||'—',!e.veiculo_execucao_id?'Sem veículo utilizado':v.length>1?'Associação ambígua':v.length===1?'Associação cadastral, conferir item':old.length?'Contrato encerrado':'Sem contrato vigente identificado',e.terminou?'Registrado':'Sem encerramento registrado',e.km_executado,e.observacao,'Aguardando lançamento'];}));
$('ct-extra-summary').textContent=extras.length+' extras consideradas concluídas. '+Object.entries(names).map(([k,n])=>n+': '+extras.filter(e=>e.tipo_rota===k).length).join(' · ')+'. Valor potencial ainda não informado.';
const dates=[...new Set(ds.map(d=>d.data))].sort();let acc=0;const points=dates.map(d=>{acc+=sum(ds.filter(x=>x.data===d).map(x=>x.valor));return acc;});const max=Math.max(...points,1);$('ct-trend').innerHTML=points.length?'<svg class="ct-plot" viewBox="0 0 600 180" role="img" aria-label="Evolução das diárias acumuladas"><polyline fill="none" stroke="#21b8eb" stroke-width="3" points="'+points.map((v,i)=>(20+(points.length===1?0:i/(points.length-1))*560)+','+(160-v/max*140)).join(' ')+'"/>'+points.map((v,i)=>'<circle cx="'+(20+(points.length===1?0:i/(points.length-1))*560)+'" cy="'+(160-v/max*140)+'" r="4" fill="#21b8eb"/>').join('')+'</svg><p>'+br(dates[0])+' → '+br(dates.at(-1))+' · '+money(dv)+'</p>':'<p>Sem diárias com valor apurado.</p>';
const suppliers=new Map();const add=(c,v)=>{if(v!==null)suppliers.set(c.prestador,(suppliers.get(c.prestador)||0)+v);};ds.forEach(d=>add(C.get(String(d.contrato_id)),d.valor));ms.forEach(m=>add(m.c,m.valor));const sorted=[...suppliers].sort((x,y)=>y[1]-x[1]),smax=Math.max(...sorted.map(x=>x[1]),1);$('ct-suppliers').innerHTML=sorted.slice(0,6).map(([n,v])=>'<div class="ct-bar"><label><span>'+esc(n)+'</span><span>'+money(v)+'</span></label><i style="width:'+Math.max(0,v/smax*100)+'%"></i></div>').join('')||'<p>Sem valores apurados.</p>';
const fleet=new Set(rows.filter(e=>e.iniciou&&e.veiculo_execucao_id).map(e=>String(e.veiculo_execucao_id))),extraFleet=new Set(extras.filter(e=>e.veiculo_execucao_id).map(e=>String(e.veiculo_execucao_id)));$('ct-fleet').innerHTML='<p><b>'+fleet.size+'</b> com início registrado</p><p><b>'+extraFleet.size+'</b> com demandas extras</p><p><b>'+extras.filter(e=>!e.veiculo_execucao_id).length+'</b> extras sem veículo utilizado</p>';
}

const fleetRows=[...new Map((D.frota||[]).map(v=>[String(v.id),v])).values()];
const types=[['FROTA_PROPRIA','Próprios','#22c59a'],['FROTA_TERCEIRIZADA','Terceirizados','#1c9be8'],['FROTA_LOCADA','Locados','#f4ad42'],['FROTA_PARCEIRO','Parceiros','#a88ce8']];
const activeFleet=fleetRows.filter(v=>v.status==='A');
const counts=types.map(([code,label,color])=>({label,color,n:activeFleet.filter(v=>v.tipo_contrato_locacao===code).length}));counts.push({label:'Outros / não informado',color:'#8292a0',n:activeFleet.filter(v=>!types.some(t=>t[0]===v.tipo_contrato_locacao)).length});
let angle=0;const segments=counts.filter(x=>x.n).map(x=>{const begin=angle;angle+=x.n/Math.max(activeFleet.length,1)*100;return x.color+' '+begin+'% '+angle+'%';});
$('ct-fleet-pie').innerHTML=activeFleet.length?'<div role="img" aria-label="Distribuição dos vínculos da frota ativa" style="width:170px;height:170px;border-radius:50%;margin:auto;background:conic-gradient('+segments.join(',')+')"></div>'+counts.map(x=>'<p><span style="color:'+x.color+'">●</span> '+esc(x.label)+': <b>'+x.n+'</b> ('+(x.n/activeFleet.length*100).toFixed(1)+'%)</p>').join(''):'<p>Sem veículos ativos no cadastro.</p>';
const bars=(values,max,color)=>values.map(([label,n])=>'<div class="ct-bar"><label><span>'+esc(label)+'</span><b>'+n+'</b></label><i style="background:'+color+';width:'+(n/Math.max(max,1)*100)+'%"></i></div>').join('');
const status=[['Ativos (A)',fleetRows.filter(v=>v.status==='A').length],['Inativos (I)',fleetRows.filter(v=>v.status==='I').length],['Outros / não informado',fleetRows.filter(v=>!['A','I'].includes(v.status)).length]];
$('ct-fleet-status').innerHTML=bars(status,fleetRows.length,'#18a6e5');
const maintained=new Set((D.manutencao||[]).map(v=>String(v.veiculo_id))),known=fleetRows.filter(v=>maintained.has(String(v.id))).length;
$('ct-maintenance').innerHTML=bars([['Com chamado em oficina (CO)',known],['Sem chamado em oficina (CO)',fleetRows.length-known]],fleetRows.length,'#f4ad42');
$('ct-update').textContent='Atualizado em '+new Date(D.atualizado).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'});$('ct-month').value=D.hoje.slice(0,7);$('ct-month').min=D.inicio.slice(0,7);$('ct-month').max=D.hoje.slice(0,7);$('ct-start').value=D.hoje.slice(0,7)+'-01';$('ct-end').value=D.hoje;for(const id of ['ct-start','ct-end']){$(id).min=D.inicio;$(id).max=D.hoje;}$('ct-mode').addEventListener('change',()=>{const range=$('ct-mode').value==='range';$('ct-month-wrap').hidden=range;$('ct-start-wrap').hidden=!range;$('ct-end-wrap').hidden=!range;});$('ct-apply').addEventListener('click',render);render();
})();
</script>
'''

"""Empacota o HTML em blocos gzip pequenos, sem reduzir o histórico."""
import gzip
import hashlib
import json
from pathlib import Path


def publicar_compacto(html, destino='public', tamanho_bloco=8 * 1024 * 1024):
    pasta = Path(destino)
    pasta.mkdir(parents=True, exist_ok=True)
    assets = pasta / 'dados'
    assets.mkdir(exist_ok=True)
    bruto = html.encode('utf-8')
    arquivos = []
    total = 0
    for pos in range(0, len(bruto), tamanho_bloco):
        bloco = gzip.compress(bruto[pos:pos+tamanho_bloco], compresslevel=6, mtime=0)
        nome = hashlib.sha256(bloco).hexdigest()[:24] + '.gz'
        (assets / nome).write_bytes(bloco)
        arquivos.append('dados/' + nome)
        total += len(bloco)
    pagina = LOADER.replace('__ARQUIVOS__', json.dumps(arquivos))
    (pasta / 'index.html').write_text(pagina, encoding='utf-8')
    if (pasta / 'index.html').stat().st_size > 10 * 1024 * 1024:
        raise RuntimeError('Índice inesperadamente grande; publicação interrompida.')
    print(f'Painel: {len(bruto):,} bytes originais; {total:,} bytes comprimidos; '
          f'{len(arquivos)} blocos. Nenhum dado foi removido.')


LOADER = '''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Control Tower Log-PI</title>
<style>body{margin:0;background:#091522;color:#eaf3fa;font:16px system-ui;display:grid;min-height:100vh;place-items:center}main{max-width:600px;padding:32px}progress{width:100%;accent-color:#22ba9b}button{padding:12px;background:#087e73;color:white;border:0;border-radius:6px;cursor:pointer}</style></head>
<body><main><h1>Control Tower Log-PI</h1><p id="estado" role="status">Carregando o histórico do painel…</p><progress id="progresso"></progress><button id="tentar" hidden onclick="location.reload()">Tentar novamente</button><noscript>Ative JavaScript para abrir o painel.</noscript></main>
<script>
(async()=>{
  const arquivos=__ARQUIVOS__,estado=document.getElementById('estado'),barra=document.getElementById('progresso');
  try {
    if(typeof DecompressionStream==='undefined')throw Error('Abra o painel em uma versão atual do Chrome, Edge, Firefox ou Safari.');
    barra.max=arquivos.length;barra.value=0;
    const partes=[],decoder=new TextDecoder('utf-8',{fatal:true});
    for(let i=0;i<arquivos.length;i++){
      const resposta=await fetch(new URL(arquivos[i],location.href));
      if(!resposta.ok)throw Error('Não foi possível carregar um bloco do painel (HTTP '+resposta.status+').');
      const stream=resposta.body.pipeThrough(new DecompressionStream('gzip'));
      const bytes=await new Response(stream).arrayBuffer();
      partes.push(decoder.decode(bytes,{stream:true}));
      barra.value=i+1;estado.textContent='Carregando histórico: '+(i+1)+' de '+arquivos.length+' blocos.';
    }
    partes.push(decoder.decode());
    const pagina=partes.join('');
    document.open();document.write(pagina);document.close();
  }catch(erro){estado.textContent='Falha ao abrir o painel. '+erro.message;barra.hidden=true;document.getElementById('tentar').hidden=false;}
})();
</script></body></html>'''


if __name__ == '__main__':
    import os
    import psycopg2
    conn = psycopg2.connect(host=os.environ['DB_HOST'],
        port=int(os.environ.get('DB_PORT') or '5432'),
        database=os.environ.get('DB_NAME') or 'postgres',
        user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
        sslmode='require', connect_timeout=15)
    try:
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL TIME ZONE 'America/Sao_Paulo'")
                cur.execute("SET LOCAL statement_timeout = '120s'")
            dados = preparar_financeiro(carregar_centro(conn, '2026-01-01'))
    finally:
        conn.close()
    html = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Control Tower Log-PI</title></head><body style="margin:0">'
            + componente(dados) + '</body></html>')
    publicar_compacto(html)
