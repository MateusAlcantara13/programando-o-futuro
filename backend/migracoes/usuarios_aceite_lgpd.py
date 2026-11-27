"""Migração: registro do aceite da LGPD na tabela `usuarios`.

Roda sozinha no startup da aplicação (ver init_db em main.py) e também pode
ser executada à mão contra um banco, a partir da pasta backend/:

    python -m migracoes.usuarios_aceite_lgpd

É idempotente: rodar várias vezes deixa o banco no mesmo estado.

O que faz:
1. Cria `aceite_lgpd_em` (DATETIME NULL, em UTC): quando o aluno aceitou.
2. Cria `aceite_lgpd_versao` (VARCHAR(20) NULL): qual versão do termo ele
   aceitou. Sem saber qual texto a pessoa leu, o registro não serve depois.
3. Tira o padrão de `aceite_lgpd` e torna a coluna NOT NULL. Com padrão
   TRUE, qualquer INSERT que esquecesse o campo gravava um consentimento
   que não existiu. Sem padrão e NOT NULL, todo INSERT precisa dizer o
   valor: em modo estrito (padrão do MySQL 8), omitir o campo dá erro.
   Nenhuma linha existente é alterada. Se houver linha com NULL, a migração
   para e avisa, em vez de inventar um valor de consentimento.

Usuários que já existem ficam com `aceite_lgpd` como está e com data e
versão NULL. Até 26/11/2026 o front mandava aceite_lgpd=true fixo, sem o
aluno marcar nada, então esses aceites não foram dados de verdade. Data
NULL é o registro honesto disso: inventar uma data de consentimento seria
pior do que não ter.
"""
import logging

from migracoes.jobs_heartbeat import _tabela_existe, _info_coluna

logger = logging.getLogger(__name__)

COMO_RESOLVER = (
    "O que fazer: (1) procure acima neste log as linhas que começam com "
    "'migracao usuarios' para ver qual passo falhou e a mensagem do MySQL; "
    "(2) corrija a causa e rode a migração à mão, na pasta backend/, com: "
    "python -m migracoes.usuarios_aceite_lgpd ; "
    "(3) não altere a tabela usuarios direto no console do banco. "
    "A aplicação não vai servir requisições até isso ser resolvido."
)

COLUNAS = (
    ("aceite_lgpd_em", "DATETIME NULL"),
    ("aceite_lgpd_versao", "VARCHAR(20) NULL"),
)


class EsquemaUsuariosInvalido(RuntimeError):
    """O esquema da tabela usuarios não está como o código espera."""


async def _estado_aceite(cur):
    """Devolve (IS_NULLABLE, COLUMN_DEFAULT) de usuarios.aceite_lgpd. O default vem como texto ou None."""
    await cur.execute(
        "SELECT IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'usuarios' AND COLUMN_NAME = 'aceite_lgpd'"
    )
    linha = await cur.fetchone()
    if not linha:
        return None
    return linha[0], (None if linha[1] is None else str(linha[1]))


async def migrar_usuarios_aceite_lgpd(conn):
    async with conn.cursor() as cur:
        if not await _tabela_existe(cur, "usuarios"):
            raise EsquemaUsuariosInvalido(
                "migracao usuarios: a tabela usuarios não existe neste banco. "
                "No startup ela é criada por criar_tabelas() antes desta migração; "
                "se você rodou o script à mão, confira se DB_NAME aponta para o banco certo. "
                + COMO_RESOLVER
            )
        try:
            for coluna, tipo in COLUNAS:
                if await _info_coluna(cur, "usuarios", coluna) is not None:
                    logger.info(f"migracao usuarios.{coluna}: coluna já existe, nada a fazer")
                    continue
                # Sem default: as linhas existentes ficam NULL, que é o certo.
                await cur.execute(f"ALTER TABLE usuarios ADD COLUMN {coluna} {tipo}")
                logger.info(f"migracao usuarios.{coluna}: coluna criada (linhas existentes ficam NULL)")

            if await _estado_aceite(cur) == ("NO", None):
                logger.info("migracao usuarios.aceite_lgpd: já é NOT NULL sem padrão, nada a fazer")
            else:
                await cur.execute("SELECT COUNT(*) FROM usuarios WHERE aceite_lgpd IS NULL")
                (nulos,) = await cur.fetchone()
                if nulos:
                    raise EsquemaUsuariosInvalido(
                        f"migracao usuarios.aceite_lgpd: {nulos} usuário(s) com aceite_lgpd NULL. "
                        "A migração não inventa valor de consentimento; decida com a equipe o que "
                        "esses registros significam antes de rodar de novo. " + COMO_RESOLVER
                    )
                # MODIFY sem cláusula DEFAULT: a coluna fica sem padrão.
                await cur.execute("ALTER TABLE usuarios MODIFY aceite_lgpd BOOLEAN NOT NULL")
                logger.info("migracao usuarios.aceite_lgpd: agora NOT NULL e sem padrão (nenhuma linha alterada)")
        except EsquemaUsuariosInvalido:
            raise
        except Exception as e:
            logger.error(f"migracao usuarios: falhou com {type(e).__name__}: {e}. {COMO_RESOLVER}")
            raise


async def verificar_usuarios_aceite_lgpd(conn):
    """Recusa seguir se as colunas do aceite não existirem ou se aceite_lgpd aceitar NULL ou tiver padrão."""
    problemas = []
    async with conn.cursor() as cur:
        for coluna, _ in COLUNAS:
            if await _info_coluna(cur, "usuarios", coluna) is None:
                problemas.append(f"a coluna usuarios.{coluna} não existe")
        estado = await _estado_aceite(cur)
        if estado != ("NO", None):
            nulo, padrao = estado or ("?", "?")
            problemas.append(
                f"usuarios.aceite_lgpd com IS_NULLABLE={nulo} e padrão {padrao!r} "
                "(deveria ser NOT NULL e sem padrão)"
            )
    if problemas:
        msg = (
            "Esquema do banco desatualizado, a aplicação não vai iniciar: "
            + "; ".join(problemas)
            + ". A migração automática do startup deveria ter corrigido isso. "
            + COMO_RESOLVER
        )
        logger.error(msg)
        raise EsquemaUsuariosInvalido(msg)
    logger.info("migracao usuarios: verificação ok (colunas do aceite presentes, aceite_lgpd NOT NULL sem padrão)")


async def _executar_manual():
    # Importado aqui dentro para que importar este módulo a partir de main.py
    # não gere import circular.
    from main import criar_pool

    pool = await criar_pool()
    try:
        async with pool.acquire() as conn:
            await migrar_usuarios_aceite_lgpd(conn)
            await verificar_usuarios_aceite_lgpd(conn)
    finally:
        pool.close()
        await pool.wait_closed()


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    asyncio.run(_executar_manual())
