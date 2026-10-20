"""Painel independente de manutenção. PostgreSQL somente leitura."""
import json
import os
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Sao_Paulo')
STATUS = {'NI':'Solicitado', 'RO':'Direcionado / agendado', 'EA':'Serviço em andamento',
          'AO':'Checklist realizado', 'CO':'Diagnóstico e previsão registrados',
          'CC':'Finalizado', 'CA':'Cancelado'}
PENDENTES = {'NI','RO','EA','AO','CO'}

def normalizar(s):
    return ''.join(c for c in unicodedata.normalize('NFD', str(s or '')) if unicodedata.category(c) != 'Mn').upper()

def data_local(x):
    if not x: return None
    if isinstance(x,str): x=datetime.fromisoformat(x.replace('Z','+00:00'))
    return x.astimezone(TZ).isoformat()

def dia(x): return data_local(x)[:10] if x else None

def classificar(nome, tipo):
    n=normalizar(nome)
    if tipo=='peca':
        if re.match(r'^PNEU\b',n): return 'Pneu — item lançado'
        if re.match(r'^OLEO\b',n) and 'DIESEL' not in n: return 'Óleo — item lançado'
        return 'Outras peças'
    if 'PNEU' in n:
        if any(w in n for w in ['CONSERTO','REMENDO','VULCAN','REPARO']): return 'Pneu — reparo'
        if 'RECAP' in n: return 'Pneu — recapagem'
        if any(w in n for w in ['RODIZIO','REVEZAMENTO']): return 'Pneu — rodízio'
        if 'CALIBR' in n: return 'Pneu — calibragem'
        if 'TROCA' in n and not any(w in n for w in ['PITO','VALVULA']): return 'Pneu — troca'
        return 'Pneu — outros serviços'
    # Não confundir sensor, bomba, junta ou mangueira de óleo com troca de fluido.
    if re.search(r'COMPLET\w* (?:O |DO |DE )?OLEO',n): return 'Óleo — complemento'
    if re.search(r'TROCA (?:DE |DO )?OLEO',n): return 'Óleo — troca'
    return 'Outros serviços'

def preparar(raw):
    vehicles={str(v['id']):v for v in raw['veiculos']}
    chamados={str(c['id']):c for c in raw['chamados']}
    por_chamado=defaultdict(list)
    for o in raw['os']: por_chamado[str(o['chamado_id'])].append(o)
    itens=defaultdict(list)
    for i in raw['itens']: itens[str(i['os_id'])].append(i)
    records=[]
    for c in raw['chamados']:
        v=vehicles.get(str(c['veiculo_id']),{})
        common=dict(chamado=c['id'],veiculo=c['veiculo_id'],placa=v.get('placa') or 'SEM PLACA',
            categoria=v.get('categoria') or 'NÃO INFORMADA',status_veiculo=v.get('status'),
            fornecedor=v.get('fornecedor') or 'SEM FORNECEDOR',fornecedor_id=v.get('fornecedor_id'),
            oficina=c.get('oficina') or 'SEM OFICINA',oficina_id=c.get('oficina_id'),
            gre=v.get('gre') or 'SEM GRE',cidade=v.get('cidade') or 'SEM CIDADE',
            status=c['status'],situacao=STATUS.get(c['status'],'Status não mapeado: '+str(c['status'])),
            condicao=c.get('condicao_operacional'),abertura=dia(c.get('emissao')),
            abertura_hora=data_local(c.get('emissao')),previsao_hora=data_local(c.get('data_previsao')),
            inicio_hora=data_local(c.get('inicio_servico')),fechamento_hora=data_local(c.get('entrega')),
            extracao_chamado=data_local(c.get('_airbyte_extracted_at')),
            previsao=dia(c.get('data_previsao')),fechamento=dia(c.get('entrega')),
            inicio=dia(c.get('inicio_servico')),pendente=c['status'] in PENDENTES)
        for o in por_chamado.get(str(c['id'])) or [None]:
            r=dict(common,os=o['id'] if o else None,status_os=o['status'] if o else None,
                data_os=dia(o.get('data')) if o else None,data_os_hora=data_local(o.get('data')) if o else None,pecas=0,servicos=0,incompletos=0,simbolicos=0,grupos={})
            for i in itens.get(str(r['os']),[]):
                q,val=i.get('quantidade'),i.get('valor')
                valido=q is not None and val is not None and q>0 and val>=0
                custo=float(q*val) if valido else 0
                if not valido:r['incompletos']+=1
                if i['tipo']=='servico' and val in (0,1):r['simbolicos']+=1
                r['pecas' if i['tipo']=='peca' else 'servicos']+=custo
                label=classificar(i.get('nome'),i['tipo']) if i.get('nome') else 'Sem catálogo localizado'
                g=r['grupos'].setdefault(label,{'itens':0,'custo':0})
                g['itens']+=1;g['custo']+=custo
            r['itens_registrados']=len(itens.get(str(r['os']),[]))
            r['custo']=r['pecas']+r['servicos']
            r['conflito']=bool(o and ((c['status']=='CC' and o['status']!='CC') or (c['status']!='CC' and o['status']=='CC')))
            r['fechado']=bool(o and c['status']=='CC' and o['status']=='CC' and c.get('entrega') and not r['conflito'])
            r['data_invalida']=bool(c.get('entrega') and (c['entrega']>raw['agora'] or (c.get('inicio_servico') and c['entrega']<c['inicio_servico']) or (c.get('emissao') and c['entrega']<c['emissao'])))
            r['pontual']=None if not r['fechado'] or not r['previsao'] or r['data_invalida'] else r['fechamento']<=r['previsao']
            r['dias_atendimento']=None
            if r['fechado'] and not r['data_invalida'] and c.get('emissao'):
                r['dias_atendimento']=round((c['entrega']-c['emissao']).total_seconds()/86400,2)
            records.append(r)
    # Recorrência por chamado, não por item ou OS. Cada novo chamado vincula só a conclusão anterior mais recente.
    events=defaultdict(list)
    for c in raw['chamados']:
        if c.get('veiculo_id') is not None and c.get('emissao') and c['status']!='CA':events[str(c['veiculo_id'])].append(c)
    recurrence={}
    for cs in events.values():
        closed=sorted([c for c in cs if c['status']=='CC' and c.get('entrega') and c['entrega']>=c['emissao'] and c['entrega']<=raw['agora']],key=lambda c:c['entrega'])
        j=0;prev=None
        for c in sorted(cs,key=lambda c:c['emissao']):
            while j<len(closed) and closed[j]['entrega']<c['emissao']:
                prev=closed[j];j+=1
            if prev:
                days=(c['emissao']-prev['entrega']).total_seconds()/86400
                if days<=30:recurrence[c['id']]={'anterior':prev['id'],'dias':round(days,2),'mesma_oficina':c.get('oficina_id') is not None and c.get('oficina_id')==prev.get('oficina_id'),'oficina_anterior':prev.get('oficina') or 'SEM OFICINA'}
    for r in records:r['retorno']=recurrence.get(r['chamado'])
    latest={k:data_local(v) for k,v in raw['extracoes'].items()}
    return dict(agora=data_local(raw['agora']),extracoes=latest,veiculos=raw['veiculos'],registros=records,
                os_sem_chamado=sum(str(o['chamado_id']) not in chamados for o in raw['os']))

def carregar(conn):
    from psycopg2.extras import RealDictCursor
    sqls={
    'veiculos':"""SELECT v.id,v.placa,v.status,v.tipo_contrato_locacao AS categoria,v.fornecedor_id,
    COALESCE(f.nome,'SEM FORNECEDOR') AS fornecedor,COALESCE(g.nome,'SEM GRE') AS gre,
    COALESCE(NULLIF(TRIM(v.cidade),''),'SEM CIDADE') AS cidade
    FROM airbyte.veiculos_veiculo v LEFT JOIN airbyte.motoristas_fornecedor f ON f.id=v.fornecedor_id
    LEFT JOIN airbyte.escolas_gre g ON g.id=v.gre_id""",
    'chamados':"""SELECT c.id,c.veiculo_id,c.status,c.condicao_operacional,c.emissao,c.inicio_servico,
    c.data_previsao,c.entrega,c.oficina_id,c._airbyte_extracted_at,f.nome AS oficina FROM airbyte.ordens_chamado c
    LEFT JOIN airbyte.motoristas_fornecedor f ON f.id=c.oficina_id""",
    'os':'SELECT id,chamado_id,status,data FROM airbyte.ordens_ordemservico',
    'itens':"""SELECT 'peca' AS tipo,i.os_id,i.quantidade,i.valor,p.descricao AS nome FROM airbyte.ordens_peca i
    LEFT JOIN airbyte.ordens_produto p ON p.id=i.produto_id
    UNION ALL SELECT 'servico',i.os_id,i.quantidade,i.valor,s.descricao FROM airbyte.ordens_servico i
    LEFT JOIN airbyte.ordens_servicodisponivel s ON s.id=i.servico_disponivel_id"""}
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT CURRENT_TIMESTAMP AS agora');raw=dict(cur.fetchone());raw['extracoes']={}
        for k,sql in sqls.items():cur.execute(sql);raw[k]=[dict(r) for r in cur.fetchall()]
        for table in ['ordens_chamado','ordens_ordemservico','ordens_peca','ordens_servico','veiculos_veiculo']:
            cur.execute('SELECT MAX(_airbyte_extracted_at) AS ultima FROM airbyte.'+table)
            raw['extracoes'][table]=cur.fetchone()['ultima']
    return preparar(raw)

def montar_html(d):
    return HTML.replace('__DATA__',json.dumps(d,ensure_ascii=False,default=str,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026'))

HTML = r'''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Log-PI · Manutenção</title><style>
*{box-sizing:border-box}body{margin:0;background:#091522;color:#eef6ff;font:16px/1.5 system-ui}main{max-width:1850px;margin:auto;padding:24px}h1{margin:4px 0;font-size:28px}h2{font-size:19px}a{color:#50ddc2}header{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}p,label,.note{color:#cddde9}.note{font-size:14px}.filters{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0}label{display:grid;gap:5px;font-size:14px}select,input,button{background:#1c3549;color:#f5f9ff;border:1px solid #59768d;border-radius:6px;padding:10px;font:inherit;max-width:260px}button{cursor:pointer}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.card,section{border:1px solid #355166;background:#122432;border-radius:10px;padding:18px;min-width:0}section{margin:18px 0}.card strong{font-size:27px;display:block;margin:8px 0}.card span{font-size:14px}.scroll{overflow:auto;max-height:480px}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}th,td{padding:12px;text-align:left;border-bottom:1px solid #355166}th{position:sticky;top:0;background:#1b364a}th button{border:0;padding:0;background:none;font-weight:bold}.alert{padding:16px;border-left:4px solid #ffc36b;background:#26313b}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}.bar{height:10px;background:#36cdaa;border-radius:4px;display:block;margin:5px 0}.annual{max-height:none}.annual td:first-child{position:sticky;left:0;background:#1b364a}summary{cursor:pointer}details p{max-width:1300px}:focus-visible{outline:3px solid #35bbef}@media(max-width:1050px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.grid{grid-template-columns:1fr}}@media(max-width:650px){main{padding:12px}.cards{grid-template-columns:1fr}.filters label{width:100%}select,input{max-width:100%}}
#fleet{grid-template-columns:repeat(3,minmax(0,1fr))}@media(max-width:650px){#fleet{grid-template-columns:1fr}}
.workshop-monthly th:first-child,.workshop-monthly td:first-child{position:sticky;left:0;min-width:240px;background:#1b364a;z-index:1}.workshop-monthly th:first-child{z-index:3}.workshop-monthly td:not(:first-child){text-align:center;font-weight:650;font-size:16px}.workshop-monthly th{min-width:76px}.workshop-monthly td:last-child{background:#19413f}#availability-chart svg{display:block;min-width:950px;width:100%;height:auto}#availability-chart [data-day]:focus{outline:none;stroke:#fff}#availability-download{background:#137d72;margin:8px 0}#availability .cards{margin-bottom:16px}#availability .scroll{margin-top:14px}</style><main><header><div><small>LOG-PI / CONTROL TOWER</small><h1>Frota e manutenção</h1><p>Atendimento, custos registrados, recorrências e previsões</p></div><nav><a href="../">Contratos</a> · <a href="../abastecimento/">Abastecimento</a> · <a href="../rastreamento/">Rastreamento</a></nav></header>
<p id="updated" class="note"></p><div id="freshness" class="alert"></div>
<div class="filters"><label>Ano<select id="year"></select></label><label>Mês<select id="month"><option value="">Todos os meses</option></select></label><label>GRE<select id="gre"></select></label><label>Cidade do veículo<select id="cidade"></select></label><label>Categoria<select id="categoria"></select></label><label>Fornecedor da frota<select id="fornecedor"></select></label><label>Oficina<select id="oficina"></select></label><label>Buscar placa<input id="plate" placeholder="Placa"></label><button id="reset">Limpar filtros</button></div>
<p id="scope"></p><div class="cards" id="kpis"></div>
<section><h2>Frota ativa — situação registrada na última extração</h2><p class="note">Independente do mês selecionado. Condição PARADO/RESTRITO é a informada no chamado; não comprova a condição física atual.</p><div class="cards" id="fleet"></div></section>
<section id="availability"><h2>Disponibilidade da frota — estimativa por veículo-dia</h2><p id="availability-note" class="alert"></p><p class="note">Regra aprovada: início do serviço até fechamento da OS; manutenções programadas também reduzem a disponibilidade. Dias de início e fechamento contam por inteiro. Períodos sobrepostos da mesma placa não duplicam dias. Base: frota ativa atual, aplicada retroativamente; não é o cadastro histórico da frota.</p><h3>Posição na data da fonte</h3><div class="cards" id="availability-snapshot"></div><div class="scroll" id="availability-snapshot-categories"></div><h3>Consolidado do mês selecionado</h3><div class="cards" id="availability-month-cards"></div><div class="scroll" id="availability-summary"></div><h3>Evolução diária da disponibilidade</h3><div class="scroll" id="availability-chart"></div><p id="availability-day" class="note" aria-live="polite"></p><h3>Detalhamento por placa</h3><button id="availability-download" type="button">Baixar Excel desta análise</button><p class="note">Excel com resumo, evolução diária, dias por placa, veículo-dia, intervalos de OS e critérios. Nenhum outro bloco é exportado. Disponível estimado significa ausência de manutenção nos registros segundo a regra adotada, não comprovação de execução de rotas.</p><div class="scroll" id="availability-plates"></div></section>
<section><h2>OS fechadas por oficina — mês a mês</h2><p class="note">Oficinas nas linhas e meses nas colunas. Conta OS distintas pela data de fechamento válida, com OS e chamado finalizados e sem divergência. Respeita os filtros, mantendo o ano completo independentemente do mês selecionado. Traço indica mês fora da cobertura observada; zero indica nenhuma conclusão registrada no recorte.</p><div class="scroll workshop-monthly" id="workshop-monthly"></div></section>
<section><h2>Gastos por oficina — mês a mês</h2><p class="note">Peças + serviços registrados, pela data da OS, com OS e chamado CC e sem divergência. Valores registrados não equivalem a pagamentos. Mantém o ano completo e respeita os demais filtros. Traço indica mês fora da cobertura; zero significa nenhum valor elegível registrado, não ausência comprovada de custo.</p><div class="scroll workshop-monthly" id="workshop-cost-monthly"></div></section>
<section><h2>Evolução anual — OS e custos registrados</h2><p class="note">Mantém todos os meses do ano. OS e custos pela data da OS; fechamentos e pontualidade pela data de entrega vinculada.</p><div class="scroll annual" id="annual"></div></section>
<section><h2>OS em aberto por oficina</h2><p class="note">Posição na última extração, independente de ano e mês. Respeita os demais filtros. Conta OS distintas com código AB ou EA e chamado pendente (NI, RO, EA, AO ou CO), com ou sem previsão. Cancelamentos, finalizações e divergências ficam fora desta contagem. Veículos vencidos são contados uma vez em cada oficina, somente entre essas OS abertas.</p><div class="scroll" id="open-workshops"></div></section>
<section><h2>Previsões e pendências</h2><p class="note">Abertura do chamado, abertura da OS e início do serviço são datas distintas, mostradas separadamente. A previsão é a última cadastrada no chamado. Os dias de atraso usam a data de referência da fonte indicada nos cards, não a data atual. Datas antigas não são corrigidas automaticamente: precisam ser conferidas no sistema.</p><div class="cards" id="forecast"></div><div class="scroll" id="pending"></div></section>
<section><h2>Fornecedor da frota — volume e valores registrados</h2><p class="note">Fornecedor do cadastro atual do veículo. Frota atual não representa o tamanho histórico da frota; não é usado um índice de eficiência histórica com esse denominador.</p><div class="scroll" id="suppliers"></div></section>
<section><h2>Oficinas — entradas, conclusões e prazo</h2><p class="note">Recebidos são chamados atribuídos à oficina atual, agrupados pela abertura. Conclusões pela entrega. São grupos diferentes; sua divisão não é uma taxa de eficiência.</p><div class="scroll" id="workshops"></div></section>
<section><h2>Veículos com mais OS e custo</h2><p class="note">Clique nos títulos para ordenar. Valores de peças e serviços separados.</p><div class="scroll" id="vehicles"></div></section>
<section><h2>Retornos após fechamento — até 30 dias</h2><p class="note">Novo chamado após a conclusão anterior mais recente do veículo. Não comprova retrabalho. O mês filtra a abertura do novo chamado. Janelas de 7, 15 e 30 dias são cumulativas.</p><div class="cards" id="return-kpis"></div><div class="scroll" id="returns"></div></section>
<section><h2>Pneus e óleo — por placa e oficina</h2><p class="note">Classificação pelo catálogo. Contamos OS distintas por grupo, não somamos linhas como trocas físicas. Quantidades de óleo não são convertidas em litros: unidades e embalagens não estão padronizadas.</p><div class="scroll" id="items"></div></section>
<section><h2>OS do período — detalhamento</h2><div class="scroll" id="details"></div></section>
<section><h2>Conferência de dados</h2><div id="quality"></div></section>
<details><summary>Regras e limites da análise</summary><p>Consultas somente leitura. Custos = quantidade × valor dos itens, regra observada na interface, ainda pendente de conciliação de uma OS completa com o banco. São valores registrados, não pagamentos nem custo integral da mão de obra. Serviços de 0 ou 1 são preservados. Itens com quantidade inválida ou valor ausente/negativo são sinalizados e não entram na soma.</p><p>Custos padrão incluem OS com status CC e chamado CC, sem divergência. Demais OS aparecem no detalhamento para conferência. Fechamento usa entrega do chamado vinculado; comparação com a última previsão é por dia em São Paulo. Não há histórico de revisões da previsão. Cancelados ficam fora das pendências e recorrências.</p><p>Status dos chamados: NI solicitado; RO direcionado; EA serviço iniciado; AO checklist realizado; CO diagnóstico/previsão; CC finalizado; CA cancelado. Etapas intermediárias inferidas de exemplos. Status das OS não são traduzidos automaticamente. Não há comprovação de imobilização por ausência de fechamento. Datas inválidas e divergências são excluídas da pontualidade.</p><p>O período de observação é limitado pela extração. Retornos contam novos chamados observados, sem taxa de reincidência por janela madura e sem inferir repetição do mesmo defeito. Fornecedor, categoria, GRE e cidade são cadastros atuais do veículo; oficina vem do chamado. Fornecedor de compra de peças não é confundido com oficina executora.</p></details>
</main><script type="application/json" id="data">__DATA__</script><script>
(()=>{'use strict';const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id),R=D.registros,V=D.veiculos;
const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),money=x=>Number(x).toLocaleString('pt-BR',{style:'currency',currency:'BRL'}),n=x=>Number(x).toLocaleString('pt-BR',{maximumFractionDigits:1}),sum=(a,k)=>a.reduce((s,r)=>s+(r[k]||0),0),uniq=(a,k)=>[...new Map(a.map(r=>[r[k],r])).values()],count=(a,k)=>new Set(a.filter(r=>r[k]!=null).map(r=>r[k])).size,pct=(a,b)=>b?n(100*a/b)+'%':'—',norm=x=>String(x||'').replace(/[^a-z0-9]/gi,'').toUpperCase();
const names=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'],cats={FROTA_PROPRIA:'Próprios',FROTA_LOCADA:'Locados',FROTA_PARCEIRO:'Parceiros',FROTA_TERCEIRIZADA:'Terceirizados'},label=(k,x)=>k==='categoria'?(cats[x]||x):x;
const source=D.extracoes.ordens_chamado,asof=(source||D.agora).slice(0,10),days=(a,b)=>Math.floor((Date.parse(a+'T12:00:00Z')-Date.parse(b+'T12:00:00Z'))/86400000),periodMatch=(d,p)=>!!d&&d.startsWith(p);
const years=[...new Set([D.agora.slice(0,4),...R.flatMap(r=>[r.abertura,r.data_os,r.fechamento].filter(Boolean).map(d=>d.slice(0,4)))])].sort().reverse();years.forEach(y=>$('year').add(new Option(y,y)));names.forEach((x,i)=>$('month').add(new Option(x,String(i+1).padStart(2,'0'))));
const keyValue=(r,k)=>k==='fornecedor'?String(r.fornecedor_id??'sem'):k==='oficina'?String(r.oficina_id??'sem'):r[k];
for(const k of ['gre','cidade','categoria','fornecedor','oficina']){const map=new Map([...V,...R].filter(r=>r[k]!=null).map(r=>[keyValue(r,k),label(k,r[k])]));$(''+k).innerHTML='<option value="">Todos</option>'+[...map].sort((a,b)=>a[1].localeCompare(b[1],'pt-BR')).map(([v,l])=>'<option value="'+esc(v)+'">'+esc(l)+(k==='fornecedor'||k==='oficina'?' · #'+esc(v):'')+'</option>').join('');}
const brdate=x=>x?x.slice(0,10).split('-').reverse().join('/'):'—';
const sorts={};function table(id,headers,rows){const st=sorts[id];if(st)rows=[...rows].sort((a,b)=>{const x=a[st.i],y=b[st.i];return st.d*(typeof x==='number'&&typeof y==='number'?x-y:String(x??'').localeCompare(String(y??''),'pt-BR',{numeric:true}));});$(id).innerHTML='<table><thead><tr>'+headers.map((h,i)=>'<th><button data-i="'+i+'">'+esc(h)+' ↕</button></th>').join('')+'</tr></thead><tbody>'+(rows.length?rows.map(r=>'<tr>'+r.map((v,i)=>'<td>'+esc(typeof v==='number'&&headers[i].includes('R$')?money(v):v)+'</td>').join('')+'</tr>').join(''):'<tr><td colspan="'+headers.length+'">Sem registros neste recorte.</td></tr>')+'</tbody></table>';$(id).querySelectorAll('button').forEach(b=>b.onclick=()=>{const i=Number(b.dataset.i);sorts[id]={i,d:st?.i===i?-st.d:1};table(id,headers,rows);});}
function cards(id,rows){$(id).innerHTML=rows.map(([l,v,t])=>'<article class="card"><span>'+esc(l)+'</span><strong>'+esc(v)+'</strong><span>'+esc(t||'')+'</span></article>').join('');}
function grouped(rows,key){const m=new Map();for(const r of rows){const v=key(r);if(!m.has(v))m.set(v,[]);m.get(v).push(r);}return [...m];}
/* Cálculo por veículo-dia. Base: frota ativa atual, aplicada como estimativa histórica. */
function availabilityModel(vehicles, records, month, cutoff, floorDay){
 const start=month+'-01',end=new Date(Date.UTC(Number(month.slice(0,4)),Number(month.slice(5,7)),0)).toISOString().slice(0,10);
 const ds=[];for(let d=start;d<=end;d=new Date(Date.parse(d+'T12:00:00Z')+86400000).toISOString().slice(0,10))ds.push(d);
 const known=ds.filter(d=>cutoff&&d<=cutoff&&floorDay&&d>=floorDay),ids=new Set(vehicles.map(v=>v.id)),byVehicle=new Map(vehicles.map(v=>[v.id,[]])),audit=[];
 for(const r of records){
  if(!ids.has(r.veiculo)||r.os==null||r.status==='CA'||r.status_os==='CA')continue;
  let reason='',a=r.inicio,b=r.fechamento;
  const startedStates=['EA','AO','CO','CC'].includes(r.status);
  if(!a&&!startedStates)continue;
  if(r.conflito)reason='Divergência entre status do chamado e da OS';
  else if(!a)reason='Sem início de serviço';
  else if(r.data_invalida||(b&&a>b))reason='Datas de manutenção inconsistentes';
  else if(r.status==='CC'&&!b)reason='Finalizada sem data de fechamento';
  else if(!b&&!r.pendente)reason='Status não validado para intervalo aberto';
  if(!b&&!reason)b=cutoff;
  if(!cutoff)reason='Sem data de extração';
  // Sem início: considerar dúvida desde a abertura conhecida, sem inventar manutenção.
  let lo=a||r.abertura||r.data_os||start,hi=reason?(b||cutoff||end):b;
  if(a&&b&&a>b){reason='Datas de manutenção invertidas';lo=[a,b,r.abertura].filter(Boolean).sort()[0];hi=cutoff||end;}
  if(!hi||lo>hi){if(lo>end)continue;reason=reason||'Intervalo invertido';}
  if(lo>end||(hi&&hi<start))continue;
  const item={r,start:lo,end:hi||end,reason};byVehicle.get(r.veiculo).push(item);
  audit.push([r.placa,r.os,r.chamado,r.oficina,r.status,r.status_os,r.inicio||null,r.fechamento||null,r.previsao||null,reason||'Incluído; dias de início e fechamento contam',lo,hi||null]);
 }
 const daily=[],detail=[],plateRows=[];
 for(const v of vehicles){
  let maintenance=0,unknown=0,available=0;const periods=byVehicle.get(v.id);
  for(const d of known){const matches=periods.filter(p=>p.start<=d&&p.end>=d),valid=matches.filter(p=>!p.reason),bad=matches.filter(p=>p.reason);let state;
   if(valid.length){state='Em manutenção';maintenance++;}else if(bad.length){state='Indeterminado';unknown++;}else{state='Disponível estimado';available++;}
   detail.push({day:d,v,state,os:[...new Set(matches.map(p=>p.r.os))].join(', '),chamados:[...new Set(matches.map(p=>p.r.chamado))].join(', '),oficinas:[...new Set(matches.map(p=>p.r.oficina))].join(' / ')});
  }
  plateRows.push({v,base:known.length,maintenance,unknown,available,rate:known.length&&!unknown?available/known.length:null});
 }
 const categories=[...new Set(vehicles.map(v=>v.categoria||'NÃO INFORMADA'))];
 for(const day of ds){const observed=known.includes(day);const rows=detail.filter(r=>r.day===day);const stats=group=>{const vs=group===null?vehicles:vehicles.filter(v=>(v.categoria||'NÃO INFORMADA')===group),rr=group===null?rows:rows.filter(r=>(r.v.categoria||'NÃO INFORMADA')===group),m=rr.filter(r=>r.state==='Em manutenção').length,u=rr.filter(r=>r.state==='Indeterminado').length,a=rr.filter(r=>r.state==='Disponível estimado').length;return {total:vs.length,maintenance:observed?m:null,unknown:observed?u:null,available:observed?a:null,rate:observed&&vs.length&&!u?a/vs.length:null};};
  daily.push({day,observed,total:stats(null),categories:Object.fromEntries(categories.map(c=>[c,stats(c)]))});
 }
 const summarize=c=>{const rows=c===null?plateRows:plateRows.filter(r=>(r.v.categoria||'NÃO INFORMADA')===c),base=rows.reduce((a,r)=>a+r.base,0),maintenance=rows.reduce((a,r)=>a+r.maintenance,0),unknown=rows.reduce((a,r)=>a+r.unknown,0),available=rows.reduce((a,r)=>a+r.available,0);return {category:c||'TOTAL',vehicles:rows.length,days:known.length,base,maintenance,unknown,available,rate:base&&!unknown?available/base:null};};
 return {month,start,end,cutoff,known,daily,detail,plateRows,audit,summary:[summarize(null),...categories.map(summarize)]};
}
let availabilityExport=null;
function renderAvailability(match){
 const vf=V.filter(v=>v.status==='A'&&match(v));
 const cutoffRaw=D.extracoes.ordens_chamado,cutoff=cutoffRaw?cutoffRaw.slice(0,10):null;
 const floor=R.flatMap(r=>[r.abertura,r.data_os,r.inicio]).filter(Boolean).sort()[0]||null;
 const selectedMonth=$('month').value||($('year').value===(cutoff||'').slice(0,4)?cutoff.slice(5,7):'12'),month=$('year').value+'-'+selectedMonth;
 const model=availabilityModel(vf,R,month,cutoff,floor);
 // Snapshot separado do mês selecionado, na última data observada da fonte.
 const snap=cutoff?availabilityModel(vf,R,cutoff.slice(0,7),cutoff,floor).daily.find(r=>r.day===cutoff):null;
 const tot=model.summary[0],rate=x=>x===null?'—':n(x*100)+'%',result=x=>x===null?'Não avaliado':x>=.85?'Meta atingida':'Abaixo de 85%';
 $('availability-note').textContent='ESTIMATIVA sobre '+vf.length+' veículos ativos no cadastro atual. Mês: '+month+'. '+model.known.length+' dias observados. '+(!$('month').value?'Com “Todos os meses”, este bloco usa '+month+'. ':'')+'Filtro de oficina não restringe esta análise: considera manutenções em todas as oficinas dos veículos selecionados. '+(cutoff&&cutoff===D.agora.slice(0,10)?'Fonte do dia; último dia parcial.':'Fonte defasada ou ausente: não representa a disponibilidade de hoje.');
 cards('availability-snapshot',[['Frota ativa atual',vf.length,'Base constante da estimativa'],['Em manutenção na fonte',snap?.total.maintenance??'—',cutoff?brdate(cutoff):'Sem referência'],['Disponibilidade estimada na fonte',rate(snap?.total.rate??null),'Meta ≥ 85%; referência da fonte'],['Veículos indeterminados',snap?.total.unknown??'—','Pendências de datas/status impedem percentual conclusivo']]);
 const catName=c=>cats[c]||c;
 table('availability-snapshot-categories',['Categoria','Frota atual','Em manutenção na fonte','Disponíveis estimados','Indeterminados','Disponibilidade'],Object.values(cats).map((label,i)=>{const key=Object.keys(cats)[i],r=snap?.categories[key];return[label,r?.total??0,r?.maintenance??'—',r?.available??'—',r?.unknown??'—',rate(r?.rate??null)];}));
 cards('availability-month-cards',[['Disponibilidade estimada do mês',rate(tot.rate),result(tot.rate)],['Veículos-dia em manutenção',tot.maintenance,'Dias sobrepostos contados uma vez por placa'],['Veículos-dia disponíveis',tot.available,'Ausência de manutenção nos dados, pela regra adotada'],['Base de veículos-dia',tot.base,vf.length+' veículos × '+model.known.length+' dias']]);
 table('availability-summary',['Categoria','Frota atual','Dias observados','Veículos-dia totais','Em manutenção (veículos-dia)','Disponíveis (veículos-dia)','Indeterminados (veículos-dia)','Disponibilidade','Meta 85%'],model.summary.map(r=>[catName(r.category),r.vehicles,r.days,r.base,r.maintenance,r.available,r.unknown,rate(r.rate),result(r.rate)]));
 table('availability-plates',['Placa','Categoria','Fornecedor','Dias observados','Dias em manutenção','Dias disponíveis','Dias indeterminados','Disponibilidade'],model.plateRows.sort((a,b)=>b.maintenance-a.maintenance).map(r=>[r.v.placa,catName(r.v.categoria),r.v.fornecedor,r.base,r.maintenance,r.available,r.unknown,rate(r.rate)]));
 const specs=[['TOTAL','Total','#f4f8fc'],...Object.entries(cats).map(([k,l],i)=>[k,l,['#3bbbf2','#ffc36b','#b899f3','#35d2ac'][i]])],w=1120,h=350,left=55,right=1090,top=30,bottom=285,x=i=>left+i*(right-left)/Math.max(1,model.daily.length-1),y=v=>bottom-v*(bottom-top);
 let svg='<svg viewBox="0 0 '+w+' '+h+'" role="img" aria-label="Disponibilidade diária estimada no mês">';
 for(const v of [0,.25,.5,.75,1])svg+='<line x1="'+left+'" x2="'+right+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="#355166"/><text x="45" y="'+(y(v)+5)+'" text-anchor="end" fill="#d8e7f3">'+(v*100)+'%</text>';
 svg+='<line x1="'+left+'" x2="'+right+'" y1="'+y(.85)+'" y2="'+y(.85)+'" stroke="#ffb257" stroke-dasharray="7 5"/><text x="'+right+'" y="'+(y(.85)-6)+'" text-anchor="end" fill="#ffcb85">Meta 85%</text>';
 for(const [key,label,color] of specs){let segment=[];const flush=()=>{if(segment.length)svg+='<polyline fill="none" stroke="'+color+'" stroke-width="2.5" points="'+segment.join(' ')+'"/>';segment=[];};model.daily.forEach((d,i)=>{const r=key==='TOTAL'?d.total:d.categories[key];if(r?.rate==null){flush();return;}segment.push(x(i)+','+y(r.rate));svg+='<circle cx="'+x(i)+'" cy="'+y(r.rate)+'" r="3" fill="'+color+'"><title>'+esc(label+' · '+brdate(d.day)+' · '+rate(r.rate)+' · '+r.maintenance+' em manutenção / '+r.total+' veículos')+'</title></circle>';});flush();}
 model.daily.forEach((d,i)=>{svg+='<text x="'+x(i)+'" y="310" fill="#d8e7f3" text-anchor="middle" font-size="13">'+d.day.slice(8)+'</text><rect data-day="'+i+'" tabindex="0" aria-label="'+esc(brdate(d.day))+'" x="'+(x(i)-14)+'" y="20" width="28" height="270" fill="transparent"><title>'+esc(brdate(d.day)+' · '+(d.observed?'Disponibilidade '+rate(d.total.rate):'Sem observação'))+'</title></rect>';});
 $('availability-chart').innerHTML=svg+'</svg><div class="note">'+specs.map(([k,l,c])=>'<span style="color:'+c+'">● '+esc(l)+'</span>').join(' · ')+'</div>';
 const showDay=i=>{const d=model.daily[i];$('availability-day').textContent=brdate(d.day)+' · '+(d.observed?specs.map(([k,l])=>{const r=k==='TOTAL'?d.total:d.categories[k];return l+': '+rate(r?.rate??null)+(r?' ('+r.maintenance+' em manutenção / '+r.total+')':'');}).join(' · '):'Sem dados observados para este dia.');};
 $('availability-chart').querySelectorAll('[data-day]').forEach(el=>{el.onpointerenter=()=>showDay(Number(el.dataset.day));el.onfocus=el.onclick=()=>showDay(Number(el.dataset.day));});$('availability-day').textContent='Passe o mouse, toque ou use Tab sobre um dia para ver os valores. Lacunas não representam disponibilidade zero.';
 availabilityExport={model,snap,cutoff,filters:['GRE','Cidade','Categoria','Fornecedor','Placa'].map((x,i)=>x+': '+($( ['gre','cidade','categoria','fornecedor','plate'][i]).value||'Todos')).join(' | ')};
 $('availability-download').disabled=!model.known.length||!vf.length;
}

/* Exportação XLSX no navegador: OOXML com células tipadas, ZIP sem dependência externa. */
function availabilityWorkbookSheets(payload){
 const {model:m,cutoff,filters}=payload,cn=c=>cats[c]||c,dateCell=d=>d?{v:Math.round((Date.parse(d.slice(0,10)+'T00:00:00Z')-Date.UTC(1899,11,30))/86400000),s:3}:null,percentage=v=>v===null?null:{v,s:2};
 const summary=[['Disponibilidade estimada — '+m.month],['Base: frota ativa atual; não representa cadastro histórico.'],['Categoria','Veículos atuais','Dias observados','Veículos-dia totais','Dias em manutenção','Dias disponíveis','Dias indeterminados','Disponibilidade','Meta'],...m.summary.map(r=>[cn(r.category),r.vehicles,r.days,r.base,r.maintenance,r.available,r.unknown,percentage(r.rate),percentage(.85)])];
 const daily=[['Dia','Categoria','Frota atual','Em manutenção','Disponíveis estimados','Indeterminados','Disponibilidade','Observado'],...m.daily.flatMap(d=>[['TOTAL',d.total],...Object.entries(d.categories)].map(([c,r])=>[dateCell(d.day),cn(c),r.total,r.maintenance,r.available,r.unknown,percentage(r.rate),d.observed?'Sim':'Não']))];
 const plates=[['Veículo ID','Placa','Categoria','Fornecedor','GRE','Cidade','Dias observados','Dias em manutenção','Dias disponíveis','Dias indeterminados','Disponibilidade'],...m.plateRows.map(r=>[String(r.v.id),r.v.placa,cn(r.v.categoria),r.v.fornecedor,r.v.gre,r.v.cidade,r.base,r.maintenance,r.available,r.unknown,percentage(r.rate)])];
 const detail=[['Data','Veículo ID','Placa','Categoria','Fornecedor','GRE','Cidade','Situação estimada','OS relacionadas','Chamados relacionados','Oficinas'],...m.detail.map(r=>[dateCell(r.day),String(r.v.id),r.v.placa,cn(r.v.categoria),r.v.fornecedor,r.v.gre,r.v.cidade,r.state,r.os,r.chamados,r.oficinas])];
 const audit=[['Placa','OS','Chamado','Oficina','Status chamado','Status OS','Início serviço','Fechamento','Previsão','Tratamento','Início considerado','Fim considerado'],...m.audit.map(r=>r.map((v,i)=>[6,7,8,10,11].includes(i)?dateCell(v):[1,2].includes(i)?String(v):v))];
 const rules=[['Critério','Definição'],['Período',m.month],['Fonte até',dateCell(cutoff)],['Painel gerado',D.agora],['Filtros',filters],['População','Veículos ativos no cadastro atual, aplicada retroativamente como estimativa. Sem histórico de entrada/saída, GRE, categoria e fornecedor.'],['Intervalo','Início do serviço até fechamento. Início e fechamento contam como dias inteiros. Mesma placa e mesmo dia contam uma única vez.'],['Programadas','Também reduzem a disponibilidade.'],['OS sem fechamento','Contadas até a última extração de chamados; não se prolonga até hoje quando a fonte está defasada.'],['Fórmula','Dias disponíveis / veículos-dia totais. Categoria e total usam soma dos dias, não média simples de percentuais.'],['Meta',percentage(.85)],['Desconhecidos','Intervalos inconsistentes ficam indeterminados. Se houver indeterminação no grupo, seu percentual não é calculado.'],['Sem manutenção registrada','Tratado como disponível estimado pela regra adotada; não comprova atendimento às rotas.'],['Oficina','Filtro de oficina ignorado só neste bloco: são incluídas todas as oficinas da frota selecionada.'],['Dias fora da observação','Sem percentual: após a última extração ou antes do primeiro registro observado.'],['Excel','Valores são um retrato dos filtros no momento do download; não se atualizam ao abrir o arquivo.']];
 return [{name:'Resumo',rows:summary,header:3},{name:'Diario',rows:daily,header:1},{name:'Por placa',rows:plates,header:1},{name:'Veiculo-dia',rows:detail,header:1},{name:'Periodos OS',rows:audit,header:1},{name:'Criterios',rows:rules,header:1}];
}
function createAvailabilityXlsx(sheets){
 const xml=s=>String(s??'').replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g,'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c])),enc=new TextEncoder(),files=[];
 const add=(name,s)=>files.push({name:enc.encode(name),bytes:enc.encode(s)}),col=i=>{let s='';for(i++;i;i=Math.floor((i-1)/26))s=String.fromCharCode(65+(i-1)%26)+s;return s;};
 add('[Content_Types].xml','<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+sheets.map((s,i)=>'<Override PartName="/xl/worksheets/sheet'+(i+1)+'.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>').join('')+'</Types>');
 add('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>');
 add('xl/workbook.xml','<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+sheets.map((s,i)=>'<sheet name="'+xml(s.name)+'" sheetId="'+(i+1)+'" r:id="rId'+(i+1)+'"/>').join('')+'</sheets></workbook>');
 add('xl/_rels/workbook.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+sheets.map((s,i)=>'<Relationship Id="rId'+(i+1)+'" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet'+(i+1)+'.xml"/>').join('')+'<Relationship Id="rId'+(sheets.length+1)+'" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>');
 add('xl/styles.xml','<?xml version="1.0"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><numFmts count="2"><numFmt numFmtId="164" formatCode="0.0%"/><numFmt numFmtId="165" formatCode="dd/mm/yyyy"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF193449"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="4"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>');
 sheets.forEach((s,i)=>{const last=col(Math.max(...s.rows.map(r=>r.length))-1)+s.rows.length;const rows=s.rows.map((r,ri)=>'<row r="'+(ri+1)+'"'+(ri+1===s.header?' ht="32" customHeight="1"':'')+'>'+r.map((cell,ci)=>{const v=cell&&typeof cell==='object'?cell.v:cell,style=ri+1===s.header?1:cell&&typeof cell==='object'?cell.s||0:0,ref=col(ci)+(ri+1);if(v===null||v===undefined)return '<c r="'+ref+'"/>';if(typeof v==='number'&&Number.isFinite(v))return '<c r="'+ref+'" s="'+style+'"><v>'+v+'</v></c>';return '<c r="'+ref+'" s="'+style+'" t="inlineStr"><is><t xml:space="preserve">'+xml(String(v).slice(0,32767))+'</t></is></c>';}).join('')+'</row>').join('');add('xl/worksheets/sheet'+(i+1)+'.xml','<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><dimension ref="A1:'+last+'"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="'+s.header+'" topLeftCell="A'+(s.header+1)+'" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols><col min="1" max="1" width="24" customWidth="1"/><col min="2" max="20" width="23" customWidth="1"/></cols><sheetData>'+rows+'</sheetData><autoFilter ref="A'+s.header+':'+last+'"/></worksheet>');});
 const crcTable=Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++)n=n&1?0xEDB88320^(n>>>1):n>>>1;return n>>>0;}),crc=b=>{let c=0xFFFFFFFF;for(const x of b)c=crcTable[(c^x)&255]^(c>>>8);return (c^0xFFFFFFFF)>>>0;};
 const chunks=[],central=[];let offset=0,centralSize=0;
 for(const f of files){const checksum=crc(f.bytes),head=new Uint8Array(30+f.name.length),v=new DataView(head.buffer);v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(6,0x800,true);v.setUint16(12,33,true);v.setUint32(14,checksum,true);v.setUint32(18,f.bytes.length,true);v.setUint32(22,f.bytes.length,true);v.setUint16(26,f.name.length,true);head.set(f.name,30);chunks.push(head,f.bytes);
 const ch=new Uint8Array(46+f.name.length),d=new DataView(ch.buffer);d.setUint32(0,0x02014b50,true);d.setUint16(4,20,true);d.setUint16(6,20,true);d.setUint16(8,0x800,true);d.setUint16(14,33,true);d.setUint32(16,checksum,true);d.setUint32(20,f.bytes.length,true);d.setUint32(24,f.bytes.length,true);d.setUint16(28,f.name.length,true);d.setUint32(42,offset,true);ch.set(f.name,46);central.push(ch);centralSize+=ch.length;offset+=head.length+f.bytes.length;}
 const end=new Uint8Array(22),e=new DataView(end.buffer);e.setUint32(0,0x06054b50,true);e.setUint16(8,files.length,true);e.setUint16(10,files.length,true);e.setUint32(12,centralSize,true);e.setUint32(16,offset,true);
 return new Blob([...chunks,...central,end],{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
}
function downloadAvailability(){if(!availabilityExport)return;const button=$('availability-download');button.disabled=true;try{const blob=createAvailabilityXlsx(availabilityWorkbookSheets(availabilityExport)),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='disponibilidade_estimada_'+availabilityExport.model.month+'.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}finally{button.disabled=false;}}

function render(){const year=$('year').value,period=year+($('month').value?'-'+$('month').value:''),match=r=>['gre','cidade','categoria','fornecedor'].every(k=>!$(k).value||keyValue(r,k)===$(k).value)&&(!$('plate').value||norm(r.placa).includes(norm($('plate').value))),all=R.filter(r=>match(r)&&(!$('oficina').value||keyValue(r,'oficina')===$('oficina').value)),os=all.filter(r=>r.os&&periodMatch(r.data_os,period)),cost=os.filter(r=>r.status==='CC'&&r.status_os==='CC'&&!r.conflito),closed=all.filter(r=>r.fechado&&!r.data_invalida&&periodMatch(r.fechamento,period)),eligible=closed.filter(r=>r.pontual!==null),opened=uniq(all.filter(r=>periodMatch(r.abertura,period)),'chamado');
renderAvailability(match);
$('scope').textContent='Período: '+period+' · custos e OS pela data da OS; conclusões pelo fechamento.';
cards('kpis',[['OS no período',count(os,'os'),'Todos os status; consulte o detalhamento'],['Veículos com OS',count(os,'veiculo'),'Veículos distintos'],['Peças registradas',money(sum(cost,'pecas')),'OS e chamado CC, sem divergência'],['Serviços registrados',money(sum(cost,'servicos')),'Inclui valores 0 e 1'],['Total registrado',money(sum(cost,'custo')),'Não equivale a valor pago'],['OS fechadas',count(closed,'os'),'Fechamento válido no período'],['Fechamento no prazo',pct(eligible.filter(r=>r.pontual).length,eligible.length),eligible.length+' OS com previsão válida'],['Chamados cancelados',opened.filter(r=>r.status==='CA').length,'Abertos no período']]);
const pending=uniq(all.filter(r=>r.pendente),'chamado'),active=V.filter(v=>v.status==='A'&&match(v)&&(!$('oficina').value||all.some(r=>r.veiculo===v.id))),activeIds=new Set(active.map(v=>v.id)),pa=pending.filter(r=>activeIds.has(r.veiculo)),inservice=pa.filter(r=>['EA','AO','CO'].includes(r.status));
cards('fleet',[['Frota ativa cadastrada',active.length,$('oficina').value?'Veículos com vínculo de chamado à oficina':'Cadastro atual'],['Com atendimento em curso',count(inservice,'veiculo'),'Etapas EA, AO ou CO'],['Parado informado em pendência',count(pa.filter(r=>r.condicao==='PARADO'),'veiculo'),'Não é posição física confirmada']]);
const firstMonth=R.map(r=>r.data_os||r.abertura).filter(Boolean).sort()[0]?.slice(0,7)||asof.slice(0,7);const months=names.map((x,i)=>year+'-'+String(i+1).padStart(2,'0'));
const yearClosed=uniq(all.filter(r=>r.os&&r.fechado&&!r.data_invalida&&periodMatch(r.fechamento,year)),'os');
const workshopYear=all.filter(r=>periodMatch(r.abertura,year)||periodMatch(r.data_os,year)||periodMatch(r.fechamento,year));
table('workshop-monthly',['Oficina',...names.map((nm,i)=>nm+(months[i]===asof.slice(0,7)?' · parcial':'')),'Total'],grouped(workshopYear,r=>String(r.oficina_id??'sem')).map(([id,rs])=>{const closed=yearClosed.filter(r=>String(r.oficina_id??'sem')===id);return [rs[0].oficina+' #'+id,...months.map(m=>m>asof.slice(0,7)||m<firstMonth?'—':count(closed.filter(r=>periodMatch(r.fechamento,m)),'os')),count(closed,'os')];}).sort((a,b)=>b[13]-a[13]));
const yearCosts=uniq(all.filter(r=>r.os&&periodMatch(r.data_os,year)&&r.status==='CC'&&r.status_os==='CC'&&!r.conflito),'os');
table('workshop-cost-monthly',['Oficina',...names.map((nm,i)=>nm+' R$'+(months[i]===asof.slice(0,7)?' · parcial':'')),'Total R$'],grouped(workshopYear,r=>String(r.oficina_id??'sem')).map(([id,rs])=>{const costs=yearCosts.filter(r=>String(r.oficina_id??'sem')===id);return [rs[0].oficina+' #'+id,...months.map(m=>m>asof.slice(0,7)||m<firstMonth?'—':sum(costs.filter(r=>periodMatch(r.data_os,m)),'custo')),sum(costs,'custo')];}).sort((a,b)=>b[13]-a[13]));
const monthly=months.map(m=>{const rows=all.filter(r=>r.os&&periodMatch(r.data_os,m)),c=rows.filter(r=>r.status==='CC'&&r.status_os==='CC'&&!r.conflito),f=all.filter(r=>r.fechado&&!r.data_invalida&&periodMatch(r.fechamento,m));return {os:count(rows,'os'),fleet:count(rows,'veiculo'),cost:sum(c,'custo'),closed:count(f,'os')};});
table('annual',['Indicador',...names],[['OS',...monthly.map((s,i)=>(months[i]>asof.slice(0,7)||months[i]<firstMonth)?'—':s.os)],['Veículos com OS',...monthly.map((s,i)=>(months[i]>asof.slice(0,7)||months[i]<firstMonth)?'—':s.fleet)],['Valor registrado',...monthly.map((s,i)=>(months[i]>asof.slice(0,7)||months[i]<firstMonth)?'—':money(s.cost))],['OS fechadas',...monthly.map((s,i)=>(months[i]>asof.slice(0,7)||months[i]<firstMonth)?'—':s.closed)]]);
const late=pending.filter(r=>r.previsao&&r.previsao<asof),today=pending.filter(r=>r.previsao===asof),next=pending.filter(r=>r.previsao&&days(r.previsao,asof)>0&&days(r.previsao,asof)<=7),nodate=pending.filter(r=>!r.previsao);
const openOrders=uniq(all.filter(r=>r.os!=null&&['AB','EA'].includes(r.status_os)&&r.pendente&&!r.conflito),'os');
table('open-workshops',['Oficina','OS em aberto','Veículos com previsão vencida'],grouped(openOrders,r=>String(r.oficina_id??'sem')).map(([id,rs])=>[rs[0].oficina+' #'+id,count(rs,'os'),count(rs.filter(r=>r.previsao&&r.previsao<asof),'veiculo')]).sort((a,b)=>b[1]-a[1]));
cards('forecast',[['OS em aberto',count(openOrders,'os'),'Com ou sem previsão; todas as datas de abertura'],['Veículos com previsão vencida',count(late,'veiculo'),'Referência: '+asof],['Entrega na data de referência',count(today,'veiculo'),asof],['Entrega nos próximos 7 dias',count(next,'veiculo'),'Após '+asof],['Veículos sem previsão',count(nodate,'veiculo'),'Chamados pendentes; grupos podem se sobrepor']]);
table('pending',['Placa','Chamado','OS','Oficina','Situação','Condição informada','Abertura do chamado','Abertura da OS','Início do serviço','Previsão cadastrada','Dias desde abertura do chamado','Dias desde abertura da OS','Dias de atraso na fonte'],pending.sort((a,b)=>(a.previsao||'9999').localeCompare(b.previsao||'9999')).map(r=>[r.placa,r.chamado,r.os,r.oficina,r.situacao,r.condicao,brdate(r.abertura),brdate(r.data_os),brdate(r.inicio),brdate(r.previsao),r.abertura?days(asof,r.abertura):null,r.data_os?days(asof,r.data_os):null,r.previsao?Math.max(0,days(asof,r.previsao)):null]));
const supplierIds=new Set([...active.map(r=>String(r.fornecedor_id??'sem')),...os.map(r=>String(r.fornecedor_id??'sem'))]);table('suppliers',['Fornecedor / ID','Frota ativa atual','OS','Veículos com OS','Peças R$','Serviços R$','Total R$'],[...supplierIds].map(id=>{const a=active.filter(r=>String(r.fornecedor_id??'sem')===id),o=os.filter(r=>String(r.fornecedor_id??'sem')===id),c=cost.filter(r=>String(r.fornecedor_id??'sem')===id);return[(o[0]?.fornecedor||a[0]?.fornecedor||'SEM FORNECEDOR')+' #'+id,a.length,count(o,'os'),count(o,'veiculo'),sum(c,'pecas'),sum(c,'servicos'),sum(c,'custo')];}).sort((a,b)=>b[6]-a[6]));
table('workshops',['Oficina / ID','Chamados recebidos','OS no período','Chamados fechados','Pendências na fonte','OS avaliadas no prazo','No prazo','Média dias atendimento','OS com peças','Novos chamados na mesma oficina em 30d','Valor registrado R$'],grouped(all,r=>String(r.oficina_id??'sem')).map(([id,rs])=>{const f=closed.filter(r=>String(r.oficina_id??'sem')===id),e=f.filter(r=>r.pontual!==null);return[rs[0].oficina+' #'+id,opened.filter(r=>String(r.oficina_id??'sem')===id).length,count(os.filter(r=>String(r.oficina_id??'sem')===id),'os'),count(f,'chamado'),count(rs.filter(r=>r.pendente),'chamado'),e.length,pct(e.filter(r=>r.pontual).length,e.length),f.length?n(sum(f,'dias_atendimento')/f.length):'—',count(cost.filter(r=>String(r.oficina_id??'sem')===id&&Object.keys(r.grupos).some(k=>k.includes('peças')||k.endsWith('item lançado'))),'os'),opened.filter(r=>String(r.oficina_id??'sem')===id&&r.retorno?.mesma_oficina).length,sum(cost.filter(r=>String(r.oficina_id??'sem')===id),'custo')];}).sort((a,b)=>b[10]-a[10]));
table('vehicles',['Placa','Fornecedor','Categoria','OS','Chamados','Peças R$','Serviços R$','Total R$'],grouped(os,r=>r.veiculo??'sem').map(([id,rs])=>{const c=cost.filter(r=>r.veiculo===id);return[rs[0].placa,rs[0].fornecedor,cats[rs[0].categoria]||rs[0].categoria,count(rs,'os'),count(rs,'chamado'),sum(c,'pecas'),sum(c,'servicos'),sum(c,'custo')];}).sort((a,b)=>b[7]-a[7]));
const returns=opened.filter(r=>r.retorno&&r.status!=='CA');cards('return-kpis',[7,15,30].map(d=>['Novos chamados em até '+d+' dias',returns.filter(r=>r.retorno.dias<=d).length,'Janela cumulativa']).concat([['Retornos à mesma oficina',returns.filter(r=>r.retorno.mesma_oficina).length,'Em até 30 dias']]));
table('returns',['Placa','Novo chamado','Chamado anterior','Dias após fechamento','Oficina anterior','Oficina atual','Mesma oficina'],returns.map(r=>[r.placa,r.chamado,r.retorno.anterior,r.retorno.dias,r.retorno.oficina_anterior,r.oficina,r.retorno.mesma_oficina?'Sim':'Não']));
const itemRows=[];for(const r of cost)for(const [g,v] of Object.entries(r.grupos))if(g.startsWith('Pneu')||g.startsWith('Óleo'))itemRows.push({...r,grupo:g,grupo_custo:v.custo,linhas:v.itens});
table('items',['Placa','Oficina','Grupo','OS distintas','Linhas de itens','Valor registrado R$'],grouped(itemRows,r=>JSON.stringify([r.veiculo,r.oficina_id,r.grupo])).map(([k,rs])=>[rs[0].placa,rs[0].oficina,rs[0].grupo,count(rs,'os'),sum(rs,'linhas'),sum(rs,'grupo_custo')]).sort((a,b)=>b[3]-a[3]));
table('details',['OS','Chamado','Placa','Oficina','Data OS','Status OS (código)','Situação chamado','Previsão','Fechamento','Pontualidade','Valor lançado R$'],os.map(r=>[r.os,r.chamado,r.placa,r.oficina,r.data_os,r.status_os,r.situacao,r.previsao,r.fechamento,r.pontual===null?'Não avaliada':r.pontual?'No prazo':'Com atraso',r.custo]));
$('quality').textContent=count(all.filter(r=>r.conflito),'os')+' OS com divergência de status; '+count(all.filter(r=>r.data_invalida),'chamado')+' chamados com fechamento inconsistente; '+sum(os,'incompletos')+' itens com valor/quantidade inválidos; '+sum(os,'simbolicos')+' serviços com valor 0 ou 1; '+os.filter(r=>!r.itens_registrados).length+' OS sem itens lançados (zero registrado não comprova ausência de custo). '+D.os_sem_chamado+' OS sem chamado localizado na extração geral.';
}
$('updated').textContent='Painel gerado em '+new Date(D.agora).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'});$('freshness').textContent='Últimas extrações registradas: '+Object.entries(D.extracoes).map(([k,v])=>k.replace('ordens_','')+': '+(v?new Date(v).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'não informada')).join(' · ')+'. Datas de extração não garantem sincronização completa. Pendências não confirmam a situação atual.';
['year','month','gre','cidade','categoria','fornecedor','oficina'].forEach(k=>$(k).onchange=render);$('availability-download').onclick=downloadAvailability;$('plate').oninput=render;$('reset').onclick=()=>{['month','gre','cidade','categoria','fornecedor','oficina','plate'].forEach(k=>$(k).value='');render();};render();})();
</script></html>'''

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
    conn=psycopg2.connect(host=os.environ['DB_HOST'],port=int(os.environ.get('DB_PORT') or '5432'),
        database=os.environ.get('DB_NAME') or 'postgres',user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],sslmode='require',connect_timeout=15)
    try:
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL TIME ZONE 'America/Sao_Paulo'")
                cur.execute("SET LOCAL statement_timeout = '120s'")
            dados=carregar(conn)
    finally:
        conn.close()
    publicar_compacto(montar_html(dados),destino='public/manutencao')
