"""Ferramentas que o agente de IA pode chamar (ETAPA 10). TODAS são SOMENTE LEITURA.

Decisão de segurança importante: o modelo NÃO recebe acesso livre ao banco (nada de "rode este SQL").
Ele só pode chamar as funções abaixo, cada uma com consultas fixas e parâmetros validados. Assim:
  - não existe como o modelo alterar ou apagar dados;
  - não existe injeção de SQL;
  - você controla exatamente o que pode sair do seu computador (veja allow_queries).

Cada ferramenta devolve texto JSON. Erros esperados viram GA4ProjectError (o agente os mostra ao modelo como erro).
"""
import json
import math
from datetime import date

import numpy as np
import pandas as pd

from ga_project.dashboard_data import (
    compute_kpis,
    load_channels,
    load_daily,
    load_date_range,
    load_last_loads,
    load_top_queries,
    previous_period,
)
from ga_project.errors import GA4ProjectError
from ga_project.insights import generate_insights

MAX_DAYS = 120            # período máximo por consulta
MAX_QUERIES = 50          # linhas máximas de consultas
MAX_JSON_CHARS = 40_000   # tamanho máximo de uma resposta de ferramenta
QUERY_RULES = {"ctr_baixo", "quase_primeira_pagina"}   # insights que citam consultas e páginas do site

_PERIOD_PROPERTIES = {
    "inicio": {"type": "string", "description": "Data inicial, formato AAAA-MM-DD."},
    "fim": {"type": "string", "description": "Data final, formato AAAA-MM-DD."},
}

TOOLS = [
    {
        "name": "get_data_coverage",
        "description": (
            "Informa o intervalo de datas disponível no banco e quando cada tabela foi atualizada pela última vez. "
            "Use primeiro, para saber até que data há dados."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_period_summary",
        "description": (
            "KPIs de um período: sessões, sessões orgânicas do Google, usuários ativos (média por dia), páginas vistas, "
            "cliques, impressões e CTR do Search Console, com a variação contra o período anterior de mesmo tamanho."
        ),
        "input_schema": {"type": "object", "properties": _PERIOD_PROPERTIES, "required": ["inicio", "fim"]},
    },
    {
        "name": "get_daily_metrics",
        "description": (
            f"Métricas dia a dia (GA4 + Search Console) de um período de até {MAX_DAYS} dias. "
            "sem_dados=true indica provável falha de coleta no GA4."
        ),
        "input_schema": {"type": "object", "properties": _PERIOD_PROPERTIES, "required": ["inicio", "fim"]},
    },
    {
        "name": "get_channel_breakdown",
        "description": "Sessões por canal de aquisição (Organic Search, Direct, Paid Search etc.) em um período, com a participação de cada um.",
        "input_schema": {"type": "object", "properties": _PERIOD_PROPERTIES, "required": ["inicio", "fim"]},
    },
    {
        "name": "get_top_queries",
        "description": (
            "Principais consultas de busca e páginas do Search Console (foto do período mais recente gravado): "
            "cliques, impressões, CTR e posição média."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limite": {"type": "integer", "description": f"Quantidade de linhas, de 1 a {MAX_QUERIES}. Padrão 20."}},
        },
    },
    {
        "name": "get_insights",
        "description": (
            "Riscos, oportunidades e destaques detectados por regras fixas sobre os dados (queda de sessões ou cliques, "
            "falhas de coleta, dependência de canal, CTR baixo, consultas quase na 1ª página), com severidade e impacto."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def available_tools(allow_queries: bool = True) -> list[dict]:
    """Lista de ferramentas enviada ao modelo. Sem allow_queries, as consultas/páginas ficam de fora."""
    return [t for t in TOOLS if allow_queries or t["name"] != "get_top_queries"]


# ---------------------------------------------------------------------------
# Conversão para JSON (sem NaN, sem objetos de data)
# ---------------------------------------------------------------------------
def _clean(value):
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 4)
    if isinstance(value, (bool, int, str)):
        return value
    return str(value)


def _records(df: pd.DataFrame) -> list[dict]:
    return [{key: _clean(value) for key, value in row.items()} for row in df.to_dict("records")]


def _dump(payload: dict) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > MAX_JSON_CHARS:
        raise GA4ProjectError("Resposta grande demais. Peça um período menor ou menos linhas.")
    return text


# ---------------------------------------------------------------------------
# Validação de parâmetros
# ---------------------------------------------------------------------------
def _parse_date(value, name: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise GA4ProjectError(f"{name} inválida: '{value}'. Use o formato AAAA-MM-DD.") from exc


def _parse_period(conn, args: dict) -> tuple[date, date]:
    """Valida o período e o ajusta ao intervalo disponível no banco."""
    start, end = _parse_date(args.get("inicio"), "Data inicial"), _parse_date(args.get("fim"), "Data final")
    if start > end:
        raise GA4ProjectError("A data inicial é depois da data final.")
    if (end - start).days + 1 > MAX_DAYS:
        raise GA4ProjectError(f"Período grande demais: no máximo {MAX_DAYS} dias por consulta.")
    available = load_date_range(conn)
    if available is None:
        raise GA4ProjectError("O banco está vazio.")
    first, last = available
    if end < first or start > last:
        raise GA4ProjectError(f"Período fora do intervalo disponível ({first.isoformat()} a {last.isoformat()}).")
    return max(start, first), min(end, last)


# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------
def tool_get_data_coverage(conn, args, today, allow_queries) -> str:
    available = load_date_range(conn)
    if available is None:
        return _dump({"banco_vazio": True})
    first, last = available
    return _dump({
        "primeira_data": first.isoformat(),
        "ultima_data": last.isoformat(),
        "hoje": today.isoformat(),
        "ultimas_cargas": _records(load_last_loads(conn)),
        "observacao": "O Search Console tem atraso de ~3 dias: as últimas datas podem não ter cliques e impressões.",
    })


def tool_get_period_summary(conn, args, today, allow_queries) -> str:
    start, end = _parse_period(conn, args)
    current = load_daily(conn, start, end)
    prev_start, prev_end = previous_period(start, end)
    previous = load_daily(conn, prev_start, prev_end)
    kpis = [
        {"nome": k["label"], "valor": _clean(k["value"]), "variacao": _clean(k["delta"]),
         "tipo_variacao": "pontos percentuais" if k["delta_kind"] == "pp" else "percentual"}
        for k in compute_kpis(current, previous)
    ]
    return _dump({
        "periodo": {"inicio": start.isoformat(), "fim": end.isoformat(), "dias_com_linha": len(current)},
        "periodo_anterior": {"inicio": prev_start.isoformat(), "fim": prev_end.isoformat(), "dias_com_linha": len(previous)},
        "dias_sem_dados_no_ga4": int(current["sem_dados"].sum()) if not current.empty else 0,
        "kpis": kpis,
        "observacao": "A variação só é calculada se o período anterior tiver o mesmo número de dias no banco.",
    })


def tool_get_daily_metrics(conn, args, today, allow_queries) -> str:
    start, end = _parse_period(conn, args)
    daily = load_daily(conn, start, end)
    return _dump({"periodo": {"inicio": start.isoformat(), "fim": end.isoformat()}, "dias": _records(daily)})


def tool_get_channel_breakdown(conn, args, today, allow_queries) -> str:
    start, end = _parse_period(conn, args)
    channels = load_channels(conn, start, end)
    total = channels["sessoes"].sum() if not channels.empty else 0
    channels["participacao_pct"] = (channels["sessoes"] / total * 100).round(1) if total else 0.0
    return _dump({"periodo": {"inicio": start.isoformat(), "fim": end.isoformat()}, "canais": _records(channels)})


def tool_get_top_queries(conn, args, today, allow_queries) -> str:
    if not allow_queries:
        raise GA4ProjectError("Consultas e páginas estão desativadas por privacidade (AGENT_SEND_QUERIES=false).")
    try:
        limit = int(args.get("limite", 20))
    except (TypeError, ValueError) as exc:
        raise GA4ProjectError("'limite' deve ser um número inteiro.") from exc
    limit = max(1, min(limit, MAX_QUERIES))
    return _dump({"consultas": _records(load_top_queries(conn, limit))})


def tool_get_insights(conn, args, today, allow_queries) -> str:
    insights, skipped, last = generate_insights(conn, today)
    if not allow_queries:
        insights = insights[~insights["regra"].isin(QUERY_RULES)]
    return _dump({
        "gerado_em": today.isoformat(),
        "dados_ate": last.isoformat(),
        "insights": _records(insights.drop(columns=["gerado_em"])),
        "regras_nao_avaliadas": skipped,
    })


_HANDLERS = {
    "get_data_coverage": tool_get_data_coverage,
    "get_period_summary": tool_get_period_summary,
    "get_daily_metrics": tool_get_daily_metrics,
    "get_channel_breakdown": tool_get_channel_breakdown,
    "get_top_queries": tool_get_top_queries,
    "get_insights": tool_get_insights,
}


def execute_tool(name: str, args: dict | None, conn, allow_queries: bool = True, today: date | None = None) -> str:
    """Executa uma ferramenta pelo nome e devolve o resultado em JSON (texto)."""
    handler = _HANDLERS.get(name)
    if handler is None:
        raise GA4ProjectError(f"Ferramenta desconhecida: {name}.")
    return handler(conn, args or {}, today or date.today(), allow_queries)
