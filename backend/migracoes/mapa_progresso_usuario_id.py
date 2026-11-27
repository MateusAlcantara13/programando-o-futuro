"""Migração: tipo de `mapa_progresso.usuario_id`, de INT para VARCHAR(36).

Roda sozinha no startup da aplicação (ver init_db em main.py) e também pode
ser executada à mão contra um banco, a partir da pasta backend/:

    python -m migracoes.mapa_progresso_usuario_id

É idempotente: com a coluna já em VARCHAR, não faz nada.

O problema: a coluna nasceu INT, mas o id do usuário é um UUID em texto.
Com o MySQL em modo estrito (padrão do MySQL 8), gravar '3f2a...' numa
coluna INT dá erro, e o progresso nunca foi salvo. Sem modo estrito, o
MySQL grava só os dígitos do começo do UUID ('3f2a...' vira 3, e um UUID
que começa com letra vira 0). Como a coluna é UNIQUE, alunos diferentes
passam a dividir a mesma linha e um sobrescreve o progresso do outro.

Por isso, antes de alterar a coluna, a migração conta e registra no log:
o total de linhas, quantas pertencem a um usuário existente e quantas
estão com usuario_id = 0. Em ambos os modos, a expectativa é de zero
linhas utilizáveis.

As linhas antigas NÃO são apagadas. Depois da conversão elas ficam com
usuario_id '3', '0' etc., que não coincidem com nenhum UUID, então
nenhuma rota da aplicação chega até elas. Apagar ou não é decisão da
equipe, não da migração.
"""
import logging

from migracoes.jobs_heartbeat import _tabela_existe

logger = logging.getLogger(__name__)

COMO_RESOLVER = (
    "O que fazer: (1) procure acima neste log as linhas que começam com "
    "'migracao mapa_progresso' para ver o que falhou e a mensagem do MySQL; "
    "(2) corrija a causa e rode a migração à mão, na pasta backend/, com: "
    "python -m migracoes.mapa_progresso_usuario_id ; "
    "(3) não altere a tabela direto no console do banco. "
    "A aplicação não vai servir requisições até isso ser resolvido."
)


class EsquemaMapaProgressoInvalido(RuntimeError):
    """O esquema da tabela mapa_progresso não está como o código espera."""


async def _tipo_usuario_id(cur):
    """Devolve (DATA_TYPE, CHARACTER_MAXIMUM_LENGTH) de mapa_progresso.usuario_id, ou None se não existe."""
    await cur.execute(
        "SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mapa_progresso' AND COLUMN_NAME = 'usuario_id'"
    )
    linha = await cur.fetchone()
    return (linha[0].lower(), linha[1]) if linha else None


async def contar_linhas(cur):
    """Conta (total, utilizaveis, com_zero) em mapa_progresso.

    A comparação com usuarios.id é feita em Python, como texto. Em SQL,
    "mapa_progresso.usuario_id = usuarios.id" compararia INT com VARCHAR, e o
    MySQL converteria os dois lados para número: '3f2a...' viraria 3, e uma
    linha corrompida pareceria pertencer a um aluno.
    """
    await cur.execute("SELECT usuario_id FROM mapa_progresso")
    valores = [str(v) for (v,) in await cur.fetchall()]
    await cur.execute("SELECT id FROM usuarios")
    ids = {str(i) for (i,) in await cur.fetchall()}
    total = len(valores)
    utilizaveis = sum(1 for v in valores if v in ids)
    com_zero = sum(1 for v in valores if v == "0")
    return total, utilizaveis, com_zero


async def migrar_mapa_progresso_usuario_id(conn):
    async with conn.cursor() as cur:
        if not await _tabela_existe(cur, "mapa_progresso"):
            raise EsquemaMapaProgressoInvalido(
                "migracao mapa_progresso: a tabela mapa_progresso não existe neste banco. "
                "No startup ela é criada por criar_tabelas() antes desta migração; "
                "se você rodou o script à mão, confira se DB_NAME aponta para o banco certo. "
                + COMO_RESOLVER
            )
        try:
            tipo = await _tipo_usuario_id(cur)
            if tipo is None:
                raise EsquemaMapaProgressoInvalido(
                    "migracao mapa_progresso: a coluna usuario_id não existe. " + COMO_RESOLVER
                )
            if tipo[0] == "varchar":
                logger.info("migracao mapa_progresso.usuario_id: já é VARCHAR, nada a fazer")
                return
            if tipo[0] != "int":
                raise EsquemaMapaProgressoInvalido(
                    f"migracao mapa_progresso: usuario_id tem tipo inesperado '{tipo[0]}' "
                    "(esperava int, antes da migração, ou varchar, depois). " + COMO_RESOLVER
                )

            total, utilizaveis, com_zero = await contar_linhas(cur)
            logger.warning(
                f"migracao mapa_progresso.usuario_id: antes de migrar, {total} linha(s) na tabela, "
                f"{utilizaveis} com usuario_id de um usuário existente, {com_zero} com usuario_id = 0. "
                f"As {total - utilizaveis} linha(s) sem dono são mantidas e ficam inalcançáveis pela aplicação."
            )
            # INT para VARCHAR não perde nada: cada número vira o texto dele.
            # O UNIQUE da coluna é mantido pelo MODIFY.
            await cur.execute("ALTER TABLE mapa_progresso MODIFY usuario_id VARCHAR(36) NOT NULL")
            logger.info("migracao mapa_progresso.usuario_id: coluna convertida para VARCHAR(36)")
        except EsquemaMapaProgressoInvalido:
            raise
        except Exception as e:
            logger.error(f"migracao mapa_progresso: falhou com {type(e).__name__}: {e}. {COMO_RESOLVER}")
            raise


async def verificar_mapa_progresso_usuario_id(conn):
    """Recusa seguir se usuario_id não for VARCHAR com espaço para um UUID."""
    async with conn.cursor() as cur:
        tipo = await _tipo_usuario_id(cur)
    if tipo is None or tipo[0] != "varchar" or (tipo[1] or 0) < 36:
        encontrado = "coluna ausente" if tipo is None else f"{tipo[0]}({tipo[1]})"
        msg = (
            "Esquema do banco desatualizado, a aplicação não vai iniciar: "
            f"mapa_progresso.usuario_id deveria ser VARCHAR(36), encontrado {encontrado}. "
            "A migração automática do startup deveria ter corrigido isso. " + COMO_RESOLVER
        )
        logger.error(msg)
        raise EsquemaMapaProgressoInvalido(msg)
    logger.info("migracao mapa_progresso: verificação ok (usuario_id é VARCHAR(36))")


async def _executar_manual():
    # Importado aqui dentro para que importar este módulo a partir de main.py
    # não gere import circular.
    from main import criar_pool

    pool = await criar_pool()
    try:
        async with pool.acquire() as conn:
            await migrar_mapa_progresso_usuario_id(conn)
            await verificar_mapa_progresso_usuario_id(conn)
    finally:
        pool.close()
        await pool.wait_closed()


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(_executar_manual())
