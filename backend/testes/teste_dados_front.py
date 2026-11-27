"""Verificações do Bloco 3 (dados e front) que não precisam de banco.

Não usa MySQL: as rotas são chamadas pelo TestClient do FastAPI sem rodar o
startup, então nenhuma conexão é aberta. Onde o cadastro chega a gravar, o
pool é um falso em memória que só registra os comandos. As variáveis
obrigatórias recebem valores falsos antes de importar main.py.

Como rodar, da raiz do repositório:

    .venv/Scripts/python.exe backend/testes/teste_dados_front.py

Leva poucos segundos (o caso da produção sobe dois processos Python).

Cobre: recusa de cadastro com aceite falso, ausente ou em texto, e com
versão do termo errada; cadastro aceito gravando data e versão; rota do
termo; formato de hash bcrypt nos dois sentidos, com acento; comparação de
senha com acento nos dois caminhos; a consulta de contagem usando o mesmo
padrão do Python; CORS_ORIGENS obrigatória em produção, validação da lista e
o middleware respondendo só às origens da lista.
"""
import asyncio, logging, os, subprocess, sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

FALSAS = {
    "ANTHROPIC_API_KEY": "chave-falsa-de-teste-0000",
    "AMBIENTE": "local",
    "JWT_SECRET": "segredo-falso-de-teste",
    "ADMIN_SECRET": "admin-falso-de-teste",
}
os.environ.update(FALSAS)
for var in ("CORS_ORIGENS", "IA_SIMULADA"):
    os.environ.pop(var, None)

sys.stdout.reconfigure(encoding="utf-8")

import bcrypt
from fastapi.testclient import TestClient
import main

logging.getLogger().setLevel(logging.CRITICAL)

falhas = 0
def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1


# ── Banco falso: registra os comandos; SELECT de e-mail não acha ninguém ──────
class CursorFalso:
    rowcount = 1
    def __init__(self, log): self.log = log
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def execute(self, sql, params=None): self.log.append((sql, params))
    async def fetchone(self): return None
    async def fetchall(self): return []

class ConexaoFalsa:
    def __init__(self, log): self.log = log
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def cursor(self, *a): return CursorFalso(self.log)

class PoolFalso:
    def __init__(self): self.log = []
    def acquire(self): return ConexaoFalsa(self.log)


cliente = TestClient(main.app)
BASE = {"nome": "Aluna Teste", "email": "aluna@teste.local", "senha": "senha123"}
VERSAO = main.TERMO_LGPD_VERSAO

def cadastrar(**extra):
    return cliente.post("/api/auth/cadastro", json={**BASE, **extra})

def codigo(resp):
    try:
        return resp.json()["detail"]["codigo"]
    except Exception:
        return None


print("\n== 1. Cadastro recusa aceite que não seja true ==")
main.db_pool = PoolFalso()
r = cadastrar(aceite_lgpd=False, versao_termo_lgpd=VERSAO)
checa(r.status_code == 400 and codigo(r) == "LGPD_RECUSADO", f"aceite false: {r.status_code} {codigo(r)}")
checa("aceitar o termo" in r.json()["detail"]["erro"], f"mensagem: {r.json()['detail']['erro']}")
r = cadastrar(versao_termo_lgpd=VERSAO)
checa(r.status_code == 400 and codigo(r) == "LGPD_AUSENTE", f"aceite ausente: {r.status_code} {codigo(r)} (não o 422 genérico)")
checa("obrigatório" in r.json()["detail"]["erro"], f"mensagem: {r.json()['detail']['erro']}")
r = cadastrar(aceite_lgpd=None, versao_termo_lgpd=VERSAO)
checa(r.status_code == 400 and codigo(r) == "LGPD_AUSENTE", f"aceite null: {r.status_code} {codigo(r)}")
r = cadastrar(aceite_lgpd="true", versao_termo_lgpd=VERSAO)
checa(r.status_code == 422, f"aceite em texto \"true\": {r.status_code} (recusado, não vira true)")
r = cadastrar(aceite_lgpd=1, versao_termo_lgpd=VERSAO)
checa(r.status_code == 422, f"aceite numérico 1: {r.status_code}")
checa(main.db_pool.log == [], "nenhuma recusa chegou ao banco")

print("\n== 2. Cadastro recusa versão do termo diferente da atual ==")
r = cadastrar(aceite_lgpd=True, versao_termo_lgpd="2020-01-01")
checa(r.status_code == 400 and codigo(r) == "LGPD_VERSAO_INVALIDA", f"versão antiga: {r.status_code} {codigo(r)}")
r = cadastrar(aceite_lgpd=True)
checa(r.status_code == 400 and codigo(r) == "LGPD_VERSAO_INVALIDA", f"versão ausente: {r.status_code} {codigo(r)}")

print("\n== 3. Cadastro aceito grava data e versão do aceite ==")
main.db_pool = PoolFalso()
# aceite_menor=True de propósito: nenhuma tela coleta isso, o backend tem de ignorar.
r = cadastrar(aceite_lgpd=True, versao_termo_lgpd=VERSAO, aceite_menor=True)
checa(r.status_code == 201, f"status: {r.status_code}")
inserts = [(sql, p) for sql, p in main.db_pool.log if sql.startswith("INSERT INTO usuarios")]
checa(len(inserts) == 1, "um INSERT em usuarios")
sql, params = inserts[0] if inserts else ("", ())
checa("aceite_lgpd_em" in sql and "UTC_TIMESTAMP()" in sql, "data do aceite gravada pelo banco, em UTC")
checa(VERSAO in params, f"versão gravada: {VERSAO}")
checa(sql.rstrip().endswith("NULL)") and True not in params, "aceite_menor gravado como NULL (não coletado), valor do cliente ignorado")
checa(r.json()["usuario"]["aceite_menor"] is None, "resposta devolve aceite_menor = null")
checa("senha123" not in params, "senha não vai em texto plano para o INSERT")
checa("senha" not in r.json()["usuario"], "resposta não devolve senha")

print("\n== 4. Rota do termo ==")
r = cliente.get("/api/lgpd/termo")
t = r.json()
checa(r.status_code == 200 and t["versao"] == VERSAO, f"versão servida: {t.get('versao')}")
checa(len(t["paragrafos"]) >= 1 and all(isinstance(p, str) and p for p in t["paragrafos"]), f"{len(t['paragrafos'])} parágrafo(s)")
checa(bool(t["confirmacao"]), "texto da caixa de confirmação presente")

print("\n== 5. Formato de hash bcrypt ==")
hash_b = bcrypt.hashpw("pão-com-açúcar".encode("utf-8"), bcrypt.gensalt()).decode()
casos = {
    hash_b: True,
    "$2a$" + hash_b[4:]: True,
    "$2y$" + hash_b[4:]: True,
    "senha123": False,
    "pão-com-açúcar": False,
    "$2b$12$curta": False,                       # prefixo certo, tamanho errado
    "$2B$" + hash_b[4:]: False,                  # maiúscula não é bcrypt
    hash_b + "x": False,                         # 61 caracteres
    "$2b$1x$" + hash_b[7:]: False,               # custo não numérico
    "": False,
}
for valor, esperado in casos.items():
    rotulo = valor if len(valor) < 20 else valor[:12] + "..."
    checa(main.eh_hash_bcrypt(valor) is esperado, f"{rotulo!r} -> {esperado}")

print("\n== 6. Comparação de senha com acento nos dois caminhos ==")
async def comparar():
    return (
        await main.verificar_senha("pão-com-açúcar", hash_b),
        await main.verificar_senha("pao-com-acucar", hash_b),
        await main.verificar_senha("pão-com-açúcar", "pão-com-açúcar"),
        await main.verificar_senha("pão-com-acúcar", "pão-com-açúcar"),
    )
ok_hash, errada_hash, ok_plano, errada_plano = asyncio.run(comparar())
checa(ok_hash and not errada_hash, "hash: certa aceita, sem acento recusada")
checa(ok_plano and not errada_plano, "texto plano: certa aceita, um acento trocado recusado")

print("\n== 7. Contagem no SQL usa o mesmo padrão do Python ==")
class CursorContagem:
    async def execute(self, sql, params=None): self.sql, self.params = sql, params
    async def fetchone(self): return (4,)
cur = CursorContagem()
n = asyncio.run(main.contar_senhas_texto_plano(cur))
checa(n == 4, "devolve o número da consulta")
checa("REGEXP_LIKE" in cur.sql and "'c'" in cur.sql, "REGEXP_LIKE com 'c' (diferencia maiúsculas)")
checa(cur.params == (main.PADRAO_HASH_BCRYPT,), "padrão passado é o mesmo do eh_hash_bcrypt")

print("\n== 8. CORS_ORIGENS ==")
f = main.carregar_cors_origens
checa(f("local", None) == ["http://localhost:8000", "http://127.0.0.1:8000"], "local sem variável: localhost do uvicorn")
checa(f("producao", "https://a.com.br, https://b.org") == ["https://a.com.br", "https://b.org"], "lista separada por vírgula")
for ruim in ("*", "https://a.com.br/", "a.com.br", "https://a.com.br, *", "ftp://a.com.br"):
    try:
        f("producao", ruim)
        checa(False, f"'{ruim}' deveria ser recusado")
    except RuntimeError:
        checa(True, f"'{ruim}' recusado")
for vazio in (None, "", "  ", " , "):
    try:
        f("producao", vazio)
        checa(False, f"produção com {vazio!r} deveria falhar")
    except RuntimeError as e:
        checa("CORS_ORIGENS" in str(e), f"produção com {vazio!r}: recusa citando a variável")

def subir(extra):
    # PYTHONIOENCODING: no Windows o processo filho escreveria o log em cp1252.
    env = {**os.environ, **FALSAS, "AMBIENTE": "producao", "PYTHONIOENCODING": "utf-8", **extra}
    env.pop("CORS_ORIGENS", None) if "CORS_ORIGENS" not in extra else None
    return subprocess.run([sys.executable, "-c", "import main; print('SUBIU')"], cwd=BACKEND,
                          env=env, capture_output=True, text=True, encoding="utf-8")
p = subir({})
checa(p.returncode != 0 and "CORS_ORIGENS" in p.stderr, "processo em produção sem CORS_ORIGENS não sobe")
p = subir({"CORS_ORIGENS": "https://programando-o-futuro.onrender.com"})
checa(p.returncode == 0 and "SUBIU" in p.stdout, "com CORS_ORIGENS definida, sobe")

pre = {"Access-Control-Request-Method": "GET"}
r = cliente.options("/api/lgpd/termo", headers={**pre, "Origin": "http://localhost:8000"})
checa(r.headers.get("access-control-allow-origin") == "http://localhost:8000", "origem da lista recebe permissão")
r = cliente.options("/api/lgpd/termo", headers={**pre, "Origin": "https://site-qualquer.com"})
checa("access-control-allow-origin" not in r.headers, f"origem fora da lista não recebe permissão ({r.status_code})")

print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
sys.exit(1 if falhas else 0)
