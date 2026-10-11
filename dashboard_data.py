"""Dados e cálculos do dashboard (ETAPA 08).

Tudo que NÃO é tela fica aqui (consultas ao banco, KPIs, formatação), para poder ser testado sem Streamlit.
O arquivo 08-dashboard/app.py só desenha na tela o que estas funções devolvem.

Regras:
  - o dashboard só LÊ do banco (SELECT); nunca grava nem apaga;
  - "Usuários ativos" não se soma entre dias (a mesma pessoa contaria várias vezes): o KPI usa a MÉDIA por dia;
  - dias com sem_dados = True (zero em tudo no GA4) ficam fora das médias.
"""
from datetime import date, timedelta

import pandas as pd

from ga_project.database import _sql

DAILY_NUMERIC = [
    "usuarios_ativos", "sessoes", "visualizacoes_pagina",
    "cliques", "impressoes", "ctr", "posicao_media", "sessoes_organicas_google",
]


# ---------------------------------------------------------------------------
# Consultas (somente leitura)
# ---------------------------------------------------------------------------
def fetch_df(conn, sql: str, params: dict | None = None) -> pd.DataFrame:
    """Executa um SELECT e devolve um DataFrame."""
    cur = conn.cursor()
    if params:
        cur.execute(_sql(conn, sql), params)
    else:
        cur.execute(_sql(conn, sql))
    columns = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=columns)


def _to_date(value) -> date | None:
    if value is None or pd.isna(value):
        return None
    return pd.to_datetime(value).date()


def load_date_range(conn) -> tuple[date, date] | None:
    """Primeira e última data disponíveis no banco (None se o banco estiver vazio)."""
    df = fetch_df(conn, "SELECT MIN(data) AS primeira, MAX(data) AS ultima FROM ga4_diario")
    first, last = _to_date(df.loc[0, "primeira"]), _to_date(df.loc[0, "ultima"])
    return (first, last) if first and last else None


def load_daily(conn, start: date, end: date) -> pd.DataFrame:
    """Uma linha por dia: GA4 + sessões orgânicas do Google + Search Console (LEFT JOIN: GA4 manda)."""
    sql = """
        SELECT g.data, g.usuarios_ativos, g.sessoes, g.visualizacoes_pagina, g.sem_dados,
               s.cliques, s.impressoes, s.ctr, s.posicao_media,
               COALESCE(o.sessoes_organicas_google, 0) AS sessoes_organicas_google
        FROM ga4_diario g
        LEFT JOIN gsc_diario s ON s.data = g.data
        LEFT JOIN (
            SELECT data, CAST(SUM(sessoes) AS BIGINT) AS sessoes_organicas_google
            FROM ga4_sessoes_canal
            WHERE canal = 'Organic Search' AND origem = 'google'
            GROUP BY data
        ) o ON o.data = g.data
        WHERE g.data BETWEEN :inicio AND :fim
        ORDER BY g.data"""
    df = fetch_df(conn, sql, {"inicio": start, "fim": end})
    df["data"] = pd.to_datetime(df["data"])
    df["sem_dados"] = df["sem_dados"].astype(bool)
    for col in DAILY_NUMERIC:
        df[col] = pd.to_numeric(df[col])
    return df


def load_channels(conn, start: date, end: date) -> pd.DataFrame:
    """Sessões por canal no período (maiores primeiro)."""
    sql = """
        SELECT canal, CAST(SUM(sessoes) AS BIGINT) AS sessoes
        FROM ga4_sessoes_canal
        WHERE data BETWEEN :inicio AND :fim
        GROUP BY canal
        ORDER BY sessoes DESC"""
    df = fetch_df(conn, sql, {"inicio": start, "fim": end})
    df["sessoes"] = pd.to_numeric(df["sessoes"])
    return df


def load_top_queries(conn, limit: int = 20) -> pd.DataFrame:
    """Melhores consultas + páginas (por cliques) da foto de período mais recente do Search Console."""
    sql = """
        SELECT consulta, pagina, cliques, impressoes, ctr, posicao_media, periodo_inicio, periodo_fim
        FROM gsc_consulta_pagina
        WHERE periodo_fim = (SELECT MAX(periodo_fim) FROM gsc_consulta_pagina)
        ORDER BY cliques DESC, impressoes DESC
        LIMIT :limite"""
    df = fetch_df(conn, sql, {"limite": limit})
    for col in ("cliques", "impressoes", "ctr", "posicao_media"):
        df[col] = pd.to_numeric(df[col])
    return df


def load_last_loads(conn) -> pd.DataFrame:
    """Data da última carga de cada tabela (mostra quão atualizado está o banco)."""
    return fetch_df(conn, "SELECT fonte, MAX(executado_em) AS ultima_carga FROM carga_log GROUP BY fonte ORDER BY fonte")


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
def previous_period(start: date, end: date) -> tuple[date, date]:
    """Período imediatamente anterior, com o mesmo número de dias."""
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=days - 1), prev_end


def pct_change(current, previous) -> float | None:
    """Variação em % (None se não der para calcular)."""
    if current is None or previous is None or pd.isna(current) or pd.isna(previous) or previous == 0:
        return None
    return float((current - previous) / previous * 100)


def _sum(df: pd.DataFrame, col: str):
    series = df[col].dropna()
    return float(series.sum()) if not series.empty else None


def _mean_with_data(df: pd.DataFrame, col: str):
    series = df.loc[~df["sem_dados"], col].dropna()
    return float(series.mean()) if not series.empty else None


def _ctr(df: pd.DataFrame):
    clicks, impressions = _sum(df, "cliques"), _sum(df, "impressoes")
    return clicks / impressions * 100 if clicks is not None and impressions else None


def compute_kpis(current: pd.DataFrame, previous: pd.DataFrame) -> list[dict]:
    """KPIs do período, com a variação contra o período anterior.

    Cada item: {"label", "value", "kind" ("int" | "float" | "pct"), "delta", "delta_kind" ("pct" | "pp")}.
    A variação só é calculada se o período anterior tiver o MESMO número de dias (senão a comparação engana).
    """
    comparable = len(previous) == len(current) and len(current) > 0

    def kpi(label, getter, kind, delta_kind="pct"):
        value = getter(current)
        delta = None
        if comparable:
            before = getter(previous)
            if delta_kind == "pp":
                delta = None if value is None or before is None else value - before
            else:
                delta = pct_change(value, before)
        return {"label": label, "value": value, "kind": kind, "delta": delta, "delta_kind": delta_kind}

    return [
        kpi("Sessões", lambda d: _sum(d, "sessoes"), "int"),
        kpi("Sessões orgânicas (Google)", lambda d: _sum(d, "sessoes_organicas_google"), "int"),
        kpi("Usuários ativos (média/dia)", lambda d: _mean_with_data(d, "usuarios_ativos"), "float"),
        kpi("Páginas vistas", lambda d: _sum(d, "visualizacoes_pagina"), "int"),
        kpi("Cliques (Search Console)", lambda d: _sum(d, "cliques"), "int"),
        kpi("Impressões (Search Console)", lambda d: _sum(d, "impressoes"), "int"),
        kpi("CTR (Search Console)", _ctr, "pct", delta_kind="pp"),
    ]


# ---------------------------------------------------------------------------
# Formatação (padrão brasileiro: 1.234,5)
# ---------------------------------------------------------------------------
def _br(text: str) -> str:
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_value(value, kind: str) -> str:
    if value is None or pd.isna(value):
        return "—"
    if kind == "int":
        return _br(f"{value:,.0f}")
    if kind == "float":
        return _br(f"{value:,.1f}")
    return _br(f"{value:.2f}") + "%"


def fmt_delta(delta, delta_kind: str) -> str | None:
    if delta is None or pd.isna(delta):
        return None
    suffix = "%" if delta_kind == "pct" else " pp"
    return _br(f"{delta:+.1f}") + suffix
