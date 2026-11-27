"""Verificações do Bloco 3 (dados e front) que precisam de banco.

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O host é fixo e o .env não é usado para o banco: o script cria e APAGA bancos
chamados teste_lgpd_a..c. O banco de desenvolvimento programando_futuro não
é tocado.

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_dados_db.py

Imprime OK/FALHA por verificação e sai com código 1 se alguma falhar.

Cobre: migração do aceite da LGPD em banco antigo com usuários (colunas
novas NULL, aceite existente intacto, padrão trocado para FALSE), segunda
execução sem efeito, verificação recusando o esquema antigo; contagem de
senhas em texto plano no SQL batendo com o eh_hash_bcrypt do Python, inclusive
nos casos de maiúscula e tamanho; métrica no /api/admin/dados; cadastro
gravando data e versão do aceite.
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
os.environ.pop("CORS_ORIGENS", None)

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore", category=Warning, module="aiomysql")

import bcrypt
import main
from migracoes.usuarios_aceite_lgpd import (
    migrar_usuarios_aceite_lgpd, verificar_usuarios_aceite_lgpd, EsquemaUsuariosInvalido,
)

logging.getLogger().setLevel(logging.ERROR)

# Esquema de usuarios antes deste bloco: aceite com padrão TRUE e sem data/versão.
ESQUEMA_ANTIGO = """CREATE TABLE usuarios (
    id VARCHAR(36) PRIMARY KEY,
    nome VARCHAR(120) NOT NULL,
    email VARCHAR(120) NOT NULL UNIQUE,
    senha VARCHAR(255) NOT NULL,
    avatar_iniciais VARCHAR(10),
    aceite_lgpd BOOLEAN DEFAULT TRUE,
    aceite_menor BOOLEAN DEFAULT FALSE,
    teste_inicial_concluido BOOLEAN DEFAULT FALSE,
    modulos_concluidos JSON DEFAULT ('[]'),
    cidade VARCHAR(100),
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

async def recriar(nome):
    c = await conectar(None)
    async with c.cursor() as cur:
        await cur.execute(f"DROP DATABASE IF EXISTS {nome}")
        await cur.execute(f"CREATE DATABASE {nome}")
    c.close()
    return await conectar(nome)

async def colunas_aceite(c):
    async with c.cursor() as cur:
        await cur.execute("SELECT id, aceite_lgpd, aceite_lgpd_em, aceite_lgpd_versao FROM usuarios ORDER BY id")
        return await cur.fetchall()

async def main_teste():
    print("\n== Cenário A: migração em banco antigo com usuários ==")
    c = await recriar("teste_lgpd_a")
    async with c.cursor() as cur:
        await cur.execute(ESQUEMA_ANTIGO)
        await cur.execute("INSERT INTO usuarios (id, nome, email, senha) VALUES ('u1','A','a@x','x'), ('u2','B','b@x','y')")
    await migrar_usuarios_aceite_lgpd(c)
    await verificar_usuarios_aceite_lgpd(c)
    linhas = await colunas_aceite(c)
    checa(all(l[1] == 1 for l in linhas), "aceite_lgpd dos usuários existentes ficou como estava (1)")
    checa(all(l[2] is None and l[3] is None for l in linhas), "data e versão do aceite NULL nos existentes")
    async with c.cursor() as cur:
        await cur.execute("SELECT @@SESSION.sql_mode")
        (modo,) = await cur.fetchone()
        try:
            await cur.execute("INSERT INTO usuarios (id, nome, email, senha) VALUES ('u3','C','c@x','z')")
            recusado = False
        except aiomysql.Error:
            recusado = True
    checa("STRICT_TRANS_TABLES" in modo, f"banco em modo estrito (sql_mode={modo})")
    checa(recusado, "INSERT sem aceite_lgpd é recusado: a coluna exige valor explícito")

    print("\n== Cenário A2: segunda execução não muda nada ==")
    antes = await colunas_aceite(c)
    await migrar_usuarios_aceite_lgpd(c)
    await verificar_usuarios_aceite_lgpd(c)
    checa(await colunas_aceite(c) == antes, "mesmas linhas depois da segunda execução")
    c.close()

    print("\n== Cenário B: verificação recusa o esquema antigo ==")
    c = await recriar("teste_lgpd_b")
    async with c.cursor() as cur:
        await cur.execute(ESQUEMA_ANTIGO)
    try:
        await verificar_usuarios_aceite_lgpd(c)
        checa(False, "deveria ter levantado EsquemaUsuariosInvalido")
    except EsquemaUsuariosInvalido as e:
        checa("aceite_lgpd_em não existe" in str(e) and "NOT NULL e sem padrão" in str(e),
              "mensagem cita as colunas ausentes e o aceite com padrão")
    async with c.cursor() as cur:
        await cur.execute("INSERT INTO usuarios (id, nome, email, senha, aceite_lgpd) VALUES ('n1','N','n@x','x',NULL)")
    try:
        await migrar_usuarios_aceite_lgpd(c)
        checa(False, "migração deveria parar com aceite NULL no banco")
    except EsquemaUsuariosInvalido as e:
        checa("1 usuário(s) com aceite_lgpd NULL" in str(e), "migração para e não inventa valor para aceite NULL")
    c.close()

    print("\n== Cenário C: contagem de senhas em texto plano no SQL ==")
    await recriar("teste_lgpd_c")
    main.db_pool = await aiomysql.create_pool(host="127.0.0.1", port=3306, user="root",
                                              password=ROOT_PASSWORD, db="teste_lgpd_c", autocommit=True)
    await main.criar_tabelas()
    async with main.db_pool.acquire() as conn:
        await migrar_usuarios_aceite_lgpd(conn)
    h = bcrypt.hashpw("pão".encode("utf-8"), bcrypt.gensalt()).decode()
    senhas = [h, "$2a$" + h[4:], "$2y$" + h[4:], "senha123", "pão-com-açúcar",
              "$2B$" + h[4:], "$2b$12$curta", h + "x"]
    async with main.db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            for i, s in enumerate(senhas):
                await cur.execute("INSERT INTO usuarios (id, nome, email, senha, aceite_lgpd) VALUES (%s,%s,%s,%s,FALSE)",
                                  (f"s{i}", f"S{i}", f"s{i}@x", s))
            n_sql = await main.contar_senhas_texto_plano(cur)
    n_python = sum(1 for s in senhas if not main.eh_hash_bcrypt(s))
    checa(n_python == 5, f"Python classifica {n_python} como texto plano (esperado 5)")
    checa(n_sql == n_python, f"SQL conta {n_sql}, igual ao Python")

    print("\n== Cenário C2: métrica no painel admin ==")
    dados = await main.admin_dados(senha=main.ADMIN_SECRET)
    checa(dados["metricas"].get("senhas_texto_plano") == n_python,
          f"metricas.senhas_texto_plano = {dados['metricas'].get('senhas_texto_plano')}")

    print("\n== Cenário C3: cadastro grava data e versão do aceite ==")
    body = main.CadastroBody(nome="Nova", email="nova@x", senha="senha123", aceite_lgpd=True,
                             versao_termo_lgpd=main.TERMO_LGPD_VERSAO)
    resp = await main.cadastro(body)
    async with main.db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT aceite_lgpd, aceite_lgpd_em, aceite_lgpd_versao, senha FROM usuarios WHERE id=%s",
                              (resp["usuario"]["id"],))
            aceite, em, versao, senha = await cur.fetchone()
    checa(aceite == 1 and em is not None, f"aceite gravado com data ({em})")
    checa(versao == main.TERMO_LGPD_VERSAO, f"versão gravada: {versao}")
    checa(main.eh_hash_bcrypt(senha), "senha gravada como hash")
    main.db_pool.close()
    await main.db_pool.wait_closed()

    c = await conectar(None)
    async with c.cursor() as cur:
        for n in "abc":
            await cur.execute(f"DROP DATABASE IF EXISTS teste_lgpd_{n}")
    c.close()
    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main_teste())
