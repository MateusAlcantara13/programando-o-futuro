"""Verificações do progresso do mapa no front (js/mapa-progresso.js), sem banco.

Executa o js/mapa-progresso.js de verdade num motor JavaScript (QuickJS),
com armazenamento do navegador e servidor simulados. Nenhuma rede, nenhum
banco.

Precisa do QuickJS para Python, que é dependência só de teste:

    .venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt

Como rodar, da raiz do repositório:

    .venv/Scripts/python.exe backend/testes/teste_mapa_progresso_front.py

Cobre: na carga, o servidor sobrescreve o cache; o cache aparece antes da
resposta do servidor; servidor fora mantém o cache e avisa; envio que falha
avisa que a marcação não foi salva, e o seguinte que dá certo tira o aviso;
envios saem em fila, um de cada vez, sempre com o estado mais recente.
"""
import json, os, sys

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.stdout.reconfigure(encoding="utf-8")

try:
    import quickjs
except ImportError:
    sys.exit("Falta o QuickJS: pip install -r backend/requirements-dev.txt")

CODIGO = open(os.path.join(RAIZ, "js", "mapa-progresso.js"), encoding="utf-8").read()

AMBIENTE = r"""
function FakeStorage() {}
Object.defineProperty(FakeStorage.prototype, 'getItem', { value: function (k) { return Object.prototype.hasOwnProperty.call(this, k) ? this[k] : null; } });
Object.defineProperty(FakeStorage.prototype, 'setItem', { value: function (k, v) { this[k] = String(v); } });

var armazenamento = new FakeStorage();
var avisos = [];
var atualizacoes = [];
var servidor = { dados: { etapasConcluidas: {}, checksFeitos: {} }, falharBusca: false, falharEnvio: false };
var envios = [];          // corpo de cada envio, na ordem em que SAÍRAM
var enviosAbertos = 0, maxAbertos = 0;
var liberar = [];         // envios parados esperando o teste liberar
var segurarEnvios = false;

async function buscar() {
  if (servidor.falharBusca) throw new Error('fora do ar');
  return JSON.parse(JSON.stringify(servidor.dados));
}
async function enviar(dados) {
  enviosAbertos++; maxAbertos = Math.max(maxAbertos, enviosAbertos);
  envios.push(JSON.stringify(dados));
  if (segurarEnvios) await new Promise(function (r) { liberar.push(r); });
  enviosAbertos--;
  if (servidor.falharEnvio) throw new Error('fora do ar');
  servidor.dados = JSON.parse(JSON.stringify(dados));
}
function novo() {
  return criarProgressoMapa({ armazenamento: armazenamento, buscar: buscar, enviar: enviar,
    aoAvisar: function (t) { avisos.push(t); } });
}
"""

ctx = quickjs.Context()
ctx.eval(AMBIENTE)
ctx.eval(CODIGO)

def js(expr):
    return json.loads(ctx.eval(f"JSON.stringify({expr})"))

def rodar_jobs():
    while ctx.execute_pending_job():
        pass

def esperar(expr):
    ctx.eval(f"var __r = undefined, __fim = false; ({expr}).then(function (v) {{ __r = v; __fim = true; }});")
    rodar_jobs()
    return js("__r") if ctx.eval("__fim") else "PENDENTE"

falhas = 0
def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1

print("\n== 1. Na carga, o servidor sobrescreve o cache ==")
ctx.eval("""armazenamento.setItem('pf_mapa_done', JSON.stringify({velho: true}));
servidor.dados = { etapasConcluidas: {passo1: true}, checksFeitos: {passo1: {'passo1-0': true}} };
var p = novo();
var vistoNaPrimeira = null;
var aoAtualizar = function () { atualizacoes.push(JSON.stringify(p.estado.etapasConcluidas)); };""")
r = esperar("p.carregar(aoAtualizar)")
checa(r == "servidor", f"origem: {r}")
checa(js("atualizacoes") == ['{"velho":true}', '{"passo1":true}'], f"tela: cache primeiro, servidor depois ({js('atualizacoes')})")
checa(js("p.estado.etapasConcluidas") == {"passo1": True}, "estado final é o do servidor, sem o 'velho' do cache")
checa(json.loads(js("armazenamento.getItem('pf_mapa_done')")) == {"passo1": True}, "cache sobrescrito com o do servidor")
checa(js("avisos") == [None], f"sem aviso ({js('avisos')})")

print("\n== 2. Servidor fora na carga: fica o cache, com aviso ==")
ctx.eval("avisos = []; atualizacoes = []; servidor.falharBusca = true; var p2 = novo();")
r = esperar("p2.carregar()")
checa(r == "cache", f"origem: {r}")
checa(js("p2.estado.etapasConcluidas") == {"passo1": True}, "mostra o que está no cache")
checa(js("avisos") == ["carga"], f"aviso de carga ({js('avisos')})")
ctx.eval("servidor.falharBusca = false")

print("\n== 3. Envio que falha avisa; o seguinte que dá certo tira o aviso ==")
ctx.eval("avisos = []; servidor.falharEnvio = true; p.estado.etapasConcluidas.passo2 = true;")
r = esperar("p.salvar()")
checa(r is False, "salvar devolve false")
checa(js("avisos") == ["salvar"], f"aviso de não salvo ({js('avisos')})")
checa("passo2" not in js("servidor.dados.etapasConcluidas"), "servidor não tem o passo2")
checa("passo2" in json.loads(js("armazenamento.getItem('pf_mapa_done')")), "cache tem o passo2 (o aviso explica que ele some)")
ctx.eval("servidor.falharEnvio = false")
r = esperar("p.salvar()")
checa(r is True and js("avisos") == ["salvar", None], f"novo envio deu certo e tirou o aviso ({js('avisos')})")
checa("passo2" in js("servidor.dados.etapasConcluidas"), "servidor agora tem o passo2")

print("\n== 4. Envios em fila, sempre com o estado mais recente ==")
ctx.eval("""envios = []; maxAbertos = 0; segurarEnvios = true;
p.estado.etapasConcluidas.passo3 = true; var e1 = p.salvar();
p.estado.etapasConcluidas.passo4 = true; var e2 = p.salvar();""")
rodar_jobs()
checa(js("envios.length") == 1, f"com o 1º envio parado, o 2º não saiu ({js('envios.length')} saíram)")
ctx.eval("liberar.shift()()")
rodar_jobs()
checa(js("envios.length") == 2, "liberado o 1º, o 2º saiu")
ctx.eval("segurarEnvios = false; liberar.shift()()")
rodar_jobs()
checa(js("maxAbertos") == 1, f"nunca mais de um envio aberto (máximo {js('maxAbertos')})")
checa("passo4" in js("servidor.dados.etapasConcluidas"), "servidor terminou com o estado mais recente")

print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
sys.exit(1 if falhas else 0)
