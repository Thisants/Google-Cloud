"""Chaves da API (multi-cliente).

  - cada chave pertence a UM cliente (papel "cliente") ou é de administração (papel "admin", vê toda a carteira);
  - o banco guarda só o HASH (SHA-256) da chave: se o banco vazar, as chaves não vazam;
  - a chave completa aparece UMA vez, na criação. Formato:  ga_<id de 8 caracteres>_<segredo aleatório>;
  - a chave tem alta entropia (256 bits), então SHA-256 basta (senhas de gente é que precisariam de hash lento).
"""
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

import pandas as pd

from ga_project.clientes import get_cliente
from ga_project.dashboard_data import fetch_df
from ga_project.database import _sql
from ga_project.errors import GA4ProjectError

ROLES = {"admin", "cliente"}
KEY_RE = re.compile(r"^ga_([0-9a-f]{8})_([A-Za-z0-9_-]{20,})$")


@dataclass(frozen=True)
class KeyInfo:
    id: str
    papel: str
    cliente_id: str | None
    nome: str


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def looks_like_key(value: str | None) -> bool:
    """Confere só o FORMATO (sem tocar no banco): descarta lixo antes de gastar uma consulta."""
    return bool(value) and KEY_RE.match(value) is not None


def create_key(conn, *, papel: str, nome: str, cliente_id: str | None = None) -> tuple[str, str]:
    """Cria uma chave. Devolve (id, chave_completa). A chave completa NÃO fica guardada em lugar nenhum."""
    if papel not in ROLES:
        raise GA4ProjectError("Papel inválido: use 'admin' ou 'cliente'.")
    if not (nome or "").strip():
        raise GA4ProjectError("Dê um nome à chave (ex.: 'painel do cliente' ou 'minha chave de administrador').")
    if papel == "cliente":
        if not cliente_id:
            raise GA4ProjectError("Chave de cliente precisa do slug do cliente.")
        get_cliente(conn, cliente_id)                       # erro claro se o cliente não existir
    elif cliente_id:
        raise GA4ProjectError("Chave de administrador não pertence a um cliente.")

    key_id = secrets.token_hex(4)
    key = f"ga_{key_id}_{secrets.token_urlsafe(32)}"
    try:
        conn.cursor().execute(
            _sql(conn, "INSERT INTO api_chaves (id, cliente_id, papel, nome, hash_chave) "
                       "VALUES (:id, :cliente, :papel, :nome, :hash)"),
            {"id": key_id, "cliente": cliente_id, "papel": papel, "nome": nome.strip(), "hash": hash_key(key)},
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise GA4ProjectError(f"Não consegui criar a chave (tente de novo): {exc}") from exc
    return key_id, key


_DUMMY_HASH = hash_key("chave-falsa-para-igualar-o-tempo-de-resposta")


def verify_key(conn, key: str | None) -> KeyInfo | None:
    """Devolve quem é o dono da chave, ou None se for inválida, revogada ou de cliente desativado."""
    match = KEY_RE.match(key or "")
    if not match:
        return None
    df = fetch_df(conn, "SELECT k.id, k.cliente_id, k.papel, k.nome, k.hash_chave, k.ativa, c.ativo AS cliente_ativo "
                        "FROM api_chaves k LEFT JOIN clientes c ON c.slug = k.cliente_id WHERE k.id = :id",
                  {"id": match.group(1)})
    row = df.iloc[0] if not df.empty else None
    expected = row["hash_chave"] if row is not None else _DUMMY_HASH     # compara sempre, para não vazar pelo tempo
    matches = hmac.compare_digest(hash_key(key), str(expected))
    if row is None or not matches or not bool(row["ativa"]):
        return None
    if row["papel"] == "cliente" and not bool(row["cliente_ativo"]):
        return None
    return KeyInfo(id=row["id"], papel=row["papel"], cliente_id=row["cliente_id"] or None, nome=row["nome"])


def revoke_key(conn, key_id: str) -> None:
    """Revoga (desativa) a chave. Não apaga: o registro continua para auditoria."""
    exists = fetch_df(conn, "SELECT id FROM api_chaves WHERE id = :id", {"id": key_id})
    if exists.empty:
        raise GA4ProjectError(f"Chave '{key_id}' não encontrada.")
    conn.cursor().execute(_sql(conn, "UPDATE api_chaves SET ativa = :ativa WHERE id = :id"), {"ativa": False, "id": key_id})
    conn.commit()


def list_keys(conn, cliente_id: str | None = None) -> pd.DataFrame:
    """Lista as chaves (nunca mostra o hash)."""
    sql = "SELECT id, papel, cliente_id, nome, ativa, criada_em FROM api_chaves"
    if cliente_id:
        return fetch_df(conn, sql + " WHERE cliente_id = :c ORDER BY criada_em", {"c": cliente_id})
    return fetch_df(conn, sql + " ORDER BY criada_em")
