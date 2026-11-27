# Programando o Futuro — Plano do Segundo Semestre de 2026

> [!CAUTION]
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

Documento central da equipe. Toda decisão de escopo, ordem de execução e divisão de trabalho está aqui. Se algo não está neste documento, não está no escopo do semestre.

**Equipe:** Mateus Alcântara (responsável técnico), Yago Dias dos Santos, Ricardo Ongari Rodrigues.
**Orientador:** professor André Luís.
**Período:** 31 de agosto a 13 de dezembro de 2026, quinze semanas.
**Repositório:** `MateusAlcantara13/programando-o-futuro`. O repositório `vic-cavalcant3/Programando-o-Futuro` não é mais o do projeto.

---

## 1. Objetivo do semestre

Transformar um protótipo que funcionou em uma escola por dois dias em um sistema que aguenta uso real, com código que três pessoas conseguem manter ao mesmo tempo, e com qualidade de saída medida em vez de estimada.

Três resultados esperados até dezembro:

1. Nenhuma senha em texto plano, nenhum segredo no repositório, nenhum acesso administrativo sem autenticação adequada.
2. Cinquenta usuários simultâneos completando o fluxo sem falha, com número medido antes e depois.
3. Qualidade do plano de carreira avaliada por rubrica, com comparação documentada entre a versão de agosto e a de dezembro.

## 2. O que está fora do escopo

Escrito aqui para evitar discussão recorrente. Nada disso entra neste semestre, independentemente de quão interessante pareça no meio do caminho:

- Árvore de agentes ou orquestração multi-etapas além da separação em duas chamadas prevista na Fase 3.
- Qualquer trabalho voltado a mercado, venda institucional, edital ou modelo de negócio.
- Funcionalidade nova de produto que não esteja listada neste documento.
- Consentimento parental sob LGPD, que é pré-requisito de venda e não de funcionamento.
- Registro de marca no INPI.

Ideia que surgir vai para a seção 10 e é decidida no fim do semestre.

## 3. Áreas de propriedade

Cada pessoa é dona de uma área. Dono significa que decide, implementa e revisa mudanças naquela área. Ninguém altera área de outro sem combinar antes.

**Mateus — camada de IA e arquitetura**
Prompt, schema de saída, chamada à API, fila e ciclo de vida dos jobs, decisões de arquitetura, revisão final de qualquer alteração estrutural.

**Ricardo — dados e segurança**
Autenticação, hash de senha, migrações de banco, esquema das tabelas, segredos e variáveis de ambiente, rotas administrativas do backend.

**Yago — interface e medição**
Todas as páginas, JavaScript e estilos, painel administrativo no front, script de teste de carga, conjunto de perfis de teste e rubrica de qualidade.

Fora dessas áreas existem dois territórios compartilhados que exigem regra explícita, tratados na seção 4.

**Semana de 01/11/2026.** Yago e Ricardo estão fora e o Mateus está tocando todas as áreas, inclusive esquema e migrações. Enquanto isso durar, as áreas servem como ordem de execução. Ver a situação da Fase 1.

Durante esta semana, os pull requests são aprovados pelo próprio autor. Quando o Yago e o Ricardo voltarem, eles revisam os PRs #4 a #6 e os demais mergeados nesta semana, e podem abrir correção sobre qualquer um deles. A regra de revisão por outra pessoa da seção 4 continua valendo, e a revisão desses PRs só acontece mais tarde.

## 4. Regras para não atrapalhar uns aos outros

**O `main.py` é o principal risco de colisão.** São 1154 linhas com tudo dentro. Enquanto ele não for quebrado em módulos, vale a regra: no máximo um pull request aberto por vez tocando nesse arquivo. Quem for começar avisa no grupo antes de criar o branch.

**A modularização acontece em uma semana de congelamento.** Na semana 5, ninguém abre outro pull request no backend. Mateus quebra o arquivo, os três revisam juntos, e só depois o trabalho paralelo recomeça. Tentar modularizar com três frentes abertas gera conflito em todo arquivo.

**O JSON do plano é um contrato.** O front do Yago consome exatamente os campos que a IA do Mateus produz. Qualquer alteração de campo passa por aviso no grupo e atualização da seção 7 deste documento no mesmo pull request. Campo alterado sem aviso quebra tela sem ninguém entender por quê.

**O esquema do banco só muda por migração escrita.** Ricardo é o único que altera `criar_tabelas` e toda alteração vem com script de migração para os dados existentes. Alterar tipo de coluna direto no Aiven não é aceito.

**Fluxo de trabalho no Git.** Branch protegida na `main`, sem push direto. Um branch por tarefa, nomeado com a fase e o assunto, por exemplo `fase1/fila-jobs`. Todo pull request precisa de aprovação de pelo menos uma pessoa que não seja o autor. Pull request que fica mais de três dias aberto vira assunto da reunião semanal.

**Rituais.** Reunião de trinta minutos toda segunda para definir a semana e checar bloqueios. Checkpoint curto na quinta apenas para sinalizar o que travou. Nada além disso.

---

## 5. Roadmap

### Fase 0 — Segurança (semana 1, 31/08 a 06/09)

Os três trabalham juntos nesta semana. É a única fase sem paralelismo, porque são correções curtas e interdependentes e porque todo mundo precisa entender o que foi exposto.

**Deploy desligado.** Desde 08/10/2026 o sistema não roda no Render. A `main` não publica nada, e a validação de cada PR acontece no ambiente local com Docker. O deploy volta na última tarefa desta fase, depois que todas as outras estiverem fechadas e o banco de produção resolvido.

| Tarefa | Responsável | Critério de conclusão |
|---|---|---|
| Hash de senha com bcrypt no cadastro, login e troca de senha | Ricardo | Nenhuma senha legível no banco, login funcionando |
| Script de migração das senhas existentes | Ricardo | Contas anteriores conseguem entrar sem redefinir senha |
| Remover `backend/data.json` do repositório e do histórico do Git | Mateus | Arquivo ausente em qualquer commit acessível |
| Avisar as pessoas com dado exposto no arquivo | Mateus | Comunicação feita e registrada |
| Remover todos os valores padrão de segredo do código | Ricardo | Aplicação recusa iniciar sem `JWT_SECRET` e `ADMIN_SECRET` |
| Mover senha de admin de query string para cabeçalho | Ricardo | Nenhum segredo aparece em URL |
| Restringir CORS ao domínio publicado | Mateus | Requisição de origem desconhecida é bloqueada |
| Restringir `/pages/{page}` a lista fixa de páginas | Yago | Nome fora da lista retorna 404 |
| Verificar dono do job em `/api/resultado/status` | Mateus | Job de outro usuário retorna 403 |
| Configuração de TLS do banco: verificação de hostname, CA configurável e modo local | Ricardo | Hostname do servidor é verificado, a CA vem de variável de ambiente, e a aplicação roda contra MySQL local sem alterar código. **Concluído em 01/11/2026 (PR #5).** A verificação de hostname ainda não foi testada, ver reconexão do deploy |
| Remover a senha guardada no `localStorage` dos navegadores | Yago | Nenhuma página do site deixa o campo `senha` dentro de `pf_user` depois de carregar |
| Front chama a API pela origem da própria página, sem endereço fixo | Yago | Nenhum endereço de servidor escrito no front, e o mesmo código funciona no backend local e em produção |
| Documentar o ambiente local no repositório | Mateus | Ricardo sobe o sistema na própria máquina seguindo só o documento, sem perguntar nada a ninguém. **Ambiente criado em 01/11/2026 (PR #5). Falta a verificação pelo Ricardo** |
| Reconectar o deploy no Render | Mateus | Merge na `main` volta a publicar, com o banco de produção definido e todas as tarefas acima fechadas |

A senha `25107Senai` está no código-fonte público hoje. Ela precisa ser trocada, não apenas movida para variável de ambiente.

O mesmo vale para o `JWT_SECRET`. O valor padrão escrito no código está público no repositório, então produção precisa de um valor aleatório novo, e a aplicação tem de recusar subir em produção sem a variável definida.

**Configuração de TLS do banco.** O `init_db` monta o contexto SSL com três problemas. Primeiro, `check_hostname=False` aceita qualquer certificado assinado pela CA, sem conferir o nome do servidor. Segundo, o caminho da CA está fixo no código, apontando para o `ca.pem` do Aiven, e o provedor do banco vai mudar. Terceiro, hoje não é possível rodar o backend contra um MySQL local sem alterar código. O aiomysql 0.2.0 avisa ao servidor que vai usar TLS sempre que recebe um contexto SSL (`aiomysql/connection.py:244-245`), e um servidor sem TLS recusa a conexão com `(1043, 'Bad handshake')`. Isso foi verificado em 08/10/2026 contra MySQL 8.0.46. Por isso o modo local passa a ser um requisito.

O que muda: uma variável `DB_SSL_MODE`, obrigatória, com dois valores. Em `verificar`, a CA é lida de `DB_SSL_CA`, o hostname é conferido e, depois de conectar, o código consulta `SHOW SESSION STATUS LIKE 'Ssl_cipher'` e recusa iniciar se o resultado vier vazio. Em `desligado`, o pool é criado sem contexto SSL e um aviso vai para o log. Esse modo serve só para MySQL local.

Hipótese não verificada: um atacante ativo no caminho entre o Render e o banco poderia retirar dos pacotes iniciais, que trafegam sem criptografia, o anúncio de TLS do servidor e o aviso de TLS do cliente, fazendo a conexão seguir em texto claro. A consulta a `Ssl_cipher` na inicialização serve de defesa barata contra essa possibilidade, mas não cobre as conexões abertas depois pelo pool.

Como verificar: (1) MySQL local sem TLS em modo `desligado`, a aplicação sobe e o aviso aparece no log; (2) o mesmo banco em modo `verificar`, a aplicação não sobe e explica o motivo; (3) banco com TLS e CA correta em modo `verificar`, a aplicação sobe; (4) CA errada, a aplicação não sobe; (5) certificado assinado pela CA certa, mas com outro nome de servidor, a aplicação não sobe.

**Como ficou no PR #5 (01/11/2026).** A implementação seguiu um caminho mais simples que o descrito acima. No lugar de `DB_SSL_MODE`, a variável `DB_SSL_DISABLED=true` desliga o TLS, e sem ela o TLS é exigido. A CA vem de `DB_SSL_CA`. O hostname é conferido, porque o `check_hostname` fica no padrão do `ssl.create_default_context`. A consulta a `Ssl_cipher` na inicialização não foi implementada. Os testes (3) a (5) dependem de um banco com TLS e ficam para a reconexão do deploy.

**Senha guardada no navegador.** Até a correção do `PATCH /api/auth/perfil`, essa rota devolvia a linha inteira de `usuarios`, com a coluna `senha`. Antes do PR de hash, isso era a senha em texto plano. Cinco páginas gravam essa resposta com `auth.setUser`: `oportunidades.html:436`, `mapa_carreira.html:572`, `inicial_logada.html:782`, `inicial_mapa_feito.html:1103` e `resultado.html:734`. Todo aluno que editou o perfil ficou com a senha legível no `localStorage` (chave `pf_user`) do navegador. Em computador de laboratório, qualquer pessoa que abrir as ferramentas do desenvolvedor consegue ler esse valor. O servidor não tem como apagar dado guardado no navegador.

O que muda, tudo centralizado no `js/api.js`, que é carregado por 14 páginas e é o único lugar que lê e grava `pf_user`. São dois pontos, e os dois são obrigatórios. Primeiro, o `auth.setUser` passa a descartar o campo `senha` antes de gravar, para que nenhuma rota volte a causar o problema. Segundo, ao carregar o script, ele lê o `pf_user` já guardado, apaga o campo `senha` se existir e grava o objeto de volta. Esse segundo ponto é o que limpa o que já vazou. Não implementar página por página: uma página esquecida ou uma página nova trariam o problema de volta.

Limitação: a limpeza só acontece em navegadores onde alguém abrir o site de novo. Com o deploy desligado, ela só começa a valer quando o site voltar ao ar. Para os computadores da escola parceira usados na validação de maio, vale pedir à escola que limpe os dados de navegação das máquinas do laboratório. Até a reconexão, esse pedido é a única medida que alcança esses navegadores.

Como verificar: (1) gravar à mão um `pf_user` com campo `senha` pelo console do navegador; (2) abrir `index.html` e uma página de módulo, e conferir que o campo sumiu; (3) editar o perfil e conferir que `pf_user` não tem `senha`.

**Endereço fixo da API no front.** O front escreve o endereço de produção direto no código: `js/api.js:6` (`API_URL`, usado por todas as chamadas do `apiFetch`), `pages/admin.html:219` (`API`, usado em oito chamadas) e `pages/mapa_carreira.html:306` e `:327`. Com o backend rodando localmente, as páginas abertas em `http://127.0.0.1:8000` mandam as requisições para o Render, que está desligado. No `mapa_carreira.html` há também um erro: o código lê `window.API_URL`, mas o `api.js` declara `const API_URL`, e uma `const` no topo de um script não vira propriedade de `window`. O resultado é que a página sempre usa o endereço fixo de reserva.

Front e back são servidos pela mesma origem. O próprio backend entrega `index.html` e `/pages/*` (`main.py:632-645`) e monta `/js`, `/styles`, `/assets` e `/partials` como arquivos estáticos (`main.py:1173-1177`). O repositório não tem configuração de hospedagem separada para o front. Por isso o endereço da API é sempre o mesmo da página, e o endereço fixo é desnecessário. Antes da reconexão do deploy, confirmar no painel do Render que existe um único serviço, sem um site estático separado.

O que muda: as chamadas passam a usar caminho relativo (`/api/...`). No `api.js`, `API_URL` vira string vazia, o que equivale a usar `window.location.origin` sem precisar de condicional. No `admin.html`, o mesmo vale para `API`. O `mapa_carreira.html` deixa de montar o próprio `fetch` e passa a usar `api.get` e `api.post` do `api.js`, o que elimina o erro do `window.API_URL`. Consequência: abrir o HTML direto do disco ou por um servidor de desenvolvimento separado, como o Live Server, deixa de funcionar. O site passa a ser aberto sempre pelo backend. O `backend/utils/teste_carga.py` continua com endereço próprio, porque é um script que aponta para um servidor, e já tem tarefa de reescrita na Fase 1.

Como verificar: (1) uma busca por `onrender` em `js/` e `pages/` não encontra nada; (2) com o backend local, abrir `http://127.0.0.1:8000`, fazer cadastro, login e abrir o mapa, e conferir na aba Rede das ferramentas do desenvolvedor que todas as requisições vão para `127.0.0.1:8000`; (3) o painel admin carrega os dados localmente.

**Ambiente local documentado.** Com o deploy desligado, o ambiente local é o único lugar onde o sistema roda, e hoje só uma máquina tem ele montado. O documento fica no repositório, em `docs/ambiente-local.md`, com link no README, e cobre: o comando do container (`mysql:8.0` na porta 3307, com `--skip-ssl`, banco e usuário de teste); o `backend/.env` local, explicando que o nome tem de ser `.env`, porque o `load_dotenv()` não lê `.env.local`; o ambiente virtual criado fora do repositório com `py -3.13 -m venv`; a instalação das dependências; o comando para subir o backend; um teste rápido de cadastro e login; e como derrubar e recriar o banco do zero. O `backend/.env.example` é atualizado junto, com valores de exemplo para uso local.

Dependências: esta tarefa vem depois de duas outras. Primeiro, a configuração de TLS: sem o modo `DB_SSL_MODE=desligado`, o backend não conecta em MySQL local sem um script de contorno fora do repositório, e documentar esse contorno ensinaria a equipe a depender dele. Segundo, a remoção do endereço fixo da API: sem ela, o backend sobe, mas o site aberto no navegador chama o Render em vez do backend local. O documento deve dizer que o site é aberto sempre por `http://127.0.0.1:8000`, e não direto do disco.

Como verificar: Ricardo segue o documento numa máquina onde o ambiente nunca foi montado, até conseguir fazer cadastro e login. Se ele precisar perguntar qualquer coisa ao Mateus, o documento não está pronto: a resposta entra no documento e a verificação recomeça do zero.

**Como ficou no PR #5 (01/11/2026).** O `CLAUDE.md` já dizia que a validação de cada PR acontecia no ambiente local com Docker, mas até esse PR o repositório não tinha esse ambiente. Agora tem. O banco sobe pelo `docker-compose.yml` na raiz (MySQL 8.0 na porta 3306, com a aplicação conectando sem TLS por `DB_SSL_DISABLED=true`), e a documentação ficou na seção "Como rodar localmente" do README em vez de `docs/ambiente-local.md`. Falta a verificação pelo Ricardo descrita acima.

**Reconexão do deploy.** Última tarefa da fase, só depois de todas as outras fechadas e do banco de produção resolvido. Antes de reconectar: confirmar no painel do Render que o serviço aponta para `MateusAlcantara13/programando-o-futuro`; cadastrar as variáveis de ambiente de produção, já sem nenhum valor padrão no código; usar `DB_SSL_MODE=verificar` com a CA do provedor novo; e confirmar que a `ADMIN_SECRET` foi trocada. Depois de reconectar, o `CLAUDE.md` volta a dizer que merge na `main` publica em produção.

Cinco pendências descobertas em 01/11/2026, também antes de reconectar:

1. Gerar um `JWT_SECRET` aleatório e fazer a aplicação recusar subir em produção sem a variável definida. Faz parte da tarefa de remover os valores padrão de segredo, ver acima.
2. Conferir o `DB_SSL_CA`. O valor padrão é um caminho relativo à raiz do repositório (`backend/ca.pem`), mas o backend roda de dentro de `backend/`, então esse caminho não encontra o arquivo.
3. Confirmar a verificação de hostname do certificado contra o banco novo, com os testes (3) a (5) da configuração de TLS. Ela foi ativada no PR #5, mas não pôde ser testada, porque o banco local roda sem TLS.
4. Implementar a consulta a `Ssl_cipher` na inicialização, que estava no plano da tarefa de TLS e ficou de fora do PR #5. Sem ela, a aplicação não tem como confirmar que o TLS está ativo em produção, só supor. A limitação descrita na hipótese acima continua: a consulta cobre a conexão da inicialização, e não as abertas depois pelo pool.
5. Criar uma variável de ambiente que identifique onde a aplicação está rodando, para que os modos perigosos se recusem a ligar em produção em vez de só avisar no log. Hoje o código não tem como saber se está em produção, e três pontos dependem de ninguém esquecer uma variável: o `JWT_SECRET` com valor padrão, o `DB_SSL_DISABLED` e o `IA_SIMULADA`.

**Achado de 26/11/2026: o progresso do mapa de carreira nunca foi salvo no servidor, desde o começo do projeto.** Duas falhas independentes impediam isso:
- `mapa_progresso.usuario_id` era `INT` e recebia o UUID do aluno, que é texto. Com o MySQL em modo estrito, o INSERT dava erro. Sem modo estrito, o UUID virava número e alunos diferentes dividiam a mesma linha. Isso valia também para a produção, inclusive na validação de maio. Corrigido no Bloco 2 (PR #10).
- A página `mapa_carreira.html` lia `window.API_URL`, que nunca existiu, porque `const` não vira propriedade de `window`. Com isso, ela sempre caía no endereço do Render escrito à mão. Com o backend rodando local, as chamadas iam para o Render, e desde 08/10/2026, com o deploy desligado, falhavam na rede. Corrigido no Bloco 3.

Além disso, a falha do POST era engolida por um `catch` vazio. O aluno via o visto na tela e nunca era avisado de que nada tinha sido salvo. O progresso existia só no navegador de cada máquina. Consequência: o acompanhamento (Bloco 6) começa do zero. Não existe histórico de progresso de nenhum aluno, nem dos 31 da validação de maio. Que os dois consertos destravaram o caminho é hipótese até `backend/testes/teste_mapa_progresso.py` rodar com MySQL.

**Pendências registradas em 26/11/2026 (Bloco 3, dados e front).**

1. **Consentimento dos responsáveis.** Os alunos são menores de idade, e o consentimento dos responsáveis não foi implementado. Fica para a fase da rede pública, fora deste semestre (ver seção 10). Até 26/11/2026 o front mandava `aceite_menor: false` fixo. Desde então ele não manda nada, e o cadastro grava NULL, que quer dizer "não coletado". As linhas antigas com `false` também não significam nada.
2. **Usuários com aceite anterior a 26/11/2026.** Eles têm `aceite_lgpd = 1` e `aceite_lgpd_em` NULL, porque o front mandava o aceite fixo, sem o aluno marcar nada. Falta decidir se esses usuários precisam ler e aceitar o termo no próximo login. Não implementado.
3. **Texto do termo da LGPD.** A versão `2026-11-26` é rascunho e precisa de revisão do orientador antes de ser usada com alunos. Ela está em `TERMO_LGPD_PARAGRAFOS`, em `backend/main.py`. Qualquer mudança no texto exige versão nova em `TERMO_LGPD_VERSAO`.
4. **Remover o caminho de senha em texto plano.** Apagar o trecho de texto plano de `verificar_senha` e a conversão em hash dentro de `login()` quando a métrica "Senhas sem hash" do painel admin chegar a zero. Antes disso, quem ainda não migrou fica trancado fora da conta.
5. **`CORS_ORIGENS` na reconexão do deploy.** Com `AMBIENTE=producao`, a aplicação não sobe sem essa variável. Ela entra na lista de variáveis de produção.
6. **Rascunhos de resposta em `sessionStorage`.** Fechar o navegador no meio de um módulo apaga o rascunho guardado no navegador. As respostas que já foram enviadas ao backend continuam salvas. Uma aba nova também começa sem sessão. Foi escolhido assim para o próximo aluno na mesma máquina não ver nada do anterior.
7. **Aluno que levanta sem clicar em Sair.** O `sessionStorage` só é apagado ao sair ou ao fechar o navegador. Se o aluno deixa a aba aberta, o próximo que sentar usa a conta dele até o token vencer (`JWT_EXPIRES_H`, hoje 24 h). Opções a avaliar: saída automática por inatividade no front e um prazo de token menor. Não implementado.

### Fase 1 — Confiabilidade (semanas 2 a 4, 07/09 a 27/09)

Aqui começa o trabalho paralelo. Cada um na sua área.

**Mateus, fila e concorrência**
Semáforo limitando chamadas simultâneas à API, com o limite como variável de ambiente para permitir ajuste sem novo deploy. Colunas `tentativas` e `atualizado_em` na tabela `jobs`. Rotina de inicialização que identifica job travado em `processando` e reenfileira. Reprocessamento automático substituindo o botão manual do admin. Cliente HTTP único no ciclo de vida da aplicação em vez de um por chamada. Tratamento de resposta truncada por limite de tokens, que hoje cai no retry sem diagnóstico.
Concluído em 01/11/2026: semáforo (PR #4) e colunas `tentativas` e `atualizado_em`, com heartbeat gravado a cada tentativa de chamada à IA (PR #6).

**Ricardo, correção de dados**
Correção do tipo de `mapa_progresso.usuario_id`, hoje `INT` recebendo UUID, com verificação de quantos registros foram perdidos. Chave estrangeira e índice na tabela. Índice em `jobs` por usuário e data. Migração da coluna `modulos_concluidos` se aparecer inconsistência.

**Yago, medição**
Reescrita do `teste_carga.py` para rodar com número de usuários parametrizável e produzir relatório com taxa de sucesso, latência média e distribuição de erros. Execução com 15, 31 e 50 usuários, com os números registrados. Montagem do conjunto de doze perfis fixos de teste e da rubrica de qualidade descrita na seção 8. Geração da linha de base de qualidade usando o sistema como está hoje.
A versão completa do `teste_carga.py` usada na validação de maio nunca foi commitada e se perdeu. No repositório existe só um script simples de 67 linhas, que aponta para o Render e não gera relatório. Ele serve de ponto de partida, mas a tarefa passa a ser escrever o teste do zero.

A linha de base precisa sair antes de qualquer mudança no prompt. Sem ela, não há comparação possível em dezembro.

**Marco da semana 4:** cinquenta usuários simultâneos com falha abaixo de cinco por cento, e doze planos de linha de base arquivados.

**Situação em 01/11/2026.** A Fase 1 foi dimensionada para três pessoas, com prazo até 07/11. Nesta semana o Yago e o Ricardo estão fora e o Mateus está tocando todas as áreas sozinho, e com uma pessoa esse prazo não se sustenta. Ordem solo do Mateus:

1. Teste de carga, escrito do zero.
2. Rodar as três cargas, com 15, 31 e 50 usuários, e registrar os números.
3. Recuperação de job travado.
4. Tratamento de resposta truncada.

A adaptação das telas de resultado da Fase 3 fica reservada para o Yago e o Ricardo.

**Pendências registradas em 01/11/2026.**

- **Folga curta entre a duração de uma geração e o timeout.** **Resolvida em 26/11/2026:** o timeout virou a variável `IA_TIMEOUT_S`, com padrão 300 s, e o limite de job travado passou a ser calculado a partir dele (ver registro de decisões). O valor definitivo continua dependendo do teste de carga, e a hipótese sobre as falhas de maio continua sem confirmação. Texto original: O `_chamar_ia_com_retry` usa timeout de 120 s. Três gerações reais completas, medidas em 01/11/2026 no ambiente local, uma de cada vez e sem concorrência, levaram 100,8 s, 93,6 s e 94,4 s (valor de `chamada=` no log). A folga é de 20 a 26 segundos. Como a API só devolve a resposta quando termina de gerar, esses 120 s funcionam como limite para a geração inteira, e uma API um pouco mais lenta sob carga basta para estourar o tempo e fazer o retry gerar o plano de novo do zero. Hipótese: isso explica parte das falhas por timeout da validação de maio. Não é causa comprovada, porque as medições foram feitas sem carga. A confirmação vem do teste de carga. O aumento do timeout é candidato a entrar nesta fase. Se ele mudar, o limite de 10 minutos da recuperação de job travado precisa ser recalculado, porque foi tirado do intervalo de cerca de 145 s entre heartbeats, que depende do timeout de 120 s.
- **`/api/vagas` não passa pelo semáforo.** **Resolvida em 26/11/2026:** a rota passou a usar um semáforo próprio, com limite em `IA_MAX_CONCORRENTES_LISTA` (ver registro de decisões). Texto original: A rota chama `chamar_ia_lista`, que faz o POST direto para a API, sem semáforo, heartbeat nem retry. Com muitos alunos abrindo a página de oportunidades ao mesmo tempo, essas chamadas escapam do limite de concorrência. Não corrigido.
- **Avaliar streaming na chamada à API.** Uma resposta de 8192 tokens que só chega quando termina é frágil por natureza. Com streaming, a resposta chega aos poucos, e o timeout passa a valer entre um pedaço e outro, em vez de valer para a geração inteira. É uma mudança grande e fica para depois do teste de carga.

### Fase 2 — Estrutura (semanas 5 a 8, 28/09 a 25/10)

**Semana 5 é congelamento de backend.** Mateus quebra o `main.py` em módulos separando rotas de autenticação, rotas do teste inicial, rotas dos módulos, camada de banco, camada de IA e dados das perguntas. Ninguém mais abre pull request no backend nessa semana. Revisão conjunta antes do merge.

Depois do congelamento, nas semanas 6 a 8:

**Ricardo** escreve testes de autenticação e banco com pytest, cobrindo cadastro, login, token expirado e salvamento de resposta.
**Mateus** escreve testes do ciclo de vida do job, com a chamada à API simulada, cobrindo sucesso, erro, retry e recuperação de job travado.
**Yago** configura GitHub Actions rodando os testes a cada pull request, e revisa o front em celular de baixo custo, medindo tempo até a primeira tela útil.

**Pendência menor.** No `main.py`, a mensagem de erro de formato inválido montada em `processar_resultado_ia_db`, que aparece no painel admin, tem o texto `teste_carga.py` no começo, resto de uma edição mal feita.

**Marco da semana 8:** nenhum arquivo de backend acima de trezentas linhas, testes rodando automaticamente em cada pull request, `main` com histórico limpo.

### Fase 3 — Qualidade da saída (semanas 9 a 12, 26/10 a 22/11)

Esta é a fase que ataca o problema do roadmap fraco. Ordem importa, porque cada item depende do anterior.

**Semana 9, correções baratas.** Mateus passa a cidade do usuário e a data corrente para o prompt. Os dois campos existem no sistema e nenhum chega ao modelo hoje. Yago roda os doze perfis novamente e compara com a linha de base. Essa comparação isolada tem valor de defesa na banca, porque mostra ganho medido a partir de mudança mínima.

**Como ficou em 26/11/2026 (Bloco 5, metade segura).** A unificação da estrutura do plano NÃO entrou: ela toca prompt, backend e quatro telas e vem depois dos testes. O que entrou:
- **Data de hoje** no prompt, por extenso e em ISO, no horário de Brasília. Junto vai a instrução de que todo prazo é posterior a ela e de que um prazo vencido vira a próxima ocorrência, com o ano. A data usada fica gravada em `jobs.data_referencia`.
- **Cidade do aluno** no prompt, com a instrução de priorizar o que é alcançável de transporte público. Correção do parágrafo acima: a pergunta 3 do teste inicial já pedia "cidade e estado" como obrigatória, e a resposta chegava ao modelo, só que como uma linha qualquer, sem instrução. A coluna `usuarios.cidade` existia, mas nunca chegava. Nenhum campo novo foi criado no cadastro.
- **O `status` saiu do schema**, antes da unificação, porque o mapa dependia dele para bloquear passos. No lugar entrou `dataLimite` (AAAA-MM-DD ou null). O status é calculado no backend a partir do progresso salvo: concluído com a data gravada pelo servidor, pendente ou vencido.

Pendências registradas em 26/11/2026 (Bloco 5):
1. **Planos já gerados não têm `dataLimite`.** Nenhum passo deles aparece como vencido até o plano ser gerado de novo.
2. **A `dataLimite` vem da IA e ninguém confere.** Uma data errada marca como vencido o que não venceu, ou esconde o que venceu. Conferir contra o calendário oficial (ENEM, SISU, ProUni, FIES) por código, na mesma linha da decisão de verificar instituições por código e não por IA.
3. **Marcações de progresso anteriores a 26/11/2026** ficam como concluídas sem data de conclusão. Nenhuma data é inventada.
4. **A cidade da pergunta 3 é texto livre,** sem normalização de cidade e UF. Isso basta para o prompt, mas não para filtrar instituições por código.
5. **A unificação das semanas 10 e 11** precisa manter a `dataLimite` e não trazer o `status` de volta para o JSON da IA.
6. **O `mapa_carreira.html` não foi aberto num navegador.** Os estados pendente, concluído e vencido precisam de revisão visual.
7. **O plano é uma foto do momento da geração.** Se o aluno preencher ou mudar a cidade no perfil depois de o plano ser gerado, o plano não muda: as instituições recomendadas continuam as da cidade usada na geração. Isso é aceitável agora e não é bug. Atualizar o plano exige uma geração nova, que é paga. Se um dia isso for oferecido, o lugar natural é a tela de perfil, ao mudar a cidade.

**Semanas 10 e 11, reestruturação da saída.** Mateus unifica `caminhos`, `proximosPassos` e `mapaCarreira` em uma estrutura única de plano, com etapas ordenadas, cada passo com prazo relativo e critério de conclusão verificável. O campo `status` sai do JSON gerado pela IA e passa a ser calculado pelo backend a partir do progresso salvo. Cardinalidade definida em todos os arrays. Separação em duas chamadas, uma para diagnóstico e outra para o plano, com o diagnóstico servindo de entrada para a segunda.

**O schema congela no fim da semana 10.** Yago só começa a adaptar as telas depois disso. Adaptar antes significa refazer.

**Semana 11, front.** Yago reescreve `resultado.html`, `mapa_carreira.html` e a visualização do plano consumindo a estrutura nova, eliminando a repetição de conteúdo entre páginas.

**Semana 12, verificação.** Ricardo constrói a checagem determinística dos nomes de instituição e curso contra base pública do INEP ou do MEC, marcando o que não corresponde a registro real. Isso é código comum, não chamada de IA.

**Marco da semana 12:** rubrica aplicada aos doze perfis com resultado documentado lado a lado com a linha de base de setembro.

### Fase 4 — Fechamento (semanas 13 a 15, 23/11 a 13/12)

Nova rodada de teste de carga com os números finais. Atualização do README com a arquitetura real, hoje desatualizada e ainda marcando o projeto como finalizado. Documentação das decisões técnicas do semestre a partir do registro da seção 9. Preparação da apresentação com três gráficos: carga antes e depois, qualidade antes e depois, e tempo médio de geração antes e depois.

Data da banca a confirmar com o professor André Luís. A semana 15 fica reservada para folga de cronograma, porque alguma fase vai atrasar.

---

## 6. Cadeia de dependências

Ordem obrigatória. Antecipar um item quebra o seguinte.

Hash de senha antes de qualquer coisa que toque em usuário.
Correção do `mapa_progresso` antes de qualquer trabalho de progresso ou acompanhamento, porque hoje provavelmente não salva.
Linha de base de qualidade antes de qualquer mudança no prompt.
Modularização antes dos testes, porque testar arquivo de mil linhas é inviável.
Testes antes da reestruturação do schema, porque é a rede de proteção da mudança mais arriscada do semestre.
Congelamento do schema antes do trabalho de front da Fase 3.

## 7. Contrato do plano de carreira

Seção viva. Atualizada no mesmo pull request que alterar o schema, sempre.

**Versão atual (v1, agosto de 2026):** estrutura descrita em `montar_prompt_base`, com `caminhos`, `proximosPassos` e `mapaCarreira` separados e sobrepostos. Documentada apenas no código.

**Versão alvo (v2, novembro de 2026):** estrutura única de plano. A definição de campos entra aqui na semana 10, escrita pelo Mateus, revisada pelo Yago antes do congelamento.

## 8. Rubrica de qualidade

Construída pelo Yago na Fase 1, aplicada em três momentos: linha de base em setembro, após as correções baratas em outubro, e final em novembro.

Cada plano gerado recebe nota de zero a três em cada critério:

1. As instituições citadas existem e ficam a distância razoável da cidade do aluno.
2. Os programas de acesso citados correspondem à situação real do aluno em renda e escolaridade.
3. O primeiro passo é executável em uma semana, sem custo e sem depender de terceiros.
4. Cada passo tem critério de conclusão verificável, não apenas uma intenção.
5. Os prazos estão ancorados no calendário real de ENEM, SISU e ProUni.
6. Não há repetição de conteúdo entre as páginas de resultado, mapa e oportunidades.
7. A linguagem é compreensível por um adolescente sem repertório familiar sobre carreiras.

Os doze perfis de teste precisam cobrir variação de renda, cidade, ano escolar, ter feito ENEM ou não, e ter clareza de objetivo ou não. Perfis todos parecidos não medem nada.

## 9. Registro de decisões

Toda decisão de arquitetura entra nesta tabela, com data, quem decidiu e por quê. Serve para não rediscutir a mesma coisa em novembro e para alimentar o relatório final.

| Data | Decisão | Motivo | Quem |
|---|---|---|---|
| 27/08/2026 | Árvore de agentes fora do escopo do semestre | Multiplica chamadas por aluno e piora o gargalo de concorrência que é o problema central | Equipe |
| 27/08/2026 | Verificação de instituições feita por código, não por IA | Reprodutível, sem custo de token, mais confiável | Equipe |
| 27/08/2026 | Separação em duas chamadas em vez de uma | Roadmap disputa orçamento de tokens com nove outras seções | Equipe |
| 01/11/2026 | Recuperação de job travado usa o heartbeat em `atualizado_em`, combinado com `tentativas > 0`, e não o tempo desde a criação | Job esperando vaga no semáforo fica com `tentativas = 0` e `atualizado_em` igual a `criado_em`, e não pode ser confundido com job parado | Mateus |
| 01/11/2026 | Limite de 10 minutos sem heartbeat para considerar job travado | O intervalo máximo entre heartbeats de um job trabalhando é de cerca de 145 segundos: timeout de 120 s da chamada mais a maior espera entre tentativas. Se esses tempos mudarem, o limite precisa ser revisto | Mateus |
| 01/11/2026 | Reenfileiramento por UPDATE condicional: só pega o job se o status ainda for `processando` e o heartbeat ainda estiver velho, e só dispara a tarefa se o UPDATE afetou uma linha | Sem isso, a mesma geração pode ser paga duas vezes | Mateus |
| 01/11/2026 | Migração de esquema roda sozinha no startup, de forma idempotente, com verificação logo depois que recusa servir se o esquema estiver errado | Depender de script manual derrubaria a aplicação a cada push com esquema novo até alguém lembrar de rodar. O script continua disponível para rodar à mão | Mateus |
| 26/11/2026 | Limite de job travado calculado a partir do timeout: 2 × (conexão + timeout + maior espera entre tentativas + gravação do heartbeat), o que dá 690 s com timeout de 300 s. Substitui o limite fixo de 10 minutos de 01/11 | O timeout virou variável de ambiente (`IA_TIMEOUT_S`) e subiu de 120 para 300 s. Com o limite fixo, mudar o timeout exigiria lembrar de recalcular. A margem de 2x existe porque o timeout do httpx vale por operação de rede, e não para a chamada inteira | Mateus |
| 26/11/2026 | Coluna `recuperacoes` em `jobs`, com teto em `IA_MAX_RECUPERACOES` (padrão 2: duas recuperações, três execuções). O reenfileiramento soma 1 e só acontece com `recuperacoes < teto` no WHERE do UPDATE condicional. No teto, o job é encerrado como erro, com mensagem no painel dizendo quantas vezes foi recuperado sem concluir | Reenfileirar zera `tentativas`, o que é necessário para a varredura não pegar job na fila, mas apagava o histórico. Um job que derruba o processo voltaria para a fila a cada reinício, cada volta paga, sem nada no banco mostrando. Deixar o job no teto em `processando` faria a varredura olhar para ele a cada rodada para sempre. Custo no pior caso: recuperações e tentativas se multiplicam, porque cada recuperação é uma execução nova com as suas 3 tentativas. Com teto 2, são (1 + 2) × 3 = até 9 chamadas pagas para o mesmo aluno. O número definitivo sai do teste de carga, como o `IA_TIMEOUT_S` | Mateus |
| 26/11/2026 | Semáforo próprio para as chamadas de lista (`/api/vagas`), com limite em `IA_MAX_CONCORRENTES_LISTA` (padrão 2). O teto real de chamadas simultâneas à API é a soma dos dois limites | Com um semáforo só, a chamada de ~20 s esperava atrás de uma fila de gerações de ~100 s, um bloqueio de cabeça de fila pior que o problema original. Com dois, nenhuma chamada fica fora de controle e a concorrência total continua conhecida | Mateus |
| 26/11/2026 | Senha com hash é reconhecida pelo formato completo do bcrypt (prefixo `$2a$`, `$2b$` ou `$2y$`, custo de dois dígitos, 60 caracteres), com o mesmo padrão no Python e na contagem em SQL. A contagem aparece no log do startup e no painel admin | Olhar só o prefixo confundiria uma senha em texto plano que começasse com `$2b$`. Um padrão só impede que o código e a métrica discordem. Sem a métrica, não há como saber quando o caminho de texto plano pode ser removido sem trancar ninguém fora da conta | Mateus |
| 26/11/2026 | Aceite da LGPD com caixa que o aluno marca, texto e versão servidos pelo backend (`GET /api/lgpd/termo`), e recusa no backend para aceite que não seja `true` ou versão diferente da atual. Grava a data em UTC e a versão aceita. A coluna `aceite_lgpd` passa a ser NOT NULL e sem padrão, e todo INSERT tem de dizer o valor. Aceite ausente e aceite falso têm erros diferentes (`LGPD_AUSENTE` e `LGPD_RECUSADO`). O `aceite_menor` deixa de ser enviado e é gravado como NULL. Aceites anteriores ficam com data NULL | O front mandava o aceite fixo em `true`, e o banco guardava um consentimento que não existiu. Pior ainda, o `DEFAULT TRUE` da coluna faria qualquer INSERT futuro que esquecesse o campo gravar um consentimento. Sem saber a versão, não dá para saber o que a pessoa leu. Inventar data para os aceites antigos seria pior que não ter | Mateus |
| 26/11/2026 | O servidor é a fonte da verdade do progresso do mapa, e o navegador é só cache (`pf_mapa_done`, `pf_mapa_checks`). Na carga, o cache aparece primeiro e o servidor sobrescreve quando responder. Envio que falha mostra aviso fixo de que a marcação não foi salva. Os envios saem em fila. A lógica fica em `js/mapa-progresso.js` | Progresso guardado só no navegador some ao fechar e não acompanha o aluno de uma máquina para outra, o que inviabiliza o acompanhamento. Falhar em silêncio fazia o aluno achar que tinha salvo. A fila impede que um envio antigo chegue depois de um novo e apague a marcação mais recente | Mateus |
| 26/11/2026 | CORS com lista explícita em `CORS_ORIGENS`, obrigatória com `AMBIENTE=producao`. Em local, o padrão é o localhost do uvicorn. O front usa endereço relativo, com um único ponto de configuração em `js/api.js` | `*` aceitava qualquer origem. Falhar no deploy é melhor que servir liberado. Como o backend serve o front, o endereço relativo funciona igual em local e em produção | Mateus |
| 26/11/2026 | Data de hoje no prompt, por extenso e em ISO, no horário de Brasília (UTC−3 fixo), com a instrução de prazos posteriores a ela e de usar a próxima ocorrência de um prazo vencido. A data usada fica gravada em `jobs.data_referencia` | Sem a data, a IA gerava passo já vencido no primeiro dia. Sem gravar a data, ninguém consegue julgar depois se o plano estava certo quando foi feito. O offset fixo evita depender do `tzdata`, que o Python no Windows não traz, e o Brasil não tem horário de verão desde 2019 | Mateus |
| 26/11/2026 | Cidade do aluno no prompt vinda do perfil (`usuarios.cidade`) ou da pergunta 3 do teste, sem campo novo no cadastro. Coleta mínima: cidade e estado, nunca endereço. **Precedência: o perfil ganha da pergunta 3**, e a pergunta 3 só é usada quando o perfil está vazio | O plano recomenda instituições e precisa saber o que é alcançável. A pergunta 3 já pede cidade e estado como obrigatória, e pedir de novo no cadastro seria coletar duas vezes o mesmo dado pessoal de um menor de idade. O perfil ganha porque o aluno pode editá-lo depois do teste, então ele é o dado mais recente. Não inverter achando que a resposta do teste é mais confiável. Limitação aceita: o plano é uma foto do momento da geração, e mudar a cidade depois não muda o plano (pendência 7 do Bloco 5) | Mateus |
| 26/11/2026 | O status de cada passo do mapa é calculado no backend a partir do progresso salvo, e qualquer status vindo da IA é descartado. O schema deixa de pedir `status` e passa a pedir `dataLimite`. A data de conclusão é gravada pelo servidor e nunca vem do navegador. Antecipado da unificação das semanas 10 e 11 | A IA não tem como saber o que o aluno fez: o `locked` dela impedia o aluno de marcar um passo feito, e o `done` mostrava como concluído o que ninguém marcou. Pedir um campo que vai ser descartado gasta token e convida a IA a inventar. Sem uma data comparável, um passo vencido ficaria pendente para sempre | Mateus |
| 26/11/2026 | Todo dado do sistema no navegador (chaves `pf_*`) fica em `sessionStorage`, não em `localStorage`. Sair e sessão expirada apagam tudo. Na primeira carga, o código apaga o que versões antigas deixaram em `localStorage`. Página que volta do cache do navegador (botão Voltar) sem sessão é trocada pela tela inicial. O progresso do mapa também fica em `sessionStorage`, mas só como cache: ver a decisão seguinte | Os alunos usam computadores compartilhados da escola. Nenhuma senha era gravada, mas o token, o perfil e os rascunhos com texto livre ficavam para o próximo aluno, e os rascunhos apareciam preenchidos na tela dele | Mateus |

## 10. Ideias fora de escopo

Lista de estacionamento. Nada aqui é trabalhado neste semestre. Revisão em dezembro para decidir o que entra no próximo.

- Árvore de agentes para o acompanhamento pós-teste.
- Tool use com base própria de instituições por cidade.
- Questionário com ramificação adaptativa.
- Perfil resumido persistido e reutilizável entre interações.
- Check-in que retoma o histórico do aluno.
- Fluxo de consentimento parental sob LGPD.

## 11. Riscos conhecidos

**O plano gratuito do Render hiberna.** O deploy está desligado desde 08/10/2026, e este risco volta com a reconexão no fim da Fase 0. A hibernação reinicia o processo e é a causa provável de job travado. A rotina de recuperação da Fase 1 trata o sintoma. A causa só sai com plano pago, o que está fora do orçamento.

**Sobreposição de instâncias no deploy.** Na inicialização, a recuperação de job travado reenfileira todo job em `processando` com heartbeat anterior ao início do processo, porque assume que o processo anterior morreu. Se a instância antiga ainda estiver atendendo durante um deploy, os jobs dela também são pegos e a geração é paga duas vezes. Hoje há uma instância só. Pendência da reconexão do deploy: conferir se o Render mantém as duas instâncias no ar durante a troca e, se mantiver, tratar isso antes de religar.

**Três pessoas em vez de cinco.** O cronograma já considera isso, mas não há folga real. Se a Fase 2 atrasar, a verificação de instituições da semana 12 é o primeiro item a ser cortado.

**A reestruturação do schema é a mudança mais arriscada do semestre.** Ela toca prompt, backend e quatro telas ao mesmo tempo. É por isso que ela vem depois dos testes e não antes.

**Uso de API pay-per-use durante os testes.** Doze perfis rodados três vezes ao longo do semestre consomem cota. Vale acompanhar o gasto desde a Fase 1 para não descobrir o limite em novembro.
