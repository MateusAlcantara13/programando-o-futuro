"""Verificações da migração migracoes/jobs_heartbeat.py.

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O host é fixo de propósito e o .env é ignorado: o script cria e APAGA bancos
chamados teste_mig_a..d, então nunca pode apontar para o Aiven. O banco de
desenvolvimento programando_futuro não é tocado.

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_migracao.py

Imprime OK/FALHA por verificação e sai com código 1 se alguma falhar.

Cobre: banco antigo com dados, segunda execução preservando heartbeat real,
INSERT da aplicação (criado_em == atualizado_em), queda entre os passos 1 e 2,
job inserido por código antigo durante a migração, e a verificação recusando
coluna ausente ou que aceita NULL. Os casos de banco novo e de usuário sem
permissão de ALTER foram testados subindo o uvicorn e não estão automatizados
aqui. Quando houver framework de testes (Fase 2), adaptar estes cenários.
"""
import asyncio, logging, os, sys, warnings
import aiomysql

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)
from migracoes.jobs_heartbeat import migrar_jobs_heartbeat, verificar_jobs_heartbeat, EsquemaJobsInvalido

ROOT_PASSWORD = os.environ.get("TESTE_MYSQL_ROOT_PASSWORD")
if not ROOT_PASSWORD:
    sys.exit("Defina TESTE_MYSQL_ROOT_PASSWORD com a senha de root do MySQL local (docker-compose.yml).")

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=Warning, module="aiomysql")  # "Can't drop database ... doesn't exist"
logging.basicConfig(level=logging.INFO, format="  [%(levelname)s] %(message)s")

ESQUEMA_ANTIGO = """CREATE TABLE jobs (
    id VARCHAR(36) PRIMARY KEY,
    usuario_id VARCHAR(36) NOT NULL,
    status ENUM('processando','concluido','erro') DEFAULT 'processando',
    erro TEXT,
    criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
)"""

falhas = 0
def checa(cond, desc):
    global falhas
    print(("  OK   " if cond else "  FALHA ") + desc)
    if not cond:
        falhas += 1

async def conectar(db):
    return await aiomysql.connect(host="127.0.0.1", port=3306, user="root",
                                  password=ROOT_PASSWORD, db=db, autocommit=True)

async def banco_antigo_com_dados(nome):
    c = await conectar(None)
    async with c.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS {nome}")
        await cur.execute(f"CREATE DATABASE {nome}")
    c.close()
    c = await conectar(nome)
    async with c.cursor() as cur:
        await cur.execute(ESQUEMA_ANTIGO)
        await cur.execute("""INSERT INTO jobs (id, usuario_id, status, criado_em) VALUES
            ('j1','u1','concluido','2026-05-20 09:00:00'),
            ('j2','u2','erro','2026-05-20 09:01:30'),
            ('j3','u3','processando','2026-05-20 09:02:45')""")
    return c

async def linhas(c):
    async with c.cursor() as cur:
        await cur.execute("SELECT id, criado_em, atualizado_em, tentativas FROM jobs ORDER BY id")
        return await cur.fetchall()

async def nulidade(c, coluna):
    async with c.cursor() as cur:
        await cur.execute("SELECT IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS "
                          "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='jobs' AND COLUMN_NAME=%s", (coluna,))
        return await cur.fetchone()

async def main():
    print("\n== Cenário A: banco antigo com dados, primeira execução ==")
    c = await banco_antigo_com_dados("teste_mig_a")
    await migrar_jobs_heartbeat(c)
    await verificar_jobs_heartbeat(c)
    rs = await linhas(c)
    checa(all(r[2] == r[1] for r in rs), "atualizado_em == criado_em em todas as linhas antigas")
    checa(all(r[3] == 0 for r in rs), "tentativas == 0 nas linhas antigas")
    checa((await nulidade(c, "atualizado_em"))[0] == "NO", "atualizado_em é NOT NULL")
    checa((await nulidade(c, "tentativas"))[0] == "NO", "tentativas é NOT NULL")

    print("\n== Cenário A2: heartbeat real gravado, migração roda de novo ==")
    async with c.cursor() as cur:
        await cur.execute("UPDATE jobs SET atualizado_em='2026-11-01 23:00:00', tentativas=2 WHERE id='j3'")
    await migrar_jobs_heartbeat(c)
    await verificar_jobs_heartbeat(c)
    rs = {r[0]: r for r in await linhas(c)}
    checa(str(rs["j3"][2]) == "2026-11-01 23:00:00", "heartbeat real de j3 preservado")
    checa(rs["j3"][3] == 2, "tentativas de j3 preservado")
    checa(rs["j1"][2] == rs["j1"][1], "j1 continua igual")

    print("\n== Cenário A3: INSERT como o da aplicação, criado_em == atualizado_em ==")
    async with c.cursor() as cur:
        await cur.execute("INSERT INTO jobs (id, usuario_id, status) VALUES ('j4','u4','processando')")
    rs = {r[0]: r for r in await linhas(c)}
    checa(rs["j4"][1] == rs["j4"][2], f"novo job: criado_em={rs['j4'][1]} atualizado_em={rs['j4'][2]}")
    checa(rs["j4"][3] == 0, "novo job: tentativas == 0")
    c.close()

    print("\n== Cenário B: processo caiu depois do passo 1 ==")
    c = await banco_antigo_com_dados("teste_mig_b")
    async with c.cursor() as cur:
        await cur.execute("ALTER TABLE jobs ADD COLUMN atualizado_em DATETIME NULL")
    await migrar_jobs_heartbeat(c)
    await verificar_jobs_heartbeat(c)
    rs = await linhas(c)
    checa(all(r[2] == r[1] for r in rs), "linhas preenchidas com criado_em mesmo com coluna já criada")
    checa((await nulidade(c, "atualizado_em"))[0] == "NO", "atualizado_em ficou NOT NULL")
    c.close()

    print("\n== Cenário C: código antigo insere job no meio da migração (entre passo 1 e 2) ==")
    c = await banco_antigo_com_dados("teste_mig_c")
    async with c.cursor() as cur:
        await cur.execute("ALTER TABLE jobs ADD COLUMN atualizado_em DATETIME NULL")
        await cur.execute("INSERT INTO jobs (id, usuario_id, status) VALUES ('velho','u9','processando')")
    await migrar_jobs_heartbeat(c)
    rs = {r[0]: r for r in await linhas(c)}
    checa(rs["velho"][2] == rs["velho"][1], "job do código antigo recebeu criado_em")
    c.close()

    print("\n== Cenário D: verificação recusa esquema antigo ==")
    c = await banco_antigo_com_dados("teste_mig_d")
    try:
        await verificar_jobs_heartbeat(c)
        checa(False, "deveria ter levantado EsquemaJobsInvalido")
    except EsquemaJobsInvalido as e:
        checa("tentativas não existe" in str(e) and "atualizado_em não existe" in str(e), "mensagem cita as duas colunas")
    async with c.cursor() as cur:
        await cur.execute("ALTER TABLE jobs ADD COLUMN tentativas INT NOT NULL DEFAULT 0")
        await cur.execute("ALTER TABLE jobs ADD COLUMN atualizado_em DATETIME NULL")
    try:
        await verificar_jobs_heartbeat(c)
        checa(False, "deveria ter levantado com coluna NULL")
    except EsquemaJobsInvalido as e:
        checa("atualizado_em aceita NULL" in str(e) and "3 linha(s)" in str(e), "mensagem acusa NULL e conta as linhas")
    c.close()

    c = await conectar(None)
    async with c.cursor() as cur:
        for n in "abcd":
            await cur.execute(f"DROP DATABASE IF EXISTS teste_mig_{n}")
    c.close()
    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main())
