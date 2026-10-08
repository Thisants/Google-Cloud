"""Análise descritiva dos dados tratados (ETAPA 04).

Fluxo:  read_treated_csv() -> analyze() = add_derived_metrics + summarize + by_weekday + compare_periods

Só descreve o que aconteceu (totais, médias, padrões, comparação de períodos).
NÃO detecta problemas/oportunidades automaticamente (ETAPA 09) nem desenha gráficos (ETAPA 08).

Regra importante: um dia com 0 em TODAS as métricas (coluna sem_dados = True) é tratado como
"sem dados" (provável falha de coleta), não como "zero visitas". Esses dias ficam fora das
médias, máximos, mínimos e comparações.
"""
from pathlib import Path

import pandas as pd

from ga_project.errors import GA4ProjectError
from ga_project.tratamento import WEEKDAYS_PT

METRICS = ["usuarios_ativos", "sessoes", "visualizacoes_pagina"]
TREATED_COLUMNS = ["data", "dia_semana", *METRICS, "sem_dados"]


def read_treated_csv(path: Path) -> pd.DataFrame:
    """Lê o CSV gerado pela ETAPA 03 e confere colunas e tipos."""
    path = Path(path)
    if not path.is_file():
        raise GA4ProjectError(
            f"CSV tratado não encontrado: {path}. Rode antes a ETAPA 03: python 03-tratamento\\main.py"
        )
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise GA4ProjectError(f"O CSV está vazio: {path}") from exc
    except (OSError, pd.errors.ParserError) as exc:
        raise GA4ProjectError(f"Não consegui ler o CSV {path}: {exc}") from exc

    missing = [c for c in TREATED_COLUMNS if c not in df.columns]
    if missing:
        raise GA4ProjectError(f"Colunas ausentes no CSV tratado: {', '.join(missing)}")

    df = df[TREATED_COLUMNS].copy()
    df["data"] = pd.to_datetime(df["data"], format="ISO8601")
    df["sem_dados"] = df["sem_dados"].astype(str).str.lower().eq("true")
    return df.sort_values("data").reset_index(drop=True)


def add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona métricas calculadas.

    - sessoes_por_usuario:      sessões / usuários ativos
    - paginas_por_sessao:       visualizações de página / sessões
    - media_movel_7d_sessoes:   média das sessões nos últimos 7 dias (suaviza a oscilação diária)
    Divisão por zero vira vazio (NaN), nunca erro.
    """
    df = df.copy()
    df["sessoes_por_usuario"] = (df["sessoes"] / df["usuarios_ativos"].where(df["usuarios_ativos"] != 0)).round(2)
    df["paginas_por_sessao"] = (df["visualizacoes_pagina"] / df["sessoes"].where(df["sessoes"] != 0)).round(2)

    sessions_with_data = df["sessoes"].where(~df["sem_dados"])  # dias sem dados não entram na média
    df["media_movel_7d_sessoes"] = sessions_with_data.rolling(7, min_periods=4).mean().round(1)
    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Resumo por métrica: total, média diária, máximo e mínimo (com a data de cada um)."""
    valid = df[~df["sem_dados"]]
    rows = []
    for metric in METRICS:
        s = valid[metric]
        rows.append(
            {
                "metrica": metric,
                "total": int(s.sum()),
                "media_diaria": round(float(s.mean()), 1),
                "maximo": int(s.max()),
                "data_maximo": valid.loc[s.idxmax(), "data"].date().isoformat(),
                "minimo": int(s.min()),
                "data_minimo": valid.loc[s.idxmin(), "data"].date().isoformat(),
            }
        )
    return pd.DataFrame(rows)


def by_weekday(df: pd.DataFrame) -> pd.DataFrame:
    """Média das métricas por dia da semana (segunda ... domingo)."""
    valid = df[~df["sem_dados"]]
    table = valid.groupby("dia_semana")[METRICS].mean().round(1)
    table["dias"] = valid.groupby("dia_semana").size()
    table = table.reindex(WEEKDAYS_PT).dropna(subset=["dias"]).rename_axis("dia_semana")
    table["dias"] = table["dias"].astype(int)
    return table.reset_index()


def compare_periods(df: pd.DataFrame, window: int = 7):
    """Compara os últimos `window` dias com os `window` dias anteriores (média diária).

    Devolve (tabela, periodos) ou None se não houver dias suficientes.
    """
    if len(df) < 2 * window:
        return None
    recent = df.tail(window)
    previous = df.iloc[-2 * window : -window]

    rows = []
    for metric in METRICS:
        before = previous.loc[~previous["sem_dados"], metric].mean()
        now = recent.loc[~recent["sem_dados"], metric].mean()
        if pd.isna(before) or pd.isna(now) or before == 0:
            change = float("nan")
        else:
            change = round((now - before) / before * 100, 1)
        rows.append(
            {
                "metrica": metric,
                "media_anterior": None if pd.isna(before) else round(float(before), 1),
                "media_atual": None if pd.isna(now) else round(float(now), 1),
                "variacao_pct": change,
            }
        )

    def span(part):
        return part["data"].min().date().isoformat(), part["data"].max().date().isoformat()

    return pd.DataFrame(rows), {"anterior": span(previous), "atual": span(recent)}


def analyze(df: pd.DataFrame) -> dict:
    """Roda a análise completa e devolve um dicionário com todos os resultados."""
    if df["sem_dados"].all():
        raise GA4ProjectError("Todos os dias estão sem dados; não há o que analisar.")

    daily = add_derived_metrics(df)
    return {
        "periodo": (df["data"].min().date().isoformat(), df["data"].max().date().isoformat()),
        "dias": len(df),
        "dias_sem_dados": int(df["sem_dados"].sum()),
        "diario": daily,
        "resumo": summarize(df),
        "dia_semana": by_weekday(df),
        "comparacao": compare_periods(df),
    }
