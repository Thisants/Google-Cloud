"""Cadastro de clientes (multi-cliente).

Cada cliente é uma empresa com a sua propriedade do GA4 e o seu site no Search Console. O "slug" (ex.: loja-exemplo)
é o identificador PERMANENTE do cliente: aparece em toda linha de dados (coluna cliente_id) e nunca é renomeado.

Modelo de acesso: a agência usa UMA conta de serviço do Google. Cada cliente adiciona o e-mail dessa conta como
"Leitor" no GA4 e no Search Console. Nenhuma senha de cliente é guardada aqui.
"""
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ga_project.config import PROJECT_ROOT
from ga_project.dashboard_data import fetch_df
from ga_project.database import _sql
from ga_project.errors import GA4ProjectError

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
EDITABLE_FIELDS = {"nome", "ga4_property_id", "gsc_site_url", "enviar_consultas_ia"}


@dataclass(frozen=True)
class Cliente:
    slug: str
    nome: str
    ga4_property_id: str | None
    gsc_site_url: str | None
    ativo: bool
    enviar_consultas_ia: bool


# ---------- validações ----------
def validate_slug(slug: str) -> str:
    slug = (slug or "").strip()
    if not SLUG_RE.match(slug):
        raise GA4ProjectError(
            f"Slug inválido: '{slug}'. Use 2 a 40 caracteres: letras minúsculas, números e hífen "
            "(ex.: loja-exemplo), sem espaços nem acentos, começando e terminando com letra ou número."
        )
    return slug


def validate_ga4_property_id(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if text.lower().startswith("properties/"):
        text = text.split("/", 1)[1]
    if not text.isdigit():
        raise GA4ProjectError("ID da propriedade GA4 inválido: use só números (ex.: 123456789).")
    return text


def validate_gsc_site_url(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    if not text.startswith(("sc-domain:", "http://", "https://")):
        raise GA4ProjectError(
            "URL do Search Console inválida: use exatamente como aparece no Search Console, "
            "'sc-domain:exemplo.com.br' ou 'https://www.exemplo.com.br/' (com a barra final)."
        )
    return text


def validate_nome(nome: str) -> str:
    nome = (nome or "").strip()
    if len(nome) < 2:
        raise GA4ProjectError("O nome do cliente precisa ter pelo menos 2 caracteres.")
    return nome


# ---------- acesso ao banco ----------
def _from_row(row) -> Cliente:
    return Cliente(
        slug=row["slug"], nome=row["nome"],
        ga4_property_id=row["ga4_property_id"] or None, gsc_site_url=row["gsc_site_url"] or None,
        ativo=bool(row["ativo"]), enviar_consultas_ia=bool(row["enviar_consultas_ia"]),
    )


_SELECT = "SELECT slug, nome, ga4_property_id, gsc_site_url, ativo, enviar_consultas_ia FROM clientes"


def get_cliente(conn, slug: str) -> Cliente:
    df = fetch_df(conn, _SELECT + " WHERE slug = :slug", {"slug": slug})
    if df.empty:
        raise GA4ProjectError(f"Cliente '{slug}' não encontrado. Veja os cadastrados com: gerenciar_clientes.py list")
    return _from_row(df.iloc[0])


def list_clientes(conn, only_active: bool = False, limit: int | None = None, offset: int = 0) -> list[Cliente]:
    """Clientes em ordem de slug. limit/offset permitem paginar quando a carteira crescer."""
    sql, params = _SELECT, {}
    if only_active:
        sql += " WHERE ativo = :ativo"
        params["ativo"] = True
    sql += " ORDER BY slug"
    if limit is not None:
        sql += " LIMIT :limite OFFSET :offset"
        params.update({"limite": int(limit), "offset": int(offset)})
    df = fetch_df(conn, sql, params or None)
    return [_from_row(row) for _, row in df.iterrows()]


def count_clientes(conn, only_active: bool = False) -> int:
    sql = "SELECT COUNT(*) AS n FROM clientes" + (" WHERE ativo = :ativo" if only_active else "")
    return int(fetch_df(conn, sql, {"ativo": True} if only_active else None).loc[0, "n"])


def add_cliente(conn, slug: str, nome: str, ga4_property_id: str | None = None, gsc_site_url: str | None = None,
                enviar_consultas_ia: bool = False) -> Cliente:
    """Cadastra um cliente novo. Por padrão, as consultas de busca NÃO são enviadas à IA (privacidade)."""
    slug = validate_slug(slug)
    try:
        get_cliente(conn, slug)
    except GA4ProjectError:
        pass
    else:
        raise GA4ProjectError(f"Já existe um cliente com o slug '{slug}'. O slug não pode ser repetido nem renomeado.")
    conn.cursor().execute(
        _sql(conn, "INSERT INTO clientes (slug, nome, ga4_property_id, gsc_site_url, enviar_consultas_ia) "
                   "VALUES (:slug, :nome, :ga4, :gsc, :ia)"),
        {"slug": slug, "nome": validate_nome(nome), "ga4": validate_ga4_property_id(ga4_property_id),
         "gsc": validate_gsc_site_url(gsc_site_url), "ia": bool(enviar_consultas_ia)},
    )
    conn.commit()
    return get_cliente(conn, slug)


def ensure_cliente(conn, slug: str, nome: str) -> Cliente:
    """Garante que o cliente existe (idempotente): cria se não existir, senão devolve o existente."""
    try:
        return get_cliente(conn, slug)
    except GA4ProjectError:
        return add_cliente(conn, slug, nome)


def update_cliente(conn, slug: str, **fields) -> Cliente:
    """Atualiza dados do cliente. O slug não muda nunca."""
    get_cliente(conn, slug)                                    # erro claro se não existir
    unknown = set(fields) - EDITABLE_FIELDS
    if unknown:
        raise GA4ProjectError(f"Campo(s) não editável(is): {', '.join(sorted(unknown))}.")
    cleaners = {"nome": validate_nome, "ga4_property_id": validate_ga4_property_id,
                "gsc_site_url": validate_gsc_site_url, "enviar_consultas_ia": bool}
    values = {key: cleaners[key](value) for key, value in fields.items()}
    if values:
        assignments = ", ".join(f"{key} = :{key}" for key in values)
        conn.cursor().execute(
            _sql(conn, f"UPDATE clientes SET {assignments}, atualizado_em = CURRENT_TIMESTAMP WHERE slug = :slug"),
            {**values, "slug": slug},
        )
        conn.commit()
    return get_cliente(conn, slug)


def set_ativo(conn, slug: str, ativo: bool) -> Cliente:
    """Ativa ou desativa o cliente. Desativar NÃO apaga dados: só tira o cliente das rotinas."""
    get_cliente(conn, slug)
    conn.cursor().execute(
        _sql(conn, "UPDATE clientes SET ativo = :ativo, atualizado_em = CURRENT_TIMESTAMP WHERE slug = :slug"),
        {"ativo": bool(ativo), "slug": slug},
    )
    conn.commit()
    return get_cliente(conn, slug)


# ---------- e-mail da conta de serviço (para o cliente liberar o acesso) ----------
def service_account_email(path: Path | None = None) -> str | None:
    """Lê o e-mail (client_email) da chave JSON da conta de serviço. Devolve None se não conseguir ler.

    Só o e-mail é lido; a chave privada nunca é exibida.
    """
    if path is None:
        raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("client_email")
    except (OSError, ValueError):
        return None
