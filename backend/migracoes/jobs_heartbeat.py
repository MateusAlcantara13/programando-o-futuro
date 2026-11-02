"""Migração: colunas `tentativas` e `atualizado_em` na tabela `jobs`.

Roda sozinha no startup da aplicação (ver init_db em main.py) e também pode
ser executada à mão contra um banco, a partir da pasta backend/:

    python -m migracoes.jobs_heartbeat

É idempotente: rodar várias vezes deixa o banco no mesmo estado.

Por que os passos de atualizado_em são três e não um:
no MySQL todo ALTER TABLE faz commit implícito, então não dá para pôr os
passos numa transação. Se o processo cair no meio, a próxima execução
precisa conseguir terminar o trabalho olhando só o estado do banco. Por
isso a guarda da cópia de criado_em é "atualizado_em IS NULL", e não
"a coluna foi criada nesta execução".
"""
import logging

logger = logging.getLogger(__name__)

COMO_RESOLVER = (
    "O que fazer: (1) procure acima neste log as linhas que começam com "
    "'migracao jobs' para ver qual passo falhou e a mensagem do MySQL; "
    "(2) corrija a causa (permissão do usuário do banco, conexão, etc.) e "
    "rode a migração à mão, na pasta backend/, com: "
    "python -m migracoes.jobs_heartbeat ; "
    "(3) não altere a tabela jobs direto no console do banco. "
    "A aplicação não vai servir requisições até isso ser resolvido."
)


class EsquemaJobsInvalido(RuntimeError):
    """O esquema da tabela jobs não está como o código espera."""


async def _tabela_existe(cur, tabela: str) -> bool:
    await cur.execute(
        "SELECT COUNT(*) FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
        (tabela,),
    )
    (total,) = await cur.fetchone()
    return total > 0


async def _info_coluna(cur, tabela: str, coluna: str):
    """Devolve None se a coluna não existe, ou o valor de IS_NULLABLE ('YES'/'NO')."""
    await cur.execute(
        "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (tabela, coluna),
    )
    linha = await cur.fetchone()
    return linha[0] if linha else None


async def _migrar_tentativas(cur):
    if await _info_coluna(cur, "jobs", "tentativas") is not None:
        logger.info("migracao jobs.tentativas: coluna já existe, nada a fazer")
        return
    # Linhas antigas recebem 0, que deve ser lido como "não registrado".
    await cur.execute("ALTER TABLE jobs ADD COLUMN tentativas INT NOT NULL DEFAULT 0")
    logger.info("migracao jobs.tentativas: coluna criada")


async def _migrar_atualizado_em(cur):
    # Passo 1: cria a coluna NULA e SEM default. Sem default, as linhas
    # existentes ficam NULL em vez de receber a data da migração.
    if await _info_coluna(cur, "jobs", "atualizado_em") is None:
        await cur.execute("ALTER TABLE jobs ADD COLUMN atualizado_em DATETIME NULL")
        logger.info("migracao jobs.atualizado_em: coluna criada (passo 1)")
    else:
        logger.info("migracao jobs.atualizado_em: coluna já existe (passo 1 pulado)")

    # Passo 2: copia criado_em SOMENTE onde atualizado_em é NULL.
    # NULL só existe entre o passo 1 e o passo 3, e o heartbeat sempre grava
    # NOW(), que nunca é NULL. Esta condição nunca alcança um heartbeat real.
    # Também cobre job inserido por código antigo durante a migração.
    await cur.execute("UPDATE jobs SET atualizado_em = criado_em WHERE atualizado_em IS NULL")
    logger.info(f"migracao jobs.atualizado_em: {cur.rowcount} linha(s) preenchida(s) com criado_em (passo 2)")

    # Passo 3: fecha a coluna. Depois disso NULL é impossível e o passo 2 vira
    # no-op permanente. Se sobrar alguma linha NULL, o MODIFY falha em modo
    # estrito (padrão do MySQL 8) em vez de converter em silêncio.
    # Sem ON UPDATE: o valor só muda quando o código grava o heartbeat.
    if await _info_coluna(cur, "jobs", "atualizado_em") == "YES":
        await cur.execute(
            "ALTER TABLE jobs MODIFY atualizado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
        )
        logger.info("migracao jobs.atualizado_em: NOT NULL aplicado (passo 3)")
    else:
        logger.info("migracao jobs.atualizado_em: já é NOT NULL (passo 3 pulado)")


async def migrar_jobs_heartbeat(conn):
    async with conn.cursor() as cur:
        if not await _tabela_existe(cur, "jobs"):
            raise EsquemaJobsInvalido(
                "migracao jobs: a tabela jobs não existe neste banco. "
                "No startup ela é criada por criar_tabelas() antes desta migração; "
                "se você rodou o script à mão, confira se DB_NAME aponta para o banco certo. "
                + COMO_RESOLVER
            )
        try:
            await _migrar_tentativas(cur)
            await _migrar_atualizado_em(cur)
        except Exception as e:
            logger.error(f"migracao jobs: falhou com {type(e).__name__}: {e}. {COMO_RESOLVER}")
            raise


async def verificar_jobs_heartbeat(conn):
    """Recusa seguir se as colunas não existirem ou aceitarem NULL."""
    problemas = []
    async with conn.cursor() as cur:
        for coluna in ("tentativas", "atualizado_em"):
            nulo = await _info_coluna(cur, "jobs", coluna)
            if nulo is None:
                problemas.append(f"a coluna jobs.{coluna} não existe")
            elif nulo == "YES":
                await cur.execute(f"SELECT COUNT(*) FROM jobs WHERE {coluna} IS NULL")
                (nulos,) = await cur.fetchone()
                problemas.append(
                    f"a coluna jobs.{coluna} aceita NULL (deveria ser NOT NULL; {nulos} linha(s) com NULL hoje)"
                )
    if problemas:
        msg = (
            "Esquema do banco desatualizado, a aplicação não vai iniciar: "
            + "; ".join(problemas)
            + ". A migração automática do startup deveria ter corrigido isso. "
            + COMO_RESOLVER
        )
        logger.error(msg)
        raise EsquemaJobsInvalido(msg)
    logger.info("migracao jobs: verificação ok (tentativas e atualizado_em presentes e NOT NULL)")


async def _executar_manual():
    # Importado aqui dentro para que importar este módulo a partir de main.py
    # não gere import circular.
    from main import criar_pool

    pool = await criar_pool()
    try:
        async with pool.acquire() as conn:
            await migrar_jobs_heartbeat(conn)
            await verificar_jobs_heartbeat(conn)
    finally:
        pool.close()
        await pool.wait_closed()


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(_executar_manual())
