# Programando o Futuro

Plataforma web que gera planos de carreira personalizados para estudantes de escola pública usando a API do Claude. Projeto de extensão do Centro Universitário SENAI-SP. Validado em campo na escola parceira em maio de 2026, com 31 alunos.

O sistema está fora do ar, mas os dados reais de alunos, incluindo menores de idade, continuam no banco de produção. O mesmo cuidado se aplica a toda alteração.

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

O deploy está desligado desde 08/10/2026. A branch `main` não publica nada. A validação de cada PR acontece no ambiente local com Docker. O deploy no Render volta só quando a Fase 0 estiver fechada e o banco de produção resolvido, conforme a última tarefa da Fase 0 no `ROADMAP.md`.

## Segredos

Nunca commite o arquivo `.env`. Confira o `.gitignore` antes de qualquer commit que toque em configuração.

Nunca imprima o conteúdo de variáveis de ambiente, chave de API ou credencial de banco em resposta, log ou mensagem de erro.

Nunca escreva valor padrão de segredo no código. Se uma variável de ambiente obrigatória estiver ausente, a aplicação deve recusar iniciar com mensagem clara.

## Stack

Back-end: Python com FastAPI e Uvicorn, acesso ao banco com aiomysql sobre SSL.
Front-end: HTML, CSS e JavaScript puro, sem framework.
Banco: MySQL no Aiven.
IA: API do Claude chamada direto via httpx.
Hospedagem: Render, plano gratuito. Desligado desde 08/10/2026, volta no fim da Fase 0.

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

- A cidade do aluno existe na tabela `usuarios` mas nunca é passada para o prompt.
- A data corrente também não é passada, então o modelo não ancora prazos no calendário de ENEM, SISU e ProUni.
- O schema pede três estruturas concorrentes para a mesma informação: `caminhos[].passos`, `proximosPassos` e `mapaCarreira`.
- O campo `status` do `mapaCarreira` é gerado pela IA, que não tem como saber o que o aluno já fez.
- Nenhum passo tem critério de conclusão verificável e nenhum array tem cardinalidade definida.

## Equipe e áreas

Três pessoas no segundo semestre de 2026. Não altere arquivo fora da minha área sem me avisar que vai precisar.

Mateus Alcantara, responsável técnico: camada de IA, prompt, schema, fila e ciclo de vida dos jobs, arquitetura.
Ricardo Ongari Rodrigues: autenticação, segurança, esquema e migrações de banco, rotas administrativas.
Yago Dias dos Santos: páginas, JavaScript, estilos, painel administrativo no front, teste de carga, rubrica de qualidade.

Orientador: professor Caio Silva.

## Fora de escopo neste semestre

Se eu pedir algo nesta lista, lembre que foi decidido contra e pergunte se eu quero mesmo reabrir.

- Árvore de agentes, orquestração multi-etapas, tool use ou skills na geração do plano. Avaliado e recusado em agosto de 2026: multiplica chamadas por aluno e piora o gargalo de concorrência, que é o problema central.
- Trabalho de mercado, venda institucional, edital ou modelo de negócio.
- Funcionalidade nova de produto fora do roadmap em `ROADMAP.md`.
- Fluxo de consentimento parental sob LGPD, que é pré-requisito de venda e não de funcionamento.

## Decisões registradas

Verificação de nomes de instituição será feita por código consultando base pública, não por IA. Motivo: reprodutível, sem custo de token, mais confiável.

A geração do plano será separada em duas chamadas, uma de diagnóstico e outra de plano. Motivo: hoje o plano de ação disputa orçamento de tokens com nove outras seções e fica raso.
