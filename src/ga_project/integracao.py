"""Integração GA4 + Search Console (ETAPA 06).

Fluxo:
  GA4 (data x canal x origem x sessões) -> summarize_ga4_by_date()  \
                                                                      >-> merge_sources() -> integration_summary()
  Search Console (CSV da ETAPA 05)      -> read_gsc_by_date_csv()   /

Chave de junção: a DATA. O que o cruzamento compara:
  - Search Console: quantas pessoas CLICARAM no resultado do Google (gsc_cliques)
  - GA4:            quantas SESSÕES chegaram por busca orgânica do Google (ga4_sessoes_organicas_google)

Cuidado ao interpretar: os dois números nunca batem exatamente (consentimento de cookies, bloqueadores,
fuso horário, regras de contagem diferentes). O que vale é a tendência e a proporção, não o valor exato.
"""
from pathlib import Path

import pandas as pd

from ga_project.errors import GA4ProjectError
from ga_project.tratamento import WEEKDAYS_PT

# O que pedimos ao GA4 (nomes oficiais da Data API)
GA4_DIMENSIONS = ["date", "sessionDefaultChannelGroup", "sessionSource"]
GA4_METRICS = ["sessions"]

# Valores que o GA4 devolve (em inglês)
ORGANIC_GROUP = "Organic Search"
GOOGLE_SOURCE = "google"

GSC_COLUMNS = ["data", "cliques", "impressoes", "ctr", "posicao_media"]

FINAL_COLUMNS = [
    "data",
    "dia_semana",
    "ga4_sessoes_total",
    "ga4_sessoes_organicas_google",
    "gsc_cliques",
    "gsc_impressoes",
    "gsc_ctr",
    "gsc_posicao_media",
    "pct_organico_google",
    "sessoes_por_clique",
]


def rename_ga4_channels(df: pd.DataFrame) -> pd.DataFrame:
    """Padroniza os nomes do relatório bruto do GA4 (data x canal x origem)."""
    return df.rename(
        columns={
            "date": "data",
            "sessionDefaultChannelGroup": "canal",
            "sessionSource": "origem",
            "sessions": "sessoes",
        }
    )


def summarize_ga4_by_date(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Resume o GA4 em uma linha por dia: sessões totais e sessões orgânicas do Google.

    df: relatório bruto (colunas date, sessionDefaultChannelGroup, sessionSource, sessions).
    Dias sem nenhuma sessão não vêm da API: são criados com 0.
    """
    total = df.groupby("date")["sessions"].sum()
    is_google_organic = (df["sessionDefaultChannelGroup"] == ORGANIC_GROUP) & (df["sessionSource"] == GOOGLE_SOURCE)
    organic = df[is_google_organic].groupby("date")["sessions"].sum()

    daily = pd.DataFrame({"ga4_sessoes_total": total, "ga4_sessoes_organicas_google": organic})
    full_index = pd.date_range(start, end, freq="D", name="data")
    daily.index.name = "data"
    daily = daily.reindex(full_index).fillna(0).astype("int64")
    return daily.reset_index()


def channel_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Sessões por canal no período, com a participação (%) de cada um. Maiores primeiro."""
    totals = df.groupby("sessionDefaultChannelGroup")["sessions"].sum().sort_values(ascending=False)
    result = totals.rename("sessoes").reset_index().rename(columns={"sessionDefaultChannelGroup": "canal"})
    all_sessions = result["sessoes"].sum()
    result["pct"] = (result["sessoes"] / all_sessions * 100).round(1) if all_sessions else 0.0
    return result


def read_gsc_by_date_csv(path: Path) -> pd.DataFrame:
    """Lê o CSV por data gerado pela ETAPA 05."""
    path = Path(path)
    if not path.is_file():
        raise GA4ProjectError(
            f"CSV do Search Console não encontrado: {path}. Rode antes a ETAPA 05: python 05-search-console\\main.py"
        )
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise GA4ProjectError(f"O CSV está vazio: {path}") from exc
    except (OSError, pd.errors.ParserError) as exc:
        raise GA4ProjectError(f"Não consegui ler o CSV {path}: {exc}") from exc

    missing = [c for c in GSC_COLUMNS if c not in df.columns]
    if missing:
        raise GA4ProjectError(f"Colunas ausentes no CSV do Search Console: {', '.join(missing)}")

    df = df[GSC_COLUMNS].copy()
    df["data"] = pd.to_datetime(df["data"], format="ISO8601")
    return df.sort_values("data").reset_index(drop=True)


def merge_sources(ga4_daily: pd.DataFrame, gsc_daily: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Junta GA4 e Search Console pela data (só dias que existem nas duas fontes).

    Devolve (tabela_integrada, info). Lança erro se não houver nenhum dia em comum.
    """
    ga4 = ga4_daily.copy()
    gsc = gsc_daily.rename(
        columns={
            "cliques": "gsc_cliques",
            "impressoes": "gsc_impressoes",
            "ctr": "gsc_ctr",
            "posicao_media": "gsc_posicao_media",
        }
    )
    ga4["data"] = pd.to_datetime(ga4["data"]).astype("datetime64[ns]")
    gsc["data"] = pd.to_datetime(gsc["data"]).astype("datetime64[ns]")

    merged = ga4.merge(gsc, on="data", how="inner")
    info = {
        "dias_ga4": len(ga4),
        "dias_gsc": len(gsc),
        "dias_em_comum": len(merged),
    }
    if merged.empty:
        raise GA4ProjectError(
            "Nenhuma data em comum entre GA4 e Search Console. Rode a ETAPA 05 e a ETAPA 06 no mesmo dia."
        )
    info["periodo_comum"] = (
        merged["data"].min().date().isoformat(),
        merged["data"].max().date().isoformat(),
    )

    merged = merged.sort_values("data").reset_index(drop=True)
    merged["dia_semana"] = merged["data"].dt.dayofweek.map(lambda i: WEEKDAYS_PT[i])

    total = merged["ga4_sessoes_total"].where(merged["ga4_sessoes_total"] != 0)
    clicks = merged["gsc_cliques"].where(merged["gsc_cliques"] != 0)
    merged["pct_organico_google"] = (merged["ga4_sessoes_organicas_google"] / total * 100).round(1)
    merged["sessoes_por_clique"] = (merged["ga4_sessoes_organicas_google"] / clicks).round(2)
    return merged[FINAL_COLUMNS], info


def integration_summary(merged: pd.DataFrame) -> pd.DataFrame:
    """Indicadores do cruzamento (tabela indicador / valor).

    A correlação (-1 a 1) diz se os dois números sobem e descem juntos. Com ~30 dias é só
    um INDICADOR: não prova que uma coisa causa a outra.
    """
    total_clicks = int(merged["gsc_cliques"].sum())
    total_organic = int(merged["ga4_sessoes_organicas_google"].sum())
    total_sessions = int(merged["ga4_sessoes_total"].sum())

    def safe_ratio(a, b, scale=1.0):
        return round(a / b * scale, 2) if b else float("nan")

    def corr(col_a, col_b):
        value = merged[col_a].corr(merged[col_b])
        return round(float(value), 2) if pd.notna(value) else float("nan")

    rows = [
        ("dias_em_comum", len(merged)),
        ("total_sessoes_ga4", total_sessions),
        ("total_sessoes_organicas_google_ga4", total_organic),
        ("total_cliques_gsc", total_clicks),
        ("pct_sessoes_organicas_google", safe_ratio(total_organic, total_sessions, 100)),
        ("sessoes_organicas_por_clique", safe_ratio(total_organic, total_clicks)),
        ("correlacao_cliques_x_sessoes_organicas", corr("gsc_cliques", "ga4_sessoes_organicas_google")),
        ("correlacao_impressoes_x_sessoes_organicas", corr("gsc_impressoes", "ga4_sessoes_organicas_google")),
    ]
    # dtype=object mantém inteiros como inteiros (30, não 30.00) na hora de mostrar
    return pd.DataFrame(
        {"indicador": [name for name, _ in rows], "valor": pd.Series([value for _, value in rows], dtype=object)}
    )
