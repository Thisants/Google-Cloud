"""Carga dos CSVs das etapas anteriores para o PostgreSQL (ETAPA 07).

CSV (etapas 03, 05 e 06)  ->  upsert nas tabelas  ->  registro em carga_log

A carga NÃO consulta o Google: só lê os CSVs que as etapas anteriores já geraram.
Fluxo recomendado: rodar as etapas 02, 03, 05 e 06 e, em seguida, a 07. Os CSVs são
sobrescritos a cada coleta, mas o banco acumula: dias antigos continuam lá.
"""
from pathlib import Path

import pandas as pd

from ga_project.analise import read_treated_csv
from ga_project.config import PROJECT_ROOT
from ga_project.database import DatabaseWriteError, save_dataframe
from ga_project.errors import GA4ProjectError
from ga_project.integracao import read_gsc_by_date_csv


def default_paths(base_dir: Path = PROJECT_ROOT) -> dict[str, Path]:
    """Onde cada etapa salva o seu CSV."""
    return {
        "ga4_diario": base_dir / "03-tratamento" / "dados" / "analytics_30_dias_tratado.csv",
        "ga4_sessoes_canal": base_dir / "06-integracao-fontes" / "dados" / "ga4_sessoes_por_canal_30_dias.csv",
        "gsc_diario": base_dir / "05-search-console" / "dados" / "gsc_30_dias_por_data.csv",
        "gsc_consulta_pagina": base_dir / "05-search-console" / "dados" / "gsc_30_dias_consulta_pagina.csv",
    }


def _read_csv(path: Path, columns: list[str], step: str) -> pd.DataFrame:
    path = Path(path)
    if not path.is_file():
        raise GA4ProjectError(f"CSV não encontrado: {path}. Rode antes a {step}.")
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise GA4ProjectError(f"O CSV está vazio: {path}") from exc
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise GA4ProjectError(f"Colunas ausentes em {path.name}: {', '.join(missing)}")
    return df[columns].copy()


def load_ga4_diario(conn, path: Path) -> int:
    """ETAPA 03 -> tabela ga4_diario."""
    df = read_treated_csv(path)[["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"]]
    if df.empty:
        return 0
    return save_dataframe(conn, "ga4_diario", df, df["data"].min(), df["data"].max())


def load_ga4_canais(conn, path: Path) -> int:
    """ETAPA 06 (GA4 por canal) -> tabela ga4_sessoes_canal."""
    df = _read_csv(path, ["data", "canal", "origem", "sessoes"], "ETAPA 06")
    if df.empty:
        return 0
    df["data"] = pd.to_datetime(df["data"], format="ISO8601")
    df["canal"] = df["canal"].fillna("(not set)")
    df["origem"] = df["origem"].fillna("(not set)")
    df["sessoes"] = pd.to_numeric(df["sessoes"]).astype("int64")
    return save_dataframe(conn, "ga4_sessoes_canal", df, df["data"].min(), df["data"].max())


def load_gsc_diario(conn, path: Path) -> int:
    """ETAPA 05 (por data) -> tabela gsc_diario."""
    df = read_gsc_by_date_csv(path)
    if df.empty:
        return 0
    return save_dataframe(conn, "gsc_diario", df, df["data"].min(), df["data"].max())


def load_gsc_consulta_pagina(conn, path: Path, daily_path: Path) -> int:
    """ETAPA 05 (consulta + página) -> tabela gsc_consulta_pagina.

    O CSV não traz o período; ele é obtido do CSV por data da mesma coleta.
    """
    df = _read_csv(path, ["consulta", "pagina", "cliques", "impressoes", "ctr", "posicao_media"], "ETAPA 05")
    if df.empty:
        return 0
    daily = read_gsc_by_date_csv(daily_path)
    start, end = daily["data"].min(), daily["data"].max()
    df["periodo_inicio"] = start
    df["periodo_fim"] = end
    df["cliques"] = pd.to_numeric(df["cliques"]).astype("int64")
    df["impressoes"] = pd.to_numeric(df["impressoes"]).astype("int64")
    return save_dataframe(conn, "gsc_consulta_pagina", df, start, end)


def run_all(conn, base_dir: Path = PROJECT_ROOT) -> dict[str, int | None]:
    """Carrega todos os CSVs que existirem. Devolve {tabela: linhas gravadas, ou None se foi pulada}."""
    paths = default_paths(base_dir)
    loaders = {
        "ga4_diario": lambda: load_ga4_diario(conn, paths["ga4_diario"]),
        "ga4_sessoes_canal": lambda: load_ga4_canais(conn, paths["ga4_sessoes_canal"]),
        "gsc_diario": lambda: load_gsc_diario(conn, paths["gsc_diario"]),
        "gsc_consulta_pagina": lambda: load_gsc_consulta_pagina(conn, paths["gsc_consulta_pagina"], paths["gsc_diario"]),
    }
    results: dict[str, int | None] = {}
    for name, loader in loaders.items():
        try:
            results[name] = loader()
        except DatabaseWriteError:
            raise  # erro de banco é grave: não continua
        except GA4ProjectError as exc:  # CSV ausente/incompleto: só avisa e segue
            print(f"  AVISO ({name}): pulada. {exc}")
            results[name] = None
    return results
