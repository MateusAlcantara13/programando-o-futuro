"""Ciclo inteiro do progresso do mapa: navegador -> servidor -> banco -> navegador novo.

Prova que o progresso sobrevive ao navegador: marca um passo, joga fora o
armazenamento do navegador, carrega de novo, e o passo continua marcado
porque veio do servidor.

Contra qual banco: SOMENTE o MySQL local do docker-compose (127.0.0.1:3306).
O script cria e APAGA o banco teste_mapa_ciclo. As variáveis do banco são
definidas aqui antes de importar main.py, então o .env não é usado para o
banco. O banco de desenvolvimento programando_futuro não é tocado.

O app sobe de verdade pelo TestClient do FastAPI, com startup e migrações.
O js/mapa-progresso.js roda num motor JavaScript (QuickJS) e as chamadas de
rede dele vão para as rotas reais /api/mapa/progresso. Nenhuma chamada à IA.

Precisa do QuickJS (dependência só de teste):

    .venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt

Como rodar, da raiz do repositório, com o container do banco no ar
(docker compose up -d):

    TESTE_MYSQL_ROOT_PASSWORD=<MYSQL_ROOT_PASSWORD do docker-compose.yml> \
        .venv/Scripts/python.exe backend/testes/teste_mapa_progresso.py

Cobre: POST do progresso grava em mapa_progresso com o UUID completo do
aluno; navegador novo, sem nada guardado, carrega o passo marcado do
servidor; cache local desatualizado é sobrescrito pelo servidor.
"""
import json, os, re, sys, warnings

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RAIZ = os.path.join(BACKEND, "..")
sys.path.insert(0, BACKEND)

ROOT_PASSWORD = os.environ.get("TESTE_MYSQL_ROOT_PASSWORD")
if not ROOT_PASSWORD:
    sys.exit("Defina TESTE_MYSQL_ROOT_PASSWORD com a senha de root do MySQL local (docker-compose.yml).")
try:
    import quickjs
except ImportError:
    sys.exit("Falta o QuickJS: pip install -r backend/requirements-dev.txt")

BANCO = "teste_mapa_ciclo"
DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
os.environ.update({
    "ANTHROPIC_API_KEY": "chave-falsa-de-teste-0000",
    "AMBIENTE": "local",
    "JWT_SECRET": "segredo-falso-de-teste",
    "ADMIN_SECRET": "admin-falso-de-teste",
    "DB_HOST": "127.0.0.1", "DB_PORT": "3306", "DB_USER": "root",
    "DB_PASSWORD": ROOT_PASSWORD, "DB_NAME": BANCO, "DB_SSL_DISABLED": "true",
})
for var in ("IA_SIMULADA", "CORS_ORIGENS"):
    os.environ.pop(var, None)

sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

import pymysql
from fastapi.testclient import TestClient
import main

falhas = 0
def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1

def sql(consulta, params=(), db=BANCO):
    c = pymysql.connect(host="127.0.0.1", port=3306, user="root", password=ROOT_PASSWORD,
                        database=db, autocommit=True)
    try:
        with c.cursor() as cur:
            cur.execute(consulta, params)
            return cur.fetchall()
    finally:
        c.close()

sql(f"DROP DATABASE IF EXISTS {BANCO}", db=None)
sql(f"CREATE DATABASE {BANCO}", db=None)

CODIGO = open(os.path.join(RAIZ, "js", "mapa-progresso.js"), encoding="utf-8").read()
PONTE = r"""
function FakeStorage() {}
Object.defineProperty(FakeStorage.prototype, 'getItem', { value: function (k) { return Object.prototype.hasOwnProperty.call(this, k) ? this[k] : null; } });
Object.defineProperty(FakeStorage.prototype, 'setItem', { value: function (k, v) { this[k] = String(v); } });
var avisos = [];
// py_req chama a rota real pelo TestClient e devolve {status, body} em JSON.
async function buscar() {
  const r = JSON.parse(py_req('GET', '/api/mapa/progresso', ''));
  if (r.status !== 200) throw new Error('HTTP ' + r.status);
  return r.body;
}
async function enviar(dados) {
  const r = JSON.parse(py_req('POST', '/api/mapa/progresso', JSON.stringify(dados)));
  if (r.status !== 200) throw new Error('HTTP ' + r.status);
  return r.body;
}
function navegador(armazenamento) {
  return criarProgressoMapa({ armazenamento: armazenamento, buscar: buscar, enviar: enviar,
    aoAvisar: function (t) { avisos.push(t); } });
}
"""

try:
    with TestClient(main.app) as cliente:   # roda o startup: tabelas e migrações
        r = cliente.post("/api/auth/cadastro", json={
            "nome": "Aluna Ciclo", "email": "ciclo@teste.local", "senha": "senha123",
            "aceite_lgpd": True, "versao_termo_lgpd": main.TERMO_LGPD_VERSAO,
        })
        checa(r.status_code == 201, f"cadastro: {r.status_code}")
        token = r.json()["token"]
        uid = r.json()["usuario"]["id"]
        cab = {"Authorization": f"Bearer {token}"}

        def py_req(metodo, caminho, corpo):
            if metodo == "GET":
                resp = cliente.get(caminho, headers=cab)
            else:
                resp = cliente.post(caminho, content=corpo,
                                    headers={**cab, "Content-Type": "application/json"})
            return json.dumps({"status": resp.status_code, "body": resp.json()})

        ctx = quickjs.Context()
        ctx.add_callable("py_req", py_req)
        ctx.eval(PONTE)
        ctx.eval(CODIGO)

        def esperar(expr):
            ctx.eval(f"var __r, __fim = false; ({expr}).then(function (v) {{ __r = v; __fim = true; }});")
            while ctx.execute_pending_job():
                pass
            return json.loads(ctx.eval("JSON.stringify(__r)")) if ctx.eval("__fim") else "PENDENTE"

        def js(expr):
            return json.loads(ctx.eval(f"JSON.stringify({expr})"))

        print("\n== 1. Marca um passo e salva ==")
        ctx.eval("var nav1 = navegador(new FakeStorage());")
        checa(esperar("nav1.carregar()") == "servidor", "primeira carga veio do servidor")
        ctx.eval("nav1.estado.etapasConcluidas['inicio-0'] = true;"
                 "nav1.estado.checksFeitos['inicio-0'] = {'inicio-0-1': true};")
        checa(esperar("nav1.salvar()") is True, "salvar devolveu true")
        checa(js("avisos").count("salvar") == 0, "nenhum aviso de não salvo")

        print("\n== 2. O banco tem a linha, com o UUID completo ==")
        linhas = sql("SELECT usuario_id, etapas_concluidas FROM mapa_progresso")
        checa(len(linhas) == 1 and linhas[0][0] == uid, f"usuario_id gravado = {linhas[0][0] if linhas else None}")
        gravadas = json.loads(linhas[0][1]) if linhas else {}
        # Desde o Bloco 5 o servidor grava a data de conclusão no lugar de true.
        checa(list(gravadas) == ["inicio-0"] and DATA_ISO.match(str(gravadas["inicio-0"])),
              f"etapa gravada com data do servidor: {gravadas}")

        print("\n== 3. Navegador novo, sem nada guardado: o passo vem do servidor ==")
        ctx.eval("var nav2 = navegador(new FakeStorage());")
        checa(esperar("nav2.carregar()") == "servidor", "carga veio do servidor")
        checa(js("nav2.estado.etapasConcluidas") == gravadas, "passo continua marcado, com a data do servidor")
        checa(js("nav2.estado.checksFeitos") == {"inicio-0": {"inicio-0-1": True}}, "checklist continua marcado")

        print("\n== 4. Cache desatualizado perde para o servidor ==")
        ctx.eval("var velho = new FakeStorage(); velho.setItem('pf_mapa_done', '{}');"
                 "var nav3 = navegador(velho);")
        esperar("nav3.carregar()")
        checa(js("nav3.estado.etapasConcluidas") == gravadas, "estado é o do servidor")
        checa(json.loads(js("velho.getItem('pf_mapa_done')")) == gravadas, "cache sobrescrito")
finally:
    sql(f"DROP DATABASE IF EXISTS {BANCO}", db=None)

print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
sys.exit(1 if falhas else 0)
