"""Modo de IA simulada: responde no lugar da API do Claude, sem chamada real.

Serve para depurar o teste de carga e testar o ciclo de vida do job sem pagar
geração. A simulação substitui só o envio HTTP (ver _enviar_para_ia em main.py).
Semáforo, heartbeat, contagem de tentativas, tratamento de status HTTP,
extração do JSON e esperas entre tentativas rodam exatamente como no modo real.

Variáveis de ambiente (lidas por configurar(), chamado por main.py depois do
load_dotenv):

    IA_SIMULADA=true            liga o modo. Qualquer outro valor, ou ausente: desligado.
    IA_SIMULADA_ESPERA=min,max  segundos sorteados por tentativa do plano.
    IA_SIMULADA_ESPERA_LISTA=min,max   o mesmo, para /api/vagas.
    IA_SIMULADA_FALHA=0.0       probabilidade de cada tentativa falhar, de 0 a 1.
                                Com 1, toda tentativa falha e tentativas chega a 3.
    IA_SIMULADA_TIPO_FALHA=529  529 | 429 | timeout | conexao | json

Valor inválido em qualquer uma delas impede a aplicação de iniciar.
"""
import asyncio
import json
import os
import random
from dataclasses import dataclass

import httpx

# Faixa padrão da espera do plano: três gerações reais completas medidas em
# 01/11/2026 no ambiente local, uma de cada vez, sem concorrência
# (chamada= 100,8 s, 93,6 s e 94,4 s no log). Sob carga de 31 alunos a duração
# real provavelmente é maior. É um padrão provisório, não medição de produção.
ESPERA_PLANO_PADRAO = (93.6, 100.8)

# Faixa padrão da espera de /api/vagas (max_tokens 2000): três chamadas reais
# medidas em 01/11/2026 no ambiente local, uma de cada vez, sem concorrência
# (23,0 s, 18,6 s e 20,6 s; listas de 6 itens). Medidas no cliente, em volta da
# requisição, porque chamar_ia_lista não registra a duração no log. Mesma
# ressalva do plano: padrão provisório, não medição de produção.
ESPERA_LISTA_PADRAO = (18.6, 23.0)

TIPOS_FALHA = ("529", "429", "timeout", "conexao", "json")

_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_DIR, "ia_simulada_plano.json"), encoding="utf-8") as _f:
    # Plano real gerado para um perfil fictício em 01/11/2026, com "[SIMULADO]"
    # no perfilLabel e na mensagemPersonalizada, para que qualquer pessoa olhando
    # a tela de resultado ou o painel admin perceba que não é um plano de verdade.
    PLANO_SIMULADO = json.load(_f)

LISTA_SIMULADA = [
    {
        "titulo": f"[SIMULADO] Oportunidade de exemplo {i}",
        "empresa": "[SIMULADO] Instituição fictícia",
        "descricao": "Item gerado pelo modo IA_SIMULADA. Não corresponde a nenhuma oportunidade real.",
        "comoAcessar": "Não acessar: este item existe só para teste.",
        "tipo": tipo,
        "gratuito": True,
    }
    for i, tipo in enumerate(["aprendiz", "estagio", "certificacao", "concurso", "aprendiz", "estagio"], 1)
]


@dataclass
class Config:
    ativa: bool = False
    espera_plano: tuple = ESPERA_PLANO_PADRAO
    espera_lista: tuple = ESPERA_LISTA_PADRAO
    falha: float = 0.0
    tipo_falha: str = "529"


config = Config()


class ConfigInvalida(RuntimeError):
    pass


def _faixa(nome: str, padrao: tuple) -> tuple:
    bruto = os.getenv(nome)
    if bruto is None or bruto.strip() == "":
        return padrao
    try:
        minimo, maximo = (float(x) for x in bruto.split(","))
    except ValueError:
        raise ConfigInvalida(f"{nome}='{bruto}' inválida. Use 'min,max' em segundos, por exemplo '93.6,100.8'.")
    if minimo < 0 or maximo < minimo:
        raise ConfigInvalida(f"{nome}='{bruto}' inválida. Precisa de 0 <= min <= max.")
    return (minimo, maximo)


def carregar_config() -> Config:
    ativa = os.getenv("IA_SIMULADA", "false").lower() == "true"
    falha_bruta = os.getenv("IA_SIMULADA_FALHA", "0")
    try:
        falha = float(falha_bruta)
    except ValueError:
        raise ConfigInvalida(f"IA_SIMULADA_FALHA='{falha_bruta}' inválida. Use um número de 0 a 1.")
    if not 0.0 <= falha <= 1.0:
        raise ConfigInvalida(f"IA_SIMULADA_FALHA='{falha_bruta}' inválida. Use um número de 0 a 1.")
    tipo = os.getenv("IA_SIMULADA_TIPO_FALHA", "529").lower()
    if tipo not in TIPOS_FALHA:
        raise ConfigInvalida(f"IA_SIMULADA_TIPO_FALHA='{tipo}' inválida. Use um de: {', '.join(TIPOS_FALHA)}.")
    return Config(
        ativa=ativa,
        espera_plano=_faixa("IA_SIMULADA_ESPERA", ESPERA_PLANO_PADRAO),
        espera_lista=_faixa("IA_SIMULADA_ESPERA_LISTA", ESPERA_LISTA_PADRAO),
        falha=falha,
        tipo_falha=tipo,
    )


def configurar() -> Config:
    global config
    config = carregar_config()
    return config


def aviso_startup() -> str:
    c = config
    return (
        "🧪🧪🧪 IA SIMULADA LIGADA (IA_SIMULADA=true): NENHUMA chamada real à API do Claude "
        "vai acontecer. Os planos gravados são uma resposta pronta marcada com [SIMULADO]. "
        f"Espera do plano {c.espera_plano[0]}-{c.espera_plano[1]} s, "
        f"espera de vagas {c.espera_lista[0]}-{c.espera_lista[1]} s, "
        f"falha {c.falha:.0%} por tentativa (tipo {c.tipo_falha}). "
        "Nunca use isso em produção."
    )


class RespostaSimulada:
    """Imita o que main.py usa de httpx.Response: status_code, json() e text."""

    def __init__(self, status_code: int, corpo: dict):
        self.status_code = status_code
        self._corpo = corpo

    def json(self):
        return self._corpo

    @property
    def text(self):
        return json.dumps(self._corpo, ensure_ascii=False)


async def enviar(tipo: str) -> RespostaSimulada:
    """Simula um POST para /v1/messages. tipo: 'plano' (chamar_ia) ou 'lista' (chamar_ia_lista)."""
    c = config
    faixa = c.espera_plano if tipo == "plano" else c.espera_lista
    duracao = random.uniform(*faixa)
    falhar = random.random() < c.falha

    if falhar and c.tipo_falha == "conexao":
        # Falha de conexão real acontece no início, sem esperar a geração.
        await asyncio.sleep(min(duracao, 1.0))
        raise httpx.ConnectError("[SIMULADO] falha de conexão")

    await asyncio.sleep(duracao)

    if falhar:
        if c.tipo_falha == "timeout":
            raise httpx.ReadTimeout("[SIMULADO] timeout")
        if c.tipo_falha in ("429", "529"):
            return RespostaSimulada(int(c.tipo_falha), {"error": {"message": f"[SIMULADO] erro {c.tipo_falha}"}})
        if c.tipo_falha == "json":
            # Sem colchetes nem chaves, para não casar com as regex que extraem JSON.
            return RespostaSimulada(200, {"content": [{"text": "SIMULADO: resposta sem JSON"}]})

    conteudo = PLANO_SIMULADO if tipo == "plano" else LISTA_SIMULADA
    return RespostaSimulada(200, {"content": [{"text": json.dumps(conteudo, ensure_ascii=False)}]})
