"""Painel de abastecimento: consultas somente leitura e geração estática."""
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo


COMBUSTIVEL_SQL = """
SELECT a.datetime_abastecimento::date AS data,
       a.veiculo_id,
       COALESCE(v.placa, 'SEM PLACA') AS placa,
       COALESCE(g.nome, 'SEM GRE') AS gre,
       COALESCE(NULLIF(TRIM(v.cidade), ''), 'SEM CIDADE') AS cidade,
       COUNT(*) AS registros,
       SUM(a.litros) AS litros,
       SUM(a.valor_total) AS gasto
FROM airbyte.abastecimentos_abastecimento a
LEFT JOIN airbyte.veiculos_veiculo v ON v.id = a.veiculo_id
LEFT JOIN airbyte.escolas_gre g ON g.id = COALESCE(a.gre_id, v.gre_id)
WHERE a.valor_total > 0 AND a.litros > 0
  AND a.datetime_abastecimento >= %(inicio)s::date
  AND a.datetime_abastecimento < CURRENT_DATE + INTERVAL '1 day'
GROUP BY a.datetime_abastecimento::date, a.veiculo_id, v.placa,
         g.nome, COALESCE(NULLIF(TRIM(v.cidade), ''), 'SEM CIDADE')
ORDER BY data
"""

ROTAS_SQL = """
SELECT e.data::date AS data,
       COALESCE(g.nome, 'SEM GRE') AS gre,
       COALESCE(NULLIF(TRIM(r.cidade), ''), 'SEM CIDADE') AS cidade,
       COUNT(*) AS concluidas
FROM airbyte.rotas_escalarota e
LEFT JOIN airbyte.rotas_rota r ON r.id = e.rota_id
LEFT JOIN airbyte.escolas_gre g ON g.id = r.gre_id
WHERE e.data >= %(inicio)s::date
  AND e.data < CURRENT_DATE + INTERVAL '1 day'
  AND e.anulada = false
  AND e.tipo_rota = 'RR'
  AND e.inicio_execucao IS NOT NULL
  AND e.fim_execucao IS NOT NULL
GROUP BY e.data::date, g.nome, COALESCE(NULLIF(TRIM(r.cidade), ''), 'SEM CIDADE')
ORDER BY data
"""


def preparar(dados):
    totais = {}
    for r in dados['rotas']:
        d = str(r['data'])[:10]
        totais[d] = totais.get(d, 0) + int(r['concluidas'])
    # Calendário global: não aplicar o limite de 350 a cada GRE/cidade.
    dados['dias_letivos'] = sorted(d for d, n in totais.items() if n > 350)
    return dados


def carregar(conn, inicio):
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT CURRENT_DATE AS hoje, CURRENT_TIMESTAMP AS atualizado')
        dados = dict(cur.fetchone())
        dados['inicio'] = inicio
        for chave, sql in [('abastecimentos', COMBUSTIVEL_SQL), ('rotas', ROTAS_SQL)]:
            cur.execute(sql, {'inicio': inicio})
            dados[chave] = [dict(r) for r in cur.fetchall()]
    return preparar(dados)


def montar_html(dados):
    serializado = json.dumps(dados, ensure_ascii=False, default=str, allow_nan=False)
    serializado = serializado.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return PAGINA.replace('__DADOS__', serializado)


PAGINA = r'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Log-PI · Abastecimento</title>
<style>
:root{color-scheme:dark;--bg:#091522;--panel:#122432;--line:#355166;--ink:#f2f7fb;--muted:#c3d2de;--blue:#3bbbf2;--green:#35d2ac;--amber:#ffc36b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif}main{max-width:1920px;margin:auto;padding:24px 20px}header{display:flex;justify-content:space-between;gap:20px;align-items:center}h1{font-size:28px;margin:4px 0}h2{font-size:18px;margin:0 0 16px}p{color:var(--muted)}a{color:var(--green)}.eyebrow{font-size:13px;color:var(--green);letter-spacing:.08em}label{display:grid;gap:6px;font-size:14px;color:var(--muted)}select,button{font:inherit;padding:10px 14px;color:var(--ink);background:#193449;border:1px solid #57758b;border-radius:7px;min-height:44px}button{background:#087c72;cursor:pointer}:focus-visible{outline:3px solid var(--blue);outline-offset:3px}.filters{display:flex;flex-wrap:wrap;gap:16px;margin:24px 0;align-items:end}.filters label{min-width:160px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;min-width:0}.cards strong{font-size:30px;display:block;margin:10px 0;line-height:1.2;letter-spacing:-.02em}.cards .card:first-child{background:#123d3a;border-color:#298d7c}.small{font-size:14px;color:var(--muted)}.section{margin-top:18px}.scroll{overflow:auto;scrollbar-color:#7796ae #183043}table{border-collapse:collapse;width:100%;font-size:14px}td,th{text-align:right;padding:14px 12px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:#edf6fc;background:#193449}td:first-child,th:first-child{text-align:left}.annual th:first-child,.annual td:first-child{position:sticky;left:0;background:#193449;z-index:1;min-width:180px}.annual td{min-width:130px}.annual td strong{display:block;font-size:18px}.delta{font-size:13px;display:block;margin-top:5px;color:#d0dfeb}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.charts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.charts .card{padding:16px}.charts h2{font-size:16px;min-height:48px}.charts .legend{font-size:14px}.chart svg{width:100%;height:220px;display:block}.legend{font-size:14px;color:var(--muted)}.limited{max-height:430px;overflow:auto}.limited th{position:sticky;top:0}.notes{padding:14px 18px;background:#182c3b;border-left:3px solid var(--amber);border-radius:5px}.pill{font-size:12px;color:var(--amber)}#scope{margin:12px 0 20px}.empty{padding:18px;color:var(--muted)}@media(max-width:1150px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.charts{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){main{padding:14px}header{align-items:start;flex-direction:column}h1{font-size:24px}.cards,.grid,.charts{grid-template-columns:1fr}.filters label{width:100%}.cards strong{font-size:28px}}
.evolution-legend{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}.evolution-legend button{font-size:14px;background:#193449}.evolution-legend button[aria-pressed="false"]{opacity:.5}#evolution svg{display:block;width:100%;min-width:850px;height:auto}.evolution-tip{position:fixed;z-index:10;pointer-events:none;background:#142c40;border:1px solid #6d91ab;box-shadow:0 10px 30px #0007;border-radius:9px;padding:15px;max-width:340px;font-size:15px;color:#f2f7fb}.evolution-tip strong{display:block;margin-bottom:8px}.evolution-tip div{margin:5px 0}.month-hit:focus{outline:none;fill:#ffffff0b;stroke:#c7e4fa;stroke-width:1}
</style></head><body><main>
<header><div><div class="eyebrow">LOG-PI / CONTROL TOWER</div><h1>Abastecimento · evolução e resultados</h1><div class="small">Frota, litragem e atendimento no mesmo período.</div></div><div><a href="../">Abrir painel de contratos</a><p class="small" id="updated"></p></div></header>
<div class="filters"><label>Ano<select id="year"></select></label><label>GRE<select id="gre"></select></label><label>Cidade<select id="city"></select></label><button type="button" id="reset">Limpar GRE e cidade</button></div>
<p id="scope" role="status"></p>
<div class="cards" id="kpis"></div>
<section class="card section"><h2>Evolução mensal — visão conjunta</h2><p class="small">Cada linha usa escala relativa ao seu maior valor no ano selecionado (0–100%), para comparar a evolução de unidades diferentes. Passe o mouse, toque ou use Tab nos meses para ver os valores reais. Clique na legenda para ocultar ou mostrar uma linha.</p><div id="evolution-legend" class="evolution-legend"></div><div id="evolution" class="scroll"></div><div id="evolution-tip" class="evolution-tip" role="status" hidden></div></section>
<section class="card section"><h2>Comparativo anual — frota, litros e rotas</h2><p class="small">Variação contra o mês anterior encerrado. Mês atual parcial, sem comparação automática com mês completo. Rotas são contexto operacional; não calculamos litros por rota. Deslize a tabela para a direita para ver os demais meses.</p><div class="scroll annual" id="annual"></div></section>
<div class="charts section"><section class="card"><h2>Gasto total por mês</h2><div id="chart-cost" class="chart"></div></section><section class="card"><h2>Litros abastecidos por mês</h2><div id="chart-liters" class="chart"></div></section><section class="card"><h2>Veículos abastecidos por mês</h2><div id="chart-fleet" class="chart"></div></section><section class="card"><h2>Preço médio por litro / mês</h2><div id="chart-price" class="chart"></div></section></div>
<section class="card section"><h2>Calendário operacional e gasto</h2><div class="scroll annual" id="calendar"></div><p class="small">Dia letivo: mais de 350 rotas regulares com início e fim registrados no conjunto da operação. O calendário geral permanece igual ao filtrar GRE/cidade. Dias fora do critério significam que o registro não atingiu o limite; não comprovam ausência de atendimento.</p></section>
<div class="notes section" id="comparison"></div>
<div class="grid section"><section class="card"><h2>Por GRE</h2><div class="limited" id="by-gre"></div></section><section class="card"><h2>Por cidade</h2><div class="limited" id="by-city"></div></section></div>
<section class="card section"><h2>Sábados — consumo e atendimento registrado</h2><div class="limited" id="saturdays"></div></section>
<section class="card section"><h2>Detalhamento por placa</h2><label style="max-width:240px;margin-bottom:16px">Mês do detalhamento<select id="detail-month"><option value="">Todos os meses do ano</option></select></label><div class="limited" id="plates"></div></section>
<details class="card section"><summary>Critérios de leitura dos resultados</summary><p>Somente registros com valor total maior que zero e litros maiores que zero são contabilizados, independentemente do status. A data usada é a de abastecimento. Abastecimentos fora dos dias letivos também entram nos totais.</p><p>GRE do abastecimento: campo próprio do registro, com GRE do veículo como alternativa. Cidade do abastecimento: cadastro do veículo; não representa a localização do posto. Rotas usam a GRE e a cidade da rota. Alterações cadastrais podem afetar a comparação histórica.</p><p>Veículos são contados por identificador distinto: não some as frotas mensais para obter a frota anual. Um veículo que abasteceu em mais de uma GRE/cidade pode aparecer em mais de um grupo. Sem identificador de veículo, o gasto e a litragem são incluídos, mas o registro não aumenta a contagem de frota.</p><p>Preço médio ponderado por litro = gasto total ÷ litros do mês; não é a média simples dos preços de cada registro. Pode variar também com a composição dos combustíveis e veículos. Litros por dia letivo = todos os litros abastecidos no mês ÷ dias letivos do calendário geral, inclusive litros abastecidos em outros dias. Custo por dia letivo = gasto total do mês ÷ dias letivos do calendário geral, incluindo o gasto dos outros dias. Sem litros ou sem dias letivos, a respectiva média aparece como não disponível. Litros por dia letivo/veículo = litros do mês ÷ dias letivos do calendário geral ÷ veículos distintos abastecidos no recorte. Sem dias letivos ou sem veículos identificados, aparece como não disponível. É uma média geral e não comprova o consumo individual nem que todos os veículos operaram em todos os dias. Não calculamos litros por rota. A evolução ajuda a acompanhar ações, mas não comprova sua causa. Para comparar antes e depois de uma implantação, ainda precisamos das datas e do escopo das ações.</p><p id="coverage"></p></details>
</main><script type="application/json" id="data">__DADOS__</script><script>
(()=>{'use strict';const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id),day=x=>String(x||'').slice(0,10),today=day(D.hoje),start=day(D.inicio),currentMonth=today.slice(0,7),names=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];
const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=x=>Number(x||0).toLocaleString('pt-BR',{maximumFractionDigits:0}),lit=x=>Number(x||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2}),money=x=>Number(x||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'}),br=x=>day(x).split('-').reverse().join('/'),sum=(rows,key)=>rows.reduce((s,r)=>s+Number(r[key]||0),0),vehicles=rows=>new Set(rows.filter(r=>r.veiculo_id!==null&&r.veiculo_id!==undefined).map(r=>String(r.veiculo_id))).size,letivos=new Set(D.dias_letivos),saturday=d=>new Date(day(d)+'T12:00:00Z').getUTCDay()===6;
const fuel=D.abastecimentos.map(r=>({...r,data:day(r.data),litros:Number(r.litros),gasto:Number(r.gasto)})),routes=D.rotas.map(r=>({...r,data:day(r.data),concluidas:Number(r.concluidas)}));
function options(id,values,label){$(id).innerHTML='<option value="">'+label+'</option>'+values.map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('');}
const unique=(rows,key)=>[...new Set(rows.map(r=>r[key]))].sort((a,b)=>a.localeCompare(b,'pt-BR'));
for(let y=Number(today.slice(0,4));y>=Number(start.slice(0,4));y--)$('year').add(new Option(String(y),String(y)));
options('gre',unique([...fuel,...routes],'gre'),'Todas as GREs');
function cities(){const g=$('gre').value;options('city',unique([...fuel,...routes].filter(r=>!g||r.gre===g),'cidade'),'Todas as cidades');}
cities();names.forEach((n,i)=>$('detail-month').add(new Option(n,String(i+1).padStart(2,'0'))));
function tab(id,heads,rows){$(id).innerHTML='<table><thead><tr>'+heads.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+(rows.length?rows.map(r=>'<tr>'+r.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>').join(''):'<tr><td colspan="'+heads.length+'">Sem registros para os filtros.</td></tr>')+'</tbody></table>';}
const previous=m=>{let [y,n]=m.split('-').map(Number);return n===1?(y-1)+'-12':y+'-'+String(n-1).padStart(2,'0');};
const avgPrice=v=>v===null?'—':money(v)+' / L',avgDaily=v=>v===null?'—':lit(v)+' L/dia',avgCostDay=v=>v===null?'—':money(v)+' / dia',avgVehicleDay=v=>v===null?'—':lit(v)+' L/dia/veículo';
function variation(value,base,m){if(value===null||base===null)return 'Sem base para comparação';if(m===currentMonth)return 'Parcial · sem comparação';if(m<start.slice(0,7))return 'Fora da cobertura';if(previous(m)<start.slice(0,7))return 'Sem mês anterior';if(base===0)return value===0?'Sem alteração':'Sem base percentual';const delta=(value/base-1)*100;return (delta>0?'+':'')+delta.toLocaleString('pt-BR',{maximumFractionDigits:1})+'% vs. mês anterior';}
function plot(id,series,key,format,color){const max=Math.max(...series.map(m=>m[key]),1),w=660,h=220;$(id).innerHTML='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="Evolução mensal">'+series.map((m,i)=>{const x=22+i*52,height=m[key]/max*135;return '<g><title>'+esc(m.month+': '+format(m[key])+(m.partial?' (parcial)':''))+'</title><rect x="'+x+'" y="'+(170-height)+'" width="32" height="'+height+'" rx="3" fill="'+color+'" opacity="'+(m.partial?.55:1)+'"/><text x="'+(x+16)+'" y="195" text-anchor="middle" fill="#d9e5ee" font-size="24">'+names[Number(m.month.slice(5))-1]+'</text></g>';}).join('')+'</svg><div class="legend">Passe sobre as barras para ver os valores. Valores completos na tabela anual.</div>';}

function evolution(series){
const specs=[['fleet','Frota abastecida',num,'#b399ed'],['liters','Litros abastecidos',v=>lit(v)+' L','#35d2ac'],['routes','Rotas concluídas',num,'#3bbbf2'],['cost','Gasto com abastecimentos',money,'#ffc36b'],['days','Dias letivos',num,'#ff8eae']];
const w=1100,h=350,left=60,right=1060,top=35,bottom=285,x=m=>left+(Number(m.month.slice(5))-1)*(right-left)/11,y=p=>bottom-p*(bottom-top);
let svg='<svg viewBox="0 0 '+w+' '+h+'" aria-label="Evolução mensal em escala relativa; valores reais disponíveis em cada mês">';
for(const p of [0,.25,.5,.75,1])svg+='<line x1="'+left+'" x2="'+right+'" y1="'+y(p)+'" y2="'+y(p)+'" stroke="#355166"/><text x="48" y="'+(y(p)+5)+'" text-anchor="end" fill="#c3d2de" font-size="14">'+(p*100)+'%</text>';
for(let i=0;i<12;i++){const px=left+i*(right-left)/11;svg+='<text x="'+px+'" y="320" text-anchor="middle" fill="#e6eff6" font-size="15">'+names[i]+'</text>';}
for(const [key,label,fmt,color] of specs){const max=Math.max(...series.map(m=>m[key]),1);svg+='<g data-series="'+key+'"><polyline fill="none" stroke="'+color+'" stroke-width="2.8" points="'+series.map(m=>x(m)+','+y(m[key]/max)).join(' ')+'"/>'+series.map(m=>'<circle cx="'+x(m)+'" cy="'+y(m[key]/max)+'" r="4.5" fill="'+color+'"/>').join('')+'</g>';}
svg+=series.map((m,i)=>'<rect class="month-hit" data-index="'+i+'" tabindex="0" role="button" aria-label="'+esc(m.month+': '+specs.map(([k,l,f])=>l+' '+f(m[k])).join('; '))+'" x="'+(x(m)-30)+'" y="20" width="60" height="280" fill="transparent"/>').join('')+'</svg>';
$('evolution').innerHTML=svg;$('evolution-tip').hidden=true;
$('evolution-legend').innerHTML=specs.map(([k,l,f,c])=>'<button type="button" data-key="'+k+'" aria-pressed="true"><span style="color:'+c+'">●</span> '+l+'</button>').join('');
$('evolution-legend').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{const show=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',String(show));$('evolution').querySelector('[data-series="'+b.dataset.key+'"]').style.display=show?'':'none';}));
function show(i,el,event){const m=series[i],tip=$('evolution-tip');tip.innerHTML='<strong>'+names[Number(m.month.slice(5))-1]+'/'+m.month.slice(0,4)+(m.partial?' · mês parcial':'')+'</strong>'+specs.map(([k,l,f,c])=>'<div><span style="color:'+c+'">●</span> '+l+': <b>'+esc(f(m[k]))+'</b></div>').join('');tip.hidden=false;const rect=el.getBoundingClientRect(),px=event?.clientX??rect.left,py=event?.clientY??rect.top;tip.style.left=Math.max(8,Math.min(px+15,innerWidth-tip.offsetWidth-12))+'px';tip.style.top=Math.max(8,Math.min(py+15,innerHeight-tip.offsetHeight-12))+'px';}
$('evolution').querySelectorAll('.month-hit').forEach(el=>{el.addEventListener('pointermove',e=>show(Number(el.dataset.index),el,e));el.addEventListener('click',e=>show(Number(el.dataset.index),el,e));el.addEventListener('focus',()=>show(Number(el.dataset.index),el));el.addEventListener('blur',()=>{$('evolution-tip').hidden=true;});el.addEventListener('keydown',e=>{if(e.key==='Escape')$('evolution-tip').hidden=true;});});$('evolution').onpointerleave=()=>{$('evolution-tip').hidden=true;};
}
function render(){const year=$('year').value,g=$('gre').value,c=$('city').value,match=r=>(!g||r.gre===g)&&(!c||r.cidade===c),allFuel=fuel.filter(match),allRoutes=routes.filter(match),F=allFuel.filter(r=>r.data.startsWith(year)),R=allRoutes.filter(r=>r.data.startsWith(year));
const cache=new Map();function stats(month){if(cache.has(month))return cache.get(month);const f=allFuel.filter(r=>r.data.startsWith(month)),r=allRoutes.filter(r=>r.data.startsWith(month)),days=D.dias_letivos.filter(d=>d.startsWith(month));const st={month,fleet:vehicles(f),liters:sum(f,'litros'),cost:sum(f,'gasto'),routes:sum(r,'concluidas'),days:days.length,saturdays:days.filter(saturday).length,satFuel:sum(f.filter(x=>saturday(x.data)),'litros'),satCost:sum(f.filter(x=>saturday(x.data)),'gasto'),outsideCost:sum(f.filter(x=>!letivos.has(x.data)),'gasto'),partial:month===currentMonth};st.avgPrice=st.liters>0?st.cost/st.liters:null;st.avgDaily=st.days>0?st.liters/st.days:null;st.avgCostDay=st.days>0?st.cost/st.days:null;st.avgVehicleDay=st.days>0&&st.fleet>0?st.liters/st.days/st.fleet:null;cache.set(month,st);return st;}
const months=names.map((_,i)=>year+'-'+String(i+1).padStart(2,'0')),covered=months.filter(m=>m>=start.slice(0,7)&&m<=currentMonth),series=covered.map(stats),globalDays=D.dias_letivos.filter(d=>d.startsWith(year));
$('scope').textContent=year+' · '+(g||'Todas as GREs')+' · '+(c||'Todas as cidades')+' · '+(year===today.slice(0,4)?'Acumulado até '+br(today):'Ano selecionado');
$('kpis').innerHTML=[['GASTO TOTAL',money(sum(F,'gasto')),'Somente valor e litros positivos'],['LITROS ABASTECIDOS',lit(sum(F,'litros'))+' L','Inclui todos os dias com abastecimento'],['VEÍCULOS ABASTECIDOS',num(vehicles(F)),'Veículos distintos no ano selecionado'],['DIAS LETIVOS · CALENDÁRIO GERAL',num(globalDays.length),num(globalDays.filter(saturday).length)+' sábados com mais de 350 rotas concluídas']].map(([l,v,n])=>'<article class="card"><span class="small">'+l+'</span><strong>'+v+'</strong><span class="small">'+n+'</span></article>').join('');
const header='<thead><tr><th>Indicador</th>'+months.map((m,i)=>'<th>'+names[i]+(m===currentMonth?' · parcial':'')+'</th>').join('')+'</tr></thead>';
const annualRows=[['Frota abastecida','fleet',num],['Litros abastecidos','liters',lit],['Rotas concluídas (RR)','routes',num],['Gasto com abastecimentos','cost',money],['Dias letivos (geral)','days',num],['Preço médio por litro','avgPrice',avgPrice],['Litros por dia letivo','avgDaily',avgDaily],['Custo por dia letivo','avgCostDay',avgCostDay],['Litros por dia letivo/veículo','avgVehicleDay',avgVehicleDay]];
$('annual').innerHTML='<table>'+header+'<tbody>'+annualRows.map(([label,key,format])=>'<tr><th>'+label+'</th>'+months.map(m=>{if(!covered.includes(m))return '<td>—</td>';const v=stats(m)[key],base=stats(previous(m))[key];return '<td><strong>'+format(v)+'</strong><span class="delta">'+esc(variation(v,base,m))+'</span></td>';}).join('')+'</tr>').join('')+'</tbody></table>';
$('calendar').innerHTML='<table>'+header+'<tbody>'+[['Gasto total','cost',money],['Dias letivos (geral)','days',num],['Sábados letivos (geral)','saturdays',num],['Litros aos sábados','satFuel',lit],['Gasto aos sábados','satCost',money],['Gasto fora do critério letivo','outsideCost',money]].map(([l,k,f])=>'<tr><th>'+l+'</th>'+months.map(m=>'<td>'+(covered.includes(m)?f(stats(m)[k]):'—')+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
evolution(series);
plot('chart-cost',series,'cost',money,'#35d2ac');plot('chart-liters',series,'liters',lit,'#3bbbf2');plot('chart-fleet',series,'fleet',num,'#b399ed');plot('chart-price',series,'avgPrice',avgPrice,'#ffc36b');
const closed=covered.filter(m=>m<currentMonth),last=closed.at(-1);if(last&&previous(last)>=start.slice(0,7)){const now=stats(last),before=stats(previous(last));$('comparison').textContent='Último mês encerrado: '+last+'. Gasto: '+variation(now.cost,before.cost,last)+'; litros: '+variation(now.liters,before.liters,last)+'; frota: '+variation(now.fleet,before.fleet,last)+'. Dias letivos: '+before.days+' → '+now.days+'. Compare essas mudanças em conjunto antes de atribuir o resultado às ações.';}else $('comparison').textContent='Ainda não há dois meses encerrados cobertos para comparar. O mês atual aparece como parcial.';
function grouping(key,id){const grouped=new Map();F.forEach(r=>{if(!grouped.has(r[key]))grouped.set(r[key],[]);grouped.get(r[key]).push(r);});tab(id,[key==='gre'?'GRE':'Cidade','Veículos','Litros','Gasto total'],[...grouped].sort((a,b)=>sum(b[1],'gasto')-sum(a[1],'gasto')).map(([name,rs])=>[name,num(vehicles(rs)),lit(sum(rs,'litros')),money(sum(rs,'gasto'))]));}grouping('gre','by-gre');grouping('cidade','by-city');
const satDays=new Set([...F,...R].filter(r=>saturday(r.data)).map(r=>r.data));tab('saturdays',['Sábado','Dia letivo geral','Rotas RR do recorte','Veículos abastecidos','Litros','Gasto'],[...satDays].sort().map(d=>{const f=F.filter(r=>r.data===d);return[br(d),letivos.has(d)?'Sim':'Não atingiu o critério',num(sum(R.filter(r=>r.data===d),'concluidas')),num(vehicles(f)),lit(sum(f,'litros')),money(sum(f,'gasto'))];}));
const detailMonth=$('detail-month').value,group=new Map();F.filter(r=>!detailMonth||r.data.slice(5,7)===detailMonth).forEach(r=>{const k=JSON.stringify([r.veiculo_id,r.placa,r.gre,r.cidade]);if(!group.has(k))group.set(k,[]);group.get(k).push(r);});tab('plates',['Placa','GRE','Cidade cadastral','Abastecimentos','Dias abastecidos','Litros','Gasto'],[...group.values()].sort((a,b)=>sum(b,'gasto')-sum(a,'gasto')).map(rs=>[rs[0].placa,rs[0].gre,rs[0].cidade,num(sum(rs,'registros')),num(new Set(rs.map(r=>r.data)).size),lit(sum(rs,'litros')),money(sum(rs,'gasto'))]));
}
$('updated').textContent='Atualizado: '+new Date(D.atualizado).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'});$('coverage').textContent='Histórico consultado: '+br(start)+' a '+br(today)+'. Datas ausentes ou fora dessa janela não entram no painel. Trocar os filtros não consulta o banco; o GitHub Actions atualiza os dados.';
$('gre').addEventListener('change',()=>{cities();render();});['year','city','detail-month'].forEach(id=>$(id).addEventListener('change',render));$('reset').addEventListener('click',()=>{$('gre').value='';cities();render();});render();
})();
</script></body></html>'''

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
    import psycopg2
    inicio = os.environ.get('ABASTECIMENTO_INICIO') or '2025-01-01'
    date.fromisoformat(inicio)
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
            dados = carregar(conn, inicio)
    finally:
        conn.close()
    publicar_compacto(montar_html(dados), destino='public/abastecimento')
