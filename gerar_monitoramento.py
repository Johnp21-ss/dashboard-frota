"""Monitoramento operacional: consultas somente leitura e fotografia cadastral atual."""
import json, os
from datetime import datetime
from zoneinfo import ZoneInfo

TZ=ZoneInfo('America/Sao_Paulo')
SQLS={
'veiculos':'''SELECT id,placa,status,tipo_contrato_locacao AS categoria,tipo,modelo,cidade,gre_id,contrato_rota_id,is_reserva,_airbyte_extracted_at FROM airbyte.veiculos_veiculo''',
'motoristas':'''SELECT id,nome,status,tipo_vinculo,veiculo_id,cidade,gre_id,_airbyte_extracted_at FROM airbyte.motoristas_motorista''',
'gres':'''SELECT id,nome,status FROM airbyte.escolas_gre''',
'rotas':'''SELECT id,nome,status,cidade,gre_id,turno,contrato_rota_id,motorista_padrao_id,dias_semana,_airbyte_extracted_at FROM airbyte.rotas_rota''',
'itens':'''SELECT id,veiculo_id,status FROM airbyte.contratos_itemcontrato''',
'chamados':'''SELECT id,veiculo_id,status,condicao_operacional,emissao,inicio_servico,entrega,data_previsao,oficina_id,cidade,gre_id,_airbyte_extracted_at FROM airbyte.ordens_chamado''',
'os':'''SELECT id,chamado_id,status FROM airbyte.ordens_ordemservico''',
'oficinas':'''SELECT id,nome FROM airbyte.motoristas_fornecedor''',
'rastreadores':'''SELECT id,veiculo_id,status,online,ultima_atualizacao,_airbyte_extracted_at FROM airbyte.veiculos_rastreador''',
'escalas':'''SELECT id,data,rota_id,veiculo_id,motorista_id,contrato_rota_id,ativa,anulada,tipo_rota,_airbyte_extracted_at FROM airbyte.rotas_escalarota WHERE data >= CURRENT_DATE - 90 AND data < CURRENT_DATE + 31'''
}
def carregar(conn):
 from psycopg2.extras import RealDictCursor
 with conn.cursor(cursor_factory=RealDictCursor) as cur:
  cur.execute('SELECT CURRENT_TIMESTAMP AS agora');d=dict(cur.fetchone())
  for k,q in SQLS.items():cur.execute(q);d[k]=[dict(r) for r in cur.fetchall()]
 return preparar(d)
def preparar(d):
 # Fail closed: duplicate IDs would multiply joins and make the counts ambiguous.
 for key in SQLS:
  ids=[str(r['id']) for r in d[key]]
  if len(ids)!=len(set(ids)):raise ValueError('IDs duplicados na fonte '+key+'; conferir extração antes de publicar.')
 return d

def montar_html(d):
 def serial(x):
  if isinstance(x,datetime):return x.astimezone(TZ).isoformat()
  return str(x)
 data=json.dumps(d,ensure_ascii=False,default=serial,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
 return HTML.replace('__DATA__',data)
HTML=r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Central de Monitoramento · Log-PI</title><style>
*{box-sizing:border-box}body{margin:0;background:#0a1824;color:#e5f1f8;font:14px system-ui,sans-serif}main{max-width:1600px;margin:auto;padding:24px}h1{margin:6px 0}h2{font-size:20px}h3{font-size:16px}a{color:#52d9c5}.filters,nav{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}label{display:grid;gap:5px}select,input,button{font:inherit;color:inherit;border:1px solid #496277;border-radius:6px;background:#193345;padding:9px;max-width:100%}button,summary{cursor:pointer}button:hover{background:#285269}:focus-visible{outline:3px solid #ffc466}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card,section{border:1px solid #355367;border-radius:8px;padding:18px;background:#122633;margin:14px 0}.card{margin:0}.card strong{display:block;font-size:28px;margin:8px 0}.note{color:#b7cbd9;font-size:13px;line-height:1.6}.alert{padding:12px;border-left:4px solid #ffc466;background:#263340}.scroll{overflow:auto;max-height:480px}table{width:100%;border-collapse:collapse;white-space:nowrap}th,td{text-align:left;padding:11px;border-bottom:1px solid #355367}th{background:#1a3749;position:sticky;top:0}details{margin:8px 0;padding:8px;border-left:2px solid #355367}summary{padding:8px;font-weight:600}section[hidden]{display:none}nav button[aria-pressed=true]{background:#14776b}small{color:#52d9c5}.badge{color:#ffce80}@media(max-width:800px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}main{padding:12px}}@media(max-width:450px){.cards{grid-template-columns:1fr}label{width:100%}}
</style></head><body><main><small>LOG-PI / CONTROL TOWER</small><h1>Central de Monitoramento</h1><p>Frota, manutenção e planejamento cadastral em uma única consulta. <a href="../central/">Central de Painéis</a></p><p id="updated" class="note"></p>
<div class="alert">Fotografia do cadastro atual. Associação por motorista ou contrato não comprova o veículo planejado no passado. Veículo disponível significa ausência de manutenção identificada pela regra adotada, não confirmação física de aptidão.</div>
<div class="filters"><label>Região<select id="region"><option value="">Todas</option><option>Capital</option><option>Interior</option><option>Administrativo / apoio</option><option>Não classificado</option></select></label><label>GRE<select id="gre"><option value="">Todas</option></select></label><label>Cidade de atendimento<select id="city"><option value="">Todas</option></select></label><label>Vínculo da frota<select id="category"><option value="">Todos</option></select></label><label>Buscar placa<input id="plate" placeholder="Placa"></label><button id="reset">Limpar filtros</button></div>
<p class="note">Capital: 4ª, 19ª, 20ª e 21ª GREs e cadastro em Teresina; Logística Capital também entra na frota da Capital. Logística Interior e Administrativo ficam em apoio, fora do Interior automático, até validação da classificação. Rotas: Capital pelas quatro GREs; unidades de apoio ficam separadas. GRE/cidade da rota orientam seu atendimento; GRE/cidade da frota vêm do cadastro atual do veículo.</p>
<nav id="tabs"></nav><div id="sections"></div>
<script>'use strict';const D=__DATA__;
const $=id=>document.getElementById(id),esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),num=v=>Number(v).toLocaleString('pt-BR',{maximumFractionDigits:1}),pct=(a,b)=>b?num(a/b*100)+'%':'—',norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().trim(),date=s=>s?new Date(s).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'—';
const cats={FROTA_PROPRIA:'Próprios',FROTA_PARCEIRO:'Parceiros',FROTA_LOCADA:'Locados',FROTA_TERCEIRIZADA:'Terceirizados'},idx=a=>new Map(a.map(r=>[String(r.id),r])),V=idx(D.veiculos),M=idx(D.motoristas),I=idx(D.itens),G=idx(D.gres),O=idx(D.oficinas),R=idx(D.rotas),group=(a,f)=>{const m=new Map();for(const r of a){const k=f(r);if(!m.has(k))m.set(k,[]);m.get(k).push(r);}return m;},capital=new Set(['3','4','5','6']),interior=new Set(['7','8','9','10','11']);
const gname=id=>G.get(String(id))?.nome||'Sem GRE';
function region(g,c,route=false){g=String(g);if(capital.has(g))return 'Capital';if(route){if(interior.has(g))return 'Interior';if(['19','29','95'].includes(g))return 'Administrativo / apoio';return 'Não classificado';}if(norm(c)==='TERESINA'||g==='29')return 'Capital';if(['19','95'].includes(g))return 'Administrativo / apoio';return interior.has(g)?'Interior':'Não classificado';}
const latest=a=>a.map(r=>r._airbyte_extracted_at).filter(Boolean).sort().at(-1)||null,source=latest(D.chamados),cut=source?Math.min(Date.parse(source),Date.parse(D.agora)):null;
const byContrato=group(D.veiculos.filter(v=>v.status==='A'&&v.contrato_rota_id!=null),v=>String(v.contrato_rota_id));
function resolve(r,driverKey='motorista_padrao_id',direct=null){
 const candidates=[],origins=[];let ambiguous=false;
 const add=(id,origin)=>{if(id!=null){candidates.push(String(id));origins.push(origin);}};
 add(direct,'Escala');const item=I.get(String(r.contrato_rota_id));add(item?.veiculo_id,'Item de contrato');add(M.get(String(r[driverKey]))?.veiculo_id,'Motorista cadastrado');
 const reverse=byContrato.get(String(r.contrato_rota_id))||[];if(reverse.length===1)add(reverse[0].id,'Contrato no veículo');else if(reverse.length>1)ambiguous=true;
 const unique=[...new Set(candidates)];if(ambiguous||unique.length>1)return {v:null,issue:'Vínculo divergente — conferir',origins:origins.join(' / ')};
 if(!unique.length)return {v:null,issue:'Sem veículo associado',origins:'—'};const v=V.get(unique[0]);if(!v)return {v:null,issue:'Veículo não localizado',origins:origins.join(' / ')};
 return {v,issue:v.status==='A'?'':('Veículo com status '+v.status),origins:origins.join(' / ')};
}
const routes=D.rotas.filter(r=>r.status==='A').map(r=>({...r,region:region(r.gre_id,r.cidade,true),...resolve(r)}));
const oss=group(D.os,o=>String(o.chamado_id)),calls=group(D.chamados,c=>String(c.veiculo_id));
function maintenance(v){const pending=[],unknown=[];for(const c of calls.get(String(v.id))||[]){if(c.status==='CA')continue;const a=Date.parse(c.inicio_servico),b=Date.parse(c.entrega),orders=oss.get(String(c.id))||[];
 const bad=(Number.isFinite(b)&&b>Date.parse(D.agora))||orders.some(o=>(c.status==='CC')!==(o.status==='CC'))||(Number.isFinite(a)&&Number.isFinite(b)&&b<a);
 if(bad||(c.status==='CC'&&!Number.isFinite(b))){unknown.push(c);continue;}
 if(Number.isFinite(b)&&b<=cut)continue;
 if(Number.isFinite(a)&&cut!==null&&a<=cut&&['EA','AO','CO'].includes(c.status))pending.push(c);
 else if(['EA','AO','CO'].includes(c.status))unknown.push(c);
 }return {pending,unknown,state:cut===null?'Indeterminado':pending.length?'Em manutenção':unknown.length?'Indeterminado':'Disponível estimado'};}
const fleet=D.veiculos.map(v=>({...v,region:region(v.gre_id,v.cidade),...maintenance(v)}));
const planned=new Set(routes.filter(r=>r.v).map(r=>String(r.v.id))),today=D.agora.slice(0,10);
const scales=D.escalas.filter(e=>e.tipo_rota==='RR'&&e.anulada===false&&e.ativa!==false).map(e=>({...e,...resolve(e,'motorista_id',e.veiculo_id)}));
const devices=group(D.rastreadores.filter(t=>t.veiculo_id!=null),t=>String(t.veiculo_id));
function tracking(v){const ts=devices.get(String(v.id))||[];if(!ts.length)return 'Sem rastreador';const times=ts.map(t=>Date.parse(t.ultima_atualizacao)).filter(Number.isFinite);if(!times.length)return 'Inoperante — sem histórico';const last=Math.max(...times),h=(Date.parse(D.agora)-last)/3600000;return h<0?'Data futura — conferir':h<=48?'Comunicação em até 48h':'Sem comunicação há mais de 48h';}
function table(headers,rows){return '<div class="scroll"><table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';}
const cards=rows=>'<div class="cards">'+rows.map(([l,n,s])=>'<div class="card">'+esc(l)+'<strong>'+esc(n)+'</strong><span class="note">'+esc(s||'')+'</span></div>').join('')+'</div>';
function tree(rows,levels,leaf){if(!levels.length)return leaf(rows);const [label,fn]=levels[0];return [...group(rows,fn)].sort((a,b)=>String(a[0]).localeCompare(String(b[0]),'pt-BR')).map(([key,rs])=>'<details><summary>'+esc(label+': '+key)+' · '+rs.length+'</summary>'+tree(rs,levels.slice(1),leaf)+'</details>').join('');}
function matches(r,route=false){return (!$('region').value||r.region===$('region').value)&&(!$('gre').value||String(r.gre_id)===$('gre').value)&&(!$('city').value||r.cidade===$('city').value)&&(!$('category').value||(route?r.v?.categoria:r.categoria)===$('category').value)&&(!$('plate').value||norm(route?r.v?.placa:r.placa).includes(norm($('plate').value)));}
function vehicleLeaf(rs){return table(['Placa','Status cadastral','GRE','Cidade','Situação','Rota ativa associada','Reserva'],rs.map(v=>[v.placa,v.status,gname(v.gre_id),v.cidade,v.state,planned.has(String(v.id))?'Sim':'Sem associação',v.is_reserva?'Sim':'Não']));}
function fleetLeaf(rs){const available=rs.filter(v=>v.state==='Disponível estimado'),pending=rs.filter(v=>v.state==='Em manutenção'),unknown=rs.filter(v=>v.state==='Indeterminado');
 const withScale=available.filter(v=>scales.some(e=>e.data===today&&e.v&&String(e.v.id)===String(v.id))),withoutScale=available.filter(v=>!withScale.includes(v));
 const entries=pending.flatMap(v=>v.pending.map(c=>({v,c,office:O.get(String(c.oficina_id))?.nome||'Sem oficina'})));
 return '<details><summary>Disponíveis estimados · '+available.length+'</summary><p class="note">Escala para '+esc(today)+'; associação cadastral atual. Ausência de escala não é prova de falha de planejamento.</p><details><summary>Com escala planejada · '+withScale.length+'</summary>'+vehicleLeaf(withScale)+'</details><details><summary>Sem escala identificada · '+withoutScale.length+'</summary>'+vehicleLeaf(withoutScale)+'</details></details><details><summary>Em manutenção · '+pending.length+' veículos</summary><p class="note">Detalhes abaixo contam chamados; uma placa pode aparecer em mais de uma oficina.</p>'+tree(entries,[['Oficina',x=>x.office],['Cidade de atendimento',x=>x.v.cidade||'Sem cidade']],xs=>table(['Placa','Chamado','OS','Condição registrada','Início','Horas desde início','Previsão'],xs.map(({v,c})=>[v.placa,c.id,(oss.get(String(c.id))||[]).map(o=>o.id).join(', '),c.condicao_operacional,date(c.inicio_servico),num(Math.max(0,(cut-Date.parse(c.inicio_servico))/3600000)),date(c.data_previsao)])))+'</details><details><summary>Indeterminados · '+unknown.length+'</summary>'+vehicleLeaf(unknown)+'</details>';}
function render(){const vs=fleet.filter(v=>matches(v)),active=vs.filter(v=>v.status==='A'),maint=active.filter(v=>v.state==='Em manutenção'),unk=active.filter(v=>v.state==='Indeterminado'),avail=active.filter(v=>v.state==='Disponível estimado'),rr=routes.filter(r=>matches(r,true));
 $('frota').innerHTML='<h2>Frota e disponibilidade na referência da fonte</h2>'+cards([['Ativos',active.length,'Cadastro atual'],['Inativos (I)',vs.filter(v=>v.status==='I').length,'Demais status separados'],['Outros status',vs.filter(v=>!['A','I'].includes(v.status)).length,'Sem interpretação automática'],['Indeterminados',unk.length,'Datas/status para conferir'],['Disponíveis estimados',avail.length,pct(avail.length,active.length)+' da frota ativa'],['Em manutenção',maint.length,pct(maint.length,active.length)+' da frota ativa'],['% disponibilidade',pct(avail.length,active.length),'Parcela estimada disponível'],['% indisponibilidade',pct(maint.length,active.length),'Parcela em manutenção identificada']])+'<p class="note">Com indeterminados, disponível + manutenção não soma 100%. Regra: serviço iniciado e ainda não encerrado, desconsiderando cancelados. Condição RODANDO/PARADO é exibida para conferência. Não é a disponibilidade histórica ponderada por horas.</p>'+table(['Vínculo','Ativos','% da frota ativa','Em manutenção','Disponíveis estimados'],Object.entries(cats).map(([k,l])=>{const a=active.filter(v=>v.categoria===k);return[l,a.length,pct(a.length,active.length),a.filter(v=>v.state==='Em manutenção').length,a.filter(v=>v.state==='Disponível estimado').length];}))+tree(active,[['Vínculo',v=>cats[v.categoria]||v.categoria||'Sem vínculo'],['Região',v=>v.region],['Tipo',v=>v.tipo||'Sem tipo'],['Modelo',v=>v.modelo||'Sem modelo']],fleetLeaf)+'<details><summary>Todos os veículos filtrados, inclusive inativos</summary>'+vehicleLeaf(vs)+'</details><p><a href="../manutencao/">Disponibilidade histórica por horas e evolução diária no painel de manutenção</a></p>';
 const routeCategories=group(rr,r=>r.issue?'Pendente: '+r.issue:cats[r.v?.categoria]||'Vínculo não informado');
 $('rotas').innerHTML='<h2>Rotas planejadas — cadastro ativo atual</h2>'+cards([['Rotas ativas',rr.length,'Cada ID contado uma vez'],['Veículos associados',new Set(rr.filter(r=>r.v).map(r=>String(r.v.id))).size,'Não representa veículos executores'],['Pendências de vínculo',rr.filter(r=>r.issue).length,'Mantidas no denominador geral'],['Sem motorista padrão',rr.filter(r=>!M.has(String(r.motorista_padrao_id))).length,'Cadastro atual']])+table(['Vínculo / pendência','Rotas','% das rotas filtradas'],[...routeCategories].map(([k,rs])=>[k,rs.length,pct(rs.length,rr.length)]))+'<p class="note">Percentuais usam todas as rotas do recorte, inclusive pendências. Filtrar um vínculo restringe o denominador a ele. Não usamos execução. Rotas cadastradas e escalas diárias são contagens diferentes.</p>'+tree(rr,[['Região',r=>r.region],['GRE',r=>gname(r.gre_id)],['Município',r=>r.cidade||'Sem cidade'],['Vínculo',r=>r.issue||cats[r.v?.categoria]||'Não informado']],rs=>table(['Rota ID','Rota','Turno','Placa','Status veículo','Motorista padrão','Origem da associação','Pendência'],rs.map(r=>[r.id,r.nome,r.turno,r.v?.placa,r.v?.status,M.get(String(r.motorista_padrao_id))?.nome,r.origins,r.issue||'—'])))+'<h3>Veículos ativos sem associação a rota ativa</h3>'+vehicleLeaf(active.filter(v=>!planned.has(String(v.id))));
 const ms=D.motoristas.map(m=>({...m,region:region(m.gre_id,m.cidade),categoria:V.get(String(m.veiculo_id))?.categoria,placa:V.get(String(m.veiculo_id))?.placa})).filter(m=>matches(m));const driverRoutes=new Set(routes.map(r=>String(r.motorista_padrao_id)));
 $('motoristas').innerHTML='<h2>Motoristas — cadastro atual</h2>'+cards([['Ativos (A)',ms.filter(m=>m.status==='A').length,''],['Inativos (I)',ms.filter(m=>m.status==='I').length,''],['Outros status',ms.filter(m=>!['A','I'].includes(m.status)).length,'D/F e outros sem tradução automática'],['Ativos sem rota padrão',ms.filter(m=>m.status==='A'&&!driverRoutes.has(String(m.id))).length,'Sem associação encontrada no cadastro ativo']])+'<p class="note">O filtro de vínculo da frota usa o veículo cadastrado do motorista. O vínculo do motorista é detalhado abaixo e não é confundido com o vínculo da frota.</p>'+tree(ms,[['Vínculo motorista',m=>m.tipo_vinculo||'Sem vínculo'],['GRE',m=>gname(m.gre_id)],['Cidade',m=>m.cidade||'Sem cidade']],rs=>table(['Motorista','Status','Veículo cadastrado','Possui rota ativa como padrão'],rs.map(m=>[m.nome,m.status,m.placa,driverRoutes.has(String(m.id))?'Sim':'Sem associação'])));
 $('rastreamento').innerHTML='<h2>Rastreamento da frota ativa filtrada</h2>'+cards([['Frota ativa',active.length,''],['Com rastreador',active.filter(v=>devices.has(String(v.id))).length,'Equipamento associado à placa'],['Sem rastreador',active.filter(v=>!devices.has(String(v.id))).length,''],['Cobertura',pct(active.filter(v=>devices.has(String(v.id))).length,active.length),'Associação cadastral, independente da comunicação']])+tree(active,[['Situação',tracking],['Vínculo',v=>cats[v.categoria]||'Sem vínculo'],['GRE',v=>gname(v.gre_id)],['Cidade',v=>v.cidade||'Sem cidade']],vehicleLeaf);
 $('planejamento').innerHTML='<h2>Escalas planejadas — consulta por dia</h2><p class="note">Registros RR não anulados, excluindo ativa=false. Ativa nula permanece identificada como legado. Vínculo com veículo via cadastro atual: não prova histórico. Fonte carregada: 90 dias anteriores e 30 futuros à geração.</p><label>Data da escala<input type="date" id="scaleDate" value="'+esc(scaleDay)+'"></label><div id="scaleResult"></div>';
 $('scaleDate').onchange=()=>{scaleDay=$('scaleDate').value;renderScales();};renderScales();
 }
let scaleDay=today;function renderScales(){const es=scales.filter(e=>e.data===scaleDay).map(e=>{const r=R.get(String(e.rota_id))||{};return {...e,gre_id:r.gre_id,cidade:r.cidade,region:region(r.gre_id,r.cidade,true)};}).filter(e=>matches(e,true));$('scaleResult').innerHTML=cards([['Escalas',es.length,'Não é quantidade de rotas distintas'],['Rotas distintas',new Set(es.map(e=>e.rota_id).filter(x=>x!=null)).size,''],['Vínculos pendentes',es.filter(e=>e.issue).length,''],['Legado ativa nula',es.filter(e=>e.ativa==null).length,'Requer interpretação da fonte']])+table(['Escala','Rota','GRE','Cidade','Placa associada','Vínculo','Origem','Pendência / conflito'],es.map(e=>[e.id,e.rota_id,gname(e.gre_id),e.cidade,e.v?.placa,cats[e.v?.categoria],e.origins,e.issue||(fleet.find(v=>String(v.id)===String(e.v?.id))?.state==='Em manutenção'&&scaleDay===source?.slice(0,10)?'Em manutenção na referência da fonte':'—')]));}
for(const g of D.gres.slice().sort((a,b)=>a.nome.localeCompare(b.nome)))$('gre').add(new Option(g.nome,String(g.id)));for(const c of [...new Set([...D.veiculos,...D.rotas,...D.motoristas].map(r=>r.cidade).filter(Boolean))].sort())$('city').add(new Option(c,c));for(const [k,v] of Object.entries(cats))$('category').add(new Option(v,k));
const tabs=[['frota','Frota e manutenção'],['rotas','Rotas planejadas'],['planejamento','Escalas por dia'],['motoristas','Motoristas'],['rastreamento','Rastreamento']];$('sections').innerHTML=tabs.map(([k])=>'<section id="'+k+'" hidden></section>').join('');$('tabs').innerHTML=tabs.map(([k,l])=>'<button data-tab="'+k+'" aria-pressed="false">'+l+'</button>').join('');function show(k){tabs.forEach(([id])=>$(id).hidden=id!==k);$('tabs').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab===k)));}document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>show(b.dataset.tab));
$('updated').textContent='Gerado em '+date(D.agora)+' · Última extração de chamados: '+date(source)+' · Frota: '+date(latest(D.veiculos))+' · Rotas: '+date(latest(D.rotas))+' · Escalas: '+date(latest(D.escalas))+'. Datas de extração não comprovam sincronização completa.';
['region','gre','city','category'].forEach(k=>$(k).onchange=render);$('plate').oninput=render;$('reset').onclick=()=>{['region','gre','city','category','plate'].forEach(k=>$(k).value='');render();};render();show('frota');
</script></main></body></html>'''

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
 conn=psycopg2.connect(host=os.environ['DB_HOST'],port=int(os.environ.get('DB_PORT') or '5432'),database=os.environ.get('DB_NAME') or 'postgres',user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],sslmode='require',connect_timeout=15)
 try:
  conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
  with conn:
   with conn.cursor() as cur:
    cur.execute("SET LOCAL TIME ZONE 'America/Sao_Paulo'")
    cur.execute("SET LOCAL statement_timeout = '120s'")
   dados=carregar(conn)
 finally:conn.close()
 publicar_compacto(montar_html(dados),destino='public/monitoramento')
