"""Verificações do Bloco 5 (qualidade do plano) que precisam de banco.

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O host é fixo e o .env não é usado para o banco: o script cria e APAGA o banco
teste_plano. O banco de desenvolvimento programando_futuro não é tocado.

A IA não é chamada: chamar_ia é substituída por uma função que devolve um
plano pronto, com status inventado de propósito.

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_plano_db.py

Cobre: geração grava jobs.data_referencia e o plano sem status; POST do
progresso grava a data de conclusão do servidor e mantém a data numa
segunda gravação; /api/perfil, /api/mapa e /api/resultado devolvem o status
calculado (concluído com data, pendente, vencido) e não o da IA.
"""
import asyncio, json, logging, os, sys, warnings
from datetime import date

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

ROOT_PASSWORD = os.environ.get("TESTE_MYSQL_ROOT_PASSWORD")
if not ROOT_PASSWORD:
    sys.exit("Defina TESTE_MYSQL_ROOT_PASSWORD com a senha de root do MySQL local (docker-compose.yml).")

os.environ.update({
    "ANTHROPIC_API_KEY": "chave-falsa-de-teste-0000",
    "AMBIENTE": "local",
    "JWT_SECRET": "segredo-falso-de-teste",
    "ADMIN_SECRET": "admin-falso-de-teste",
})
for var in ("IA_SIMULADA", "CORS_ORIGENS"):
    os.environ.pop(var, None)

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=Warning, module="aiomysql")

import aiomysql
import main

logging.getLogger().setLevel(logging.ERROR)

BANCO = "teste_plano"
HOJE = date(2026, 11, 26)
falhas = 0
def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1

PLANO_DA_IA = {
    "areaPrincipal": "TI",
    "mapaCarreira": [
        {"id": "enem", "titulo": "Fazer o ENEM", "status": "done", "dataLimite": "2026-11-09"},
        {"id": "sisu", "titulo": "Inscrição no SISU", "status": "locked", "dataLimite": "2027-01-20"},
        {"id": "curso", "titulo": "Curso livre", "status": "active", "dataLimite": None},
    ],
}

async def ia_falsa(prompt, job_id=None):
    return json.loads(json.dumps(PLANO_DA_IA))

async def conectar(db=None):
    return await aiomysql.connect(host="127.0.0.1", port=3306, user="root",
                                  password=ROOT_PASSWORD, db=db, autocommit=True)

async def consulta(sql, params=()):
    c = await conectar(BANCO)
    async with c.cursor() as cur:
        await cur.execute(sql, params)
        r = await cur.fetchall()
    c.close()
    return r

async def main_teste():
    c = await conectar()
    async with c.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        await cur.execute(f"CREATE DATABASE {BANCO}")
    c.close()
    main.db_pool = await aiomysql.create_pool(host="127.0.0.1", port=3306, user="root",
                                              password=ROOT_PASSWORD, db=BANCO, autocommit=True)
    await main.criar_tabelas()
    chamar_original, hoje_original = main.chamar_ia, main.hoje_brasilia
    main.chamar_ia = ia_falsa
    main.hoje_brasilia = lambda agora_utc=None: HOJE
    try:
        uid = "u-plano"
        async with main.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO usuarios (id, nome, email, senha, aceite_lgpd) VALUES (%s,'Aluna','a@x','x',TRUE)", (uid,))
                await cur.execute("INSERT INTO jobs (id, usuario_id, status) VALUES ('job-p', %s, 'processando')", (uid,))
        usuario = {"id": uid, "nome": "Aluna", "cidade": "Poá - SP"}

        print("\n== 1. Geração grava a data de referência e o plano sem status ==")
        await main.processar_resultado_ia_db("job-p", uid, usuario, "Teste")
        (status, ref), = await consulta("SELECT status, data_referencia FROM jobs WHERE id='job-p'")
        checa(status == "concluido" and ref == HOJE, f"job: status={status}, data_referencia={ref}")
        (dados,), = await consulta("SELECT dados FROM perfis WHERE usuario_id=%s", (uid,))
        passos = json.loads(dados)["mapaCarreira"]
        checa(all("status" not in p for p in passos), "plano gravado sem o status da IA")

        print("\n== 2. POST do progresso grava a data do servidor ==")
        await main.save_mapa_progresso({"etapasConcluidas": {"enem": "1999-01-01T00:00:00Z"}, "checksFeitos": {}}, usuario)
        (bruto,), = await consulta("SELECT etapas_concluidas FROM mapa_progresso WHERE usuario_id=%s", (uid,))
        primeira = json.loads(bruto)["enem"]
        checa(isinstance(primeira, str) and not primeira.startswith("1999"), f"data do servidor, não a do navegador: {primeira}")
        await asyncio.sleep(1.1)
        await main.save_mapa_progresso({"etapasConcluidas": {"enem": True, "curso": True}, "checksFeitos": {}}, usuario)
        (bruto,), = await consulta("SELECT etapas_concluidas FROM mapa_progresso WHERE usuario_id=%s", (uid,))
        segunda = json.loads(bruto)
        checa(segunda["enem"] == primeira, "segunda gravação mantém a data da primeira")
        checa(isinstance(segunda["curso"], str) and segunda["curso"] != primeira, "etapa nova recebe data nova")

        print("\n== 3. Rotas devolvem o status calculado ==")
        await main.save_mapa_progresso({"etapasConcluidas": {"enem": True}, "checksFeitos": {}}, usuario)
        for nome, rota in (("/api/perfil", main.get_perfil), ("/api/resultado", main.get_resultado)):
            r = await rota(usuario)
            s = {p["id"]: p for p in r["mapaCarreira"]}
            checa(s["enem"]["status"] == "concluido" and s["enem"]["concluidoEm"] == primeira, f"{nome}: concluído com a data do banco")
            checa(s["sisu"]["status"] == "pendente", f"{nome}: SISU pendente (IA dizia locked)")
            checa(s["curso"]["status"] == "pendente", f"{nome}: curso desmarcado volta a pendente (IA dizia active)")
        await main.save_mapa_progresso({"etapasConcluidas": {}, "checksFeitos": {}}, usuario)
        steps = {p["id"]: p for p in (await main.get_mapa(usuario))["steps"]}
        checa(steps["enem"]["status"] == "vencido" and steps["enem"]["prazoVencido"], "/api/mapa: ENEM desmarcado com prazo passado = vencido")
    finally:
        main.chamar_ia, main.hoje_brasilia = chamar_original, hoje_original
        main.db_pool.close()
        await main.db_pool.wait_closed()
        c = await conectar()
        async with c.cursor() as cur:
            await cur.execute(f"DROP DATABASE IF EXISTS {BANCO}")
        c.close()

    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main_teste())
