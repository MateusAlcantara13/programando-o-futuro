from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool
from typing import Optional
from dotenv import load_dotenv
from datetime import datetime, timedelta
import asyncio, httpx, os, logging, jwt, uuid, json, re, random, ssl, hmac, time
import aiomysql
import bcrypt
from migracoes.jobs_heartbeat import migrar_jobs_heartbeat, verificar_jobs_heartbeat
from migracoes.mapa_progresso_usuario_id import (
    migrar_mapa_progresso_usuario_id, verificar_mapa_progresso_usuario_id,
)
from migracoes.usuarios_aceite_lgpd import migrar_usuarios_aceite_lgpd, verificar_usuarios_aceite_lgpd
import ia_simulada

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
BASE_DIR = os.path.join(os.path.dirname(__file__), "..")


def _variavel_obrigatoria(nome: str) -> str:
    """Lê uma variável de ambiente obrigatória. Ausente ou vazia, a aplicação não sobe.

    A mensagem de erro cita só o nome da variável, nunca o valor.
    """
    valor = os.getenv(nome, "")
    if not valor.strip():
        raise RuntimeError(
            f"Variável de ambiente {nome} não definida. A aplicação não inicia sem ela. "
            "Veja backend/.env.example."
        )
    return valor


# Onde a aplicação está rodando: "local" ou "producao". Obrigatória e sem
# valor padrão. Com padrão "local", esquecer a variável no servidor
# desligaria em silêncio as travas de produção logo abaixo.
AMBIENTES_VALIDOS = ("local", "producao")
AMBIENTE = _variavel_obrigatoria("AMBIENTE").strip()
if AMBIENTE not in AMBIENTES_VALIDOS:
    raise RuntimeError(
        f"AMBIENTE='{AMBIENTE}' inválido. Use um de: {', '.join(AMBIENTES_VALIDOS)}."
    )


# Origens que o navegador pode usar para chamar a API (CORS). O próprio
# backend serve o front, então as páginas do sistema são da mesma origem e
# não dependem desta lista: ela só decide quais OUTROS sites podem chamar a
# API a partir do navegador. Nunca "*".
CORS_ORIGENS_PADRAO_LOCAL = ("http://localhost:8000", "http://127.0.0.1:8000")

def carregar_cors_origens(ambiente: str, bruto: Optional[str]) -> list:
    """Lê CORS_ORIGENS (separada por vírgula). Valor inválido impede a aplicação de iniciar.

    Em produção a variável é obrigatória: é melhor falhar no deploy do que
    servir liberado. Em local, sem a variável, vale o localhost do uvicorn.
    """
    # Só vírgulas e espaços (" , ") conta como ausente: uma lista vazia em
    # produção deixaria a aplicação subir sem nenhuma origem configurada.
    if bruto is None or not [o for o in bruto.split(",") if o.strip()]:
        if ambiente == "producao":
            raise RuntimeError(
                "CORS_ORIGENS não definida com AMBIENTE=producao. Defina a lista de origens "
                "permitidas, separadas por vírgula, por exemplo https://exemplo.com.br"
            )
        return list(CORS_ORIGENS_PADRAO_LOCAL)
    origens = [o.strip() for o in bruto.split(",") if o.strip()]
    for o in origens:
        if o == "*" or not re.fullmatch(r"https?://[^/\s*]+", o):
            raise RuntimeError(
                f"CORS_ORIGENS contém '{o}', que não é uma origem válida. Use esquema e host, "
                "sem barra no final e sem '*', por exemplo https://exemplo.com.br"
            )
    return origens

CORS_ORIGENS = carregar_cors_origens(AMBIENTE, os.getenv("CORS_ORIGENS"))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
# Sem valor padrão: quem conhece o segredo assina token de qualquer usuário.
JWT_SECRET        = _variavel_obrigatoria("JWT_SECRET")
JWT_EXPIRES_H     = int(os.getenv("JWT_EXPIRES_H", "24"))
# Senha das rotas /api/admin/*. Sem valor padrão: o valor antigo está no
# histórico público do repositório.
ADMIN_SECRET      = _variavel_obrigatoria("ADMIN_SECRET")
IA_MAX_CONCORRENTES = int(os.getenv("IA_MAX_CONCORRENTES", "5"))


def _inteiro_positivo(nome: str, padrao: str) -> int:
    """Lê um inteiro maior que zero da variável de ambiente. Valor inválido impede a aplicação de iniciar."""
    bruto = os.getenv(nome, padrao).strip()
    try:
        valor = int(bruto)
    except ValueError:
        valor = 0
    if valor < 1:
        raise RuntimeError(f"{nome}='{bruto}' inválido. Use um inteiro maior que zero, por exemplo {padrao}.")
    return valor


# Limite próprio para as chamadas curtas de lista (/api/vagas). Separado do
# limite da geração do plano para a chamada de ~20 s não esperar atrás de uma
# fila de gerações de ~100 s. O teto real de chamadas simultâneas à API é
# IA_MAX_CONCORRENTES + IA_MAX_CONCORRENTES_LISTA.
IA_MAX_CONCORRENTES_LISTA = _inteiro_positivo("IA_MAX_CONCORRENTES_LISTA", "2")
# Quantas vezes a recuperação pode reenfileirar o mesmo job. No teto, o job é
# encerrado como erro: sem isso, um job que derruba o processo voltaria para
# a fila a cada reinício, e cada volta é uma geração paga.
# CUSTO NO PIOR CASO: recuperações e tentativas se multiplicam. Cada
# recuperação é uma execução nova com as suas próprias 3 tentativas. Com o
# padrão 2: (1 execução original + 2 recuperações) x 3 tentativas = até 9
# chamadas pagas para o mesmo aluno. Fórmula: (IA_MAX_RECUPERACOES + 1) x 3.
# O número definitivo sai do teste de carga.
IA_MAX_RECUPERACOES = _inteiro_positivo("IA_MAX_RECUPERACOES", "2")


def _segundos_positivos(nome: str, padrao: str) -> float:
    """Lê um tempo em segundos da variável de ambiente. Valor inválido impede a aplicação de iniciar."""
    bruto = os.getenv(nome, padrao).strip()
    try:
        valor = float(bruto)
    except ValueError:
        valor = float("nan")
    # A comparação dupla recusa também nan e infinito.
    if not 0 < valor < float("inf"):
        raise RuntimeError(
            f"{nome}='{bruto}' inválido. Use um número de segundos maior que zero, por exemplo {padrao}."
        )
    return valor


# Timeout de leitura da chamada que gera o plano. Uma geração real leva de
# 94 a 101 s (medido em 01/11/2026). Com 120 s a folga era de 20 a 26 s, e
# cada estouro dispara um retry que gera o plano inteiro de novo. O valor
# definitivo sai do teste de carga. Um timeout alto só é seguro porque o
# semáforo limita quantas chamadas ficam abertas ao mesmo tempo.
# Custo aceito em 26/11/2026, a medir no teste de carga antes de otimizar:
# no pior caso, as três tentativas estouram o tempo e um único job ocupa uma
# vaga do semáforo por cerca de 3 x IA_TIMEOUT_S mais as esperas (~15 min
# com 300 s), enquanto os outros alunos esperam na fila.
IA_TIMEOUT_S        = _segundos_positivos("IA_TIMEOUT_S", "300")
# TLS do banco é obrigatório por padrão: sem DB_SSL_DISABLED=true explícito,
# o comportamento é o de sempre exigir TLS. Esquecer de configurar quebra a
# conexão em vez de conectar sem TLS silenciosamente.
DB_SSL_DISABLED   = os.getenv("DB_SSL_DISABLED", "false").lower() == "true"
# Caminho do certificado da CA. O processo pode ser iniciado de dentro de
# backend/ ou da raiz, e um caminho relativo comum dependeria disso. Por
# isso, caminho relativo em DB_SSL_CA é sempre lido a partir da raiz do
# repositório, e sem a variável vale o ca.pem que fica ao lado deste arquivo.
_db_ssl_ca_env    = os.getenv("DB_SSL_CA", "").strip()
if not _db_ssl_ca_env:
    DB_SSL_CA     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ca.pem")
elif os.path.isabs(_db_ssl_ca_env):
    DB_SSL_CA     = _db_ssl_ca_env
else:
    DB_SSL_CA     = os.path.normpath(os.path.join(os.path.abspath(BASE_DIR), _db_ssl_ca_env))
# IA simulada: desligada por padrão, só liga com IA_SIMULADA=true explícito.
# Valor inválido nas variáveis IA_SIMULADA_* impede a aplicação de iniciar.
ia_simulada.configurar()

# Travas de produção: modos que só fazem sentido na máquina de quem
# desenvolve impedem a aplicação de subir com AMBIENTE=producao.
if AMBIENTE == "producao":
    if ia_simulada.config.ativa:
        raise RuntimeError(
            "IA_SIMULADA=true não é permitido com AMBIENTE=producao: todo plano gerado "
            "seria falso. Remova IA_SIMULADA das variáveis de produção."
        )
    if DB_SSL_DISABLED:
        raise RuntimeError(
            "DB_SSL_DISABLED=true não é permitido com AMBIENTE=producao: a conexão com o "
            "banco seguiria sem TLS. Remova DB_SSL_DISABLED das variáveis de produção."
        )
logger.info(f"🌎 Ambiente: {AMBIENTE}")

# Só registra se a chave existe. Nenhum pedaço do valor vai para o log.
if ANTHROPIC_API_KEY:
    logger.info("✅ ANTHROPIC_API_KEY definida")
else:
    logger.error("❌ ANTHROPIC_API_KEY não encontrada!")

app = FastAPI(title="Programando o Futuro API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGENS, allow_methods=["*"], allow_headers=["*"])
@app.on_event("startup")
async def startup():
    if ia_simulada.config.ativa:
        logger.warning(ia_simulada.aviso_startup())
    await init_db()
    logger.info(f"🌐 Origens permitidas (CORS): {', '.join(CORS_ORIGENS)}")
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                n_texto_plano = await contar_senhas_texto_plano(cur)
        if n_texto_plano > 0:
            logger.warning(
                f"⚠️ {n_texto_plano} usuário(s) ainda com senha em TEXTO PLANO no banco. Cada um vira "
                "hash no próximo login. O caminho de texto plano em verificar_senha só pode ser "
                "apagado quando este número chegar a zero."
            )
        else:
            logger.info("🔐 Senhas: nenhum usuário com senha em texto plano")
    except Exception as e:
        # Medição, não trava: não impede a aplicação de subir.
        logger.error(f"Contagem de senhas em texto plano falhou: {type(e).__name__}: {e}")
    _obter_ia_semaphore()
    _obter_ia_semaphore_lista()
    logger.info(
        f"🚦 Chamadas simultâneas à IA: até {IA_MAX_CONCORRENTES} gerando plano e "
        f"{IA_MAX_CONCORRENTES_LISTA} gerando lista, teto total {IA_MAX_CONCORRENTES + IA_MAX_CONCORRENTES_LISTA}"
    )
    logger.info(f"⏱️ Timeout da chamada que gera o plano: {IA_TIMEOUT_S:.0f}s")
    try:
        await recuperar_jobs_orfaos()
    except Exception as e:
        # Não impede a aplicação de subir: atender os alunos vale mais. Os
        # órfãos ficam para a próxima inicialização, porque a varredura
        # periódica não toca em job com tentativas = 0.
        logger.error(f"Recuperação de jobs órfãos falhou na inicialização: {type(e).__name__}: {e}")
    app.state.varredura_jobs = asyncio.create_task(_varrer_jobs_periodicamente())
    logger.info(
        f"🧹 Varredura de jobs travados a cada {VARREDURA_JOBS_INTERVALO_S}s, "
        f"limite sem heartbeat {LIMITE_JOB_TRAVADO_S}s, até {IA_MAX_RECUPERACOES} recuperação(ões) por job"
    )

@app.on_event("shutdown")
async def shutdown():
    varredura = getattr(app.state, "varredura_jobs", None)
    if varredura:
        varredura.cancel()
security = HTTPBearer()


db_pool = None
ia_semaphore: Optional[asyncio.Semaphore] = None
ia_semaphore_lista: Optional[asyncio.Semaphore] = None

def _obter_ia_semaphore_lista() -> asyncio.Semaphore:
    """Semáforo das chamadas de lista (/api/vagas), criado sob demanda como o da geração do plano."""
    global ia_semaphore_lista
    if ia_semaphore_lista is None:
        ia_semaphore_lista = asyncio.Semaphore(IA_MAX_CONCORRENTES_LISTA)
    return ia_semaphore_lista

def _obter_ia_semaphore() -> asyncio.Semaphore:
    """Cria o semáforo sob demanda, caso chamar_ia seja usada sem o startup do app ter rodado (ex.: testes)."""
    global ia_semaphore
    if ia_semaphore is None:
        ia_semaphore = asyncio.Semaphore(IA_MAX_CONCORRENTES)
    return ia_semaphore

# ── BANCO DE DADOS ───────────────────────────────────────────────────────────
async def criar_pool():
    """Cria o pool de conexões. Usado pelo startup e pelo script manual de migração."""
    ssl_ctx = None
    if DB_SSL_DISABLED:
        logger.warning("⚠️ TLS do banco DESLIGADO (DB_SSL_DISABLED=true). Use isso só em ambiente local.")
    else:
        # check_hostname fica no padrão (True) do create_default_context: o
        # certificado precisa bater com o hostname de DB_HOST, não só com a CA.
        ssl_ctx = ssl.create_default_context(cafile=DB_SSL_CA)
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED
    pool = await aiomysql.create_pool(
        host=os.getenv("DB_HOST", ""),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASSWORD", ""),
        db=os.getenv("DB_NAME", "defaultdb"),
        ssl=ssl_ctx,
        autocommit=True,
        minsize=1,
        maxsize=10,
    )
    if not DB_SSL_DISABLED:
        await _confirmar_tls(pool)
    return pool

async def _confirmar_tls(pool):
    """Confere no servidor que a conexão está mesmo cifrada. Sem TLS, fecha o pool e aborta.

    Pedir TLS não garante que ele foi negociado. Quem decide é o handshake, e
    o MySQL informa o resultado em Ssl_cipher: vazio quer dizer texto claro.

    LIMITAÇÃO CONHECIDA: a consulta vale só para a conexão aberta aqui, na
    inicialização. As conexões que o pool abrir depois não são conferidas.
    Ver no ROADMAP.md a hipótese do atacante que retira o anúncio de TLS do
    handshake, na seção de configuração de TLS do banco.
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
            linha = await cur.fetchone()
    cifra = linha[1] if linha else ""
    if not cifra:
        pool.close()
        await pool.wait_closed()
        raise RuntimeError(
            "A conexão com o banco foi aberta sem TLS (Ssl_cipher vazio). "
            "A aplicação não inicia sem TLS ativo."
        )
    logger.info(f"🔒 TLS do banco confirmado (cifra {cifra})")

async def init_db():
    global db_pool
    db_pool = await criar_pool()
    await criar_tabelas()
    # Migração antes de servir. Qualquer falha aqui sobe a exceção e o
    # startup é abortado: a aplicação não atende com esquema errado.
    async with db_pool.acquire() as conn:
        await migrar_jobs_heartbeat(conn)
        await verificar_jobs_heartbeat(conn)
        await migrar_mapa_progresso_usuario_id(conn)
        await verificar_mapa_progresso_usuario_id(conn)
        await migrar_usuarios_aceite_lgpd(conn)
        await verificar_usuarios_aceite_lgpd(conn)
    logger.info("✅ Banco de dados conectado!")

async def criar_tabelas():
    sql_statements = [
        """CREATE TABLE IF NOT EXISTS usuarios (
            id VARCHAR(36) PRIMARY KEY,
            nome VARCHAR(120) NOT NULL,
            email VARCHAR(120) NOT NULL UNIQUE,
            senha VARCHAR(255) NOT NULL,
            avatar_iniciais VARCHAR(10),
            aceite_lgpd BOOLEAN NOT NULL,
            aceite_lgpd_em DATETIME NULL,
            aceite_lgpd_versao VARCHAR(20) NULL,
            aceite_menor BOOLEAN DEFAULT FALSE,
            teste_inicial_concluido BOOLEAN DEFAULT FALSE,
            modulos_concluidos JSON DEFAULT ('[]'),
            cidade VARCHAR(100),
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS respostas_teste (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario_id VARCHAR(36) NOT NULL,
            pergunta_id VARCHAR(20) NOT NULL,
            valor TEXT,
            texto_livre TEXT,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_usuario_pergunta (usuario_id, pergunta_id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS respostas_modulo (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario_id VARCHAR(36) NOT NULL,
            modulo_id VARCHAR(10) NOT NULL,
            pergunta_id VARCHAR(30) NOT NULL,
            valor TEXT,
            texto_livre TEXT,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_usuario_modulo_pergunta (usuario_id, modulo_id, pergunta_id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS perfis (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario_id VARCHAR(36) NOT NULL UNIQUE,
            dados JSON NOT NULL,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS mapa_progresso (
            id INT AUTO_INCREMENT PRIMARY KEY,
            usuario_id VARCHAR(36) NOT NULL,
            etapas_concluidas TEXT,
            checks_feitos TEXT,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(usuario_id)
        )""",
        """CREATE TABLE IF NOT EXISTS jobs (
            id VARCHAR(36) PRIMARY KEY,
            usuario_id VARCHAR(36) NOT NULL,
            status ENUM('processando','concluido','erro') DEFAULT 'processando',
            erro TEXT,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            tentativas INT NOT NULL DEFAULT 0,
            atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            recuperacoes INT NOT NULL DEFAULT 0,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        )"""
        # Bancos que já existiam recebem essas duas colunas pela migração em
        # migracoes/jobs_heartbeat.py, chamada logo depois em init_db().
    ]
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            for sql in sql_statements:
                await cur.execute(sql)
    logger.info("✅ Tabelas verificadas/criadas!")


# ── Modelos Pydantic ───────────────────────────────────────────────────────────
class CadastroBody(BaseModel):
    nome: str
    email: str
    senha: str
    # Opcional no modelo de propósito: ausente vira None e recebe a mesma
    # recusa clara do cadastro, em vez do 422 genérico do Pydantic. StrictBool
    # aceita só true/false de JSON; "true" em texto ou 1 não valem como aceite.
    aceite_lgpd: Optional[StrictBool] = None
    versao_termo_lgpd: Optional[str] = None
    # Ignorado. Nenhuma tela coleta o consentimento dos responsáveis
    # (pendência da fase da rede pública), então nenhum valor que chegue aqui
    # significa algo. O cadastro grava NULL, que quer dizer "não coletado".
    aceite_menor: Optional[bool] = None

class LoginBody(BaseModel):
    email: str
    senha: str

class RespostaBody(BaseModel):
    perguntaId: str
    valor: str
    textoLivre: Optional[str] = None  # campo aberto opcional

class FinalizarTesteBody(BaseModel):
    respostas: list[dict]

class RespostaModuloBody(BaseModel):
    perguntaId: str
    valor: str
    textoLivre: Optional[str] = None

class ContextoLivreBody(BaseModel):
    chave: str
    texto: str

# ── Perguntas do Teste Inicial (completo) ──────────────────────────────────────
PERGUNTAS_TESTE = [
    # BLOCO 1 — Quem você é
    {"id":"1","bloco":"Quem você é","texto":"Qual é o seu nome? (pode ser só o primeiro nome)","tipo":"texto","placeholder":"Digite seu primeiro nome","obrigatorio":True},
    {"id":"2","bloco":"Quem você é","texto":"Quantos anos você tem?","tipo":"numero","placeholder":"Ex: 17","obrigatorio":True},
    {"id":"3","bloco":"Quem você é","texto":"Em qual cidade e estado você mora? ","tipo":"texto","placeholder":"Ex: Ferraz de Vasconcelos - SP","obrigatorio":True},
    {"id":"4","bloco":"Quem você é","texto":"Qual é a sua situação escolar atual?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Estou cursando o ensino médio"},
        {"letra":"B","texto":"Já concluí o ensino médio"},
        {"letra":"C","texto":"Fiz supletivo / EJA"},
        {"letra":"D","texto":"Outra situação"},
    ]},
    {"id":"5","bloco":"Quem você é","texto":"Você estudou em escola pública, privada ou foi bolsista em escola privada?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Escola pública"},
        {"letra":"B","texto":"Escola privada (pagante)"},
        {"letra":"C","texto":"Bolsista em escola privada"},
    ]},
    {"id":"6","bloco":"Quem você é","texto":"Você já fez o ENEM? Se sim, tem uma ideia da sua nota?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Sim, já fiz e tenho minhas notas"},
        {"letra":"B","texto":"Sim, mas não lembro exatamente as notas"},
        {"letra":"C","texto":"Ainda não fiz, vou fazer esse ano"},
        {"letra":"D","texto":"Ainda não fiz e não sei quando vou fazer"},
    ],"textoLivre":"Se tiver suas notas, pode colocar aqui (ex: Linguagens 650, Matemática 600...)"},

    # BLOCO 2 — Situação financeira real
    {"id":"7","bloco":"Sua situação financeira","texto":"Qual é a renda mensal aproximada da sua família somando todos que trabalham em casa?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Até R$ 1.412 (1 salário mínimo)"},
        {"letra":"B","texto":"Entre R$ 1.412 e R$ 3.000"},
        {"letra":"C","texto":"Entre R$ 3.000 e R$ 6.000"},
        {"letra":"D","texto":"Acima de R$ 6.000"},
        {"letra":"E","texto":"Prefiro não informar"},
    ],"textoLivre":"Quer descrever melhor sua situação? (ex: minha mãe trabalha sozinha, moramos de aluguel...)"},
    {"id":"8","bloco":"Sua situação financeira","texto":"Você precisa trabalhar enquanto estuda, ou pode se dedicar só aos estudos?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Sim, preciso trabalhar para me sustentar"},
        {"letra":"B","texto":"Sim, ajudo em casa mas não dependo só de mim"},
        {"letra":"C","texto":"Talvez, se não conseguir bolsa ou financiamento"},
        {"letra":"D","texto":"Não, minha família consegue me manter enquanto estudo"},
    ]},
    {"id":"9","bloco":"Sua situação financeira","texto":"Se não conseguir bolsa ou financiamento, você teria como pagar uma mensalidade? Se sim, qual faixa?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Não consigo pagar"},
        {"letra":"B","texto":"Até R$ 400/mês"},
        {"letra":"C","texto":"Até R$ 800/mês"},
        {"letra":"D","texto":"Acima de R$ 800/mês"},
    ]},
    {"id":"10","bloco":"Sua situação financeira","texto":"Em casa, você tem computador (não só celular) e internet boa o suficiente para estudar online?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Só tenho celular com internet limitada"},
        {"letra":"B","texto":"Tenho celular e acesso a computador às vezes"},
        {"letra":"C","texto":"Tenho computador com internet razoável"},
        {"letra":"D","texto":"Tenho boa estrutura tecnológica em casa"},
    ]},

    # BLOCO 3 — Onde você quer chegar
    {"id":"11","bloco":"Onde você quer chegar","texto":"Você consegue se deslocar para estudar em outra cidade? Se sim, até quanto tempo de deslocamento por dia?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Não consigo sair da minha cidade"},
        {"letra":"B","texto":"Até 30 minutos por dia"},
        {"letra":"C","texto":"Até 1 hora por dia"},
        {"letra":"D","texto":"Consigo me mudar se necessário"},
    ]},
    {"id":"12","bloco":"Onde você quer chegar","texto":"Em quanto tempo você quer ou precisa estar trabalhando na sua área?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"O mais rápido possível — em até 1 ano"},
        {"letra":"B","texto":"Entre 1 e 2 anos (curso técnico ou tecnólogo)"},
        {"letra":"C","texto":"Entre 3 e 5 anos (graduação)"},
        {"letra":"D","texto":"Mais de 5 anos (graduação + pós)"},
    ]},
    {"id":"13","bloco":"Onde você quer chegar","texto":"O que é mais importante para você na carreira? Escolha até 2 opções.","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Ganhar bem"},
        {"letra":"B","texto":"Ter estabilidade"},
        {"letra":"C","texto":"Ajudar pessoas"},
        {"letra":"D","texto":"Ser criativo"},
        {"letra":"E","texto":"Ter autonomia"},
        {"letra":"F","texto":"Crescer rápido"},
        {"letra":"G","texto":"Trabalhar com tecnologia"},
        {"letra":"H","texto":"Ter impacto social"},
    ]},
    {"id":"14","bloco":"Onde você quer chegar","texto":"Você já pesquisou ou tem interesse em algum curso, área ou profissão específica?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Sim, já tenho um curso definido na cabeça"},
        {"letra":"B","texto":"Tenho algumas opções mas estou indeciso"},
        {"letra":"C","texto":"Tenho uma área geral mas não sei o curso"},
        {"letra":"D","texto":"Não faço ideia ainda"},
    ],"textoLivre":"Se tiver, qual curso ou área você está pesquisando?"},

    # BLOCO 4 — Quem você é por dentro
    {"id":"15","bloco":"Quem você é por dentro","texto":"Fora da escola, o que você faz ou aprende por conta própria? (Ex: programar, desenhar, cuidar de pessoas, vender coisas, jogar, criar conteúdo...)","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Mexer com tecnologia, programar, criar coisas no computador"},
        {"letra":"B","texto":"Ler, escrever, pesquisar sobre assuntos que me interessam"},
        {"letra":"C","texto":"Estar com pessoas, organizar eventos, conversar"},
        {"letra":"D","texto":"Desenhar, criar, fazer coisas com as mãos"},
        {"letra":"E","texto":"Praticar esportes ou atividades ao ar livre"},
    ],"textoLivre":"Tem algo que você faz ou aprende que não está nas opções?"},
    {"id":"16","bloco":"Quem você é por dentro","texto":"Quando você se depara com um problema difícil, o que você faz primeiro?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Pesquiso bastante antes de agir"},
        {"letra":"B","texto":"Peço ajuda para alguém"},
        {"letra":"C","texto":"Tento na prática e vou ajustando"},
        {"letra":"D","texto":"Analiso tudo com calma"},
        {"letra":"E","texto":"Delego para quem sabe mais"},
    ]},
    {"id":"17","bloco":"Quem você é por dentro","texto":"Como você prefere trabalhar?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Prefiro trabalhar sozinho"},
        {"letra":"B","texto":"Trabalho bem em equipe como membro"},
        {"letra":"C","texto":"Gosto de liderar e organizar o grupo"},
        {"letra":"D","texto":"Depende do projeto"},
    ]},
    {"id":"18","bloco":"Quem você é por dentro","texto":"Em qual dessas áreas você acha que se sai melhor naturalmente?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Matemática e lógica"},
        {"letra":"B","texto":"Comunicação e escrita"},
        {"letra":"C","texto":"Ciências e saúde"},
        {"letra":"D","texto":"Artes e criação visual"},
        {"letra":"E","texto":"Organização e gestão"},
        {"letra":"F","texto":"Tecnologia e computadores"},
    ]},

    # BLOCO 5 — Contexto de vida
    {"id":"19","bloco":"Seu contexto de vida","texto":"Você já trabalhou, fez estágio, bico ou aprendeu algo profissional fora da escola? Se sim, o quê?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Nunca trabalhei"},
        {"letra":"B","texto":"Já fiz bicos ou trabalhos informais"},
        {"letra":"C","texto":"Fui ou sou Jovem Aprendiz"},
        {"letra":"D","texto":"Já fiz estágio"},
        {"letra":"E","texto":"Já trabalhei com carteira assinada"},
    ],"textoLivre":"Conta um pouco dessa experiência se quiser (o que fazia, o que aprendeu...)"},
    {"id":"20","bloco":"Seu contexto de vida","texto":"Você já tentou aprender algo por conta própria fora da escola — como um curso online, YouTube, app? Conseguiu terminar?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Sim, já terminei cursos ou aprendi bastante coisa"},
        {"letra":"B","texto":"Já tentei mas não terminei"},
        {"letra":"C","texto":"Assisto bastante mas não faço curso formal"},
        {"letra":"D","texto":"Nunca tentei aprender fora da escola"},
    ]},
    {"id":"21","bloco":"Seu contexto de vida","texto":"Qual é o seu maior medo ou bloqueio em relação à escolha de carreira?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Escolher errado e me arrepender"},
        {"letra":"B","texto":"Não conseguir emprego"},
        {"letra":"C","texto":"Não ter dinheiro para estudar"},
        {"letra":"D","texto":"Decepcionar a família"},
        {"letra":"E","texto":"Não saber por onde começar"},
        {"letra":"F","texto":"Não me sentir capaz"},
    ],"textoLivre":"Quer desabafar algo sobre esse medo? A IA leva isso em consideração na análise"},
    {"id":"22","bloco":"Seu contexto de vida","texto":"Se a IA te recomendar uma área que você nunca considerou, você estaria aberto a explorar?","tipo":"opcoes","opcoes":[
        {"letra":"A","texto":"Sim, estou aberto a explorar"},
        {"letra":"B","texto":"Depende da área"},
        {"letra":"C","texto":"Prefiro que confirme o que já penso"},
    ]},
]

PERGUNTAS_MODULOS = {
    "01":{"titulo":"Perfil Pessoal","descricao":"Entendendo seus valores e jeito de ser.","perguntas":[
        {"id":"m01p01","texto":"Quando você precisa tomar uma decisão importante, você confia mais em:","opcoes":[{"letra":"A","texto":"O que o meu coração manda"},{"letra":"B","texto":"Dados, fatos e lógica"},{"letra":"C","texto":"O que pessoas de confiança me dizem"},{"letra":"D","texto":"Meus princípios e valores"}],"textoLivre":"Tem alguma decisão difícil que você enfrenta agora?"},
        {"id":"m01p02","texto":"Sob pressão, você geralmente:","opcoes":[{"letra":"A","texto":"Fica ansioso mas empurra para frente"},{"letra":"B","texto":"Foca e produz mais"},{"letra":"C","texto":"Busca apoio de alguém"},{"letra":"D","texto":"Trava e procrastina"}]},
        {"id":"m01p03","texto":"O que mais te motiva no dia a dia?","opcoes":[{"letra":"A","texto":"Reconhecimento e elogios"},{"letra":"B","texto":"Aprender algo novo"},{"letra":"C","texto":"Ajudar alguém"},{"letra":"D","texto":"Dinheiro e recompensa"},{"letra":"E","texto":"Desafios e metas"}]},
        {"id":"m01p04","texto":"Em um grupo, você costuma ser:","opcoes":[{"letra":"A","texto":"O líder que organiza tudo"},{"letra":"B","texto":"O que resolve os problemas técnicos"},{"letra":"C","texto":"O que une as pessoas"},{"letra":"D","texto":"O que executa e entrega"}]},
        {"id":"m01p05","texto":"Qual desses valores é mais importante para você?","opcoes":[{"letra":"A","texto":"Liberdade"},{"letra":"B","texto":"Segurança"},{"letra":"C","texto":"Impacto — mudar vidas"},{"letra":"D","texto":"Crescimento pessoal"},{"letra":"E","texto":"Família e estabilidade"}],"textoLivre":"Tem outro valor que guia sua vida que não está aqui?"},
        {"id":"m01p06","texto":"Quando você erra, o que você faz?","opcoes":[{"letra":"A","texto":"Me culpo muito e demoro para superar"},{"letra":"B","texto":"Analiso o que deu errado e mudo a rota"},{"letra":"C","texto":"Peço ajuda para resolver"},{"letra":"D","texto":"Sigo em frente rápido sem olhar para trás"}]},
        {"id":"m01p07","texto":"O que te faz sentir mais realizado?","opcoes":[{"letra":"A","texto":"Conquistar uma meta difícil"},{"letra":"B","texto":"Ver o impacto do meu trabalho na vida de alguém"},{"letra":"C","texto":"Resolver um problema complexo"},{"letra":"D","texto":"Criar algo original e único"}]},
        {"id":"m01p08","texto":"Como você prefere trabalhar no dia a dia?","opcoes":[{"letra":"A","texto":"Sozinho, com total autonomia"},{"letra":"B","texto":"Em equipe, colaborando sempre"},{"letra":"C","texto":"Com orientação de alguém mais experiente"},{"letra":"D","texto":"De forma híbrida — depende do momento"}]},
    ]},
    "02":{"titulo":"Interesses e Paixões","descricao":"Descobrindo o que te move de verdade.","perguntas":[
        {"id":"m02p01","texto":"Qual assunto te faz perder a noção do tempo quando pesquisa?","opcoes":[{"letra":"A","texto":"Tecnologia, ciência e inovação"},{"letra":"B","texto":"Arte, cultura, história e filosofia"},{"letra":"C","texto":"Negócios, finanças e empreendedorismo"},{"letra":"D","texto":"Saúde, corpo humano e bem-estar"},{"letra":"E","texto":"Educação, sociedade e política"}],"textoLivre":"Tem algum assunto específico que você ama que não está aqui?"},
        {"id":"m02p02","texto":"Se você pudesse aprender qualquer coisa de graça agora, o que escolheria?","tipo":"texto_livre","placeholder":"Escreva à vontade — pode ser qualquer coisa, do culinária à programação"},
        {"id":"m02p03","texto":"Que tipo de conteúdo você mais consome (YouTube, TikTok, etc.)?","opcoes":[{"letra":"A","texto":"Tecnologia, programação, ciência"},{"letra":"B","texto":"Arte, música, cinema, cultura"},{"letra":"C","texto":"Empreendedorismo, finanças, negócios"},{"letra":"D","texto":"Saúde, esporte, bem-estar"},{"letra":"E","texto":"Humor, entretenimento geral"}],"textoLivre":"Tem algum canal ou criador que você segue e admira muito?"},
        {"id":"m02p04","texto":"Se dinheiro não fosse problema, o que você faria como trabalho?","tipo":"texto_livre","placeholder":"Sonhe à vontade — essa resposta é muito importante para a IA entender você"},
        {"id":"m02p05","texto":"Qual tipo de problema você gostaria de ajudar a resolver no mundo?","opcoes":[{"letra":"A","texto":"Desigualdade social e pobreza"},{"letra":"B","texto":"Problemas de saúde e doenças"},{"letra":"C","texto":"Educação de qualidade para todos"},{"letra":"D","texto":"Tecnologia e inovação"},{"letra":"E","texto":"Meio ambiente e sustentabilidade"}],"textoLivre":"Tem outro problema que te preocupa?"},
        {"id":"m02p06","texto":"Em qual disciplina escolar você sempre se destacou (ou menos sofreu)?","opcoes":[{"letra":"A","texto":"Matemática e Física"},{"letra":"B","texto":"Português, Redação e Literatura"},{"letra":"C","texto":"Biologia e Química"},{"letra":"D","texto":"História e Geografia"},{"letra":"E","texto":"Artes e Educação Física"}],"textoLivre":"Se nenhuma, pode contar aqui"},
        {"id":"m02p07","texto":"Você já tentou criar ou construir algo por conta própria?","opcoes":[{"letra":"A","texto":"Sim, frequentemente — tenho projetos pessoais"},{"letra":"B","texto":"Já tentei algumas vezes"},{"letra":"C","texto":"Ainda não, mas tenho vontade"},{"letra":"D","texto":"Não tenho muito interesse nisso"}],"textoLivre":"Se sim, o que você criou ou tentou criar?"},
        {"id":"m02p08","texto":"Qual profissional você mais admira (pode ser famoso ou alguém da sua vida)?","tipo":"texto_livre","placeholder":"Ex: meu tio é médico e eu admiro muito o que ele faz..."},
    ]},
    "03":{"titulo":"Habilidades e Estilo","descricao":"O que você já sabe fazer bem.","perguntas":[
        {"id":"m03p01","texto":"O que as pessoas sempre pedem sua ajuda?","opcoes":[{"letra":"A","texto":"Resolver problemas técnicos ou de tecnologia"},{"letra":"B","texto":"Criar algo bonito ou criativo"},{"letra":"C","texto":"Organizar, planejar ou tomar decisões"},{"letra":"D","texto":"Ouvir, aconselhar, apoiar emocionalmente"},{"letra":"E","texto":"Explicar assuntos ou ensinar"}],"textoLivre":"Tem outra coisa que as pessoas sempre te pedem?"},
        {"id":"m03p02","texto":"Como você prefere aprender algo novo?","opcoes":[{"letra":"A","texto":"Fazendo — aprendo na prática, errando e tentando"},{"letra":"B","texto":"Assistindo vídeos ou lendo por conta"},{"letra":"C","texto":"Com alguém me explicando pessoalmente"},{"letra":"D","texto":"Em sala de aula com professor"}]},
        {"id":"m03p03","texto":"Qual habilidade você acha que tem mais desenvolvida?","opcoes":[{"letra":"A","texto":"Raciocínio lógico e análise"},{"letra":"B","texto":"Comunicação — falar e escrever bem"},{"letra":"C","texto":"Criatividade e originalidade"},{"letra":"D","texto":"Organização e planejamento"},{"letra":"E","texto":"Empatia e relações humanas"}]},
        {"id":"m03p04","texto":"Como você lida com prazos e responsabilidades?","opcoes":[{"letra":"A","texto":"Entrego antes — sou muito organizado"},{"letra":"B","texto":"Entrego no prazo, mas na última hora"},{"letra":"C","texto":"Às vezes atraso, mas entrego"},{"letra":"D","texto":"Tenho dificuldade com prazos"}],"textoLivre":"Quer comentar algo sobre como você se organiza?"},
        {"id":"m03p05","texto":"Se você tivesse que apresentar um trabalho agora, como faria?","opcoes":[{"letra":"A","texto":"Com dados, gráficos e resultados concretos"},{"letra":"B","texto":"Com slides bonitos e apresentação visual"},{"letra":"C","texto":"Contando uma história envolvente"},{"letra":"D","texto":"Com relatório detalhado e bem estruturado"}]},
        {"id":"m03p06","texto":"Você considera que aprende rápido coisas novas?","opcoes":[{"letra":"A","texto":"Sim, geralmente pego rápido"},{"letra":"B","texto":"Depende do assunto"},{"letra":"C","texto":"Demoro mais, mas aprendo bem"},{"letra":"D","texto":"Tenho dificuldade e preciso de bastante apoio"}]},
        {"id":"m03p07","texto":"Qual sua maior qualidade segundo as pessoas que convivem com você?","tipo":"texto_livre","placeholder":"O que familiares, amigos ou professores costumam elogiar em você?"},
        {"id":"m03p08","texto":"Qual é a sua maior dificuldade que você gostaria de superar?","tipo":"texto_livre","placeholder":"Pode ser qualquer coisa — timidez, matemática, organização... seja honesto"},
    ]},
    "04":{"titulo":"Vida e Contexto Real","descricao":"Entendendo sua realidade para traçar um caminho possível.","perguntas":[
        {"id":"m04p01","texto":"Como é sua rotina diária hoje?","opcoes":[{"letra":"A","texto":"Só estudo — tenho tempo livre"},{"letra":"B","texto":"Estudo e ajudo nas tarefas de casa"},{"letra":"C","texto":"Estudo e trabalho parte do dia"},{"letra":"D","texto":"Trabalho o dia todo e estudo quando dá"}],"textoLivre":"Quer descrever melhor como é o seu dia a dia?"},
        {"id":"m04p02","texto":"Sua família apoia sua escolha profissional?","opcoes":[{"letra":"A","texto":"Sim, totalmente — me incentivam"},{"letra":"B","texto":"Apoiam, mas com algumas ressalvas"},{"letra":"C","texto":"São neutros — não incentivam nem bloqueiam"},{"letra":"D","texto":"Preferem que eu siga outro caminho"},{"letra":"E","texto":"Não temos muito diálogo sobre isso"}],"textoLivre":"Quer contar mais sobre como sua família vê seus planos?"},
        {"id":"m04p03","texto":"Você tem alguma limitação física, de saúde ou outra que possa influenciar sua escolha de carreira?","opcoes":[{"letra":"A","texto":"Não, nenhuma"},{"letra":"B","texto":"Sim, mas não impede minha escolha"},{"letra":"C","texto":"Sim, preciso levar isso em consideração"},{"letra":"D","texto":"Prefiro não informar"}],"textoLivre":"Se quiser compartilhar para a IA considerar, fique à vontade"},
        {"id":"m04p04","texto":"Você tem alguma crença religiosa, cultural ou familiar que influencia sua visão de carreira?","opcoes":[{"letra":"A","texto":"Sim, influencia bastante"},{"letra":"B","texto":"Um pouco, mas não define minha escolha"},{"letra":"C","texto":"Não, não influencia"},{"letra":"D","texto":"Prefiro não comentar"}],"textoLivre":"Quer explicar como isso influencia?"},
        {"id":"m04p05","texto":"Você tem internet boa o suficiente para fazer um curso EAD?","opcoes":[{"letra":"A","texto":"Sim, sem problemas"},{"letra":"B","texto":"Internet razoável, às vezes trava"},{"letra":"C","texto":"Só no celular, dados limitados"},{"letra":"D","texto":"Não tenho acesso adequado"}]},
        {"id":"m04p06","texto":"Você conhece os programas do governo para entrar na faculdade? (SISU, ProUni, FIES)","opcoes":[{"letra":"A","texto":"Sim, conheço bem todos"},{"letra":"B","texto":"Já ouvi falar mas não entendo direito"},{"letra":"C","texto":"Não conheço nenhum"},{"letra":"D","texto":"Já tentei algum deles"}],"textoLivre":"Se já tentou ou tem dúvidas sobre algum, pode descrever aqui"},
        {"id":"m04p07","texto":"Se você pudesse pedir uma coisa para esse sistema de orientação, o que seria?","tipo":"texto_livre","placeholder":"Ex: quero saber se consigo entrar em medicina sem pagar nada, ou quero entender como funciona o técnico..."},
        {"id":"m04p08","texto":"Tem algo importante sobre você que não foi perguntado e que acha que deve influenciar sua análise?","tipo":"texto_livre","placeholder":"Esse é seu espaço livre — escreva o que quiser. A IA vai ler tudo isso.","obrigatorio":False},
    ]},
}

# ── JWT helpers ────────────────────────────────────────────────────────────────
def gerar_token(usuario_id: str, email: str) -> str:
    payload = {"sub": usuario_id, "email": email, "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRES_H)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        return jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail={"erro": "Token expirado", "codigo": "TOKEN_EXPIRADO"})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail={"erro": "Token inválido", "codigo": "TOKEN_INVALIDO"})

async def get_usuario(token: dict = Depends(verificar_token)) -> dict:
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM usuarios WHERE id = %s", (token["sub"],))
            u = await cur.fetchone()
            if not u:
                raise HTTPException(status_code=401, detail={"erro": "Usuário não encontrado", "codigo": "USUARIO_NAO_ENCONTRADO"})
            u["modulos_concluidos"] = json.loads(u["modulos_concluidos"]) if isinstance(u["modulos_concluidos"], str) else (u["modulos_concluidos"] or [])
            u["teste_inicial_concluido"] = bool(u["teste_inicial_concluido"])
            return u

# ── IA ─────────────────────────────────────────────────────────────────────────
def montar_prompt_base(nome: str, linhas_teste: str, linhas_mod: str) -> str:
    return f"""Você é um orientador vocacional humanizado, especialista no sistema educacional e de trabalho brasileiro.
Você está analisando o perfil de um jovem que pode estar perdido, com medo ou sem dinheiro para estudar.
Sua missão é ser honesto, acolhedor e prático — dando um caminho REAL considerando a situação financeira, localização e contexto de vida dele.

Considere SEMPRE:
- Se a renda é baixa: priorize SISU (universidade pública via ENEM), ProUni (bolsa integral/parcial), FIES, institutos federais (IFSP, IFCE etc.) e cursos técnicos gratuitos
- Se precisar trabalhar: sugira cursos noturnos, EAD acessível, cursos técnicos rápidos
- Se não fez ENEM: oriente sobre como se preparar e quando fazer
- Seja específico com nomes de instituições, cursos e programas reais do Brasil

DADOS DO USUÁRIO:
Nome: {nome}

Respostas do Teste Inicial:
{linhas_teste}
{linhas_mod}

Retorne SOMENTE um JSON válido (sem markdown, sem texto adicional) neste formato:
{{
  "areaPrincipal": "string",
  "areaPrincipalJustificativa": "string — no máximo 140 caracteres, explicando por que esta área ficou em 1º lugar",
  "percentualCompatibilidade": 85,
  "areasSecundarias": [{{"nome": "string", "percentual": 70, "justificativa": "string — no máximo 140 caracteres explicando por que esta área também combina"}}],
  "perfilLabel": "string — título claro e direto do perfil em até 6 palavras",
  "perfilResumoClaro": "string — frase curta de até 120 caracteres",
  "mensagemPersonalizada": "string — mensagem acolhedora e honesta de 2-3 frases diretamente para o jovem, usando o nome dele",
  "skills": ["string — habilidades identificadas"],
  "pontosDeMelhoria": ["string — 2-3 pontos para desenvolver"],
  "caminhos": [
    {{
      "titulo": "string",
      "descricao": "string",
      "prazo": "string",
      "custo": "string",
      "dificuldade": "string",
      "passos": [{{"titulo": "string", "descricao": "string"}}]
    }}
  ],
  "faculdades": [
    {{"nome": "string", "tipo": "publica|privada|federal", "cidade": "string", "nota_enem": 0, "bolsa": false, "programa": "string"}}
  ],
  "cursosTecnicos": [
    {{"nome": "string", "instituicao": "string", "duracao": "string", "gratuito": true, "modalidade": "presencial|ead|hibrido"}}
  ],
  "cursos": [
    {{"nome": "string", "plataforma": "string", "gratuito": true, "url": "", "nivel": "iniciante|intermediario|avancado"}}
  ],
  "programasGoverno": [
    {{"nome": "string", "descricao": "string", "comoAcessar": "string", "linkOficial": "string"}}
  ],
  "proximosPassos": [
    {{"titulo": "string — acao curta em ate 80 chars", "descricao": "string — como executar em 2-3 frases"}}
  ],
  "alertas": ["string"],
  "mapaCarreira": [
    {{"id": "string", "titulo": "string", "sub": "string", "prazo": "string", "status": "done|active|locked"}}
  ],
  "respostasDestaque": {{
    "preferenciaTrabalho": "string",
    "ambienteIdeal": "string",
    "principalDesafio": "string",
    "sonho": "string"
  }}
}}"""

async def chamar_ia(prompt: str, job_id: Optional[str] = None) -> dict:
    if not ANTHROPIC_API_KEY and not ia_simulada.config.ativa:
        raise RuntimeError("Chave de API não configurada no servidor. Contate o administrador.")

    jid = job_id or uuid.uuid4().hex[:8]
    sem = _obter_ia_semaphore()
    t_inicio_espera = time.monotonic()
    async with sem:
        espera = time.monotonic() - t_inicio_espera
        logger.info(f"IA job={jid} evento=fila_entrada espera={espera:.1f}s")
        t_inicio_chamada = time.monotonic()
        try:
            return await _chamar_ia_com_retry(prompt, job_id)
        finally:
            chamada = time.monotonic() - t_inicio_chamada
            total = espera + chamada
            simulada = "sim" if ia_simulada.config.ativa else "nao"
            logger.info(f"IA job={jid} evento=concluido fila={espera:.1f}s chamada={chamada:.1f}s total={total:.1f}s simulada={simulada}")


HEARTBEAT_TIMEOUT_S = 5.0

# Tempos da chamada do plano. Ficam aqui, com nome, porque o limite de job
# travado (LIMITE_JOB_TRAVADO_S) é calculado a partir deles.
IA_CONNECT_TIMEOUT_S = 15.0
ESPERA_ENTRE_TENTATIVAS = (5, 15)   # segundos antes da 2ª e da 3ª tentativa
ESPERA_EXTRA_RATE_LIMIT = 10        # somada à espera quando a API devolve 429


def limite_job_travado_s(timeout_s: float) -> int:
    """Segundos sem heartbeat a partir dos quais um job que já começou é considerado travado.

    O heartbeat é gravado no início de cada tentativa. Entre um início e o
    seguinte cabem, no pior caso: a conexão, a chamada até o timeout, a maior
    espera antes de tentar de novo (com o acréscimo do 429) e a gravação do
    próprio heartbeat. Margem de 2x sobre esse pior caso, porque o timeout do
    httpx vale por operação de rede e não para a chamada inteira.
    Com timeout de 300 s: 2 x (15 + 300 + 15 + 10 + 5) = 690 s.
    """
    pior_intervalo = (
        IA_CONNECT_TIMEOUT_S + timeout_s + max(ESPERA_ENTRE_TENTATIVAS)
        + ESPERA_EXTRA_RATE_LIMIT + HEARTBEAT_TIMEOUT_S
    )
    return int(2 * pior_intervalo)


LIMITE_JOB_TRAVADO_S = limite_job_travado_s(IA_TIMEOUT_S)
VARREDURA_JOBS_INTERVALO_S = 60

async def _registrar_heartbeat(job_id: str) -> None:
    """Marca o início de uma tentativa de chamada à IA para o job.

    Significado das colunas para a recuperação de job travado:
    - tentativas = 0: o job nunca começou uma tentativa. Está esperando vaga
      no semáforo ou ficou órfão porque o processo caiu antes da vez dele.
      Enquanto o processo está vivo, isso NÃO indica job travado, mesmo com
      atualizado_em antigo (ele continua igual a criado_em até a 1ª tentativa).
    - tentativas > 0 e atualizado_em antigo: começou uma tentativa e parou de
      dar sinal. O limite de "travado" é LIMITE_JOB_TRAVADO_S, calculado a
      partir do timeout da chamada (ver limite_job_travado_s).

    Falha aqui não interrompe a chamada: perder uma geração paga por uma
    oscilação do banco é pior do que perder um heartbeat. O custo é que a
    recuperação pode reenfileirar um job saudável, o que é raro e será
    protegido por UPDATE condicional na rotina de recuperação.
    """
    async def _gravar():
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE jobs SET tentativas = tentativas + 1, atualizado_em = NOW() WHERE id = %s",
                    (job_id,),
                )
                return cur.rowcount

    try:
        linhas = await asyncio.wait_for(_gravar(), timeout=HEARTBEAT_TIMEOUT_S)
        if linhas == 0:
            logger.warning(f"Heartbeat job={job_id}: nenhum job com esse id na tabela jobs")
    except Exception as e:
        logger.warning(f"Heartbeat job={job_id} não gravado, seguindo com a chamada: {type(e).__name__}: {e}")


async def _enviar_para_ia(prompt: str, max_tokens: int, timeout: float, tipo: str):
    """Único ponto que faz o POST para a API do Claude.

    Com IA_SIMULADA ligada, devolve uma resposta pronta com a mesma interface
    (status_code, json(), text) ou levanta as mesmas exceções do httpx. O que
    vem antes (semáforo, heartbeat) e depois (status, parse, retry) não muda.
    tipo: 'plano' para chamar_ia, 'lista' para chamar_ia_lista.
    """
    if ia_simulada.config.ativa:
        return await ia_simulada.enviar(tipo)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=IA_CONNECT_TIMEOUT_S)) as client:
        return await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": ANTHROPIC_MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
        )


MAX_TOKENS_PLANO = 8192


class RespostaTruncada(RuntimeError):
    """A IA parou no limite de max_tokens e o JSON veio cortado.

    Não entra no retry: o prompt e o limite são os mesmos, então a nova
    tentativa trunca de novo e cada uma é paga. Falha na primeira vez.
    """

async def _chamar_ia_com_retry(prompt: str, job_id: Optional[str] = None) -> dict:
    MAX_TENTATIVAS = 3

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        # Já dentro do semáforo: este é o início real da tentativa.
        # Sem job_id (chamada fora de job), nada é gravado.
        if job_id:
            await _registrar_heartbeat(job_id)
        try:
            logger.info(f"🤖 Chamando IA — tentativa {tentativa}/{MAX_TENTATIVAS}")
            resp = await _enviar_para_ia(prompt, max_tokens=MAX_TOKENS_PLANO, timeout=IA_TIMEOUT_S, tipo="plano")
        except httpx.TimeoutException:
            msg = f"A IA demorou demais para responder (tentativa {tentativa}/{MAX_TENTATIVAS}). Muitos usuários simultâneos."
            logger.warning(f"⏱️ Timeout na tentativa {tentativa}: {msg}")
            if tentativa < MAX_TENTATIVAS:
                await asyncio.sleep(ESPERA_ENTRE_TENTATIVAS[tentativa - 1])
                continue
            raise RuntimeError("A IA não respondeu a tempo após 3 tentativas. Tente novamente em alguns minutos.")
        except httpx.ConnectError:
            msg = f"Sem conexão com o servidor de IA (tentativa {tentativa}/{MAX_TENTATIVAS})."
            logger.warning(f"🔌 Erro de conexão na tentativa {tentativa}")
            if tentativa < MAX_TENTATIVAS:
                await asyncio.sleep(ESPERA_ENTRE_TENTATIVAS[tentativa - 1])
                continue
            raise RuntimeError("Não foi possível conectar ao servidor de IA após 3 tentativas. Verifique a conexão do servidor.")
        except httpx.RequestError as err:
            logger.warning(f"⚠️ Erro de rede na tentativa {tentativa}: {err}")
            if tentativa < MAX_TENTATIVAS:
                await asyncio.sleep(ESPERA_ENTRE_TENTATIVAS[tentativa - 1])
                continue
            raise RuntimeError(f"Erro de rede ao contactar a IA após 3 tentativas: {type(err).__name__}")

        # Verificar status HTTP
        if resp.status_code == 429:
            logger.warning(f"⚡ Rate limit atingido na tentativa {tentativa}")
            if tentativa < MAX_TENTATIVAS:
                await asyncio.sleep(ESPERA_ENTRE_TENTATIVAS[tentativa - 1] + ESPERA_EXTRA_RATE_LIMIT)
                continue
            raise RuntimeError("Muitos usuários usando a IA ao mesmo tempo. Aguarde 1-2 minutos e tente novamente.")
        elif resp.status_code == 529:
            logger.warning(f"🔄 API sobrecarregada na tentativa {tentativa}")
            if tentativa < MAX_TENTATIVAS:
                await asyncio.sleep(ESPERA_ENTRE_TENTATIVAS[tentativa - 1])
                continue
            raise RuntimeError("O servidor de IA está sobrecarregado no momento. Tente novamente em alguns minutos.")
        elif resp.status_code == 401:
            raise RuntimeError("Chave de API inválida ou expirada. Contate o administrador do sistema.")
        elif resp.status_code != 200:
            try:
                detalhe = resp.json().get("error", {}).get("message", resp.text[:200])
            except Exception:
                detalhe = resp.text[:200]
            raise RuntimeError(f"Erro interno da IA (código {resp.status_code}): {detalhe}")

        # Parsear resposta
        # Os logs de falha abaixo registram tamanho e motivo, nunca o texto:
        # a resposta repete dados que o aluno escreveu no questionário.
        stop_reason = resp.json().get("stop_reason")
        texto = "".join(b.get("text", "") for b in resp.json().get("content", []))
        texto = texto.strip()
        # Verificado antes do parse: uma resposta cortada que por acaso tenha
        # chaves balanceadas passaria no json.loads incompleta.
        if stop_reason == "max_tokens":
            logger.error(
                f"Resposta truncada na tentativa {tentativa}: stop_reason=max_tokens "
                f"(tamanho={len(texto)} caracteres, max_tokens={MAX_TOKENS_PLANO}). Sem retry."
            )
            raise RespostaTruncada(
                f"A resposta da IA foi cortada no limite de {MAX_TOKENS_PLANO} tokens de saída."
            )
        texto = re.sub(r'```json\s*', '', texto)
        texto = re.sub(r'```\s*', '', texto)
        texto = texto.strip()
        match = re.search(r'\{[\s\S]*\}', texto)
        if match:
            try:
                return json.loads(match.group())
            except Exception as parse_err:
                logger.error(
                    f"Erro ao parsear JSON na tentativa {tentativa}: {type(parse_err).__name__} "
                    f"(tamanho={len(texto)} caracteres, stop_reason={stop_reason})"
                )
                if tentativa < MAX_TENTATIVAS:
                    await asyncio.sleep(ESPERA_ENTRE_TENTATIVAS[tentativa - 1])
                    continue
                raise RuntimeError("A IA retornou uma resposta em formato inválido após 3 tentativas.")
        logger.error(
            f"JSON inválido na tentativa {tentativa}: nenhum objeto JSON na resposta "
            f"(tamanho={len(texto)} caracteres, stop_reason={stop_reason})"
        )
        if tentativa < MAX_TENTATIVAS:
            await asyncio.sleep(ESPERA_ENTRE_TENTATIVAS[tentativa - 1])
            continue
        raise RuntimeError("A IA não retornou um resultado válido após 3 tentativas.")

    raise RuntimeError("Erro inesperado no processamento da IA.")


# ══════════════════════════════════════════════════════════════════════════════
# ROTAS
# ══════════════════════════════════════════════════════════════════════════════

def perguntas_teste_ativas():
    return PERGUNTAS_TESTE

def ids_perguntas_teste_ativas():
    return {p["id"] for p in perguntas_teste_ativas()}

def ids_perguntas_teste_obrigatorias():
    return {p["id"] for p in perguntas_teste_ativas() if p.get("obrigatorio", True)}

def formatar_resposta_teste(pergunta: dict, resposta: dict) -> dict:
    valor = str(resposta.get("valor", "")).strip()
    opcoes = pergunta.get("opcoes") or []
    opcao = next((op for op in opcoes if op.get("letra") == valor), None)
    texto_resposta = opcao.get("texto") if opcao else valor
    texto_livre = str(resposta.get("textoLivre", "") or "").strip()
    if texto_livre:
        texto_resposta = f"{texto_resposta} — {texto_livre}" if texto_resposta else texto_livre
    return {
        "perguntaId": pergunta["id"],
        "bloco": pergunta.get("bloco", "Resposta"),
        "pergunta": pergunta["texto"],
        "resposta": texto_resposta,
    }


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════════════════════════════════════════
def _senha_admin_valida(senha: str) -> bool:
    """Compara a senha do admin em tempo constante.

    Com !=, a comparação para no primeiro caractere diferente, e o tempo de
    resposta revela quantos caracteres do início estão certos. compare_digest
    leva o mesmo tempo qualquer que seja o ponto da diferença. A conversão
    para bytes aceita senha com acento, que compare_digest recusa em str.
    """
    return hmac.compare_digest(senha.encode("utf-8"), ADMIN_SECRET.encode("utf-8"))

@app.get("/api/admin/usuarios")
async def admin_usuarios(senha: str):
    if not _senha_admin_valida(senha):
        raise HTTPException(status_code=403)
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id, nome, email, teste_inicial_concluido, modulos_concluidos, criado_em FROM usuarios")
            return await cur.fetchall()

@app.get("/api/admin/dados")
async def admin_dados(senha: str):
    if not _senha_admin_valida(senha):
        raise HTTPException(status_code=403)
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT COUNT(*) as total FROM usuarios")
            total_usuarios = (await cur.fetchone())["total"]
            await cur.execute("SELECT COUNT(*) as total FROM perfis")
            total_perfis = (await cur.fetchone())["total"]
            await cur.execute("SELECT COUNT(*) as total FROM respostas_teste")
            total_respostas = (await cur.fetchone())["total"]
            await cur.execute("SELECT COUNT(*) as total FROM jobs WHERE status='concluido'")
            total_jobs = (await cur.fetchone())["total"]
            # Cursor comum: contar_senhas_texto_plano lê a contagem por posição.
            async with conn.cursor() as cur_simples:
                senhas_texto_plano = await contar_senhas_texto_plano(cur_simples)
            await cur.execute("SELECT id, nome, email, teste_inicial_concluido, modulos_concluidos, criado_em FROM usuarios ORDER BY criado_em DESC")
            usuarios = await cur.fetchall()
            await cur.execute("SELECT j.id, j.usuario_id, j.status, j.erro, j.criado_em, u.nome FROM jobs j LEFT JOIN usuarios u ON j.usuario_id=u.id ORDER BY j.criado_em DESC LIMIT 50")
            jobs = await cur.fetchall()
            await cur.execute("SELECT p.usuario_id, p.criado_em, p.atualizado_em, u.nome, JSON_UNQUOTE(JSON_EXTRACT(p.dados, '$.areaPrincipal')) as area FROM perfis p LEFT JOIN usuarios u ON p.usuario_id=u.id ORDER BY p.criado_em DESC")
            perfis = await cur.fetchall()
            for u in usuarios:
                u["modulos_concluidos"] = json.loads(u["modulos_concluidos"]) if isinstance(u["modulos_concluidos"], str) else (u["modulos_concluidos"] or [])
                u["teste_inicial_concluido"] = bool(u["teste_inicial_concluido"])
                if u["criado_em"]: u["criado_em"] = u["criado_em"].isoformat()
            for j in jobs:
                if j["criado_em"]: j["criado_em"] = j["criado_em"].isoformat()
            for p in perfis:
                if p["criado_em"]: p["criado_em"] = p["criado_em"].isoformat()
                if p["atualizado_em"]: p["atualizado_em"] = p["atualizado_em"].isoformat()
    return {
        "metricas": {"usuarios": total_usuarios, "perfis": total_perfis, "respostas": total_respostas,
                     "jobs_concluidos": total_jobs, "senhas_texto_plano": senhas_texto_plano},
        "usuarios": usuarios, "jobs": jobs, "perfis": perfis
    }

@app.get("/api/admin/respostas/{usuario_id}")
async def admin_respostas_usuario(usuario_id: str, senha: str):
    if not _senha_admin_valida(senha):
        raise HTTPException(status_code=403)
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT pergunta_id, valor, texto_livre, criado_em FROM respostas_teste WHERE usuario_id=%s ORDER BY CAST(pergunta_id AS UNSIGNED)", (usuario_id,))
            respostas = await cur.fetchall()
            await cur.execute("SELECT dados FROM perfis WHERE usuario_id=%s", (usuario_id,))
            perfil = await cur.fetchone()
            for r in respostas:
                if r["criado_em"]: r["criado_em"] = r["criado_em"].isoformat()
    return {
        "respostas": respostas,
        "perfil_ia": json.loads(perfil["dados"]) if perfil else None
    }

@app.delete("/api/admin/usuario/{usuario_id}")
async def admin_deletar_usuario(usuario_id: str, senha: str):
    if not _senha_admin_valida(senha):
        raise HTTPException(status_code=403)
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM usuarios WHERE id=%s", (usuario_id,))
    return {"deletado": True}

@app.delete("/api/admin/reset")
async def admin_reset(senha: str):
    if not _senha_admin_valida(senha):
        raise HTTPException(status_code=403)
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM perfis")
            await cur.execute("DELETE FROM jobs")
            await cur.execute("DELETE FROM respostas_modulo")
            await cur.execute("DELETE FROM respostas_teste")
            await cur.execute("DELETE FROM usuarios")
    return {"resetado": True}
        
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.get("/index.html", include_in_schema=False)
def serve_index_html():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.get("/pages/{page}")
def serve_page(page: str):
    path = os.path.join(BASE_DIR, "pages", page)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Página não encontrada")
    return FileResponse(path)

# ── Senhas ─────────────────────────────────────────────────────────────────────
# Formato completo de um hash bcrypt: $2a$, $2b$ ou $2y$, custo com dois
# dígitos, e 53 caracteres de sal e hash, 60 no total. Olhar só o prefixo
# confundiria uma senha em texto plano que começasse com "$2b$" com um hash.
# O mesmo padrão é usado em Python e no SQL de contar_senhas_texto_plano,
# para as duas contas nunca divergirem.
PADRAO_HASH_BCRYPT = r"^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$"

def eh_hash_bcrypt(valor: str) -> bool:
    return re.fullmatch(PADRAO_HASH_BCRYPT, valor or "") is not None

async def contar_senhas_texto_plano(cur) -> int:
    """Quantos usuários ainda têm senha gravada sem hash, pelo formato do campo.

    REGEXP_LIKE com 'c' diferencia maiúsculas de minúsculas. Sem isso, com a
    collation padrão, o MySQL aceitaria '$2A$' e a conta divergiria do Python.
    """
    await cur.execute(
        "SELECT COUNT(*) FROM usuarios WHERE NOT REGEXP_LIKE(senha, %s, 'c')",
        (PADRAO_HASH_BCRYPT,),
    )
    (total,) = await cur.fetchone()
    return int(total)

async def gerar_hash_senha(senha: str) -> str:
    # bcrypt é CPU-bound; roda em thread para não travar o event loop
    hash_bytes = await asyncio.to_thread(bcrypt.hashpw, senha.encode("utf-8"), bcrypt.gensalt())
    return hash_bytes.decode("utf-8")

async def verificar_senha(senha: str, armazenada: str) -> bool:
    if eh_hash_bcrypt(armazenada):
        return await asyncio.to_thread(bcrypt.checkpw, senha.encode("utf-8"), armazenada.encode("utf-8"))
    # TEMPORÁRIO (Fase 0): contas antigas com senha em texto plano. O login
    # converte a senha em hash no primeiro acesso que acertar.
    # CONDIÇÃO PARA APAGAR ESTE TRECHO: a contagem de senhas em texto plano
    # chegar a zero. Onde olhar: linha "senha em TEXTO PLANO" no log do
    # startup, ou a métrica "Senhas sem hash" no painel admin
    # (/api/admin/dados, metricas.senhas_texto_plano). Apagar antes disso
    # tranca o aluno fora da conta. Junto com este trecho, apagar também a
    # conversão em hash dentro de login().
    return hmac.compare_digest(senha.encode("utf-8"), armazenada.encode("utf-8"))


# ── Termo da LGPD ─────────────────────────────────────────────────────────────
# Fonte única do texto que o aluno aceita no cadastro. O front busca daqui
# (GET /api/lgpd/termo), mostra, e devolve a versão no cadastro. O banco grava
# a versão aceita. Qualquer mudança no texto exige uma versão nova: assim
# sempre dá para saber o que cada pessoa leu.
# RASCUNHO: revisar o texto com o orientador antes de usar com alunos.
TERMO_LGPD_VERSAO = "2026-11-26"
TERMO_LGPD_PARAGRAFOS = (
    "Para criar sua conta, o Programando o Futuro guarda o seu nome, o seu e-mail, a sua senha "
    "(guardada de forma protegida, que ninguém consegue ler), a sua cidade, se você informar, e as "
    "respostas que você der no questionário e nos módulos.",
    "Esses dados são usados só para montar o seu plano de carreira e mostrar o seu progresso. Para "
    "gerar o plano, as suas respostas são enviadas ao Claude, um serviço de inteligência artificial "
    "da empresa Anthropic, que fica fora do Brasil.",
    "A equipe do projeto, do Centro Universitário SENAI-SP, pode ver as suas respostas para "
    "acompanhar e melhorar o sistema. Os seus dados não são vendidos nem usados para propaganda.",
    "Você pode pedir a qualquer momento para ver, corrigir ou apagar os seus dados, falando com a "
    "equipe do projeto na sua escola.",
)
TERMO_LGPD_CONFIRMACAO = "Li e aceito que meus dados sejam usados como descrito acima."

@app.get("/api/lgpd/termo")
async def termo_lgpd():
    return {
        "versao": TERMO_LGPD_VERSAO,
        "paragrafos": list(TERMO_LGPD_PARAGRAFOS),
        "confirmacao": TERMO_LGPD_CONFIRMACAO,
    }

# ── Auth ───────────────────────────────────────────────────────────────────────
@app.post("/api/auth/cadastro", status_code=201)
async def cadastro(body: CadastroBody):
    # O front também bloqueia, mas quem garante é o backend.
    # Dois erros diferentes: ausente costuma ser defeito de quem chama a API;
    # false é a pessoa que não aceitou.
    if body.aceite_lgpd is None:
        raise HTTPException(status_code=400, detail={
            "erro": "O aceite do termo de uso dos dados (LGPD) é obrigatório e não veio no pedido de cadastro.",
            "codigo": "LGPD_AUSENTE",
        })
    if body.aceite_lgpd is not True:
        raise HTTPException(status_code=400, detail={
            "erro": "Para criar a conta, é preciso ler e aceitar o termo de uso dos dados (LGPD).",
            "codigo": "LGPD_RECUSADO",
        })
    if body.versao_termo_lgpd != TERMO_LGPD_VERSAO:
        raise HTTPException(status_code=400, detail={
            "erro": "O termo de uso dos dados mudou desde que a página foi aberta. Recarregue a página, leia o termo e aceite de novo.",
            "codigo": "LGPD_VERSAO_INVALIDA",
        })
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id FROM usuarios WHERE email = %s", (body.email,))
            if await cur.fetchone():
                raise HTTPException(status_code=409, detail={"erro": "Email já cadastrado", "codigo": "EMAIL_DUPLICADO"})
            uid = str(uuid.uuid4())
            iniciais = "".join(p[0].upper() for p in body.nome.split()[:2])
            await cur.execute(
                "INSERT INTO usuarios (id, nome, email, senha, avatar_iniciais, aceite_lgpd, aceite_lgpd_em, "
                "aceite_lgpd_versao, aceite_menor) VALUES (%s,%s,%s,%s,%s,TRUE,UTC_TIMESTAMP(),%s,NULL)",
                (uid, body.nome, body.email, await gerar_hash_senha(body.senha), iniciais,
                 TERMO_LGPD_VERSAO)
            )
            usuario = {
                "id": uid, "nome": body.nome, "email": body.email,
                "avatar_iniciais": iniciais, "aceite_lgpd": True,
                "aceite_lgpd_versao": TERMO_LGPD_VERSAO,
                "aceite_menor": None, "teste_inicial_concluido": False,
                "modulos_concluidos": [], "criado_em": datetime.utcnow().isoformat()
            }
            # O id identifica o cadastro no log sem expor dado pessoal do aluno.
            logger.info(f"✅ Cadastro: usuario_id={uid}")
            return {"token": gerar_token(uid, body.email), "usuario": usuario}

@app.post("/api/auth/login")
async def login(body: LoginBody):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM usuarios WHERE email = %s", (body.email,))
            u = await cur.fetchone()
            if not u or not await verificar_senha(body.senha, u["senha"]):
                raise HTTPException(status_code=401, detail={"erro": "Credenciais inválidas", "codigo": "CREDENCIAIS_INVALIDAS"})
            # TEMPORÁRIO (Fase 0): converte senha legada em hash no primeiro login bem-sucedido.
            # CONDIÇÃO PARA APAGAR: a contagem de senhas em texto plano chegar a zero
            # (log do startup ou métrica "Senhas sem hash" no painel admin). Ver verificar_senha.
            if not eh_hash_bcrypt(u["senha"]):
                await cur.execute("UPDATE usuarios SET senha = %s WHERE id = %s", (await gerar_hash_senha(body.senha), u["id"]))
                logger.info("🔐 Senha migrada para bcrypt")
            u["modulos_concluidos"] = json.loads(u["modulos_concluidos"]) if isinstance(u["modulos_concluidos"], str) else (u["modulos_concluidos"] or [])
            u["teste_inicial_concluido"] = bool(u["teste_inicial_concluido"])
            return {"token": gerar_token(u["id"], body.email), "usuario": {k:v for k,v in u.items() if k!="senha"}}

@app.get("/api/auth/me")
async def me(usuario: dict = Depends(get_usuario)):
    return {k:v for k,v in usuario.items() if k!="senha"}

@app.patch("/api/auth/perfil")
async def atualizar_perfil(body: dict, usuario: dict = Depends(get_usuario)):
    campos_permitidos = ["nome", "email", "cidade"]
    updates = []
    values = []
    for campo in campos_permitidos:
        if campo in body and body[campo]:
            updates.append(f"{campo}=%s")
            values.append(str(body[campo]).strip())
    if "senha_nova" in body and body["senha_nova"]:
        # verificar_senha ainda aceita senha atual em texto plano (conta antiga).
        # CONDIÇÃO PARA APAGAR esse caminho: a contagem de senhas em texto plano
        # chegar a zero (log do startup ou métrica "Senhas sem hash" no painel admin).
        if not body.get("senha_atual") or not await verificar_senha(str(body["senha_atual"]), usuario["senha"]):
            raise HTTPException(status_code=400, detail={"erro": "Senha atual incorreta"})
        updates.append("senha=%s")
        values.append(await gerar_hash_senha(str(body["senha_nova"]).strip()))
    if "nome" in body and body["nome"]:
        partes = str(body["nome"]).strip().split()
        iniciais = "".join(p[0].upper() for p in partes[:2])
        updates.append("avatar_iniciais=%s")
        values.append(iniciais)
    if updates:
        values.append(usuario["id"])
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(f"UPDATE usuarios SET {', '.join(updates)} WHERE id=%s", values)
    atualizado = await get_usuario({"sub": usuario["id"]})
    return {k:v for k,v in atualizado.items() if k!="senha"}

# ── Teste Inicial ──────────────────────────────────────────────────────────────
@app.get("/api/testeinicial/perguntas")
async def get_perguntas(usuario: dict = Depends(get_usuario)):
    perguntas = perguntas_teste_ativas()
    return {"perguntas": perguntas, "total": len(perguntas)}

@app.patch("/api/testeinicial/resposta")
async def salvar_resposta(body: RespostaBody, usuario: dict = Depends(get_usuario)):
    ids_validos = ids_perguntas_teste_ativas()
    if body.perguntaId not in ids_validos:
        raise HTTPException(status_code=400, detail={"erro": "Pergunta inicial inválida", "codigo": "PERGUNTA_INVALIDA"})
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO respostas_teste (usuario_id, pergunta_id, valor, texto_livre)
                   VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s, texto_livre=%s""",
                (usuario["id"], body.perguntaId, body.valor, body.textoLivre or "",
                 body.valor, body.textoLivre or "")
            )
            await cur.execute("SELECT COUNT(*) as total FROM respostas_teste WHERE usuario_id=%s", (usuario["id"],))
            r = await cur.fetchone()
    return {"salvo": True, "respondidas": r[0], "total": len(ids_validos)}

@app.get("/api/testeinicial/progresso")
async def progresso_teste(usuario: dict = Depends(get_usuario)):
    ids_validos = ids_perguntas_teste_ativas()
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM respostas_teste WHERE usuario_id=%s", (usuario["id"],))
            r = await cur.fetchone()
    return {"respondidas": r[0], "total": len(ids_validos)}

@app.get("/api/testeinicial/respostas/destaque")
async def respostas_teste_destaque(limite: int = 3, aleatorio: bool = True, usuario: dict = Depends(get_usuario)):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT pergunta_id, valor, texto_livre FROM respostas_teste WHERE usuario_id=%s", (usuario["id"],))
            rows = await cur.fetchall()
    respostas_dict = {r["pergunta_id"]: {"valor": r["valor"], "textoLivre": r["texto_livre"]} for r in rows}
    perguntas_por_id = {p["id"]: p for p in perguntas_teste_ativas()}
    respondidas = [
        formatar_resposta_teste(perguntas_por_id[pid], resposta)
        for pid, resposta in sorted(respostas_dict.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999)
        if pid in perguntas_por_id and str(resposta.get("valor", "")).strip()
    ]
    limite = max(1, min(limite, 22))
    if aleatorio and limite < len(respondidas):
        selecionadas = random.sample(respondidas, limite)
    else:
        selecionadas = respondidas[:limite]
    return {"respostas": selecionadas}

@app.post("/api/testeinicial/finalizar")
async def finalizar_teste(body: FinalizarTesteBody, usuario: dict = Depends(get_usuario)):
    uid = usuario["id"]
    ids_validos = ids_perguntas_teste_ativas()
    ids_obrigatorios = ids_perguntas_teste_obrigatorias()
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            for r in body.respostas:
                pid = str(r["perguntaId"])
                if pid not in ids_validos:
                    continue
                await cur.execute(
                    """INSERT INTO respostas_teste (usuario_id, pergunta_id, valor, texto_livre)
                       VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s, texto_livre=%s""",
                    (uid, pid, r.get("valor",""), r.get("textoLivre",""),
                     r.get("valor",""), r.get("textoLivre",""))
                )
            await cur.execute("SELECT pergunta_id, valor FROM respostas_teste WHERE usuario_id=%s", (uid,))
            rows = await cur.fetchall()
            respondidas = {row[0] for row in rows if str(row[1]).strip() and row[0] in ids_obrigatorios}
            if len(respondidas) < len(ids_obrigatorios):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "erro": "Responda todas as perguntas obrigatórias.",
                        "codigo": "TESTE_INICIAL_INCOMPLETO",
                        "respondidas": len(respondidas),
                        "total": len(ids_obrigatorios),
                    }
                )
            await cur.execute("UPDATE usuarios SET teste_inicial_concluido=TRUE WHERE id=%s", (uid,))
    job_id = str(uuid.uuid4())
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO jobs (id, usuario_id, status) VALUES (%s,%s,'processando')", (job_id, uid))
    usuario["teste_inicial_concluido"] = True
    asyncio.create_task(processar_resultado_ia_db(job_id, uid, usuario, "Teste inicial"))
    return {"processando": True, "jobId": job_id}


async def get_respostas_do_banco(usuario_id: str) -> dict:
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT pergunta_id, valor, texto_livre FROM respostas_teste WHERE usuario_id=%s", (usuario_id,))
            rows = await cur.fetchall()
            return {r["pergunta_id"]: {"valor": r["valor"], "textoLivre": r["texto_livre"]} for r in rows}

async def get_respostas_modulo_do_banco(usuario_id: str, modulo_id: str) -> dict:
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT pergunta_id, valor, texto_livre FROM respostas_modulo WHERE usuario_id=%s AND modulo_id=%s", (usuario_id, modulo_id))
            rows = await cur.fetchall()
            return {r["pergunta_id"]: {"valor": r["valor"], "textoLivre": r["texto_livre"]} for r in rows}


async def modulo_desbloqueado_db(modulo_id: str, usuario: dict) -> bool:
    if modulo_id not in PERGUNTAS_MODULOS:
        return False
    concluidos = usuario.get("modulos_concluidos", [])
    ids = list(PERGUNTAS_MODULOS.keys())
    idx = ids.index(modulo_id)
    if modulo_id in concluidos:
        return True
    if idx == 0:
        return bool(usuario.get("teste_inicial_concluido", False))
    return ids[idx-1] in concluidos

async def processar_resultado_ia_db(job_id: str, uid: str, usuario: dict, origem: str = "Job"):
    try:
        rt = await get_respostas_do_banco(uid)
        rm = {}
        for mid in PERGUNTAS_MODULOS.keys():
            rm[mid] = await get_respostas_modulo_do_banco(uid, mid)
        
        def fmt_respostas(resps):
            linhas = []
            for pid, dados in sorted(resps.items()):
                if isinstance(dados, dict):
                    linha = f"  [{pid}] {dados.get('valor','')}"
                    if dados.get('textoLivre'):
                        linha += f" | Texto livre: \"{dados['textoLivre']}\""
                else:
                    linha = f"  [{pid}] {dados}"
                linhas.append(linha)
            return "\n".join(linhas) or "  Não respondido"

        linhas_teste = fmt_respostas(rt)
        linhas_mod = ""
        for mid, info in PERGUNTAS_MODULOS.items():
            linhas_mod += f"\nMódulo {mid} — {info['titulo']}:\n{fmt_respostas(rm.get(mid, {}))}"

        prompt = montar_prompt_base(usuario["nome"], linhas_teste, linhas_mod)
        resultado = await chamar_ia(prompt, job_id)

        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """INSERT INTO perfis (usuario_id, dados) VALUES (%s,%s)
                       ON DUPLICATE KEY UPDATE dados=%s, atualizado_em=CURRENT_TIMESTAMP""",
                    (uid, json.dumps(resultado), json.dumps(resultado))
                )
                await cur.execute("UPDATE jobs SET status='concluido' WHERE id=%s", (job_id,))
        logger.info(f"✅ {origem} {job_id} concluído")
    except Exception as e:
        erro_raw = str(e) or repr(e)
        # Monta mensagem amigável para o admin
        # Truncagem vem primeiro e pelo tipo, não pelo texto: a mensagem dela
        # não pode cair por engano no ramo de formato inválido abaixo.
        if isinstance(e, RespostaTruncada):
            erro_admin = (
                f" Resposta cortada pelo limite de tokens ({origem}). Não é instabilidade da API: "
                "o plano não coube em max_tokens, e repetir gera o mesmo corte."
            )
        elif "tempo" in erro_raw.lower() or "timeout" in erro_raw.lower() or "demorou" in erro_raw.lower():
            erro_admin = f" Timeout — IA demorou demais ({origem}). Muitos usuários simultâneos."
        elif "rate limit" in erro_raw.lower() or "429" in erro_raw or "simultâneos" in erro_raw.lower():
            erro_admin = f" Rate limit — muitos usuários ao mesmo tempo ({origem}). Usuário pode refazer."
        elif "sobrecarregado" in erro_raw.lower() or "529" in erro_raw:
            erro_admin = f" API sobrecarregada ({origem}). Tentar novamente em alguns minutos."
        elif "conexão" in erro_raw.lower() or "connect" in erro_raw.lower():
            erro_admin = f" Falha de rede ao contactar a IA ({origem}). Verificar conectividade do servidor."
        elif "inválida" in erro_raw.lower() or "401" in erro_raw:
            erro_admin = f" Chave de API inválida ({origem}). Verificar ANTHROPIC_API_KEY nas variáveis de ambiente."
        elif "formato" in erro_raw.lower() or "json" in erro_raw.lower():
            erro_admin = f" IA retornou resposta em formato inválido ({origem}). Pode ser instabilidade da API."
        else:
            erro_admin = f"❌ Erro inesperado ({origem}): {erro_raw[:200]}"
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE jobs SET status='erro', erro=%s WHERE id=%s", (erro_admin, job_id))
        logger.exception(f"❌ {origem} {job_id} falhou: {erro_raw}")

# ── Recuperação de job travado ────────────────────────────────────────────────
# Decisões registradas no ROADMAP em 01/11/2026. Resumo:
# - tentativas = 0 quer dizer que o job nunca começou: está na fila do
#   semáforo ou ficou órfão quando o processo caiu. Com o processo vivo,
#   heartbeat velho com tentativas = 0 é fila, não trava.
# - O job só é pego por UPDATE condicional. A condição que decide se ele está
#   parado fica no WHERE do próprio UPDATE, e a tarefa só é disparada se o
#   UPDATE afetou uma linha. Dois caminhos nunca pegam o mesmo job.
# - O UPDATE zera tentativas: o job volta para a fila e, enquanto espera vaga,
#   a varredura não toca nele. O histórico fica em recuperacoes, que só cresce.
# - Job que chega a IA_MAX_RECUPERACOES é encerrado como erro (decisão de
#   26/11/2026 no ROADMAP).

# O asyncio guarda só referência fraca das tarefas criadas com create_task.
# Sem guardar a referência aqui, uma tarefa de recuperação pode ser coletada
# no meio da execução.
_tarefas_recuperacao: set = set()

async def _reenfileirar(job_id: str, uid: str, origem: str) -> bool:
    """Dispara de novo a geração de um job já reivindicado pelo UPDATE condicional."""
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id, nome FROM usuarios WHERE id=%s", (uid,))
            usuario = await cur.fetchone()
            if not usuario:
                # Normalmente impossível: apagar o usuário apaga os jobs (ON DELETE CASCADE).
                await cur.execute(
                    "UPDATE jobs SET status='erro', erro=%s WHERE id=%s",
                    (f" Usuário do job não encontrado ({origem}).", job_id),
                )
                logger.warning(f"Recuperação job={job_id}: usuário não encontrado, job marcado como erro")
                return False
    tarefa = asyncio.create_task(processar_resultado_ia_db(job_id, uid, usuario, origem))
    _tarefas_recuperacao.add(tarefa)
    tarefa.add_done_callback(_tarefas_recuperacao.discard)
    return True

async def _reenfileirar_ou_encerrar(job_id: str, uid: str, condicao: str, params: tuple, origem: str) -> str:
    """Tenta pegar um job candidato. Devolve 'reenfileirado', 'encerrado' ou 'nada'.

    condicao/params dizem o que é "parado" para quem chamou (inicialização ou
    varredura). Os dois UPDATEs repetem essa condição no WHERE e se excluem
    pelo teto:
    - abaixo do teto, reenfileira: zera tentativas, soma 1 em recuperacoes e
      renova o heartbeat;
    - no teto, encerra como erro. Se ficasse em 'processando', a varredura
      olharia para ele a cada rodada para sempre, e ninguém veria no painel.
    Se nenhum dos dois afetou linha, outro caminho mexeu no job desde o
    SELECT, e ele fica como está.
    """
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE jobs SET tentativas = 0, recuperacoes = recuperacoes + 1, atualizado_em = NOW() "
                f"WHERE id = %s AND {condicao} AND recuperacoes < %s",
                (job_id, *params, IA_MAX_RECUPERACOES),
            )
            pegou = cur.rowcount == 1
            if not pegou:
                await cur.execute(
                    "UPDATE jobs SET status = 'erro', erro = CONCAT("
                    "' Job recuperado ', recuperacoes, ' vez(es) sem concluir (', %s, '). "
                    "Não foi reenfileirado de novo, para não pagar outra geração. Procure no log as "
                    "linhas Recuperação job=', id, ' para ver o que interrompe este job.') "
                    f"WHERE id = %s AND {condicao} AND recuperacoes >= %s",
                    (origem, job_id, *params, IA_MAX_RECUPERACOES),
                )
                if cur.rowcount == 1:
                    logger.error(
                        f"Recuperação job={job_id}: atingiu o teto de {IA_MAX_RECUPERACOES} recuperação(ões) "
                        "sem concluir, encerrado como erro"
                    )
                    return "encerrado"
                return "nada"
    if await _reenfileirar(job_id, uid, origem):
        return "reenfileirado"
    return "nada"

async def recuperar_jobs_orfaos() -> dict:
    """Na inicialização: trata todo job em 'processando', qualquer que seja tentativas.

    Os jobs só vivem em memória, então o que estava em 'processando' quando o
    processo caiu ficou órfão. A condição "heartbeat anterior ao início deste
    processo" pega exatamente esses e torna o reenfileiramento sempre
    efetivo: o novo atualizado_em (NOW()) é sempre diferente do antigo, então
    rowcount = 1 quer dizer que este processo pegou o job.

    Um job que derruba o processo volta aqui a cada reinício. O teto de
    recuperacoes (IA_MAX_RECUPERACOES) encerra esse ciclo.

    LIMITAÇÃO: se outro processo ainda estiver vivo atendendo jobs, como na
    sobreposição de instâncias durante um deploy, os jobs dele também são
    pegos e a geração é paga duas vezes. Hoje há uma instância só; fica como
    pendência da reconexão do deploy (ROADMAP, riscos conhecidos).
    """
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT NOW()")
            (inicio,) = await cur.fetchone()
    condicao = "status = 'processando' AND atualizado_em < %s"
    candidatos = await _candidatos(condicao, (inicio,))
    contagem = {"reenfileirado": 0, "encerrado": 0, "nada": 0}
    for job_id, uid in candidatos:
        r = await _reenfileirar_ou_encerrar(job_id, uid, condicao, (inicio,), "Recuperação (inicialização)")
        contagem[r] += 1
        if r == "reenfileirado":
            logger.warning(f"Recuperação job={job_id}: órfão da execução anterior, reenfileirado")
    logger.info(
        f"Recuperação na inicialização: {contagem['reenfileirado']} job(s) órfão(s) reenfileirado(s), "
        f"{contagem['encerrado']} encerrado(s) por atingir o teto"
    )
    return contagem

async def recuperar_jobs_travados() -> dict:
    """Com a aplicação rodando: trata só job que começou (tentativas > 0) e parou de dar sinal.

    Job com tentativas = 0 está na fila do semáforo e não é tocado, por mais
    velho que seja o heartbeat dele.
    """
    condicao = (
        "status = 'processando' AND tentativas > 0 "
        "AND atualizado_em < NOW() - INTERVAL %s SECOND"
    )
    params = (LIMITE_JOB_TRAVADO_S,)
    contagem = {"reenfileirado": 0, "encerrado": 0, "nada": 0}
    for job_id, uid in await _candidatos(condicao, params):
        # A condição é conferida de novo nos UPDATEs: entre o SELECT e aqui o
        # job pode ter concluído, dado heartbeat ou sido pego por outro caminho.
        r = await _reenfileirar_ou_encerrar(job_id, uid, condicao, params, "Recuperação (job travado)")
        contagem[r] += 1
        if r == "reenfileirado":
            logger.warning(
                f"Recuperação job={job_id}: sem heartbeat há mais de {LIMITE_JOB_TRAVADO_S}s, reenfileirado"
            )
    return contagem

async def _candidatos(condicao: str, params: tuple) -> list:
    """Lista (id, usuario_id) dos jobs que atendem a condição. Só lista: quem decide é o UPDATE."""
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT id, usuario_id FROM jobs WHERE {condicao}", params)
            return list(await cur.fetchall())

async def _varrer_jobs_periodicamente():
    while True:
        await asyncio.sleep(VARREDURA_JOBS_INTERVALO_S)
        try:
            await recuperar_jobs_travados()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Uma falha do banco numa rodada não pode matar a varredura.
            logger.warning(f"Varredura de jobs travados falhou nesta rodada: {type(e).__name__}: {e}")

# ── Resultado ──────────────────────────────────────────────────────────────────
@app.get("/api/resultado/status")
async def resultado_status(jobId: str, usuario: dict = Depends(get_usuario)):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT status, erro FROM jobs WHERE id=%s", (jobId,))
            job = await cur.fetchone()
            if not job:
                raise HTTPException(status_code=404, detail={"erro": "Job não encontrado", "codigo": "JOB_NAO_ENCONTRADO"})
            data = {"status": job["status"]}
            if job["status"] == "erro":
                data["erro"] = job["erro"] or "A IA não conseguiu gerar o resultado agora."
            return data

@app.get("/api/resultado")
async def get_resultado(usuario: dict = Depends(get_usuario)):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT dados, atualizado_em FROM perfis WHERE usuario_id=%s", (usuario["id"],))
            r = await cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail={"erro": "Resultado não encontrado", "codigo": "RESULTADO_NAO_ENCONTRADO"})
            dados = json.loads(r["dados"])
            dados["_atualizado_em"] = r["atualizado_em"].isoformat() if r["atualizado_em"] else None
            return dados

# ── Módulos ────────────────────────────────────────────────────────────────────
@app.get("/api/modulos")
async def get_modulos(usuario: dict = Depends(get_usuario)):
    uid = usuario["id"]
    concluidos = usuario.get("modulos_concluidos", [])
    teste_ok = usuario.get("teste_inicial_concluido", False)
    modulos = []
    anterior_ok = teste_ok
    for mid, info in PERGUNTAS_MODULOS.items():
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT COUNT(*) FROM respostas_modulo WHERE usuario_id=%s AND modulo_id=%s", (uid, mid))
                r = await cur.fetchone()
                respondidas = r[0]
        concluido = mid in concluidos
        status = "done" if concluido else ("active" if anterior_ok else "locked")
        modulos.append({
            "id": mid, "numero": mid, "titulo": info["titulo"],
            "descricao": info["descricao"], "status": status,
            "progresso": 100 if concluido else round((respondidas/8)*100)
        })
        anterior_ok = concluido
    return {"modulos": modulos}

@app.get("/api/modulos/{modulo_id}/perguntas")
async def get_perguntas_modulo(modulo_id: str, usuario: dict = Depends(get_usuario)):
    if modulo_id not in PERGUNTAS_MODULOS:
        raise HTTPException(status_code=404, detail={"erro": "Módulo não encontrado"})
    if not await modulo_desbloqueado_db(modulo_id, usuario):
        raise HTTPException(status_code=403, detail={"erro": "Módulo bloqueado. Responda todas as perguntas iniciais primeiro."})
    return {"perguntas": PERGUNTAS_MODULOS[modulo_id]["perguntas"], "total": len(PERGUNTAS_MODULOS[modulo_id]["perguntas"])}

@app.patch("/api/modulos/{modulo_id}/resposta")
async def salvar_resposta_modulo(modulo_id: str, body: RespostaModuloBody, usuario: dict = Depends(get_usuario)):
    if not await modulo_desbloqueado_db(modulo_id, usuario):
        raise HTTPException(status_code=403, detail={"erro": "Módulo bloqueado. Responda todas as perguntas iniciais primeiro."})
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO respostas_modulo (usuario_id, modulo_id, pergunta_id, valor, texto_livre)
                   VALUES (%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE valor=%s, texto_livre=%s""",
                (usuario["id"], modulo_id, body.perguntaId, body.valor, body.textoLivre or "",
                 body.valor, body.textoLivre or "")
            )
            await cur.execute("SELECT COUNT(*) FROM respostas_modulo WHERE usuario_id=%s AND modulo_id=%s", (usuario["id"], modulo_id))
            r = await cur.fetchone()
    total = len(PERGUNTAS_MODULOS.get(modulo_id, {}).get("perguntas", []))
    return {"salvo": True, "respondidas": r[0], "total": total}

@app.get("/api/modulos/{modulo_id}/progresso")
async def progresso_modulo(modulo_id: str, usuario: dict = Depends(get_usuario)):
    total = len(PERGUNTAS_MODULOS.get(modulo_id, {}).get("perguntas", []))
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) FROM respostas_modulo WHERE usuario_id=%s AND modulo_id=%s", (usuario["id"], modulo_id))
            r = await cur.fetchone()
    return {"respondidas": r[0], "total": total, "percentual": round((r[0]/total)*100) if total else 0}

@app.post("/api/modulos/{modulo_id}/finalizar")
async def finalizar_modulo(modulo_id: str, usuario: dict = Depends(get_usuario)):
    if not await modulo_desbloqueado_db(modulo_id, usuario):
        raise HTTPException(status_code=403, detail={"erro": "Módulo bloqueado. Responda todas as perguntas iniciais primeiro."})
    uid = usuario["id"]
    concluidos = list(usuario.get("modulos_concluidos", []))
    if modulo_id not in concluidos:
        concluidos.append(modulo_id)
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE usuarios SET modulos_concluidos=%s WHERE id=%s", (json.dumps(concluidos), uid))
    if modulo_id == "04":
        job_id = str(uuid.uuid4())
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT INTO jobs (id, usuario_id, status) VALUES (%s,%s,'processando')", (job_id, uid))
        usuario["modulos_concluidos"] = concluidos
        asyncio.create_task(processar_resultado_ia_db(job_id, uid, usuario, "Módulo 04"))
        return {"concluido": True, "jobId": job_id}
    return {"concluido": True, "proximoModulo": f"{int(modulo_id)+1:02d}"}

# ── Histórico — reset e respostas do usuário ──────────────────────────────────
@app.delete("/api/testeinicial/resetar")
async def resetar_teste(usuario: dict = Depends(get_usuario)):
    uid = usuario["id"]
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM respostas_teste WHERE usuario_id=%s", (uid,))
            await cur.execute("DELETE FROM perfis WHERE usuario_id=%s", (uid,))
            await cur.execute("UPDATE usuarios SET teste_inicial_concluido=FALSE WHERE id=%s", (uid,))
    return {"ok": True, "mensagem": "Dados resetados com sucesso"}

@app.get("/api/testeinicial/minhas-respostas")
async def minhas_respostas(usuario: dict = Depends(get_usuario)):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT pergunta_id, valor, texto_livre FROM respostas_teste WHERE usuario_id=%s ORDER BY CAST(pergunta_id AS UNSIGNED)",
                (usuario["id"],)
            )
            rows = await cur.fetchall()
    return {"respostas": [{"perguntaId": r["pergunta_id"], "valor": r["valor"], "textoLivre": r["texto_livre"] or ""} for r in rows]}

# ── Contexto livre extra ───────────────────────────────────────────────────────
@app.post("/api/contexto")
async def salvar_contexto(body: ContextoLivreBody, usuario: dict = Depends(get_usuario)):
    return {"salvo": True}

# ── Perfil ─────────────────────────────────────────────────────────────────────
@app.get("/api/perfil")
async def get_perfil(usuario: dict = Depends(get_usuario)):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT dados FROM perfis WHERE usuario_id=%s", (usuario["id"],))
            r = await cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail={"erro": "Perfil não gerado"})
            return json.loads(r["dados"])

@app.get("/api/mapa/progresso")
async def get_mapa_progresso(usuario: dict = Depends(get_usuario)):
    usuario_id = usuario["id"]
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT etapas_concluidas, checks_feitos FROM mapa_progresso WHERE usuario_id = %s",
                (usuario_id,)
            )
            row = await cur.fetchone()
    if not row:
        return {"etapasConcluidas": {}, "checksFeitos": {}}
    return {
        "etapasConcluidas": json.loads(row["etapas_concluidas"] or "{}"),
        "checksFeitos": json.loads(row["checks_feitos"] or "{}")
    }

@app.post("/api/mapa/progresso")
async def save_mapa_progresso(body: dict, usuario: dict = Depends(get_usuario)):
    usuario_id = usuario["id"]
    etapas = json.dumps(body.get("etapasConcluidas", {}))
    checks = json.dumps(body.get("checksFeitos", {}))
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO mapa_progresso (usuario_id, etapas_concluidas, checks_feitos)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    etapas_concluidas = %s,
                    checks_feitos = %s,
                    atualizado_em = CURRENT_TIMESTAMP
            """, (usuario_id, etapas, checks, etapas, checks))
    return {"ok": True}

@app.get("/api/mapa")
async def get_mapa(usuario: dict = Depends(get_usuario)):
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT dados FROM perfis WHERE usuario_id=%s", (usuario["id"],))
            r = await cur.fetchone()
            if not r:
                raise HTTPException(status_code=404, detail={"erro": "Perfil não gerado"})
            dados = json.loads(r["dados"])
            return {"steps": dados.get("mapaCarreira", [])}

@app.get("/api/jornada/progresso")
async def jornada_prog(usuario: dict = Depends(get_usuario)):
    c = len(usuario.get("modulos_concluidos", []))
    async with db_pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT dados FROM perfis WHERE usuario_id=%s", (usuario["id"],))
            r = await cur.fetchone()
    dados = json.loads(r["dados"]) if r else {}
    return {"percentual": round((c/4)*100), "modulosCompletos": c, "totalModulos": 4,
            "habilidadesAtivas": dados.get("skills", []) if dados else []}


async def chamar_ia_lista(prompt: str) -> list:
    if not ANTHROPIC_API_KEY and not ia_simulada.config.ativa:
        raise RuntimeError("Chave de API não configurada no servidor.")
    # Semáforo próprio, separado do da geração do plano: com um só, a chamada
    # curta esperaria atrás de gerações de ~100 s. Toda chamada à IA continua
    # passando por um semáforo, e o teto total é a soma dos dois limites.
    sem = _obter_ia_semaphore_lista()
    t_inicio_espera = time.monotonic()
    async with sem:
        espera = time.monotonic() - t_inicio_espera
        logger.info(f"IA lista evento=fila_entrada espera={espera:.1f}s")
        resp = await _enviar_para_ia(prompt, max_tokens=2000, timeout=60.0, tipo="lista")
    if resp.status_code != 200:
        raise RuntimeError(f"Erro da IA: {resp.status_code}")
    texto = "".join(b.get("text", "") for b in resp.json().get("content", [])).strip()
    texto = re.sub(r'```json\s*', '', texto)
    texto = re.sub(r'```\s*', '', texto)
    texto = texto.strip()
    match = re.search(r'\[[\s\S]*\]', texto)
    if match:
        return json.loads(match.group())
    raise RuntimeError("A IA não retornou uma lista válida.")

@app.post("/api/vagas")
async def buscar_vagas(body: dict, usuario: dict = Depends(get_usuario)):
    area = body.get("profissao", "").strip()
    cidade = body.get("localizacao", "Brasil").strip()

    if not area:
        return []

    prompt = f"""Você é um orientador de carreira para jovens brasileiros do ensino médio.
O aluno mora em {cidade} e sua área de interesse é {area}.

Gere uma lista com exatamente 6 oportunidades reais de entrada no mercado para esse perfil.
Foque em: programas Jovem Aprendiz, estágios para jovens, certificações gratuitas ou baratas, e concursos públicos de nível médio.
NÃO inclua faculdades, cursos técnicos longos nem cursos online — esses já são cobertos em outras páginas do sistema.
NÃO mencione datas, prazos nem anos específicos — apenas oportunidades permanentes ou recorrentes.

Responda APENAS com JSON válido, sem texto antes ou depois, sem markdown, sem ```json:
[
  {{
    "titulo": "nome da oportunidade em até 60 caracteres",
    "empresa": "nome da instituição ou programa",
    "descricao": "o que é e como ajuda o jovem em 2 frases",
    "comoAcessar": "instrução clara de como acessar (site oficial ou passo a passo)",
    "tipo": "aprendiz|estagio|certificacao|concurso",
    "gratuito": true
  }}
]"""

    try:
        resultado = await chamar_ia_lista(prompt)
        if isinstance(resultado, list):
            return resultado
        if isinstance(resultado, dict):
            for v in resultado.values():
                if isinstance(v, list):
                    return v
        return []
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Erro ao gerar oportunidades: {str(e)}")

# ── Arquivos estáticos (deve ficar após todas as rotas) ────────────────────────
app.mount("/js",       StaticFiles(directory=os.path.join(BASE_DIR, "js")),       name="js")
app.mount("/styles",   StaticFiles(directory=os.path.join(BASE_DIR, "styles")),   name="styles")
app.mount("/assets",   StaticFiles(directory=os.path.join(BASE_DIR, "assets")),   name="assets")
app.mount("/partials", StaticFiles(directory=os.path.join(BASE_DIR, "partials")), name="partials")
app.mount("/assets", StaticFiles(directory=os.path.join(BASE_DIR, "assets")), name="assets")