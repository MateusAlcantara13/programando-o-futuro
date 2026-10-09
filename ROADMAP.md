# Programando o Futuro — Plano do Segundo Semestre de 2026

Documento central da equipe. Toda decisão de escopo, ordem de execução e divisão de trabalho está aqui. Se algo não está neste documento, não está no escopo do semestre.

**Equipe:** Mateus Alcântara (responsável técnico), Yago Dias dos Santos, Ricardo Ongari Rodrigues.
**Orientador:** professor Caio Silva.
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
| Configuração de TLS do banco: verificação de hostname, CA configurável e modo local | Ricardo | Hostname do servidor é verificado, a CA vem de variável de ambiente, e a aplicação roda contra MySQL local sem alterar código |
| Remover a senha guardada no `localStorage` dos navegadores | Yago | Nenhuma página do site deixa o campo `senha` dentro de `pf_user` depois de carregar |
| Front chama a API pela origem da própria página, sem endereço fixo | Yago | Nenhum endereço de servidor escrito no front, e o mesmo código funciona no backend local e em produção |
| Documentar o ambiente local no repositório | Mateus | Ricardo sobe o sistema na própria máquina seguindo só o documento, sem perguntar nada a ninguém |
| Reconectar o deploy no Render | Mateus | Merge na `main` volta a publicar, com o banco de produção definido e todas as tarefas acima fechadas |

A senha `25107Senai` está no código-fonte público hoje. Ela precisa ser trocada, não apenas movida para variável de ambiente.

**Configuração de TLS do banco.** O `init_db` monta o contexto SSL com três problemas. Primeiro, `check_hostname=False` aceita qualquer certificado assinado pela CA, sem conferir o nome do servidor. Segundo, o caminho da CA está fixo no código, apontando para o `ca.pem` do Aiven, e o provedor do banco vai mudar. Terceiro, hoje não é possível rodar o backend contra um MySQL local sem alterar código. O aiomysql 0.2.0 avisa ao servidor que vai usar TLS sempre que recebe um contexto SSL (`aiomysql/connection.py:244-245`), e um servidor sem TLS recusa a conexão com `(1043, 'Bad handshake')`. Isso foi verificado em 08/10/2026 contra MySQL 8.0.46. Por isso o modo local passa a ser um requisito.

O que muda: uma variável `DB_SSL_MODE`, obrigatória, com dois valores. Em `verificar`, a CA é lida de `DB_SSL_CA`, o hostname é conferido e, depois de conectar, o código consulta `SHOW SESSION STATUS LIKE 'Ssl_cipher'` e recusa iniciar se o resultado vier vazio. Em `desligado`, o pool é criado sem contexto SSL e um aviso vai para o log. Esse modo serve só para MySQL local.

Hipótese não verificada: um atacante ativo no caminho entre o Render e o banco poderia retirar dos pacotes iniciais, que trafegam sem criptografia, o anúncio de TLS do servidor e o aviso de TLS do cliente, fazendo a conexão seguir em texto claro. A consulta a `Ssl_cipher` na inicialização serve de defesa barata contra essa possibilidade, mas não cobre as conexões abertas depois pelo pool.

Como verificar: (1) MySQL local sem TLS em modo `desligado`, a aplicação sobe e o aviso aparece no log; (2) o mesmo banco em modo `verificar`, a aplicação não sobe e explica o motivo; (3) banco com TLS e CA correta em modo `verificar`, a aplicação sobe; (4) CA errada, a aplicação não sobe; (5) certificado assinado pela CA certa, mas com outro nome de servidor, a aplicação não sobe.

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

**Reconexão do deploy.** Última tarefa da fase, só depois de todas as outras fechadas e do banco de produção resolvido. Antes de reconectar: confirmar no painel do Render que o serviço aponta para `MateusAlcantara13/programando-o-futuro`; cadastrar as variáveis de ambiente de produção, já sem nenhum valor padrão no código; usar `DB_SSL_MODE=verificar` com a CA do provedor novo; e confirmar que a `ADMIN_SECRET` foi trocada. Depois de reconectar, o `CLAUDE.md` volta a dizer que merge na `main` publica em produção.

### Fase 1 — Confiabilidade (semanas 2 a 4, 07/09 a 27/09)

Aqui começa o trabalho paralelo. Cada um na sua área.

**Mateus, fila e concorrência**
Semáforo limitando chamadas simultâneas à API, com o limite como variável de ambiente para permitir ajuste sem novo deploy. Colunas `tentativas` e `atualizado_em` na tabela `jobs`. Rotina de inicialização que identifica job travado em `processando` e reenfileira. Reprocessamento automático substituindo o botão manual do admin. Cliente HTTP único no ciclo de vida da aplicação em vez de um por chamada. Tratamento de resposta truncada por limite de tokens, que hoje cai no retry sem diagnóstico.

**Ricardo, correção de dados**
Correção do tipo de `mapa_progresso.usuario_id`, hoje `INT` recebendo UUID, com verificação de quantos registros foram perdidos. Chave estrangeira e índice na tabela. Índice em `jobs` por usuário e data. Migração da coluna `modulos_concluidos` se aparecer inconsistência.

**Yago, medição**
Reescrita do `teste_carga.py` para rodar com número de usuários parametrizável e produzir relatório com taxa de sucesso, latência média e distribuição de erros. Execução com 15, 31 e 50 usuários, com os números registrados. Montagem do conjunto de doze perfis fixos de teste e da rubrica de qualidade descrita na seção 8. Geração da linha de base de qualidade usando o sistema como está hoje.

A linha de base precisa sair antes de qualquer mudança no prompt. Sem ela, não há comparação possível em dezembro.

**Marco da semana 4:** cinquenta usuários simultâneos com falha abaixo de cinco por cento, e doze planos de linha de base arquivados.

### Fase 2 — Estrutura (semanas 5 a 8, 28/09 a 25/10)

**Semana 5 é congelamento de backend.** Mateus quebra o `main.py` em módulos separando rotas de autenticação, rotas do teste inicial, rotas dos módulos, camada de banco, camada de IA e dados das perguntas. Ninguém mais abre pull request no backend nessa semana. Revisão conjunta antes do merge.

Depois do congelamento, nas semanas 6 a 8:

**Ricardo** escreve testes de autenticação e banco com pytest, cobrindo cadastro, login, token expirado e salvamento de resposta.
**Mateus** escreve testes do ciclo de vida do job, com a chamada à API simulada, cobrindo sucesso, erro, retry e recuperação de job travado.
**Yago** configura GitHub Actions rodando os testes a cada pull request, e revisa o front em celular de baixo custo, medindo tempo até a primeira tela útil.

**Marco da semana 8:** nenhum arquivo de backend acima de trezentas linhas, testes rodando automaticamente em cada pull request, `main` com histórico limpo.

### Fase 3 — Qualidade da saída (semanas 9 a 12, 26/10 a 22/11)

Esta é a fase que ataca o problema do roadmap fraco. Ordem importa, porque cada item depende do anterior.

**Semana 9, correções baratas.** Mateus passa a cidade do usuário e a data corrente para o prompt. Os dois campos existem no sistema e nenhum chega ao modelo hoje. Yago roda os doze perfis novamente e compara com a linha de base. Essa comparação isolada tem valor de defesa na banca, porque mostra ganho medido a partir de mudança mínima.

**Semanas 10 e 11, reestruturação da saída.** Mateus unifica `caminhos`, `proximosPassos` e `mapaCarreira` em uma estrutura única de plano, com etapas ordenadas, cada passo com prazo relativo e critério de conclusão verificável. O campo `status` sai do JSON gerado pela IA e passa a ser calculado pelo backend a partir do progresso salvo. Cardinalidade definida em todos os arrays. Separação em duas chamadas, uma para diagnóstico e outra para o plano, com o diagnóstico servindo de entrada para a segunda.

**O schema congela no fim da semana 10.** Yago só começa a adaptar as telas depois disso. Adaptar antes significa refazer.

**Semana 11, front.** Yago reescreve `resultado.html`, `mapa_carreira.html` e a visualização do plano consumindo a estrutura nova, eliminando a repetição de conteúdo entre páginas.

**Semana 12, verificação.** Ricardo constrói a checagem determinística dos nomes de instituição e curso contra base pública do INEP ou do MEC, marcando o que não corresponde a registro real. Isso é código comum, não chamada de IA.

**Marco da semana 12:** rubrica aplicada aos doze perfis com resultado documentado lado a lado com a linha de base de setembro.

### Fase 4 — Fechamento (semanas 13 a 15, 23/11 a 13/12)

Nova rodada de teste de carga com os números finais. Atualização do README com a arquitetura real, hoje desatualizada e ainda marcando o projeto como finalizado. Documentação das decisões técnicas do semestre a partir do registro da seção 9. Preparação da apresentação com três gráficos: carga antes e depois, qualidade antes e depois, e tempo médio de geração antes e depois.

Data da banca a confirmar com o professor Caio. A semana 15 fica reservada para folga de cronograma, porque alguma fase vai atrasar.

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

**Três pessoas em vez de cinco.** O cronograma já considera isso, mas não há folga real. Se a Fase 2 atrasar, a verificação de instituições da semana 12 é o primeiro item a ser cortado.

**A reestruturação do schema é a mudança mais arriscada do semestre.** Ela toca prompt, backend e quatro telas ao mesmo tempo. É por isso que ela vem depois dos testes e não antes.

**Uso de API pay-per-use durante os testes.** Doze perfis rodados três vezes ao longo do semestre consomem cota. Vale acompanhar o gasto desde a Fase 1 para não descobrir o limite em novembro.
