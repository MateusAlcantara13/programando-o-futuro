"""Verificações da recuperação de job travado (recuperar_jobs_orfaos e recuperar_jobs_travados).

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O host é fixo e o .env não é usado para o banco: o script cria e APAGA o banco
teste_rec. O banco de desenvolvimento programando_futuro não é tocado.

A geração em si não roda: processar_resultado_ia_db é substituída por uma
função que só registra quem foi reenfileirado. Nenhuma chamada à IA acontece.

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_recuperacao_jobs.py

Leva poucos segundos. Os heartbeats velhos são gravados direto no banco com
NOW() - INTERVAL, sem esperar o tempo passar.

Cobre: na inicialização, todo job em processando é reenfileirado, qualquer
que seja tentativas, e concluido/erro não são tocados; na varredura, job na
fila (tentativas = 0) não é tocado mesmo com heartbeat velho, job vivo
(heartbeat recente) não é tocado, job travado é reenfileirado, volta para
tentativas = 0 e soma 1 em recuperacoes; reenfileirado não é pego de novo na
rodada seguinte; job no teto de recuperações é encerrado como erro com
mensagem, na varredura e na inicialização, e não é tocado se estiver na
fila; duas varreduras simultâneas disparam cada job uma vez só.
"""
import asyncio, logging, os, sys, warnings

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

ROOT_PASSWORD = os.environ.get("TESTE_MYSQL_ROOT_PASSWORD")
if not ROOT_PASSWORD:
    sys.exit("Defina TESTE_MYSQL_ROOT_PASSWORD com a senha de root do MySQL local (docker-compose.yml).")

os.environ["ANTHROPIC_API_KEY"] = "chave-falsa-de-teste-0000"
os.environ["AMBIENTE"] = "local"
os.environ["JWT_SECRET"] = "segredo-falso-de-teste"
os.environ["ADMIN_SECRET"] = "admin-falso-de-teste"
for var in ("IA_SIMULADA", "IA_MAX_RECUPERACOES"):
    os.environ.pop(var, None)

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=Warning, module="aiomysql")

import aiomysql
import main

logging.getLogger().setLevel(logging.CRITICAL)

BANCO = "teste_rec"
VELHO = main.LIMITE_JOB_TRAVADO_S + 600   # segundos: bem além do limite
TETO = main.IA_MAX_RECUPERACOES
falhas = 0

def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1


disparos = []
async def processar_falso(job_id, uid, usuario, origem="Job"):
    disparos.append((job_id, origem))


async def conectar(db=None):
    return await aiomysql.connect(host="127.0.0.1", port=3306, user="root",
                                  password=ROOT_PASSWORD, db=db, autocommit=True)

async def criar_job(job_id, status, tentativas, idade_heartbeat_s, recuperacoes=0):
    c = await conectar(BANCO)
    async with c.cursor() as cur:
        await cur.execute("INSERT INTO usuarios (id, nome, email, senha, aceite_lgpd) VALUES (%s,%s,%s,'x',FALSE)",
                          (f"u-{job_id}", job_id, f"{job_id}@teste.local"))
        await cur.execute(
            "INSERT INTO jobs (id, usuario_id, status, tentativas, recuperacoes, criado_em, atualizado_em) "
            "VALUES (%s, %s, %s, %s, %s, NOW() - INTERVAL %s SECOND, NOW() - INTERVAL %s SECOND)",
            (job_id, f"u-{job_id}", status, tentativas, recuperacoes, idade_heartbeat_s, idade_heartbeat_s),
        )
    c.close()

async def estado(job_id):
    """(status, tentativas, recuperacoes, segundos desde o heartbeat, erro)"""
    c = await conectar(BANCO)
    async with c.cursor() as cur:
        await cur.execute(
            "SELECT status, tentativas, recuperacoes, TIMESTAMPDIFF(SECOND, atualizado_em, NOW()), erro "
            "FROM jobs WHERE id=%s",
            (job_id,),
        )
        r = await cur.fetchone()
    c.close()
    return r

async def limpar_jobs():
    c = await conectar(BANCO)
    async with c.cursor() as cur:
        await cur.execute("DELETE FROM usuarios")  # apaga os jobs junto (ON DELETE CASCADE)
    c.close()
    disparos.clear()

async def esperar_tarefas():
    await asyncio.sleep(0.2)


async def main_teste():
    c = await conectar()
    async with c.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        await cur.execute(f"CREATE DATABASE {BANCO}")
    c.close()

    main.db_pool = await aiomysql.create_pool(host="127.0.0.1", port=3306, user="root",
                                              password=ROOT_PASSWORD, db=BANCO, autocommit=True)
    await main.criar_tabelas()
    processar_original = main.processar_resultado_ia_db
    main.processar_resultado_ia_db = processar_falso

    try:
        print(f"\n(limite de job travado: {main.LIMITE_JOB_TRAVADO_S} s, teto de recuperações: {TETO})")

        # ── Cenário A: inicialização ──────────────────────────────────────────
        print("\n== Cenário A: inicialização reenfileira todo job em processando ==")
        await criar_job("orfao_fila", "processando", 0, VELHO)
        await criar_job("orfao_travado", "processando", 2, VELHO)
        await criar_job("orfao_recente", "processando", 1, 10)
        await criar_job("pronto", "concluido", 1, VELHO)
        await criar_job("falhou", "erro", 3, VELHO)
        r = await main.recuperar_jobs_orfaos()
        await esperar_tarefas()
        ids = sorted(j for j, _ in disparos)
        checa(r["reenfileirado"] == 3 and r["encerrado"] == 0, f"resultado: {r}")
        checa(ids == ["orfao_fila", "orfao_recente", "orfao_travado"], f"disparados: {ids}")
        for j in ("orfao_fila", "orfao_travado", "orfao_recente"):
            st, t, rec, idade, _ = await estado(j)
            checa(st == "processando" and t == 0 and rec == 1 and idade <= 2,
                  f"{j}: status={st}, tentativas={t}, recuperacoes={rec}, heartbeat há {idade}s")
        checa((await estado("pronto"))[:3] == ("concluido", 1, 0), "concluido não foi tocado")
        checa((await estado("falhou"))[:3] == ("erro", 3, 0), "erro não foi tocado")
        await limpar_jobs()

        # ── Cenário B: varredura periódica ────────────────────────────────────
        print("\n== Cenário B: varredura só pega tentativas > 0 com heartbeat velho ==")
        await criar_job("na_fila", "processando", 0, VELHO)
        await criar_job("travado", "processando", 2, VELHO)
        await criar_job("vivo", "processando", 1, 10)
        await criar_job("pronto", "concluido", 1, VELHO)
        r = await main.recuperar_jobs_travados()
        await esperar_tarefas()
        checa(r["reenfileirado"] == 1 and [j for j, _ in disparos] == ["travado"], f"resultado {r}, disparados {disparos}")
        st, t, rec, idade_fila, _ = await estado("na_fila")
        checa((st, t, rec) == ("processando", 0, 0) and idade_fila >= VELHO - 2,
              f"job na fila não foi tocado (heartbeat continua velho, {idade_fila}s)")
        checa((await estado("vivo"))[1] == 1, "job vivo não foi tocado")
        st, t, rec, idade, _ = await estado("travado")
        checa(st == "processando" and t == 0 and rec == 1 and idade <= 2,
              f"travado voltou para a fila: tentativas={t}, recuperacoes={rec}, heartbeat há {idade}s")

        print("\n== Cenário B2: reenfileirado não é pego de novo ==")
        disparos.clear()
        r = await main.recuperar_jobs_travados()
        await esperar_tarefas()
        checa(r["reenfileirado"] == 0 and r["encerrado"] == 0 and disparos == [], f"segunda rodada: {r}")
        await limpar_jobs()

        # ── Cenário C: teto de recuperações ───────────────────────────────────
        print("\n== Cenário C: job no teto é encerrado como erro, não reenfileirado ==")
        await criar_job("no_teto", "processando", 2, VELHO, recuperacoes=TETO)
        await criar_job("abaixo", "processando", 2, VELHO, recuperacoes=TETO - 1)
        await criar_job("teto_na_fila", "processando", 0, VELHO, recuperacoes=TETO)
        r = await main.recuperar_jobs_travados()
        await esperar_tarefas()
        checa(r == {"reenfileirado": 1, "encerrado": 1, "nada": 0}, f"resultado: {r}")
        checa([j for j, _ in disparos] == ["abaixo"], f"disparados: {disparos}")
        st, t, rec, _, erro = await estado("no_teto")
        checa(st == "erro" and rec == TETO, f"no_teto: status={st}, recuperacoes={rec}")
        checa(f"recuperado {TETO} vez(es) sem concluir" in (erro or ""), f"mensagem no painel: {(erro or '').strip()}")
        checa("no_teto" in (erro or ""), "mensagem cita o id do job para busca no log")
        st, t, rec, _, _ = await estado("abaixo")
        checa(st == "processando" and rec == TETO, f"abaixo do teto foi reenfileirado e chegou a {rec}")
        checa((await estado("teto_na_fila"))[:3] == ("processando", 0, TETO), "job no teto mas na fila não foi tocado")

        print("\n== Cenário C2: encerrado sai da varredura ==")
        disparos.clear()
        r = await main.recuperar_jobs_travados()
        checa(r["encerrado"] == 0 and r["reenfileirado"] == 0, f"rodada seguinte: {r}")
        await limpar_jobs()

        print("\n== Cenário C3: na inicialização, órfão no teto também é encerrado ==")
        await criar_job("derruba_processo", "processando", 1, VELHO, recuperacoes=TETO)
        r = await main.recuperar_jobs_orfaos()
        await esperar_tarefas()
        st, _, rec, _, erro = await estado("derruba_processo")
        checa(r["encerrado"] == 1 and disparos == [] and st == "erro",
              f"resultado {r}, status={st}, recuperacoes={rec}")
        await limpar_jobs()

        # ── Cenário D: concorrência ───────────────────────────────────────────
        print("\n== Cenário D: duas varreduras ao mesmo tempo disparam cada job uma vez ==")
        await criar_job("t1", "processando", 1, VELHO)
        await criar_job("t2", "processando", 3, VELHO)
        r1, r2 = await asyncio.gather(main.recuperar_jobs_travados(), main.recuperar_jobs_travados())
        await esperar_tarefas()
        ids = sorted(j for j, _ in disparos)
        checa(r1["reenfileirado"] + r2["reenfileirado"] == 2, f"reenfileirados no total: {r1}, {r2}")
        checa(ids == ["t1", "t2"], f"cada job disparado uma vez: {ids}")
        checa([(await estado(j))[2] for j in ("t1", "t2")] == [1, 1], "recuperacoes somou 1, não 2")
        await limpar_jobs()
    finally:
        main.processar_resultado_ia_db = processar_original
        main.db_pool.close()
        await main.db_pool.wait_closed()
        c = await conectar()
        async with c.cursor() as cur:
            await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        c.close()

    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main_teste())
