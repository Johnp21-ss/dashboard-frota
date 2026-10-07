import json
from datetime import datetime, timezone


def preparar_frota(veiculos, equipamentos, agora):
    """Uma linha por veículo; melhor evidência de atualização entre equipamentos vinculados ao veículo."""
    ids = {v["id"] for v in veiculos}
    equipamentos = [e for e in equipamentos if e["veiculo_id"] is not None and e["veiculo_id"] in ids]
    por_veiculo = {}
    for e in equipamentos:
        por_veiculo.setdefault(e['veiculo_id'], []).append(e)
    for v in veiculos:
        vinculados = por_veiculo.get(v['id'], [])
        v['equipamentos'] = len(vinculados)
        v['status_equipamentos'] = ', '.join(sorted({str(e['status'] or '?') for e in vinculados}))
        v['recente'] = False
        v['online_recente'] = False
        v['ultima'] = None
        v['horas'] = None
        if not vinculados:
            v['situacao'] = 'Sem rastreador'
            v['motivo'] = 'Nenhum rastreador vinculado ao veículo no cadastro'
            continue
        datados = [e for e in vinculados if e['ultima_atualizacao'] is not None]
        if not datados:
            v['situacao'] = 'Inoperante — sem histórico'
            v['motivo'] = 'Rastreador sem histórico de comunicação'
            continue
        ultimo = max(datados, key=lambda e: e['ultima_atualizacao'])
        horas = (agora - ultimo['ultima_atualizacao']).total_seconds() / 3600
        v['ultima'] = ultimo['ultima_atualizacao'].isoformat()
        v['horas'] = round(horas, 2)
        recentes = [e for e in datados if 0 <= (agora-e['ultima_atualizacao']).total_seconds() <= 48*3600]
        v['recente'] = bool(recentes)
        v['online_recente'] = any(e['online'] is True for e in recentes)
        if horas < 0:
            v['situacao'] = 'Inconsistente — data futura'
            v['recente'] = False
            v['online_recente'] = False
        elif recentes:
            if v['online_recente']:
                v['situacao'] = 'Online, atualizado'
            elif any(e['online'] is False for e in recentes):
                v['situacao'] = 'Offline recente'
            else:
                v['situacao'] = 'Atualizado — online não informado'
        else:
            v['situacao'] = 'Sem comunicação há mais de 48h'
        v['motivo'] = 'Mais de um rastreador vinculado: conferir vínculos' if len(vinculados)>1 else ''
    return {'veiculos': veiculos, 'equipamentos': equipamentos, 'atualizado': agora.isoformat()}


def carregar_frota(conn):
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('SELECT CURRENT_TIMESTAMP AS agora')
        agora = cur.fetchone()['agora']
        cur.execute("""SELECT v.id, v.placa, v.status, v.tipo_contrato_locacao AS categoria,
            COALESCE(NULLIF(UPPER(TRIM(v.cidade)),''),'SEM CIDADE') AS cidade,
            COALESCE(g.nome,'SEM GRE') AS gre
            FROM airbyte.veiculos_veiculo v
            LEFT JOIN airbyte.escolas_gre g ON g.id=v.gre_id""")
        veiculos = [dict(r) for r in cur.fetchall()]
        cur.execute('SELECT id, veiculo_id, status, online, ultima_atualizacao FROM airbyte.veiculos_rastreador')
        equipamentos = [dict(r) for r in cur.fetchall()]
    return preparar_frota(veiculos, equipamentos, agora)


def html_frota(dados):
    text = json.dumps(dados, ensure_ascii=False, default=str, allow_nan=False)
    return HTML.replace('__DATA__', text.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026'))


HTML = r'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Log-PI · Frota e Rastreamento</title><style>
*{box-sizing:border-box}body{margin:0;background:#091522;color:#f0f6fb;font:16px/1.5 system-ui}main{max-width:1800px;margin:auto;padding:24px}header{display:flex;justify-content:space-between;gap:20px;align-items:center}h1{margin:4px 0;font-size:28px}h2{font-size:18px;margin:0 0 16px}a{color:#41d6b1}p,.note,label{color:#cfdee9}.note{font-size:14px}.filters{display:flex;flex-wrap:wrap;gap:14px;margin:22px 0}label{display:grid;gap:6px;font-size:14px}select,input,button{background:#193449;border:1px solid #55758c;border-radius:6px;padding:10px;color:#f3f8fc;font:inherit;min-height:44px}button{cursor:pointer;background:#087e73}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card{padding:20px;background:#122432;border:1px solid #355166;border-radius:11px;min-width:0}.cards strong{display:block;font-size:32px;margin:8px 0}.cards span{font-size:14px;color:#d6e2eb}.section{margin-top:18px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.scroll{overflow:auto;max-height:480px;scrollbar-color:#7796ae #193449}table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}th,td{padding:12px;border-bottom:1px solid #355166;text-align:left}th{background:#193449;position:sticky;top:0;z-index:1}.bar{margin:14px 0}.bar div{display:flex;justify-content:space-between;gap:10px}.bar i{display:block;height:12px;background:#36cdaa;border-radius:4px;margin-top:6px}.warning{border-left:3px solid #ffc36b;padding:12px 16px;background:#1a2c3b}.badge{color:#6ee1c7;font-size:13px}:focus-visible{outline:3px solid #46beff;outline-offset:3px}@media(max-width:1100px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:700px){main{padding:14px}.cards,.grid{grid-template-columns:1fr}header{align-items:start;flex-direction:column}.filters label{width:100%}}
</style></head><body><main><header><div><div class="badge">LOG-PI / MONITORAMENTO</div><h1>Frota e Rastreamento</h1><div class="note" id="updated"></div></div><nav><a href="../">Contratos</a> · <a href="../abastecimento/">Abastecimento</a></nav></header>
<div class="filters"><label>Status do veículo<select id="status"><option value="A">Ativos</option><option value="I">Inativos</option><option value="">Todos</option><option value="outros">Outros / não informado</option></select></label><label>Categoria<select id="category"></select></label><label>GRE<select id="gre"></select></label><label>Cidade<select id="city"></select></label><button id="reset">Limpar filtros</button></div>
<p id="scope" role="status"></p><div class="cards" id="kpis"></div>
<p class="warning note">Cobertura = veículos com rastreador vinculado ÷ total de veículos do recorte, independentemente do status cadastral do equipamento. O card Online e atualizados considera qualquer atualização nas últimas 48h, mesmo com o campo online desligado. Sem comunicação indica rastreador sem histórico; atualização acima de 48h indica histórico desatualizado. A análise usa o campo ultima_atualizacao; sua equivalência ao último sinal de telemetria ainda precisa ser validada. Não é uma confirmação de defeito ou de veículo em movimento.</p>
<section class="card section"><h2>Cobertura por categoria da frota</h2><div class="scroll" id="category-table"></div><p class="note">Com rastreador: veículo com equipamento vinculado no cadastro. Sem rastreador: nenhum equipamento vinculado. Cada veículo é contado uma vez; cobertura não significa comunicação em dia.</p></section>
<section class="card section"><h2>Comunicação dos veículos com rastreador</h2><div id="communication"></div><p class="note">Online ou offline recente: atualização em até 48h. Mais de 48h sem atualização: sem comunicação, mesmo se o campo online estiver marcado. Sem data: inoperante — sem histórico.</p></section>
<section class="card section"><h2>Veículos inativos — cobertura por categoria</h2><div class="scroll" id="inactive-fleet"></div><p class="note">Este bloco usa veículos I, mantendo categoria, GRE e cidade selecionadas. Não depende do filtro de status do veículo no topo.</p></section>
<section class="card section"><h2>Frota por cidade</h2><label>Buscar cidade neste bloco<input id="search-cities" placeholder="Ex.: Teresina"></label><p class="note">Total de veículos soma as categorias da cidade dentro dos filtros selecionados. Clique no título de uma coluna para ordenar em ordem crescente ou decrescente.</p><div class="scroll" id="cities"></div></section>
<section class="card section"><h2>Cobertura por categoria e cidade</h2><label>Buscar cidade neste bloco<input id="search-matrix" placeholder="Ex.: Teresina"></label><p class="note">Clique no título de uma coluna para ordenar. As buscas de cidade afetam somente o respectivo bloco.</p><div class="scroll" id="matrix"></div></section>
<section class="card section"><h2>Placas e pendências de monitoramento</h2><div class="filters"><label>Buscar placa<input id="plate" placeholder="Digite a placa"></label><label>Situação<select id="situation"></select></label></div><div class="scroll" id="details"></div><p class="note">Busca de placa e situação filtram apenas esta lista. Veículos com vários rastreadores são contados uma vez; prevalece a evidência recente de comunicação.</p></section>
</main><script id="data" type="application/json">__DATA__</script><script>
(()=>{'use strict';const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id),esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),pct=(n,t)=>t?(n/t*100).toLocaleString('pt-BR',{maximumFractionDigits:1})+'%':'—';
const cats={FROTA_PROPRIA:'Próprios',FROTA_LOCADA:'Locados',FROTA_PARCEIRO:'Parceiros',FROTA_TERCEIRIZADA:'Terceirizados'},V=D.veiculos;
const category=v=>cats[v.categoria]||'Outros / não informado';
function options(id,values,label){$(id).innerHTML='<option value="">'+label+'</option>'+values.map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('');}
const unique=a=>[...new Set(a)].sort((a,b)=>a.localeCompare(b,'pt-BR'));
options('category',unique(V.map(category)),'Todas as categorias');options('gre',unique(V.map(v=>v.gre)),'Todas as GREs');
function cities(){options('city',unique(V.filter(v=>!$('gre').value||v.gre===$('gre').value).map(v=>v.cidade)),'Todas as cidades');}cities();options('situation',unique(V.map(v=>v.situacao)),'Todas as situações');
const normalize=x=>String(x||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase();
const sorting={};
function table(id,heads,rows){
const sortable=['cities','matrix'].includes(id),state=sorting[id];let ordered=[...rows];
const value=x=>typeof x==='number'?x:typeof x==='string'&&x.endsWith('%')?Number(x.replace('%','').replace(',','.')):x;
if(state)ordered.sort((a,b)=>{const x=value(a[state.col]),y=value(b[state.col]);if(x==='—')return y==='—'?0:1;if(y==='—')return -1;return state.dir*(typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y),'pt-BR',{numeric:true}));});
$(id).innerHTML='<table><thead><tr>'+heads.map((h,i)=>'<th'+(sortable?' aria-sort="'+(state?.col===i?(state.dir===1?'ascending':'descending'):'none')+'"':'')+'>'+(sortable?'<button type="button" data-col="'+i+'" style="background:transparent;border:0;padding:0;min-height:32px;text-align:left;font-weight:650">'+esc(h)+(state?.col===i?(state.dir===1?' ↑':' ↓'):' ↕')+'</button>':esc(h))+'</th>').join('')+'</tr></thead><tbody>'+(ordered.length?ordered.map(r=>'<tr>'+r.map(c=>'<td>'+esc(c)+'</td>').join('')+'</tr>').join(''):'<tr><td colspan="'+heads.length+'">Nenhum registro.</td></tr>')+'</tbody></table>';
if(sortable)$(id).querySelectorAll('button[data-col]').forEach(btn=>btn.addEventListener('click',()=>{const col=Number(btn.dataset.col);sorting[id]={col,dir:state?.col===col?-state.dir:1};table(id,heads,rows);}));
}
const summary=vs=>({total:vs.length,with:vs.filter(v=>v.equipamentos>0).length,recent:vs.filter(v=>v.recente).length,stale:vs.filter(v=>v.situacao==='Sem comunicação há mais de 48h').length,noHistory:vs.filter(v=>v.equipamentos>0&&v.ultima===null).length});
function bars(id,rows,max){$(id).innerHTML=rows.map(([label,n,suffix])=>'<div class="bar"><div><span>'+esc(label)+'</span><b>'+esc(n)+(suffix?' · '+esc(suffix):'')+'</b></div><i style="width:'+n/Math.max(max,1)*100+'%"></i></div>').join('')||'<p>Sem dados.</p>';}
function render(){const vs=V.filter(v=>(!$('status').value||($('status').value==='outros'?!['A','I'].includes(v.status):v.status===$('status').value))&&(!$('category').value||category(v)===$('category').value)&&(!$('gre').value||v.gre===$('gre').value)&&(!$('city').value||v.cidade===$('city').value)),s=summary(vs);
$('scope').textContent=[$('status').selectedOptions[0].textContent,$('category').value||'Todas as categorias',$('gre').value||'Todas as GREs',$('city').value||'Todas as cidades'].join(' · ');
$('kpis').innerHTML=[['VEÍCULOS',s.total,'Frota no recorte'],['COM RASTREADOR',s.with,pct(s.with,s.total)+' de cobertura cadastral'],['SEM RASTREADOR',vs.filter(v=>v.equipamentos===0).length,'Nenhum equipamento vinculado no cadastro'],['ATUALIZAÇÃO ACIMA DE 48H',s.stale,'Com rastreador e última atualização há mais de 48h'],['ONLINE E ATUALIZADOS',s.recent,'Sinal nas últimas 48h, independentemente do campo online'],['SEM COMUNICAÇÃO',s.noHistory,'Com rastreador, sem histórico de sinal — inoperantes']].map(([l,n,d])=>'<article class="card"><span>'+l+'</span><strong>'+n+'</strong><span>'+d+'</span></article>').join('');
const groups=Object.values(cats).concat(['Outros / não informado']);
const categoryRows=rows=>groups.map(c=>{const r=rows.filter(v=>category(v)===c),x=summary(r);return[c,x.total,x.with,x.total-x.with,pct(x.with,x.total)];});
table('category-table',['Categoria da frota',$('status').value==='A'?'Veículos ativos':'Veículos do recorte','Com rastreador','Sem rastreador','Cobertura'],categoryRows(vs));
const tracked=vs.filter(v=>v.equipamentos>0),states=unique(tracked.map(v=>v.situacao));bars('communication',states.map(st=>[st,tracked.filter(v=>v.situacao===st).length,pct(tracked.filter(v=>v.situacao===st).length,tracked.length)]),tracked.length);
const inactiveVehicles=V.filter(v=>v.status==='I'&&(!$('category').value||category(v)===$('category').value)&&(!$('gre').value||v.gre===$('gre').value)&&(!$('city').value||v.cidade===$('city').value));
table('inactive-fleet',['Categoria','Veículos inativos','Com rastreador','Sem rastreador','Cobertura'],categoryRows(inactiveVehicles));
table('cities',['Cidade',...groups,'Total de veículos','Com rastreador','Sem rastreador','Sem atualização há mais de 48h','Cobertura'],unique(vs.map(v=>v.cidade)).filter(c=>normalize(c).includes(normalize($('search-cities').value))).map(c=>{const rows=vs.filter(v=>v.cidade===c),x=summary(rows);return[c,...groups.map(g=>rows.filter(v=>category(v)===g).length),x.total,x.with,x.total-x.with,x.stale,pct(x.with,x.total)];}));
const combos=unique(vs.map(v=>JSON.stringify([v.cidade,category(v)])));table('matrix',['Cidade','Categoria','Veículos','Com rastreador','Sem rastreador','Online e atualizados','Cobertura'],combos.filter(k=>normalize(JSON.parse(k)[0]).includes(normalize($('search-matrix').value))).map(k=>{const [c,g]=JSON.parse(k),x=summary(vs.filter(v=>v.cidade===c&&category(v)===g));return[c,g,x.total,x.with,x.total-x.with,x.recent,pct(x.with,x.total)];}));
const dt=x=>x?new Date(x).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'}):'Sem data',hours=v=>v.horas===null?'—':v.horas<0?'Data futura':v.horas>=48?(v.horas/24).toFixed(1)+' dias':v.horas.toFixed(1)+' h';
table('details',['Placa','Categoria','Cidade','GRE','Status veículo','Rastreadores vinculados','Situação','Última atualização','Tempo','Observação'],vs.filter(v=>(!$('plate').value||String(v.placa||'').toUpperCase().includes($('plate').value.toUpperCase()))&&(!$('situation').value||v.situacao===$('situation').value)).sort((a,b)=>(b.horas??1e9)-(a.horas??1e9)).map(v=>[v.placa,category(v),v.cidade,v.gre,v.status,v.equipamentos,v.situacao,dt(v.ultima),hours(v),v.motivo]));
}
$('updated').textContent='Atualizado em '+new Date(D.atualizado).toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo'})+' · limite de 48 horas';$('gre').addEventListener('change',()=>{cities();render();});['status','category','city','situation'].forEach(id=>$(id).addEventListener('change',render));['plate','search-cities','search-matrix'].forEach(id=>$(id).addEventListener('input',render));$('reset').addEventListener('click',()=>{$('status').value='A';['category','gre','situation','plate','search-cities','search-matrix'].forEach(id=>$(id).value='');cities();render();});render();
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
    import os
    import psycopg2
    conn=psycopg2.connect(host=os.environ['DB_HOST'],port=int(os.environ.get('DB_PORT') or '5432'),database=os.environ.get('DB_NAME') or 'postgres',user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],sslmode='require',connect_timeout=15)
    try:
        conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL TIME ZONE 'America/Sao_Paulo'")
                cur.execute("SET LOCAL statement_timeout = '120s'")
            dados=carregar_frota(conn)
    finally:
        conn.close()
    publicar_compacto(html_frota(dados),destino='public/rastreamento')
