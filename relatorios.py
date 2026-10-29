"""Relatórios em texto POR CLIENTE, lendo do banco (usados pelos comandos das etapas 03 a 06).

Os dados já chegam tratados e gravados pela coleta (etapa 02): aqui só se LÊ e se resume.
"""
from datetime import date, timedelta

import pandas as pd

from ga_project.analise import analyze
from ga_project.dashboard_data import fetch_df, load_daily, load_date_range, load_top_queries
from ga_project.errors import GA4ProjectError
from ga_project.insights import rule_history_gaps, rule_stale_data
from ga_project.integracao import integration_summary, merge_sources
from ga_project.tratamento import WEEKDAYS_PT


def _daily(conn, slug: str, days: int):
    available = load_date_range(conn, cliente_id=slug)
    if available is None:
        raise GA4ProjectError("Este cliente ainda não tem dados. Rode a coleta (02-coleta-dados) antes.")
    first, last = available
    start = max(first, last - timedelta(days=days - 1))
    return load_daily(conn, start, last, cliente_id=slug), start, last


def quality_report(conn, slug: str, today: date | None = None, days: int = 90) -> str:
    """Qualidade dos dados do cliente: dias sem dados, buracos no histórico, atraso e últimas execuções."""
    today = today or date.today()
    daily, start, last = _daily(conn, slug, days)
    lines = [f"Qualidade dos dados: cliente {slug}",
             f"Período: {start} a {last} ({len(daily)} dias com linha)",
             f"Dias sem dados no GA4 (zero em tudo): {int(daily['sem_dados'].sum())}",
             f"Dias com Search Console: {int(daily['cliques'].notna().sum())} de {len(daily)}"]
    for rule in (rule_history_gaps(daily, start, last), rule_stale_data(last, today)):
        lines += [f"ALERTA: {item['titulo']}. {item['detalhe']}" for item in rule[0]]
    runs = fetch_df(conn, "SELECT status, fim, linhas, mensagem FROM execucoes WHERE cliente_id = :c "
                          "ORDER BY fim DESC LIMIT 5", {"c": slug})
    lines.append("\nÚltimas execuções da rotina:")
    lines.append(runs.to_string(index=False) if not runs.empty else "  (nenhuma registrada)")
    return "\n".join(lines)


def _treated_frame(daily: pd.DataFrame) -> pd.DataFrame:
    frame = daily[["data", "usuarios_ativos", "sessoes", "visualizacoes_pagina", "sem_dados"]].copy()
    frame.insert(1, "dia_semana", frame["data"].dt.dayofweek.map(lambda i: WEEKDAYS_PT[i]))
    return frame


def analysis_report(conn, slug: str, days: int = 30) -> str:
    """Resumo, média por dia da semana e últimos 7 dias vs 7 anteriores do cliente."""
    daily, start, last = _daily(conn, slug, days)
    result = analyze(_treated_frame(daily))
    lines = [f"Análise: cliente {slug}", f"Período: {start} a {last} ({result['dias']} dias; {result['dias_sem_dados']} sem dados)",
             "\n=== Resumo por métrica ===", result["resumo"].to_string(index=False),
             "\n=== Média por dia da semana ===", result["dia_semana"].to_string(index=False)]
    comparison = result["comparacao"]
    if comparison is None:
        lines.append("\n=== Últimos 7 dias vs 7 anteriores ===\nDados insuficientes (precisa de 14 dias).")
    else:
        table, periods = comparison
        lines += [f"\n=== Média diária: {periods['atual'][0]} a {periods['atual'][1]} vs {periods['anterior'][0]} a {periods['anterior'][1]} ===",
                  table.to_string(index=False)]
    return "\n".join(lines)


def queries_report(conn, slug: str, limit: int = 20) -> str:
    df = load_top_queries(conn, limit, cliente_id=slug)
    if df.empty:
        return f"Cliente {slug}: ainda não há consultas do Search Console. Rode a coleta (02-coleta-dados)."
    period = f"{df.loc[0, 'periodo_inicio']} a {df.loc[0, 'periodo_fim']}"
    return (f"Principais consultas + páginas: cliente {slug} (período {period})\n"
            + df.drop(columns=["periodo_inicio", "periodo_fim"]).to_string(index=False, max_colwidth=50))


def integration_report(conn, slug: str, days: int = 30) -> str:
    """Cruzamento GA4 × Search Console por data (cliques x sessões orgânicas do Google)."""
    daily, start, last = _daily(conn, slug, days)
    gsc = daily[daily["cliques"].notna()]
    if gsc.empty:
        return f"Cliente {slug}: sem dados do Search Console no período; nada para cruzar."
    ga4 = daily.rename(columns={"sessoes": "ga4_sessoes_total", "sessoes_organicas_google": "ga4_sessoes_organicas_google"})[
        ["data", "ga4_sessoes_total", "ga4_sessoes_organicas_google"]]
    gsc_frame = gsc[["data", "cliques", "impressoes", "ctr", "posicao_media"]]
    merged, info = merge_sources(ga4, gsc_frame)
    first, last_common = info["periodo_comum"]
    return (f"Integração GA4 × Search Console: cliente {slug}\nPeríodo cruzado: {first} a {last_common} ({info['dias_em_comum']} dias)\n\n"
            + integration_summary(merged).to_string(index=False))
