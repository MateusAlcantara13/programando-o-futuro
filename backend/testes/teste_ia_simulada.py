"""Verificações do modo IA_SIMULADA (backend/ia_simulada.py).

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O host é fixo e o .env não é usado para o banco: o script cria e APAGA o banco
teste_sim. O banco de desenvolvimento programando_futuro não é tocado.

O httpx.AsyncClient é substituído por uma classe que registra qualquer uso,
para provar que nenhuma chamada real sai com o modo ligado. ANTHROPIC_API_KEY
recebe um valor falso antes de importar main.py.

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_ia_simulada.py

Leva cerca de 2 minutos e meio: cada tipo de falha percorre as 3 tentativas
com as esperas reais entre elas (5 s e 15 s, mais 10 s em cada uma no 429).

Cobre: validação das variáveis; sucesso com o plano pronto de tamanho real;
os cinco tipos de falha caindo cada um no seu ramo, com tentativas = 3;
fila do semáforo; /api/vagas simulada; funcionamento sem ANTHROPIC_API_KEY.
"""
import asyncio, logging, os, sys, time, warnings

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

ROOT_PASSWORD = os.environ.get("TESTE_MYSQL_ROOT_PASSWORD")
if not ROOT_PASSWORD:
    sys.exit("Defina TESTE_MYSQL_ROOT_PASSWORD com a senha de root do MySQL local (docker-compose.yml).")

os.environ["ANTHROPIC_API_KEY"] = "chave-falsa-de-teste-0000"
for var in ("IA_SIMULADA", "IA_SIMULADA_ESPERA", "IA_SIMULADA_ESPERA_LISTA", "IA_SIMULADA_FALHA", "IA_SIMULADA_TIPO_FALHA"):
    os.environ.pop(var, None)

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=Warning, module="aiomysql")

import aiomysql, httpx
import main
import ia_simulada

logging.getLogger().setLevel(logging.ERROR)

BANCO = "teste_sim"
falhas = 0

def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1


usos_httpx = []
class ClienteProibido:
    def __init__(self, *a, **kw):
        usos_httpx.append(1)
        raise AssertionError("httpx.AsyncClient usado com IA_SIMULADA ligada")


def ligar(**kw):
    ia_simulada.config = ia_simulada.Config(ativa=True, **kw)


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
        await cur.execute("INSERT INTO jobs (id, usuario_id, status) VALUES (%s,%s,'processando')",
                          (job_id, f"u-{job_id}"))
    c.close()


def teste_config():
    print("\n== Cenário 0: leitura e validação das variáveis ==")
    checa(ia_simulada.carregar_config().ativa is False, "sem IA_SIMULADA: desligada")
    for valor in ("1", "sim", "True ", "yes"):
        os.environ["IA_SIMULADA"] = valor
        checa(ia_simulada.carregar_config().ativa is False, f"IA_SIMULADA='{valor}': desligada (só 'true' liga)")
    os.environ["IA_SIMULADA"] = "TRUE"
    cfg = ia_simulada.carregar_config()
    checa(cfg.ativa and cfg.espera_plano == (93.6, 100.8) and cfg.falha == 0.0 and cfg.tipo_falha == "529",
          f"IA_SIMULADA=TRUE: ligada com padrões {cfg.espera_plano}, falha {cfg.falha}, tipo {cfg.tipo_falha}")
    invalidos = [("IA_SIMULADA_ESPERA", "abc"), ("IA_SIMULADA_ESPERA", "10,5"), ("IA_SIMULADA_ESPERA", "-1,5"),
                 ("IA_SIMULADA_ESPERA_LISTA", "5"), ("IA_SIMULADA_FALHA", "1.5"), ("IA_SIMULADA_FALHA", "x"),
                 ("IA_SIMULADA_TIPO_FALHA", "500")]
    for var, valor in invalidos:
        os.environ[var] = valor
        try:
            ia_simulada.carregar_config()
            checa(False, f"{var}='{valor}' deveria ser recusado")
        except ia_simulada.ConfigInvalida as e:
            checa(var in str(e), f"{var}='{valor}' recusado com mensagem que cita a variável")
        os.environ.pop(var)
    os.environ.pop("IA_SIMULADA")


async def main_teste():
    teste_config()

    c = await conectar()
    async with c.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        await cur.execute(f"CREATE DATABASE {BANCO}")
    c.close()
    main.db_pool = await aiomysql.create_pool(host="127.0.0.1", port=3306, user="root",
                                              password=ROOT_PASSWORD, db=BANCO, autocommit=True)
    await main.criar_tabelas()
    httpx_original = httpx.AsyncClient
    httpx.AsyncClient = ClienteProibido

    try:
        print("\n== Cenário 1: sucesso devolve o plano pronto, com espera dentro da faixa ==")
        main.ia_semaphore = asyncio.Semaphore(5)
        ligar(espera_plano=(1.0, 1.5))
        await criar_job("ok")
        t0 = time.monotonic()
        plano = await main.chamar_ia("prompt", "ok")
        dur = time.monotonic() - t0
        checa(1.0 <= dur < 2.0, f"duração {dur:.2f}s dentro da faixa 1.0-1.5 s")
        checa(len(plano) == 18 and plano["perfilLabel"].startswith("[SIMULADO]"),
              f"plano com {len(plano)} chaves e perfilLabel '{plano['perfilLabel'][:30]}...'")
        checa("[SIMULADO]" in plano["mensagemPersonalizada"], "mensagemPersonalizada marcada com [SIMULADO]")
        checa((await estado("ok"))[0] == 1, "tentativas = 1")

        print("\n== Cenário 2: cada tipo de falha cai no seu ramo, com tentativas = 3 (≈2 min) ==")
        esperado = {
            "529": "sobrecarregado",
            "429": "Muitos usuários",
            "timeout": "não respondeu a tempo",
            "conexao": "Não foi possível conectar",
            "json": "não retornou um resultado válido",
        }
        for tipo, trecho in esperado.items():
            ligar(espera_plano=(0.1, 0.2), falha=1.0, tipo_falha=tipo)
            jid = f"falha-{tipo}"
            await criar_job(jid)
            try:
                await main.chamar_ia("prompt", jid)
                checa(False, f"{tipo}: deveria ter falhado")
            except RuntimeError as e:
                t = (await estado(jid))[0]
                checa(trecho in str(e) and t == 3, f"{tipo}: tentativas={t}, erro '{str(e)[:60]}'")

        print("\n== Cenário 3: semáforo em 1, segundo job espera na fila ==")
        main.ia_semaphore = asyncio.Semaphore(1)
        ligar(espera_plano=(2.0, 2.0))
        await criar_job("filaA")
        await criar_job("filaB")
        await asyncio.sleep(1.1)
        ta = asyncio.create_task(main.chamar_ia("prompt", "filaA"))
        await asyncio.sleep(0.3)
        tb = asyncio.create_task(main.chamar_ia("prompt", "filaB"))
        await asyncio.sleep(1.0)
        a, b = await estado("filaA"), await estado("filaB")
        checa(a[0] == 1 and b[0] == 0 and b[2] == b[1],
              f"durante a espera: A tentativas={a[0]}, B tentativas={b[0]} e atualizado_em == criado_em")
        await ta
        await tb
        b = await estado("filaB")
        checa(b[0] == 1 and b[2] > b[1], f"depois: B tentativas={b[0]}, atualizado_em {b[2]} > criado_em {b[1]}")

        print("\n== Cenário 4: /api/vagas (chamar_ia_lista) simulada ==")
        ligar(espera_lista=(0.1, 0.2))
        lista = await main.chamar_ia_lista("prompt")
        checa(isinstance(lista, list) and len(lista) == 6 and lista[0]["titulo"].startswith("[SIMULADO]"),
              f"lista com {len(lista)} itens marcados com [SIMULADO]")

        print("\n== Cenário 5: sem ANTHROPIC_API_KEY ==")
        chave = main.ANTHROPIC_API_KEY
        main.ANTHROPIC_API_KEY = ""
        try:
            ligar(espera_plano=(0.1, 0.1), espera_lista=(0.1, 0.1))
            p = await main.chamar_ia("prompt")
            l = await main.chamar_ia_lista("prompt")
            checa(len(p) == 18 and len(l) == 6, "com o modo ligado, plano e lista funcionam sem chave")
            ia_simulada.config = ia_simulada.Config()
            try:
                await main.chamar_ia("prompt")
                checa(False, "com o modo desligado e sem chave, deveria recusar")
            except RuntimeError as e:
                checa("Chave de API" in str(e), "com o modo desligado e sem chave, recusa como antes")
        finally:
            main.ANTHROPIC_API_KEY = chave

        checa(usos_httpx == [], f"httpx.AsyncClient usado {len(usos_httpx)} vez(es) com o modo ligado")
    finally:
        httpx.AsyncClient = httpx_original
        ia_simulada.config = ia_simulada.Config()
        main.db_pool.close()
        await main.db_pool.wait_closed()
        c = await conectar()
        async with c.cursor() as cur:
            await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        c.close()

    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main_teste())
