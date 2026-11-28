# Programando o Futuro

> [!NOTE]
> **Deploy religado em 28/11/2026.** O aviso "NÃO RELIGAR O DEPLOY" cumpriu o papel dele e fica abaixo, marcado como cumprido.
>
> **O que aconteceu em 28/11/2026:**
> - Serviço novo no Render, criado do zero, porque o antigo não existia mais na conta. Plano gratuito, região Oregon. A pasta raiz do serviço é a raiz do repositório, de propósito, e os comandos de build e de start apontam para `backend/` (ver o registro de decisões no `ROADMAP.md`). O start roda o uvicorn na porta fornecida pelo Render.
> - Endereço: https://programando-o-futuro-4lg4.onrender.com. O Render acrescentou o sufixo `-4lg4` porque o nome simples já estava em uso.
> - O log de subida confirmou `AMBIENTE=producao`, banco conectado com TLS, nenhuma senha em texto plano, os dois semáforos (geração e lista) e a varredura de jobs.
> - As migrações rodaram e não precisaram alterar nada, porque o banco é novo e vazio.
> - **Auto-Deploy "On Commit" ligado:** todo merge na `main` publica em produção sozinho. Ver "Regras de Git" no `CLAUDE.md`.
> - A CA do projeto Aiven novo foi colocada no Render como Secret File, em `/etc/secrets/ca-aiven.pem`, e a variável `DB_SSL_CA` aponta para esse caminho absoluto.
> - No mesmo dia rodou o primeiro teste de ponta a ponta em produção: ver "Teste de ponta a ponta em produção" na Fase 0 do `ROADMAP.md`.
>
> **Pendências abertas depois da subida:**
> - **`backend/ca.pem` desatualizado.** O arquivo versionado continua sendo a CA do projeto Aiven **antigo**. Em produção isso não quebra, porque o `DB_SSL_CA` aponta para o Secret File. Mas quem clonar o repositório e tentar conectar no banco de produção com a configuração padrão vai falhar: sem `DB_SSL_CA`, o código usa o `backend/ca.pem`, e essa CA não valida o certificado do serviço novo. Solução definitiva: substituir o `backend/ca.pem` pela CA nova e commitar. Não foi feito em 28/11/2026 porque o arquivo não estava na máquina usada.
> - **IP allowlist do banco** ainda em "Open to all". Restringir aos IPs de saída do Render.
> - **Trial do Aiven vence por volta de 26/12/2026**, e o serviço desliga sozinho sem cartão cadastrado: ver "Riscos conhecidos" no `ROADMAP.md`.
> - **`JWT_SECRET` e `ADMIN_SECRET` (pré-requisito b, abaixo).** Os valores atuais foram gerados pelo Render, então são novos em relação aos do histórico do Git. Mas apareceram na tela durante a configuração e passaram por uma conversa com assistente de IA, o que é uma exposição nova, menor mas real. Fecha quando os dois forem gerados de novo no Render, pelo botão Generate, e salvos.
>
> **Aviso anterior, que cumpriu o papel em 28/11/2026. Os itens b) e e) continuam abertos:**
>
> **NÃO RELIGAR O DEPLOY antes de cumprir, um a um, os quatro pré-requisitos abaixo.**
> Pendência da reconexão do deploy, registrada em 26/11/2026 e atualizada no mesmo dia.
>
> **Atualização de 26/11/2026, banco novo:** o banco antigo do Aiven não existe mais. Foi criado um projeto e um serviço novos no Aiven, MySQL 8.4, hospedado no DigitalOcean (região nyc), com o banco **vazio**. Por isso:
> - o pré-requisito a não se aplica a este banco, e a migração de senhas em texto plano também não, porque não existe nenhuma linha;
> - o pré-requisito d ficou mais importante: o `backend/ca.pem` do repositório é a CA do projeto **antigo** e não vai validar o certificado do serviço novo. O `DB_SSL_CA` precisa apontar para a CA do projeto novo;
> - depois que o deploy subir, falta o item e) abaixo;
> - o trial do Aiven vence por volta de 26/12/2026, quando o sistema roda na escola: ver "Riscos conhecidos" no `ROADMAP.md`.
>
> **Pré-requisitos que faltam:**
> - **a) [Não se aplica ao banco novo, que está vazio. Mantido para o caso de algum dia migrar dados de outro banco.]** **Conferir no Aiven se existe linha com `aceite_lgpd` nulo** (`SELECT COUNT(*) FROM usuarios WHERE aceite_lgpd IS NULL`). Se existir, a migração do Bloco 3 (`backend/migracoes/usuarios_aceite_lgpd.py`) para a aplicação de propósito, e isso vai parecer deploy quebrado para quem não souber. A migração não inventa valor de consentimento: decidir antes o que essas linhas significam.
> - **b) [Aberto em 28/11/2026. Os valores foram gerados pelo Render e são novos em relação aos do histórico do Git, mas foram expostos na configuração. Fecha quando os dois forem gerados de novo pelo botão Generate do Render e salvos.]** **`JWT_SECRET` e `ADMIN_SECRET` novos.** Os antigos tiveram valor padrão escrito no código e estão no histórico público do Git. Mover os valores antigos para variável de ambiente não resolve.
> - **c) [Cumprido em 28/11/2026: com `AMBIENTE=producao` a aplicação só sobe com a variável definida, e ela subiu.]** **`CORS_ORIGENS` configurada.** Com `AMBIENTE=producao`, sem ela a aplicação não sobe.
> - **d) [Cumprido em 28/11/2026 no caminho em que tudo está certo: CA nova pelo Secret File, hostname verificado (`check_hostname` fica ligado) e `Ssl_cipher` preenchido, porque a aplicação recusa subir com ele vazio. Os testes de recusa, com CA errada e com nome de servidor errado, não foram feitos contra o banco de produção.]** **`DB_SSL_CA` e verificação de hostname.** A CA do provedor do banco configurada, e a verificação de hostname e a consulta a `Ssl_cipher` conferidas contra o banco de produção, que tem TLS. O banco local roda sem TLS, então nada disso foi testado aqui. Com o banco novo, o `backend/ca.pem` do repositório não serve: ele é a CA do projeto antigo.
> - **e) [Continua aberto em 28/11/2026: ver as pendências acima.]** **Depois que o deploy subir: restringir o IP allowlist do banco**, hoje em "Open to all", aos IPs de saída do Render.
>
> **Já cumprido em 26/11/2026:** os oito testes de MySQL rodaram contra MySQL 8.0.46 local (`127.0.0.1`) e passaram, e depois contra MySQL 8.4.13 local, a mesma série do banco novo, com o mesmo número de verificações. O teste de carga com 15 alunos ao mesmo tempo também passou, mas com a espera da IA simulada encurtada; ver a ressalva na Fase 1 do `ROADMAP.md`, que diz o que ele validou e o que não validou.
>
> Texto original do aviso, com a condição antiga, já cumprida:
>
> **NÃO RELIGAR O DEPLOY antes de rodar com MySQL local os oito testes abaixo e ver todos passarem.**
> Pendência da reconexão do deploy, registrada em 26/11/2026.
>
> Os PRs #10, #11 e #12 foram para a `main` sem esses testes rodarem, porque o Docker não subiu na máquina usada. Na `main`, isso não toca em nada: o deploy está desligado desde 08/10/2026, e as migrações só rodam quando a aplicação sobe. O risco está em religar o deploy. A primeira subida roda as migrações sozinha contra o banco de produção, que guarda dados reais de alunos menores de idade:
> - A migração do Bloco 3 (`backend/migracoes/usuarios_aceite_lgpd.py`) torna `usuarios.aceite_lgpd` NOT NULL e sem padrão. Se houver no Aiven alguma linha com `aceite_lgpd` nulo, ela para e a aplicação não sobe.
> - A migração do Bloco 2 (`backend/migracoes/mapa_progresso_usuario_id.py`) altera `mapa_progresso.usuario_id` de INT para VARCHAR(36), sozinha, no startup.
>
> Os oito testes, todos em `backend/testes/`:
> 1. `teste_recuperacao_jobs.py`
> 2. `teste_migracao_mapa.py`
> 3. `teste_migracao.py`
> 4. `teste_mapa_progresso.py`
> 5. `teste_dados_db.py`
> 6. `teste_plano_db.py`
> 7. `teste_heartbeat.py`
> 8. `teste_ia_simulada.py`
>
> Como rodar está no cabeçalho de cada arquivo. Os que usam QuickJS precisam de `pip install -r backend/requirements-dev.txt`. Só apague este aviso depois que os oito passarem.

Plataforma web que gera planos de carreira personalizados para estudantes de escola pública usando a API do Claude. Projeto de extensão do Centro Universitário SENAI-SP. Validado em campo na escola parceira em maio de 2026, com 31 alunos.

O sistema está no ar desde 28/11/2026, em https://programando-o-futuro-4lg4.onrender.com, com um banco novo. Os dados da validação de maio não existem mais, mas o banco de produção vai receber dados reais de alunos, incluindo menores de idade, assim que o sistema for usado na escola. O mesmo cuidado se aplica a toda alteração.

## Como trabalhar comigo

Responda em português do Brasil.

Resolva um problema por vez. Se eu pedir algo que envolve três mudanças independentes, faça a primeira, me mostre, e espere eu confirmar antes de seguir.

Antes de escrever código, explique em duas ou três frases qual abordagem você vai usar e por quê. Se houver mais de um caminho razoável, diga quais são e qual você recomenda. Só então implemente.

Sou estudante de Análise e Desenvolvimento de Sistemas e estou usando este projeto para aprender. Quando a mudança envolver um conceito que eu possa não dominar, explique o conceito antes de aplicá-lo. Não entregue uma reescrita grande de uma vez sem eu entender o que mudou.

Não use travessão para efeito retórico, construções do tipo "não é X, é Y", nem frases simetricamente balanceadas.

Se eu propuser algo tecnicamente ruim, discorde e explique por quê. Concordar por educação atrapalha o projeto.

## Regras de Git

Nunca commite direto na `main`. Sempre crie uma branch nomeada com a fase e o assunto, por exemplo `fase0/hash-senha` ou `fase1/semaforo-ia`.

Uma tarefa, uma branch, um pull request. Não junte mudanças de assuntos diferentes no mesmo PR.

Depois de implementar, pare e me mostre o resultado antes de commitar. Eu confirmo, aí você commita.

Mensagens de commit em português, no imperativo, descrevendo o que mudou e por quê quando não for óbvio.

> [!WARNING]
> **Desde 28/11/2026, todo merge na `main` publica em produção sozinho.** O serviço do Render está com Auto-Deploy "On Commit". Até 27/11/2026 a `main` era segura, porque o deploy estava desligado desde 08/10/2026. Isso acabou: um PR mal testado que entra na `main` vai para o ar automaticamente, com alunos podendo usar, e as migrações rodam sozinhas contra o banco de produção na subida.
>
> Na prática:
> - a validação de cada PR acontece no ambiente local com Docker **antes** do merge, nunca depois;
> - merge na `main` equivale a publicar, então não faça merge de PR que não rodou localmente;
> - depois de cada merge, conferir no painel do Render se o deploy subiu e olhar o log de subida.

## Segredos

Nunca commite o arquivo `.env`. Confira o `.gitignore` antes de qualquer commit que toque em configuração.

Nunca imprima o conteúdo de variáveis de ambiente, chave de API ou credencial de banco em resposta, log ou mensagem de erro.

Nunca escreva valor padrão de segredo no código. Se uma variável de ambiente obrigatória estiver ausente, a aplicação deve recusar iniciar com mensagem clara.

## Stack

Back-end: Python com FastAPI e Uvicorn, acesso ao banco com aiomysql sobre SSL.
Front-end: HTML, CSS e JavaScript puro, sem framework.
Banco: MySQL 8.4 no Aiven, serviço novo criado em 26/11/2026, em trial até cerca de 26/12/2026.
IA: API do Claude chamada direto via httpx.
Hospedagem: Render, plano gratuito, região Oregon. Desligado de 08/10/2026 a 28/11/2026, no ar desde então num serviço novo.

Estrutura:

```
backend/
  main.py            # monolito com rotas, prompt, banco e chamada à IA
  requirements.txt
  ca.pem
  utils/teste_carga.py
js/                  # api.js, questionario-api.js, sidebar.js, footer.js
pages/               # login, cadastro, questionário, resultado, mapa,
                     # oportunidades, módulos 1 a 4, histórico, admin
partials/
styles/
assets/
index.html
```

Tabelas: `usuarios`, `respostas_teste`, `respostas_modulo`, `perfis`, `mapa_progresso`, `jobs`.

Fluxo de geração: o aluno finaliza o questionário, o backend cria registro em `jobs` com status `processando`, dispara `asyncio.create_task` e devolve o `jobId`. O front faz polling em `/api/resultado/status`. O resultado é gravado em `perfis` como JSON.

## Problemas conhecidos no código

Levantados em agosto de 2026. Não corrija nada desta lista sem eu pedir. Ela existe para você entender o estado real e não se surpreender.

Segurança, em correção na Fase 0:

- Senhas gravadas em texto plano. O cadastro grava direto e o login compara string com string.
- Valor padrão de segredo embutido no código como fallback do `os.getenv`, em rota administrativa e no segredo do JWT.
- Senha de admin trafegando por query string.
- CORS liberado para qualquer origem com `Authorization` aceito.
- Rota `/pages/{page}` monta caminho no disco a partir da URL.
- `/api/resultado/status` não verifica se o job pertence ao usuário autenticado.

Confiabilidade, previsto para a Fase 1:

- Sem limite de concorrência nas chamadas à IA. Trinta e um alunos finalizando ao mesmo tempo disparam 31 chamadas simultâneas, o que causou as falhas da validação em campo.
- Job em memória não sobrevive a reinício do processo. O Render gratuito hiberna, então o job fica em `processando` para sempre.
- `mapa_progresso.usuario_id` é `INT` mas o id do usuário é `VARCHAR(36)` com UUID. O progresso provavelmente não está salvando.
- Um `httpx.AsyncClient` novo criado a cada chamada.
- Resposta truncada por limite de tokens não é tratada. O JSON fica sem fechamento e o retry regenera tudo do zero.
- `main.py` com mais de mil linhas misturando rotas, perguntas, prompt, banco e IA.
- Nenhum teste automatizado e nenhuma integração contínua.

Qualidade da saída, previsto para a Fase 3:

- **Resolvido em 26/11/2026 (PR #12).** A cidade vai para o prompt, vinda do perfil (`usuarios.cidade`) ou da pergunta 3 do teste inicial, com o perfil tendo precedência. O texto original estava incompleto: a pergunta 3 já pedia cidade e estado e chegava ao modelo, só que sem instrução. Texto original:
  A cidade do aluno existe na tabela `usuarios` mas nunca é passada para o prompt.
- **Resolvido em 26/11/2026 (PR #12).** A data de hoje vai para o prompt, por extenso e em ISO, no horário de Brasília, e fica gravada em `jobs.data_referencia`. Texto original:
  A data corrente também não é passada, então o modelo não ancora prazos no calendário de ENEM, SISU e ProUni.
- O schema pede três estruturas concorrentes para a mesma informação: `caminhos[].passos`, `proximosPassos` e `mapaCarreira`.
- **Resolvido em 26/11/2026 (PR #12).** O status é calculado no backend a partir do progresso salvo, e o que vier da IA é descartado. O schema passou a pedir `dataLimite` no lugar do `status`. Texto original:
  O campo `status` do `mapaCarreira` é gerado pela IA, que não tem como saber o que o aluno já fez.
- Nenhum passo tem critério de conclusão verificável e nenhum array tem cardinalidade definida.

Interface, encontrado no teste de ponta a ponta em produção de 28/11/2026:

- **Resolvido em 28/11/2026 (PR #18).** O texto da pergunta 13 passou a pedir uma opção só: "Escolha a opção que mais pesa para você". A múltipla escolha de verdade ficou de fora, porque muda como a resposta é gravada e como chega ao prompt. Texto original:
  A pergunta 13 do questionário diz "Escolha até 2 opções", mas a interface só aceita uma: clicar na segunda desmarca a primeira. A pergunta está definida em `backend/main.py` com `"tipo":"opcoes"`, o mesmo tipo das perguntas de escolha única, e nenhuma pergunta do questionário usa múltipla escolha. Corrigir pede uma decisão antes: mudar o texto para uma opção só, ou criar a múltipla escolha no front e no back, o que muda como a resposta é gravada e como chega ao prompt.

## Equipe e áreas

Três pessoas no segundo semestre de 2026. Não altere arquivo fora da minha área sem me avisar que vai precisar.

Mateus Alcantara, responsável técnico: camada de IA, prompt, schema, fila e ciclo de vida dos jobs, arquitetura.
Ricardo Ongari Rodrigues: autenticação, segurança, esquema e migrações de banco, rotas administrativas.
Yago Dias dos Santos: páginas, JavaScript, estilos, painel administrativo no front, teste de carga, rubrica de qualidade.

Orientador: professor André Luís.

## Fora de escopo neste semestre

Se eu pedir algo nesta lista, lembre que foi decidido contra e pergunte se eu quero mesmo reabrir.

- Árvore de agentes, orquestração multi-etapas, tool use ou skills na geração do plano. Avaliado e recusado em agosto de 2026: multiplica chamadas por aluno e piora o gargalo de concorrência, que é o problema central.
- Trabalho de mercado, venda institucional, edital ou modelo de negócio.
- Funcionalidade nova de produto fora do roadmap em `ROADMAP.md`.
- Fluxo de consentimento parental sob LGPD, que é pré-requisito de venda e não de funcionamento.

## Decisões registradas

Verificação de nomes de instituição será feita por código consultando base pública, não por IA. Motivo: reprodutível, sem custo de token, mais confiável.

A geração do plano será separada em duas chamadas, uma de diagnóstico e outra de plano. Motivo: hoje o plano de ação disputa orçamento de tokens com nove outras seções e fica raso.
