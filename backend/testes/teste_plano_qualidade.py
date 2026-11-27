"""Verificações do Bloco 5 (qualidade do plano) que não precisam de banco.

Não usa MySQL nem a API do Claude: a chamada à IA é substituída por uma
função que devolve um plano pronto e guarda o prompt recebido, e o banco é
um pool falso em memória. As variáveis obrigatórias recebem valores falsos
antes de importar main.py.

Como rodar, da raiz do repositório:

    .venv/Scripts/python.exe backend/testes/teste_plano_qualidade.py

Cobre: data de hoje por extenso, no horário de Brasília, no prompt e com a
instrução de prazos; cidade entrando no prompt quando existe (perfil ou
pergunta 3) e o prompt inteiro sem ela; schema sem campo status; status
vindo da IA descartado antes de gravar; cálculo de pendente, concluído (com
e sem data) e vencido a partir de progresso simulado; data de conclusão
sempre do servidor; data de referência gravada no job.
"""
import asyncio, json, logging, os, sys
from datetime import date, datetime, timezone

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BACKEND)

os.environ.update({
    "ANTHROPIC_API_KEY": "chave-falsa-de-teste-0000",
    "AMBIENTE": "local",
    "JWT_SECRET": "segredo-falso-de-teste",
    "ADMIN_SECRET": "admin-falso-de-teste",
})
os.environ.pop("IA_SIMULADA", None)
sys.stdout.reconfigure(encoding="utf-8")

import main

logging.getLogger().setLevel(logging.CRITICAL)

falhas = 0
def checa(cond, desc):
    global falhas
    print(("  OK    " if cond else "  FALHA ") + desc, flush=True)
    if not cond:
        falhas += 1

HOJE = date(2026, 11, 26)

print("\n== 1. Data de hoje ==")
checa(main.data_por_extenso(HOJE) == "26 de novembro de 2026", f"por extenso: {main.data_por_extenso(HOJE)}")
checa(main.data_por_extenso(date(2027, 3, 1)) == "1 de março de 2027", "mês com acento, dia sem zero")
# 02:30 UTC do dia 27 ainda é dia 26 em Brasília (UTC-3).
checa(main.hoje_brasilia(datetime(2026, 11, 27, 2, 30, tzinfo=timezone.utc)) == HOJE, "fuso de Brasília na virada do dia")
checa(main.hoje_brasilia(datetime(2026, 11, 27, 3, 0, tzinfo=timezone.utc)) == date(2026, 11, 27), "03:00 UTC já é o dia seguinte")
prompt = main.montar_prompt_base("Aluna", "  [1] A", "", hoje=HOJE, cidade=None)
checa("DATA DE HOJE: 26 de novembro de 2026 (2026-11-26)." in prompt, "data no prompt, por extenso e em ISO")
checa("posterior a essa data" in prompt, "instrução: prazos posteriores à data")
checa("próxima ocorrência" in prompt and "ano correto" in prompt, "instrução: prazo vencido vira a próxima ocorrência, com o ano")

print("\n== 2. Cidade ==")
com = main.montar_prompt_base("Aluna", "  [1] A", "", hoje=HOJE, cidade="Ferraz de Vasconcelos - SP")
checa("LOCALIZAÇÃO DO ALUNO: Ferraz de Vasconcelos - SP" in com, "cidade no prompt quando existe")
checa("transporte público" in com, "instrução de priorizar o alcançável de transporte público")
checa("LOCALIZAÇÃO DO ALUNO" not in prompt and "transporte público" not in prompt, "sem cidade, o bloco some")
for p, rotulo in ((prompt, "sem cidade"), (com, "com cidade")):
    checa("DADOS DO USUÁRIO" in p and p.rstrip().endswith("}") and '"mapaCarreira"' in p,
          f"prompt {rotulo} segue inteiro até o fim do schema")
resp3 = {"3": {"valor": "Poá - SP", "textoLivre": ""}}
checa(main.cidade_do_aluno({"cidade": "Suzano - SP"}, resp3) == "Suzano - SP", "perfil tem prioridade")
checa(main.cidade_do_aluno({"cidade": None}, resp3) == "Poá - SP", "sem perfil, usa a pergunta 3")
checa(main.cidade_do_aluno({}, {}) is None, "sem nenhum dos dois: None")
checa(main.cidade_do_aluno({"cidade": "  "}, {"3": {"valor": "  "}}) is None, "só espaços conta como ausente")

print("\n== 3. Status fora do schema e descartado da resposta ==")
checa('"status"' not in prompt and "done|active|locked" not in prompt, "schema do prompt não pede status")
checa('"dataLimite"' in prompt, "schema pede dataLimite")
plano = {"mapaCarreira": [
    {"id": "a", "titulo": "A", "status": "done", "dataLimite": "2027-01-20"},
    {"id": "b", "titulo": "B", "status": "locked", "dataLimite": "janeiro"},
]}
limpo = main.limpar_plano_ia(plano)
checa(all("status" not in p for p in limpo["mapaCarreira"]), "status da IA removido antes de gravar")
checa([p["dataLimite"] for p in limpo["mapaCarreira"]] == ["2027-01-20", None], "dataLimite inválida vira None")

print("\n== 4. Cálculo do status a partir do progresso ==")
passos = [
    {"id": "feito", "titulo": "Feito", "status": "locked"},                 # IA dizendo locked, aluno marcou
    {"id": "antigo", "titulo": "Antigo"},                                    # marcado antes de existir data
    {"id": "aberto", "titulo": "Aberto", "status": "done"},                  # IA dizendo done, aluno não marcou
    {"id": "perdido", "titulo": "Perdido", "dataLimite": "2026-11-25"},      # prazo foi ontem
    {"id": "hoje", "titulo": "Hoje", "dataLimite": "2026-11-26"},            # último dia é hoje
    {"id": "feito-tarde", "titulo": "Feito", "dataLimite": "2026-01-10"},    # prazo passou, mas foi feito
    {"titulo": "Sem id"},                                                    # chave step-6, como no front
]
etapas = {"feito": "2026-11-20T14:00:00Z", "antigo": True, "feito-tarde": "2026-01-05T10:00:00Z", "step-6": True}
r = {p.get("id") or "sem-id": p for p in main.calcular_status_passos(passos, etapas, HOJE)}
checa(r["feito"]["status"] == "concluido" and r["feito"]["concluidoEm"] == "2026-11-20T14:00:00Z", "marcado: concluído com a data do banco")
checa(r["antigo"]["status"] == "concluido" and r["antigo"]["concluidoEm"] is None, "marcação antiga: concluído, sem inventar data")
checa(r["aberto"]["status"] == "pendente", "sem marcação: pendente, mesmo com a IA dizendo done")
checa(r["perdido"]["status"] == "vencido" and r["perdido"]["prazoVencido"], "prazo passou sem marcação: vencido")
checa(r["hoje"]["status"] == "pendente" and not r["hoje"]["prazoVencido"], "último dia é hoje: ainda pendente")
checa(r["feito-tarde"]["status"] == "concluido", "concluído não vira vencido")
checa(r["sem-id"]["status"] == "concluido", "passo sem id usa a mesma chave do front (step-<posição>)")
checa(main.calcular_status_passos([], etapas, HOJE) == [], "lista vazia")

print("\n== 5. Data de conclusão é do servidor ==")
existentes = {"a": "2026-11-01T10:00:00Z", "b": True}
m = main.mesclar_conclusoes(existentes, {"a": True, "b": True, "c": "2020-01-01T00:00:00Z", "d": False}, "2026-11-26T15:00:00Z")
checa(m["a"] == "2026-11-01T10:00:00Z", "já marcada: mantém a data antiga")
checa(m["b"] is True, "marcação antiga sem data: continua sem data")
checa(m["c"] == "2026-11-26T15:00:00Z", "nova: data do servidor, a do navegador é ignorada")
checa("d" not in m, "desmarcada sai")

print("\n== 6. Geração: data e cidade no prompt, data no job, status descartado ==")
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

recebidos = []
async def ia_falsa(prompt, job_id=None):
    recebidos.append(prompt)
    return {"areaPrincipal": "TI", "mapaCarreira": [{"id": "x", "titulo": "X", "status": "done"}]}
chamar_original, hoje_original = main.chamar_ia, main.hoje_brasilia
main.chamar_ia = ia_falsa
main.hoje_brasilia = lambda agora_utc=None: HOJE
main.db_pool = PoolFalso()
try:
    asyncio.run(main.processar_resultado_ia_db("job-1", "u-1", {"id": "u-1", "nome": "Aluna", "cidade": "Mogi das Cruzes - SP"}, "Teste"))
finally:
    main.chamar_ia, main.hoje_brasilia = chamar_original, hoje_original
log = main.db_pool.log
checa(len(recebidos) == 1 and "26 de novembro de 2026" in recebidos[0], "prompt da geração tem a data")
checa(recebidos and "LOCALIZAÇÃO DO ALUNO: Mogi das Cruzes - SP" in recebidos[0], "prompt da geração tem a cidade do perfil")
ref = [p for sql, p in log if sql.startswith("UPDATE jobs SET data_referencia")]
checa(ref == [(HOJE, "job-1")], f"data de referência gravada no job: {ref}")
salvo = [p for sql, p in log if sql.lstrip().startswith("INSERT INTO perfis")]
plano_salvo = json.loads(salvo[0][1]) if salvo else {}
checa(salvo and "status" not in plano_salvo["mapaCarreira"][0], "plano gravado sem o status da IA")
checa(any(sql.startswith("UPDATE jobs SET status='concluido'") for sql, _ in log), "job concluído")

print(f"\n{'TUDO OK' if falhas == 0 else f'{falhas} FALHA(S)'}")
sys.exit(1 if falhas else 0)
