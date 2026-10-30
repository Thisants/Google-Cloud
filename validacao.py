"""Validação dos dados ANTES de gravar no banco (etapa 3).

O banco tem restrições CHECK como segunda linha de defesa, mas aqui o erro sai claro, em português, antes de qualquer
escrita: o que está errado, em quantas linhas e um exemplo. Nada é corrigido em silêncio.
"""
from datetime import date

import pandas as pd

from ga_project.errors import GA4ProjectError

MAX_EXAMPLES = 3


class DataValidationError(GA4ProjectError):
    """Os dados a gravar estão inválidos; nada foi escrito."""


# Regras por tabela (cliente_id não entra: é acrescentado na gravação)
RULES = {
    "ga4_diario": {
        "key": ["data"], "dates": ["data"], "not_null": ["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"],
        "non_negative": ["usuarios_ativos", "sessoes", "visualizacoes_pagina"], "ratio": [], "text": [],
    },
    "ga4_sessoes_canal": {
        "key": ["data", "canal", "origem"], "dates": ["data"], "not_null": ["data", "canal", "origem", "sessoes"],
        "non_negative": ["sessoes"], "ratio": [], "text": ["canal", "origem"],
    },
    "gsc_diario": {
        "key": ["data"], "dates": ["data"], "not_null": ["data", "cliques", "impressoes"],
        "non_negative": ["cliques", "impressoes", "posicao_media"], "ratio": ["ctr"], "text": [],
        "optional": ["ctr", "posicao_media"],
    },
    "gsc_consulta_pagina": {
        "key": ["periodo_inicio", "periodo_fim", "consulta", "pagina"], "dates": ["periodo_inicio", "periodo_fim"],
        "not_null": ["periodo_inicio", "periodo_fim", "consulta", "pagina", "cliques", "impressoes"],
        "non_negative": ["cliques", "impressoes", "posicao_media"], "ratio": ["ctr"], "text": ["consulta", "pagina"],
        "optional": ["ctr", "posicao_media"],
    },
}


def _examples(values) -> str:
    return ", ".join(str(v) for v in list(values)[:MAX_EXAMPLES])


def _as_date(value) -> date | None:
    return value.date() if isinstance(value, pd.Timestamp) else value


def validate_frame(table: str, df: pd.DataFrame, period_start=None, period_end=None) -> None:
    """Confere o DataFrame contra as regras da tabela. Levanta DataValidationError com todos os problemas encontrados."""
    rules = RULES.get(table)
    if rules is None:
        raise DataValidationError(f"Tabela desconhecida para validação: {table}.")
    if df.empty:
        return
    required = set(rules["not_null"]) | set(rules.get("optional", [])) | set(rules["key"])
    missing = sorted(required - set(df.columns))
    if missing:
        raise DataValidationError(f"Dados inválidos para {table}: faltam as colunas {', '.join(missing)}.")

    problems: list[str] = []
    for col in rules["not_null"]:
        n = int(df[col].isna().sum())
        if n:
            problems.append(f"{n} linha(s) com {col} vazio")
    for col in rules["text"]:
        blank = df[col].isna() | (df[col].astype(str).str.strip() == "")
        if blank.any():
            problems.append(f"{int(blank.sum())} linha(s) com {col} em branco")
    for col in rules["non_negative"]:
        if col in df.columns:
            numbers = pd.to_numeric(df[col], errors="coerce")
            bad = numbers[(numbers < 0)]
            non_numeric = int((numbers.isna() & df[col].notna()).sum())
            if len(bad):
                problems.append(f"{len(bad)} linha(s) com {col} negativo (ex.: {_examples(bad)})")
            if non_numeric:
                problems.append(f"{non_numeric} linha(s) com {col} que não é número")
    for col in rules["ratio"]:
        if col in df.columns:
            numbers = pd.to_numeric(df[col], errors="coerce")
            bad = numbers[(numbers < 0) | (numbers > 1)]
            if len(bad):
                problems.append(f"{len(bad)} linha(s) com {col} fora de 0 a 1 (ex.: {_examples(bad)})")

    parsed = {}
    for col in rules["dates"]:
        parsed[col] = pd.to_datetime(df[col], errors="coerce")
        n = int(parsed[col].isna().sum() - df[col].isna().sum())
        if n:
            problems.append(f"{n} linha(s) com {col} que não é uma data válida")
    if period_start is not None and period_end is not None:
        start, end = pd.Timestamp(_as_date(period_start)), pd.Timestamp(_as_date(period_end))
        if start > end:
            problems.append("período inicial depois do final")
        for col, values in parsed.items():
            outside = values[(values < start) | (values > end)]
            if len(outside):
                problems.append(f"{len(outside)} linha(s) com {col} FORA do período coletado "
                                f"({start.date()} a {end.date()}), ex.: {_examples(v.date() for v in outside)}")
    if len(rules["dates"]) == 2:
        first, second = (parsed[c] for c in rules["dates"])
        if (first > second).any():
            problems.append("linha(s) com período inicial depois do final")

    duplicated = int(df.duplicated(subset=rules["key"]).sum())
    if duplicated:
        problems.append(f"{duplicated} linha(s) repetida(s) na mesma chave ({', '.join(rules['key'])})")

    if problems:
        raise DataValidationError(f"Dados inválidos para {table}, nada foi gravado: " + "; ".join(problems) + ".")
