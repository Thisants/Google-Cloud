"""Tratamento (limpeza e organização) dos dados coletados do GA4.

Fluxo:  read_raw_csv() -> check_columns() -> clean() -> rename_columns() -> add_calendar_columns()

Esta etapa NÃO faz análise (médias, taxas, tendências): isso é a ETAPA 04.
Aqui o objetivo é garantir dados confiáveis, com tipos corretos e nomes padronizados.
"""
from pathlib import Path

import pandas as pd

from ga_project.analytics_client import fill_missing_dates
from ga_project.errors import GA4ProjectError

# Colunas como a ETAPA 02 salva (nomes do GA4)
RAW_COLUMNS = ["date", "activeUsers", "sessions", "screenPageViews"]
METRIC_COLUMNS = ["activeUsers", "sessions", "screenPageViews"]

# Nomes padronizados (português, snake_case) que as próximas etapas vão usar
RENAME_MAP = {
    "date": "data",
    "activeUsers": "usuarios_ativos",
    "sessions": "sessoes",
    "screenPageViews": "visualizacoes_pagina",
}

# Lista fixa (não depende do idioma do Windows). segunda = 0 ... domingo = 6
WEEKDAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def read_raw_csv(path: Path) -> pd.DataFrame:
    """Lê o CSV gerado pela ETAPA 02."""
    path = Path(path)
    if not path.is_file():
        raise GA4ProjectError(
            f"CSV não encontrado: {path}. Rode antes a ETAPA 02: python 02-coleta-dados\\main.py"
        )
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise GA4ProjectError(f"O CSV está vazio: {path}") from exc
    except (OSError, pd.errors.ParserError) as exc:
        raise GA4ProjectError(f"Não consegui ler o CSV {path}: {exc}") from exc


def check_columns(df: pd.DataFrame) -> None:
    """Garante que todas as colunas esperadas existem."""
    missing = [c for c in RAW_COLUMNS if c not in df.columns]
    if missing:
        raise GA4ProjectError(f"Colunas ausentes no CSV: {', '.join(missing)}")


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Limpa o DataFrame e devolve (dados_limpos, avisos).

    Cada correção feita vira um aviso, para você saber exatamente o que mudou.
    """
    warnings: list[str] = []
    df = df[RAW_COLUMNS].copy()

    # 1) Tipos: data inválida vira NaT; métrica inválida vira NaN
    df["date"] = pd.to_datetime(df["date"], format="ISO8601", errors="coerce")
    for col in METRIC_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 2) Linhas sem data não servem para nada: removidas
    invalid_dates = int(df["date"].isna().sum())
    if invalid_dates:
        warnings.append(f"{invalid_dates} linha(s) com data inválida foram removidas.")
        df = df.dropna(subset=["date"])
    if df.empty:
        raise GA4ProjectError("Nenhuma linha válida no CSV depois da limpeza.")

    # 3) Métricas vazias/inválidas viram 0
    invalid_metrics = int(df[METRIC_COLUMNS].isna().sum().sum())
    if invalid_metrics:
        warnings.append(f"{invalid_metrics} valor(es) de métrica inválido(s) foram trocados por 0.")
        df[METRIC_COLUMNS] = df[METRIC_COLUMNS].fillna(0)
    df[METRIC_COLUMNS] = df[METRIC_COLUMNS].astype("int64")

    # 4) Valores negativos não deveriam existir: só avisamos (não alteramos)
    negatives = int((df[METRIC_COLUMNS] < 0).sum().sum())
    if negatives:
        warnings.append(f"ATENÇÃO: {negatives} valor(es) negativo(s) encontrados. Verifique a coleta.")

    # 5) Datas repetidas: mantém a última linha de cada data
    duplicated = int(df.duplicated(subset="date").sum())
    if duplicated:
        warnings.append(f"{duplicated} data(s) repetida(s): mantida a última linha de cada uma.")
        df = df.drop_duplicates(subset="date", keep="last")

    # 6) Ordena e garante uma linha por dia (dias sem linha viram 0)
    df = df.sort_values("date").reset_index(drop=True)
    start, end = df["date"].min(), df["date"].max()
    expected_days = (end - start).days + 1
    if len(df) < expected_days:
        warnings.append(f"{expected_days - len(df)} dia(s) ausente(s) foram criados com valor 0.")
        df = fill_missing_dates(df, start, end)

    return df, warnings


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Padroniza os nomes das colunas (RENAME_MAP)."""
    return df.rename(columns=RENAME_MAP)


def add_calendar_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Adiciona colunas de organização (usa os nomes já padronizados).

    - dia_semana: segunda ... domingo
    - sem_dados:  True se o dia teve 0 em todas as métricas
    """
    df = df.copy()
    df["dia_semana"] = df["data"].dt.dayofweek.map(lambda i: WEEKDAYS_PT[i])
    metric_names = [RENAME_MAP[c] for c in METRIC_COLUMNS]
    df["sem_dados"] = (df[metric_names] == 0).all(axis=1)
    return df[["data", "dia_semana", *metric_names, "sem_dados"]]


def treat(df_raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Pipeline completo: valida, limpa, padroniza e organiza."""
    check_columns(df_raw)
    df, warnings = clean(df_raw)
    df = add_calendar_columns(rename_columns(df))
    return df, warnings
