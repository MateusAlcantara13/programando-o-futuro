"""Verificações de robustez da chamada à IA que não precisam de banco.

Não usa MySQL: o banco, quando aparece, é um pool falso em memória. A API do
Claude também é simulada (_enviar_para_ia substituída), então nenhuma
chamada real sai da máquina. As variáveis obrigatórias recebem valores
falsos antes de importar main.py.

Como rodar, da raiz do repositório:

    .venv/Scripts/python.exe backend/testes/teste_robustez_ia.py

Leva menos de 5 s: as esperas entre tentativas são encurtadas.

Cobre: validação de IA_TIMEOUT_S; timeout da variável chegando na chamada;
limite de job travado acompanhando o timeout; validação de
IA_MAX_CONCORRENTES_LISTA e IA_MAX_RECUPERACOES; resposta truncada falhando
na primeira tentativa, sem retry, e com mensagem própria no job; JSON
inválido sem truncagem continuando no retry; /api/vagas com semáforo
próprio, sem esperar atrás da geração do plano.
"""
import asyncio, logging, os, sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

# Antes de importar main: load_dotenv não sobrescreve variável já definida,
# então nenhum valor real do .env é carregado para estas.
os.environ["ANTHROPIC_API_KEY"] = "chave-falsa-de-teste-0000"
os.environ["AMBIENTE"] = "local"
os.environ["JWT_SECRET"] = "segredo-falso-de-teste"
os.environ["ADMIN_SECRET"] = "admin-falso-de-teste"
for var in ("IA_TIMEOUT_S", "IA_MAX_CONCORRENTES_LISTA", "IA_MAX_RECUPERACOES",
            "IA_SIMULADA", "IA_SIMULADA_FALHA", "IA_SIMULADA_TIPO_FALHA"):
    os.environ.pop(var, None)

sys.stdout.reconfigure(encoding="utf-8")

import main

logging.getLogger().setLevel(logging.CRITICAL)

falhas = 0

def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1


# ── API simulada ──────────────────────────────────────────────────────────────
class RespostaFalsa:
    def __init__(self, corpo):
        self.status_code = 200
        self.text = ""
        self._corpo = corpo
    def json(self):
        return self._corpo

def resposta(texto, stop_reason="end_turn"):
    return RespostaFalsa({"content": [{"text": texto}], "stop_reason": stop_reason})

chamadas = []

def api_que_responde(r):
    async def enviar(prompt, max_tokens, timeout, tipo):
        chamadas.append({"tipo": tipo, "timeout": timeout, "max_tokens": max_tokens})
        return r
    return enviar


# ── Banco falso: registra os comandos, devolve vazio ──────────────────────────
class CursorFalso:
    rowcount = 1
    def __init__(self, log): self.log = log
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def execute(self, sql, params=None): self.log.append((sql, params))
    async def fetchall(self): return []
    async def fetchone(self): return None

class ConexaoFalsa:
    def __init__(self, log): self.log = log
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def cursor(self, *a): return CursorFalso(self.log)

class PoolFalso:
    def __init__(self): self.log = []
    def acquire(self): return ConexaoFalsa(self.log)


async def main_teste():
    enviar_original = main._enviar_para_ia
    sleep_original = asyncio.sleep
    async def sleep_rapido(_segundos):
        await sleep_original(0)

    try:
        # ── 1. IA_TIMEOUT_S ──────────────────────────────────────────────────
        print("\n== 1. IA_TIMEOUT_S: padrão, valor válido e valores recusados ==")
        checa(main.IA_TIMEOUT_S == 300, f"padrão sem a variável: {main.IA_TIMEOUT_S}")
        os.environ["IA_TIMEOUT_S"] = "180"
        checa(main._segundos_positivos("IA_TIMEOUT_S", "300") == 180, "valor 180 aceito")
        for ruim in ("abc", "0", "-5", "nan", "inf", ""):
            os.environ["IA_TIMEOUT_S"] = ruim
            try:
                main._segundos_positivos("IA_TIMEOUT_S", "300")
                checa(False, f"'{ruim}' deveria ser recusado")
            except RuntimeError as e:
                checa("IA_TIMEOUT_S" in str(e), f"'{ruim}' recusado com mensagem que cita a variável")
        os.environ.pop("IA_TIMEOUT_S")

        # ── 2. Limite de job travado derivado do timeout ──────────────────────
        print("\n== 2. Limite de job travado acompanha o timeout ==")
        checa(main.limite_job_travado_s(300) == 690, f"timeout 300 s: limite {main.limite_job_travado_s(300)} s")
        checa(main.limite_job_travado_s(120) == 330, f"timeout 120 s: limite {main.limite_job_travado_s(120)} s")
        checa(main.LIMITE_JOB_TRAVADO_S == main.limite_job_travado_s(main.IA_TIMEOUT_S),
              "LIMITE_JOB_TRAVADO_S calculado do IA_TIMEOUT_S em uso")
        pior = (main.IA_CONNECT_TIMEOUT_S + 300 + max(main.ESPERA_ENTRE_TENTATIVAS)
                + main.ESPERA_EXTRA_RATE_LIMIT + main.HEARTBEAT_TIMEOUT_S)
        checa(main.limite_job_travado_s(300) > pior, f"limite maior que o pior intervalo entre heartbeats ({pior:.0f} s)")

        # ── 2b. Inteiros novos ────────────────────────────────────────────────
        print("\n== 2b. IA_MAX_CONCORRENTES_LISTA e IA_MAX_RECUPERACOES ==")
        checa(main.IA_MAX_CONCORRENTES_LISTA == 2, f"padrão da lista: {main.IA_MAX_CONCORRENTES_LISTA}")
        checa(main.IA_MAX_RECUPERACOES == 2, f"padrão do teto de recuperações: {main.IA_MAX_RECUPERACOES}")
        for ruim in ("0", "-1", "2.5", "abc", ""):
            os.environ["IA_MAX_RECUPERACOES"] = ruim
            try:
                main._inteiro_positivo("IA_MAX_RECUPERACOES", "3")
                checa(False, f"'{ruim}' deveria ser recusado")
            except RuntimeError as e:
                checa("IA_MAX_RECUPERACOES" in str(e), f"'{ruim}' recusado")
        os.environ.pop("IA_MAX_RECUPERACOES")

        # ── 3. Resposta truncada: uma chamada só ──────────────────────────────
        print("\n== 3. stop_reason=max_tokens falha na 1ª tentativa, sem retry ==")
        asyncio.sleep = sleep_rapido
        chamadas.clear()
        # Texto cortado que mesmo assim tem chaves balanceadas: passaria no parse.
        main._enviar_para_ia = api_que_responde(resposta('{"perfil": {"nome": "x"}}', "max_tokens"))
        try:
            await main.chamar_ia("prompt truncado")
            checa(False, "deveria ter levantado RespostaTruncada")
        except main.RespostaTruncada:
            checa(True, "levantou RespostaTruncada")
        checa(len(chamadas) == 1, f"chamadas à API: {len(chamadas)} (esperado 1)")
        checa(chamadas[0]["timeout"] == main.IA_TIMEOUT_S, f"timeout usado na chamada: {chamadas[0]['timeout']}")

        # ── 4. JSON inválido sem truncagem continua no retry ──────────────────
        print("\n== 4. JSON inválido com stop_reason=end_turn continua tendo 3 tentativas ==")
        chamadas.clear()
        main._enviar_para_ia = api_que_responde(resposta("sem json nenhum", "end_turn"))
        try:
            await main.chamar_ia("prompt invalido")
            checa(False, "deveria ter levantado RuntimeError")
        except main.RespostaTruncada:
            checa(False, "não deveria ser tratado como truncagem")
        except RuntimeError:
            checa(True, "levantou RuntimeError")
        checa(len(chamadas) == 3, f"chamadas à API: {len(chamadas)} (esperado 3)")

        # ── 5. Mensagem do job no painel ──────────────────────────────────────
        print("\n== 5. Job com resposta truncada grava mensagem de limite de tokens ==")
        pool_original = main.db_pool
        main.db_pool = PoolFalso()
        main._enviar_para_ia = api_que_responde(resposta('{"a": 1', "max_tokens"))
        await main.processar_resultado_ia_db("job-trunc", "u-1", {"id": "u-1", "nome": "Aluno"}, "Teste inicial")
        erros = [p for sql, p in main.db_pool.log if sql.startswith("UPDATE jobs SET status='erro'")]
        checa(len(erros) == 1, f"job marcado como erro uma vez ({len(erros)})")
        msg = erros[0][0] if erros else ""
        checa("limite de tokens" in msg and "Não é instabilidade" in msg, f"mensagem: {msg.strip()}")
        checa("formato inválido" not in msg, "não caiu no ramo de formato inválido")
        main.db_pool = pool_original

        # ── 6. /api/vagas tem semáforo próprio ────────────────────────────────
        main._enviar_para_ia = api_que_responde(resposta("[]", "end_turn"))

        print("\n== 6a. Lista não espera atrás da geração do plano ==")
        chamadas.clear()
        main.ia_semaphore = asyncio.Semaphore(1)
        main.ia_semaphore_lista = asyncio.Semaphore(1)
        await main.ia_semaphore.acquire()  # vaga do plano ocupada por uma geração
        r = await asyncio.wait_for(main.chamar_ia_lista("prompt vagas"), timeout=2)
        checa(len(chamadas) == 1 and r == [], "com o semáforo do plano cheio, a lista saiu na hora")
        main.ia_semaphore.release()

        print("\n== 6b. Lista espera vaga no próprio semáforo ==")
        chamadas.clear()
        await main.ia_semaphore_lista.acquire()  # vaga única da lista ocupada
        tarefa = asyncio.create_task(main.chamar_ia_lista("prompt vagas"))
        await sleep_original(0.3)
        checa(chamadas == [], "com a vaga da lista ocupada, nenhuma chamada saiu")
        main.ia_semaphore_lista.release()
        r = await asyncio.wait_for(tarefa, timeout=2)
        checa(len(chamadas) == 1 and chamadas[0]["tipo"] == "lista" and r == [],
              "depois de liberada a vaga, a chamada saiu e devolveu a lista")
    finally:
        main._enviar_para_ia = enviar_original
        asyncio.sleep = sleep_original

    print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
    sys.exit(1 if falhas else 0)

asyncio.run(main_teste())
