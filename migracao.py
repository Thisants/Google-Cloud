"""Migração do formato antigo (um cliente só) para o formato multi-cliente.

O que faz, nesta ordem, TUDO em uma transação (se algo falhar, nada muda):
  1) renomeia cada tabela antiga X para legado_X;
  2) cria as tabelas novas (com cliente_id);
  3) cadastra o cliente (por padrão, o slug "padrao") e copia as linhas antigas para ele;
  4) confere se as contagens batem.
As tabelas legado_* NÃO são apagadas: você as remove manualmente, depois de validar e fazer backup.
"""
from ga_project.clientes import ensure_cliente
from ga_project.database import (
    DEFAULT_CLIENTE,
    LOG_TABLE,
    TABLES,
    DatabaseWriteError,
    _sql,
    create_tables,
    detect_legacy_tables,
    table_columns,
)
from ga_project.errors import GA4ProjectError

LEGACY_PREFIX = "legado_"


def _count(conn, table: str) -> int:
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


def migrate_legacy_to_multicliente(conn, slug: str = DEFAULT_CLIENTE,
                                   nome: str = "Cliente padrão (dados anteriores)") -> dict[str, int]:
    """Migra as tabelas antigas. Devolve {tabela: linhas copiadas}. Sem tabelas antigas, não faz nada (devolve {})."""
    legacy = detect_legacy_tables(conn)
    if not legacy:
        return {}

    cur = conn.cursor()
    try:
        for table in legacy:
            if table_columns(conn, f"{LEGACY_PREFIX}{table}"):
                raise GA4ProjectError(
                    f"A tabela {LEGACY_PREFIX}{table} já existe: a migração anterior ficou pela metade ou já foi feita. "
                    "Confira o banco antes de repetir."
                )
        for table in legacy:
            cur.execute(f"ALTER TABLE {table} RENAME TO {LEGACY_PREFIX}{table}")
        create_tables(conn)               # (faz commit interno; por isso o cliente é criado logo a seguir)
        ensure_cliente(conn, slug, nome)

        copied: dict[str, int] = {}
        for table in legacy:
            old_cols = table_columns(conn, f"{LEGACY_PREFIX}{table}")
            columns = [c for c in (TABLES[table]["columns"] if table in TABLES else
                                   ["cliente_id", "fonte", "periodo_inicio", "periodo_fim", "linhas", "executado_em"])
                       if c != "cliente_id"]
            missing = [c for c in columns if c not in old_cols]
            if missing:
                raise GA4ProjectError(f"A tabela antiga {table} não tem as colunas esperadas: {', '.join(missing)}.")
            # criado_em/atualizado_em também vão junto, quando existirem, para preservar o histórico
            extras = [c for c in ("criado_em", "atualizado_em") if c in old_cols and c not in columns]
            cols = columns + extras
            cur.execute(
                _sql(conn, f"INSERT INTO {table} (cliente_id, {', '.join(cols)}) "
                           f"SELECT CAST(:cliente AS TEXT), {', '.join(cols)} FROM {LEGACY_PREFIX}{table}"),
                {"cliente": slug},
            )
            old_count, new_count = _count(conn, f"{LEGACY_PREFIX}{table}"), _count(conn, table)
            if old_count != new_count:
                raise GA4ProjectError(f"Contagem diferente em {table}: antes {old_count}, depois {new_count}.")
            copied[table] = new_count
        conn.commit()
        return copied
    except Exception as exc:
        conn.rollback()
        if isinstance(exc, (GA4ProjectError, DatabaseWriteError)):
            raise
        raise GA4ProjectError(f"Falha na migração (nada foi alterado): {exc}") from exc
