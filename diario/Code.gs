/* Diário de Bordo Log-PI. Base própria; não escreve no Fleetbus/PostgreSQL. */
const TIPOS_ = ['analise', 'ocorrencia', 'fluxo'];
const RESULTADOS_ = ['Em apuração', 'Justificada', 'Irregularidade confirmada', 'Inconclusiva'];
const SITUACOES_ = ['Identificada', 'Aguardando esclarecimento da supervisão', 'Aguardando decisão da supervisão', 'Em ação corretiva', 'Concluída'];
const RADAR_ = ['Não avaliado', 'A registrar', 'Registrado', 'Não aplicável', 'Indisponível / implantação'];
// Executar uma vez pelo editor vinculado à planilha, antes da implantação.
function configurarDiario() {
  const ss=SpreadsheetApp.getActiveSpreadsheet();
  if(!ss || ss.getId()!=='1HljrnZIP9ZN0bFk-eprMSI3gRRa7hdwe59JimKfR0Rc') throw new Error('Execute esta configuração pelo Apps Script aberto a partir da planilha do diário.');
  const email=Session.getActiveUser().getEmail().toLowerCase();
  if(!email) throw new Error('Não foi possível identificar a conta Google.');
  const props=PropertiesService.getScriptProperties();
  if(props.getProperty('USUARIOS')) usuario_();
  else props.setProperty('USUARIOS',email);
  props.setProperty('PLANILHA_ID',ss.getId());
  if(!props.getProperty('ORIGEM_LOGPI')) props.setProperty('ORIGEM_LOGPI','https://johnp21-ss.github.io');
  return prepararDiario();
}
function usuario_() {
  const email = Session.getActiveUser().getEmail().toLowerCase();
  const permitidos = (PropertiesService.getScriptProperties().getProperty('USUARIOS') || '').toLowerCase().split(',').map(x=>x.trim()).filter(Boolean);
  if (!email || !permitidos.includes(email)) throw new Error('Conta não autorizada. Solicite acesso ao responsável pelo diário.');
  return email;
}
function planilha_() {
  const id = PropertiesService.getScriptProperties().getProperty('PLANILHA_ID') || '1HljrnZIP9ZN0bFk-eprMSI3gRRa7hdwe59JimKfR0Rc';
  return SpreadsheetApp.openById(id);
}
function eventos_() {
  const sheet = planilha_().getSheetByName('Diario_Eventos');
  if (!sheet) throw new Error('Execute prepararDiario antes de abrir o diário.');
  const rows = sheet.getDataRange().getValues();
  if (rows[0].join('|') !== 'evento_id|registro_id|tipo|versao|registrado_em|autor|dados_json') throw new Error('Cabeçalho da base alterado. Não grave até corrigir.');
  return {sheet:sheet, rows:rows.slice(1).filter(r=>r[0]).map(r=>({evento_id:String(r[0]),id:String(r[1]),tipo:String(r[2]),versao:Number(r[3]),registrado_em:String(r[4]),autor:String(r[5]),dados:JSON.parse(r[6])}))};
}
function estado_(rows) {
  const latest = {};
  rows.forEach(r=>{ if (!latest[r.id] || r.versao > latest[r.id].versao) latest[r.id]=r; });
  return latest;
}
function prepararDiario() {
  usuario_();
  const lock=LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const ss=planilha_();
    if (!ss.getSheetByName('Diario_Eventos')) {
      const sheet=ss.insertSheet('Diario_Eventos');
      sheet.appendRow(['evento_id','registro_id','tipo','versao','registrado_em','autor','dados_json']);
      sheet.setFrozenRows(1); sheet.getRange('A:G').setNumberFormat('@');
    }
    return 'Base preparada. Nenhum registro anterior foi alterado.';
  } finally {lock.releaseLock();}
}
function doGet() {
  usuario_();
  const origin=PropertiesService.getScriptProperties().getProperty('ORIGEM_LOGPI')||'';
  if(origin && !/^https:\/\/[a-z0-9.-]+(?::\d+)?$/i.test(origin)) throw new Error('ORIGEM_LOGPI deve conter somente a origem HTTPS do painel, sem caminho.');
  const html=HtmlService.createHtmlOutputFromFile('Diario').getContent().replace("const ORIGEM_LOGPI = '';",'const ORIGEM_LOGPI = '+JSON.stringify(origin)+';');
  return HtmlService.createHtmlOutput(html).setTitle('Diário de Bordo · Log-PI').setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL).addMetaTag('viewport','width=device-width, initial-scale=1');
}
function carregarDiario() {
  const email=usuario_(), rows=eventos_().rows;
  return {usuario:email,agora:new Date().toISOString(),registros:Object.values(estado_(rows)),historico:rows};
}
function texto_(v,n,max) {
  if (typeof v !== 'string' || v.length > (max||5000)) throw new Error('Campo inválido: '+n);
  return v.trim();
}
function data_(v,n,obrigatorio) {
  if (!v && !obrigatorio) return '';
  if (typeof v!=='string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(v) || !Number.isFinite(Date.parse(v+'-03:00'))) throw new Error('Data inválida: '+n);
  return v;
}
function salvarRegistro(tipo, entrada, versaoEsperada, eventoId) {
  const autor=usuario_();
  if (!TIPOS_.includes(tipo) || !entrada || typeof entrada!=='object') throw new Error('Tipo inválido.');
  if (!/^[a-zA-Z0-9-]{16,80}$/.test(eventoId||'')) throw new Error('Identificação da gravação inválida.');
  const lock=LockService.getScriptLock(); lock.waitLock(20000);
  try {
    const source=eventos_(), rows=source.rows;
    const repetido=rows.find(r=>r.evento_id===eventoId);
    if (repetido) {
      if (repetido.autor!==autor) throw new Error('Identificação da gravação em uso.');
      return repetido;
    }
    const state=estado_(rows), id=entrada.id || Utilities.getUuid(), anterior=state[id];
    if (!/^[a-zA-Z0-9-]{16,80}$/.test(id) || !Number.isInteger(versaoEsperada) || versaoEsperada<0) throw new Error('Registro inválido.');
    if ((anterior?anterior.versao:0)!==versaoEsperada || (anterior && anterior.tipo!==tipo)) throw new Error('Este registro mudou em outra sessão. Atualize a lista antes de salvar.');
    const campos=tipo==='fluxo' ? ['titulo','passos','nota_acao'] : tipo==='analise' ? ['titulo','categoria','fonte','inicio','fim','analisado_em','quantidade','unidade','resumo','limitacoes','reportado_inicio','reportado_fim','reportado_em','destinatario','canal','evidencia','cidade','gre','vinculo','nota_acao'] : ['analise_id','titulo','categoria','identificado_em','placa','motorista','cidade','gre','vinculo','descricao','evidencia','resultado','situacao','responsavel','prazo','radar','radar_protocolo','radar_em','decisor','decisao','encerrado_em','nota_acao'];
    const d={}; campos.forEach(k=>d[k]=texto_(entrada[k]??'',k,k==='nota_acao'?3000:5000));
    if (!d.titulo || !d.nota_acao || (tipo!=='fluxo' && !d.categoria)) throw new Error('Preencha título, categoria e ação realizada.');
    if (tipo==='fluxo') {
      let passos;try{passos=JSON.parse(d.passos);}catch(e){throw new Error('Fluxograma inválido.');}
      if (!Array.isArray(passos)||!passos.length||passos.length>20) throw new Error('O fluxo deve conter de 1 a 20 etapas.');
      passos.forEach(p=>{if(!p||typeof p.titulo!=='string'||!p.titulo.trim()||p.titulo.length>200||typeof p.responsavel!=='string'||p.responsavel.length>200||typeof p.destino!=='string'||p.destino.length>200)throw new Error('Preencha as etapas do fluxo.');});
    } else if (tipo==='analise') {
      ['inicio','fim','analisado_em'].forEach(k=>d[k]=data_(d[k],k,true));
      if (d.inicio>d.fim) throw new Error('O fim do período analisado deve ser igual ou posterior ao início.');
      if (d.fim>d.analisado_em) throw new Error('A análise não pode anteceder o fim do período analisado.');
      ['reportado_inicio','reportado_fim','reportado_em'].forEach(k=>d[k]=data_(d[k],k,false));
      const reportado=[d.reportado_inicio,d.reportado_fim,d.reportado_em,d.destinatario,d.canal];
      if (reportado.some(Boolean) && !reportado.every(Boolean)) throw new Error('Para registrar o reporte, preencha período reportado, data do envio, destinatário e canal.');
      if (d.reportado_em && (d.reportado_inicio>d.reportado_fim || d.reportado_fim>d.reportado_em || d.reportado_em<d.analisado_em)) throw new Error('Confira a sequência das datas do reporte.');
      if (d.quantidade!=='' && (!/^\d+$/.test(d.quantidade)||!d.unidade)) throw new Error('Informe quantidade inteira não negativa e sua unidade.');
      if (!d.fonte || !d.resumo) throw new Error('Informe fonte e resumo da análise.');
    } else {
      if (!state[d.analise_id] || state[d.analise_id].tipo!=='analise') throw new Error('Vincule a ocorrência a uma análise existente.');
      ['identificado_em'].forEach(k=>d[k]=data_(d[k],k,true));
      ['prazo','radar_em','encerrado_em'].forEach(k=>d[k]=data_(d[k],k,false));
      if (!RESULTADOS_.includes(d.resultado)||!SITUACOES_.includes(d.situacao)||!RADAR_.includes(d.radar)) throw new Error('Classificação inválida.');
      if (!d.descricao || !d.evidencia) throw new Error('Registre descrição e referência da evidência.');
      if (d.situacao!=='Identificada' && !d.responsavel) throw new Error('Informe o responsável pelo retorno ou providência.');
      if (d.radar==='Registrado' && (!d.radar_protocolo||!d.radar_em)) throw new Error('Informe protocolo/referência e data do Radar.');
      if (d.radar!=='Registrado' && (d.radar_protocolo||d.radar_em)) throw new Error('Protocolo/data do Radar exigem situação Registrado.');
      if (d.resultado==='Irregularidade confirmada' && !d.decisao) throw new Error('Registre a evidência/regra que fundamenta a confirmação.');
      if (d.situacao==='Concluída' && (d.resultado==='Em apuração'||!d.decisor||!d.decisao||!d.encerrado_em)) throw new Error('Encerramento exige resultado, responsável pela decisão, fundamento e data.');
      if (d.situacao!=='Concluída' && d.encerrado_em) throw new Error('Data de encerramento exige situação Concluída.');
      if (d.encerrado_em && d.encerrado_em<d.identificado_em) throw new Error('Encerramento anterior à identificação.');
    }
    const event={evento_id:eventoId,id:id,tipo:tipo,versao:versaoEsperada+1,registrado_em:new Date().toISOString(),autor:autor,dados:d};
    source.sheet.getRange(source.sheet.getLastRow()+1,1,1,7).setValues([[event.evento_id,event.id,event.tipo,event.versao,event.registrado_em,event.autor,JSON.stringify(d)]]);
    SpreadsheetApp.flush();
    return event;
  } finally {lock.releaseLock();}
}
