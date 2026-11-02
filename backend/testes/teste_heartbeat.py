"""Verificações do heartbeat de jobs (tentativas e atualizado_em) em chamar_ia.

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O host é fixo e o .env não é usado para o banco: o script cria e APAGA o banco
teste_hb. O banco de desenvolvimento programando_futuro não é tocado.

A API do Claude é simulada (httpx.AsyncClient substituído). Nenhuma chamada
real sai da máquina, e ANTHROPIC_API_KEY recebe um valor falso antes de
importar main.py.

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_heartbeat.py

Leva uns 25 s: o cenário de falha usa as esperas reais entre tentativas
(5 s e 15 s), que também garantem que atualizado_em, com precisão de
segundo, mude visivelmente entre uma tentativa e outra.

Cobre: job na fila do semáforo não é tocado; heartbeat só na tentativa real;
retentativas incrementam e atualizam; falha do banco no heartbeat não derruba
a chamada; chamada sem job_id não grava nada.
"""
import asyncio, logging, os, sys, warnings

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

ROOT_PASSWORD = os.environ.get("TESTE_MYSQL_ROOT_PASSWORD")
if not ROOT_PASSWORD:
    sys.exit("Defina TESTE_MYSQL_ROOT_PASSWORD com a senha de root do MySQL local (docker-compose.yml).")

# Antes de importar main: load_dotenv não sobrescreve variável já definida,
# então a chave real do .env nunca é carregada neste processo.
os.environ["ANTHROPIC_API_KEY"] = "chave-falsa-de-teste-0000"

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=Warning, module="aiomysql")

import aiomysql, httpx
import main

logging.getLogger().setLevel(logging.WARNING)  # só avisos do main durante o teste

BANCO = "teste_hb"
falhas = 0

def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc)
    if not cond:
        falhas += 1


# ── API simulada ──────────────────────────────────────────────────────────────
class RespostaFalsa:
    status_code = 200
    text = ""
    def json(self):
        return {"content": [{"text": '{"ok": true}'}]}

# prompt -> função async chamada em cada post
comportamentos = {}

class ClienteFalso:
    def __init__(self, *a, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def post(self, url, headers=None, json=None):
        prompt = json["messages"][0]["content"]
        return await comportamentos[prompt]()


# ── Banco ─────────────────────────────────────────────────────────────────────
async def conectar(db=None):
    return await aiomysql.connect(host="127.0.0.1", port=3306, user="root",
                                  password=ROOT_PASSWORD, db=db, autocommit=True)

async def estado(job_id):
    c = await conectar(BANCO)
    async with c.cursor() as cur:
        await cur.execute("SELECT tentativas, criado_em, atualizado_em FROM jobs WHERE id=%s", (job_id,))
        r = await cur.fetchone()
    c.close()
    return r

async def criar_job(job_id):
    c = await conectar(BANCO)
    async with c.cursor() as cur:
        await cur.execute("INSERT INTO usuarios (id, nome, email, senha) VALUES (%s,%s,%s,'x')",
                          (f"u-{job_id}", job_id, f"{job_id}@teste.local"))
        # Mesmo INSERT da aplicação (main.py, iniciar geração).
        await cur.execute("INSERT INTO jobs (id, usuario_id, status) VALUES (%s,%s,'processando')",
                          (job_id, f"u-{job_id}"))
    c.close()


async def main_teste():
    c = await conectar()
    async with c.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        await cur.execute(f"CREATE DATABASE {BANCO}")
    c.close()

    main.db_pool = await aiomysql.create_pool(host="127.0.0.1", port=3306, user="root",
                                              password=ROOT_PASSWORD, db=BANCO, autocommit=True)
    await main.criar_tabelas()
    httpx_original = httpx.AsyncClient
    httpx.AsyncClient = ClienteFalso
    main.ia_semaphore = asyncio.Semaphore(1)

    try:
        # ── Cenário 1: dois jobs, semáforo em 1 ───────────────────────────────
        print("\n== Cenário 1: semáforo em 1, segundo job esperando na fila ==")
        await criar_job("jobA")
        await criar_job("jobB")
        await asyncio.sleep(1.2)  # garante que NOW() da 1ª tentativa difira de criado_em

        libera_a = asyncio.Event()
        a_em_curso = asyncio.Event()
        async def comportamento_a():
            a_em_curso.set()
            await libera_a.wait()
            return RespostaFalsa()
        async def comportamento_b():
            return RespostaFalsa()
        comportamentos["prompt A"] = comportamento_a
        comportamentos["prompt B"] = comportamento_b

        tarefa_a = asyncio.create_task(main.chamar_ia("prompt A", "jobA"))
        await a_em_curso.wait()
        tarefa_b = asyncio.create_task(main.chamar_ia("prompt B", "jobB"))
        await asyncio.sleep(1.2)  # B fica um tempo parado no semáforo

        tA, cA, uA = await estado("jobA")
        tB, cB, uB = await estado("jobB")
        checa(tA == 1 and uA > cA, f"A em tentativa: tentativas={tA}, atualizado_em {uA} > criado_em {cA}")
        checa(tB == 0, f"B na fila: tentativas={tB}")
        checa(uB == cB, f"B na fila: atualizado_em == criado_em ({uB})")

        libera_a.set()
        await tarefa_a
        await tarefa_b
        tB, cB, uB2 = await estado("jobB")
        checa(tB == 1, f"B depois de ganhar vaga: tentativas={tB}")
        checa(uB2 > cB, f"B depois de ganhar vaga: atualizado_em {uB2} > criado_em {cB}")

        # ── Cenário 2: falha em todas as tentativas ───────────────────────────
        print("\n== Cenário 2: falha forçada nas 3 tentativas (≈20 s de espera real) ==")
        await criar_job("jobC")
        await asyncio.sleep(1.2)
        vistos = []
        async def comportamento_c():
            vistos.append(await estado("jobC"))  # heartbeat já gravado antes do post
            raise httpx.ConnectError("simulado")
        comportamentos["prompt C"] = comportamento_c
        try:
            await main.chamar_ia("prompt C", "jobC")
            checa(False, "chamar_ia deveria ter levantado erro após 3 tentativas")
        except RuntimeError:
            checa(True, "chamar_ia levantou RuntimeError após esgotar as tentativas")
        checa([v[0] for v in vistos] == [1, 2, 3], f"tentativas vistas a cada post: {[v[0] for v in vistos]}")
        hb = [v[2] for v in vistos]
        criado_c = vistos[0][1]
        checa(hb[0] > criado_c and hb[0] < hb[1] < hb[2],
              f"atualizado_em muda a cada tentativa: {[str(h) for h in hb]}")
        tC, _, uC = await estado("jobC")
        checa(tC == 3 and uC == hb[2], f"estado final: tentativas={tC}, atualizado_em = o da 3ª tentativa")

        # ── Cenário 3: banco falha no heartbeat ───────────────────────────────
        print("\n== Cenário 3: erro do banco no heartbeat não derruba a chamada ==")
        class PoolQuebrado:
            def acquire(self):
                raise ConnectionError("banco fora (simulado)")
        pool_real = main.db_pool
        main.db_pool = PoolQuebrado()
        comportamentos["prompt D"] = comportamento_b
        try:
            r = await main.chamar_ia("prompt D", "jobD")
            checa(r == {"ok": True}, "chamada concluiu e devolveu o resultado mesmo sem heartbeat")
        except Exception as e:
            checa(False, f"chamada caiu por causa do heartbeat: {type(e).__name__}: {e}")

        print("\n== Cenário 3b: banco travado no heartbeat respeita o limite de tempo ==")
        class PoolTravado:
            def acquire(self):
                class Ctx:
                    async def __aenter__(self_):
                        await asyncio.sleep(3600)
                    async def __aexit__(self_, *a): return False
                return Ctx()
        main.db_pool = PoolTravado()
        timeout_original = main.HEARTBEAT_TIMEOUT_S
        main.HEARTBEAT_TIMEOUT_S = 0.5
        try:
            r = await asyncio.wait_for(main.chamar_ia("prompt D", "jobD"), timeout=5)
            checa(r == {"ok": True}, "chamada concluiu depois do timeout do heartbeat")
        except Exception as e:
            checa(False, f"chamada não concluiu: {type(e).__name__}: {e}")
        finally:
            main.HEARTBEAT_TIMEOUT_S = timeout_original

        # ── Cenário 4: sem job_id ─────────────────────────────────────────────
        print("\n== Cenário 4: chamar_ia sem job_id não toca no banco ==")
        acessos = []
        class PoolEspiao:
            def acquire(self):
                acessos.append(1)
                raise AssertionError("não deveria acessar o banco")
        main.db_pool = PoolEspiao()
        r = await main.chamar_ia("prompt D")
        checa(r == {"ok": True} and acessos == [], f"resultado ok e acessos ao banco = {len(acessos)}")
        main.db_pool = pool_real
    finally:
        httpx.AsyncClient = httpx_original
        if hasattr(main.db_pool, "close"):
            main.db_pool.close()
            await main.db_pool.wait_closed()
        c = await conectar()
        async with c.cursor() as cur:
            await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        c.close()

    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main_teste())
