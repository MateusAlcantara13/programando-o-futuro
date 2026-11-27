"""Verificações da migração migracoes/mapa_progresso_usuario_id.py.

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O host é fixo de propósito e o .env é ignorado para o banco: o script cria e
APAGA bancos chamados teste_mapa_a..c, então nunca pode apontar para o
Aiven. O banco de desenvolvimento programando_futuro não é tocado.

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_migracao_mapa.py

Imprime OK/FALHA por verificação e sai com código 1 se alguma falhar.

Cobre: contagem antes de migrar, inclusive a armadilha da comparação INT com
VARCHAR no MySQL; conversão preservando as linhas e o UNIQUE; segunda
execução sem efeito; gravação de UUID depois da migração; verificação
recusando o esquema antigo; banco novo criado por criar_tabelas já no tipo
certo.
"""
import asyncio, logging, os, sys, warnings
import aiomysql

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

ROOT_PASSWORD = os.environ.get("TESTE_MYSQL_ROOT_PASSWORD")
if not ROOT_PASSWORD:
    sys.exit("Defina TESTE_MYSQL_ROOT_PASSWORD com a senha de root do MySQL local (docker-compose.yml).")

os.environ["ANTHROPIC_API_KEY"] = "chave-falsa-de-teste-0000"
os.environ["AMBIENTE"] = "local"
os.environ["JWT_SECRET"] = "segredo-falso-de-teste"
os.environ["ADMIN_SECRET"] = "admin-falso-de-teste"

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=Warning, module="aiomysql")

from migracoes.mapa_progresso_usuario_id import (
    migrar_mapa_progresso_usuario_id, verificar_mapa_progresso_usuario_id,
    contar_linhas, EsquemaMapaProgressoInvalido,
)

logging.basicConfig(level=logging.INFO, format="  [%(levelname)s] %(message)s")

ESQUEMA_ANTIGO = """CREATE TABLE mapa_progresso (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    etapas_concluidas TEXT,
    checks_feitos TEXT,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(usuario_id)
)"""
UUID_COM_DIGITO = "3f2a9c1e-0000-4000-8000-000000000001"

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
    """Banco com mapa_progresso no esquema antigo e linhas como as que o MySQL sem modo estrito gravaria."""
    c = await conectar(None)
    async with c.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS {nome}")
        await cur.execute(f"CREATE DATABASE {nome}")
    c.close()
    c = await conectar(nome)
    async with c.cursor() as cur:
        await cur.execute("CREATE TABLE usuarios (id VARCHAR(36) PRIMARY KEY, nome VARCHAR(120))")
        # Um UUID que começa com dígito e um id numérico, para exercitar a contagem.
        await cur.execute("INSERT INTO usuarios VALUES (%s, 'aluno uuid'), ('42', 'aluno numerico')", (UUID_COM_DIGITO,))
        await cur.execute(ESQUEMA_ANTIGO)
        # 3: o que sobraria de '3f2a...'. 0: o que sobraria de UUID começado por letra.
        # 42: único valor que corresponde, como texto, a um usuário existente.
        await cur.execute("INSERT INTO mapa_progresso (usuario_id, etapas_concluidas) VALUES (3,'{}'), (0,'{}'), (42,'{}')")
    return c

async def tipo_e_linhas(c):
    async with c.cursor() as cur:
        await cur.execute(
            "SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mapa_progresso' AND COLUMN_NAME = 'usuario_id'"
        )
        tipo = await cur.fetchone()
        await cur.execute("SELECT usuario_id FROM mapa_progresso ORDER BY id")
        linhas = [r[0] for r in await cur.fetchall()]
    return tipo, linhas

async def unico(c):
    async with c.cursor() as cur:
        await cur.execute(
            "SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'mapa_progresso' AND COLUMN_NAME = 'usuario_id' AND NON_UNIQUE = 0"
        )
        (n,) = await cur.fetchone()
    return n > 0

async def main():
    print("\n== Cenário A: banco antigo com dados ==")
    c = await banco_antigo_com_dados("teste_mapa_a")
    async with c.cursor() as cur:
        # A armadilha que a contagem evita: em SQL, INT = VARCHAR vira comparação numérica.
        await cur.execute("SELECT COUNT(*) FROM mapa_progresso m JOIN usuarios u ON m.usuario_id = u.id")
        (ingenua,) = await cur.fetchone()
        total, utilizaveis, zeros = await contar_linhas(cur)
    checa(ingenua == 2, f"JOIN ingênuo acha {ingenua} dono(s): o 3 'casa' com '{UUID_COM_DIGITO[:4]}...'")
    checa((total, utilizaveis, zeros) == (3, 1, 1), f"contagem: total={total}, utilizáveis={utilizaveis}, zero={zeros}")

    await migrar_mapa_progresso_usuario_id(c)
    await verificar_mapa_progresso_usuario_id(c)
    tipo, linhas = await tipo_e_linhas(c)
    checa(tipo[0].lower() == "varchar" and tipo[1] == 36, f"tipo depois: {tipo[0]}({tipo[1]})")
    checa(linhas == ["3", "0", "42"], f"linhas preservadas como texto: {linhas}")
    checa(await unico(c), "UNIQUE em usuario_id mantido")

    print("\n== Cenário A2: segunda execução não faz nada ==")
    await migrar_mapa_progresso_usuario_id(c)
    tipo2, linhas2 = await tipo_e_linhas(c)
    checa((tipo2, linhas2) == (tipo, linhas), "tipo e linhas iguais depois da segunda execução")

    print("\n== Cenário A3: UUID grava depois da migração ==")
    async with c.cursor() as cur:
        await cur.execute(
            "INSERT INTO mapa_progresso (usuario_id, etapas_concluidas) VALUES (%s, '{}')", (UUID_COM_DIGITO,)
        )
        await cur.execute("SELECT COUNT(*) FROM mapa_progresso WHERE usuario_id = %s", (UUID_COM_DIGITO,))
        (n,) = await cur.fetchone()
    checa(n == 1, "linha do aluno encontrada pelo UUID completo")
    c.close()

    print("\n== Cenário B: verificação recusa o esquema antigo ==")
    c = await banco_antigo_com_dados("teste_mapa_b")
    try:
        await verificar_mapa_progresso_usuario_id(c)
        checa(False, "deveria ter levantado EsquemaMapaProgressoInvalido")
    except EsquemaMapaProgressoInvalido as e:
        checa("VARCHAR(36)" in str(e) and "int" in str(e), "mensagem cita o tipo esperado e o encontrado")
    c.close()

    print("\n== Cenário C: banco novo criado por criar_tabelas ==")
    import main as app_main
    c = await conectar(None)
    async with c.cursor() as cur:
        await cur.execute("DROP DATABASE IF EXISTS teste_mapa_c")
        await cur.execute("CREATE DATABASE teste_mapa_c")
    c.close()
    app_main.db_pool = await aiomysql.create_pool(host="127.0.0.1", port=3306, user="root",
                                                  password=ROOT_PASSWORD, db="teste_mapa_c", autocommit=True)
    await app_main.criar_tabelas()
    app_main.db_pool.close()
    await app_main.db_pool.wait_closed()
    c = await conectar("teste_mapa_c")
    tipo, _ = await tipo_e_linhas(c)
    checa(tipo[0].lower() == "varchar", f"tabela nova já nasce com {tipo[0]}({tipo[1]})")
    await migrar_mapa_progresso_usuario_id(c)
    await verificar_mapa_progresso_usuario_id(c)
    checa(True, "migração e verificação passam sem alterar nada")
    c.close()

    c = await conectar(None)
    async with c.cursor() as cur:
        for n in "abc":
            await cur.execute(f"DROP DATABASE IF EXISTS teste_mapa_{n}")
    c.close()
    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main())
