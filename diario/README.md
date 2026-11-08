# Integração do diário ao Log-PI

Estado: a aba Diario_Eventos foi criada na planilha e os cabeçalhos foram conferidos pela conexão do Google. As regras de gravação foram verificadas localmente com serviços simulados. O aplicativo Apps Script ainda precisa ser instalado e implantado; o teste real de autorização, gravação e consulta continua pendente.

GitHub: acesso ao repositório confirmado e branch codex/diario-bordo-logpi criada. A integração será proposta para revisão antes da publicação do painel.

## Base escolhida

https://docs.google.com/spreadsheets/d/1HljrnZIP9ZN0bFk-eprMSI3gRRa7hdwe59JimKfR0Rc/edit

O Code.gs já usa essa planilha como base padrão. Não tornar a planilha pública.

## Configuração no Google

1. Na planilha, abrir Extensões → Apps Script.
2. Colocar o conteúdo de Code.gs no arquivo de código e criar o arquivo HTML Diario com o conteúdo de Diario.html.
3. Em Configurações do projeto, habilitar a exibição do manifesto. Usar o conteúdo de appsscript.json.
4. Executar configurarDiario pelo editor. Essa função vincula a planilha informada, autoriza a conta que está configurando e define https://johnp21-ss.github.io como origem do Log-PI. Preserva os registros existentes. Autorizar o acesso solicitado após conferir a conta e a planilha.
5. Para adicionar usuários depois, cadastrar os e-mails autorizados, separados por vírgula, na propriedade USUARIOS do script. Se o painel usar domínio próprio, ajustar ORIGEM_LOGPI para a origem HTTPS real, sem caminho e sem barra final.
6. A aba Diario_Eventos já está preparada. Não editar seus cabeçalhos ou inserir linhas manualmente; o aplicativo fará as gravações e manterá as versões.
7. Implantar como aplicativo da Web, executando como usuário que acessa. Restringir o acesso às contas necessárias nas opções disponíveis da organização. Cada usuário deve ter a permissão necessária na planilha; a lista USUARIOS também é verificada no código.
8. Copiar o endereço da implantação terminado em /exec.

A identidade usada na gravação é obtida no servidor, não em campo digitado no formulário. O modo de implantação e a identificação do e-mail precisam ser conferidos com as contas reais. Não mudar para execução como proprietário para contornar erro sem revisar o controle de acesso.

## Integração no GitHub

O gerar_monitoramento.py desta pasta foi comparado com a versão main do repositório Johnp21-ss/dashboard-frota, commit 39976424c4ccc4896ce1c324d8ed540188d24f84, antes de acrescentar a aba Diário de bordo. As consultas e os cálculos existentes foram preservados. Não alterar o workflow de atualização por causa desta integração.

Depois da publicação, abrir Central de Monitoramento → Diário de bordo → Conectar a base do diário. Informar o endereço /exec. O endereço é guardado neste navegador; os registros ficam no Sheets. Se a sessão Google não funcionar incorporada, usar o acesso autenticado em outra aba.

## Conferência antes do uso real

- Conferir a conta autorizada e a criação da aba Diario_Eventos.
- Registrar análise de teste, inclusive período analisado e período reportado.
- Abrir ocorrência vinculada e registrar encaminhamento ao fiscal/supervisor.
- Atualizar a ocorrência e conferir que a versão anterior permanece no histórico.
- Abrir duas sessões e confirmar que uma alteração antiga não sobrescreve a nova.
- Conferir gráficos e filtros, relatório para impressão e exportações.
- Editar o fluxo e conferir a persistência depois de recarregar.
- Conferir navegação e relatório existente do Log-PI.
- Conservar os registros de teste identificados como testes; esta versão não oferece exclusão.

## Limites desta primeira versão

Os indicadores são calculados automaticamente a partir do diário. Identificação automática de ocorrências a partir da API/Fleetbus e integração de gravação com o Radar não estão implementadas. Registro de envio de relatório é declaratório; o módulo não envia mensagens. A base armazena versões em sequência; pessoas com edição direta na planilha ainda podem alterar células fora do aplicativo. Não equivale a um sistema de auditoria inviolável. O carregamento atual lê todo o histórico e deverá ser paginado caso o volume aumente significativamente.

## Referências técnicas

- https://developers.google.com/apps-script/guides/web
- https://developers.google.com/apps-script/guides/html/communication
- https://developers.google.com/apps-script/reference/base/session
