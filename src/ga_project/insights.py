"""Detecção de problemas e oportunidades (ETAPA 09).

Regras SIMPLES e EXPLICÁVEIS (sem IA): cada alerta mostra o número que o gerou.
Todos os limites estão nas constantes abaixo, em um lugar só, para você ajustar ao seu negócio.

Fluxo:  generate_insights() -> carrega do banco (só leitura) -> roda as regras -> tabela de insights

Tipos de insight:
  - risco        : algo que pede atenção (queda, falha de coleta, dependência de um canal)
  - oportunidade : onde um esforço pode render cliques a mais (CTR baixo, quase na 1ª página)
  - destaque     : boa notícia (crescimento, melhora de posição)

Cada regra devolve (lista_de_insights, aviso). O aviso explica por que uma regra NÃO pôde ser avaliada
(por exemplo, poucos dias de dados), para o relatório nunca fingir que "está tudo bem" por falta de dados.
"""
from datetime import date, timedelta

import pandas as pd

from ga_project.dashboard_data import _br, load_channels, load_daily, load_date_range, load_top_queries
from ga_project.errors import GA4ProjectError

# ---------------------------------------------------------------------------
# Limites (ajuste aqui)
# ---------------------------------------------------------------------------
JANELA_DIAS = 7                 # compara os últimos 7 dias com os 7 anteriores
MIN_DIAS_JANELA = 5             # mínimo de dias com dados em cada janela

SESSOES = {"queda_media": 20, "queda_alta": 35, "alta_destaque": 20, "min_base": 50}       # % e sessões
CLIQUES = {"queda_media": 25, "queda_alta": 40, "alta_destaque": 25, "min_base": 20}       # % e cliques
POSICAO = {"piora_media": 2.0, "piora_alta": 4.0, "melhora_destaque": 2.0, "min_impressoes": 100}
SEM_DADOS = {"janela_dias": 14, "alta_a_partir_de": 3}
DESATUALIZADO = {"media_dias": 7, "alta_dias": 14}
CONCENTRACAO = {"media_pct": 70, "alta_pct": 85, "min_sessoes": 50}
HISTORICO = {"janela_dias": 90}  # procura buracos no histórico dos últimos 90 dias

# CTR mínimo esperado por faixa de posição (referência APROXIMADA, não é dado do Google): até a posição 3 -> 8%...
CTR_ALVO = [(3, 0.08), (5, 0.04), (10, 0.02)]
CTR_BAIXO = {"min_impressoes": 100, "min_cliques_potenciais": 3, "top": 10}
PAGINA_2 = {"pos_min": 10.0, "pos_max": 20.0, "ctr_alvo": 0.02, "min_impressoes": 100,
            "min_cliques_potenciais": 3, "top": 10}

SEVERITY_RANK = {"alta": 0, "média": 1, "baixa": 2}
TYPE_RANK = {"risco": 0, "oportunidade": 1, "destaque": 2}
COLUMNS = ["tipo", "severidade", "regra", "titulo", "detalhe", "impacto", "referencia", "gerado_em"]


def _insight(tipo, severidade, regra, titulo, detalhe, impacto=None, referencia=""):
    return {"tipo": tipo, "severidade": severidade, "regra": regra, "titulo": titulo,
            "detalhe": detalhe, "impacto": impacto, "referencia": referencia}


def _day(ts) -> str:
    return pd.Timestamp(ts).strftime("%d/%m/%Y")


def _windows(df: pd.DataFrame, end: pd.Timestamp):
    """Devolve (janela recente, janela anterior), cada uma com JANELA_DIAS dias corridos, terminando em `end`."""
    span = pd.Timedelta(days=JANELA_DIAS)
    recent = df[(df["data"] > end - span) & (df["data"] <= end)]
    previous = df[(df["data"] > end - 2 * span) & (df["data"] <= end - span)]
    return recent, previous


def _pct(now: float, before: float) -> float:
    return (now - before) / before * 100


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------
def rule_sessions_trend(daily: pd.DataFrame):
    """Queda (risco) ou alta (destaque) das sessões: últimos 7 dias vs 7 anteriores (média por dia com dados)."""
    name = "tendência de sessões"
    valid = daily[~daily["sem_dados"]]
    if valid.empty:
        return [], f"{name}: não há dias com dados."
    end = valid["data"].max()
    recent, previous = _windows(valid, end)
    if len(recent) < MIN_DIAS_JANELA or len(previous) < MIN_DIAS_JANELA:
        return [], (f"{name}: precisa de {MIN_DIAS_JANELA}+ dias com dados em cada janela de {JANELA_DIAS} dias "
                    f"(há {len(recent)} e {len(previous)}).")
    if previous["sessoes"].sum() < SESSOES["min_base"]:
        return [], f"{name}: volume baixo demais no período anterior (menos de {SESSOES['min_base']} sessões)."

    now, before = recent["sessoes"].mean(), previous["sessoes"].mean()
    change = _pct(now, before)
    ref = f"{_day(recent['data'].min())} a {_day(end)} vs {_day(previous['data'].min())} a {_day(previous['data'].max())}"
    detail = f"Média de {_br(f'{now:,.1f}')} sessões/dia contra {_br(f'{before:,.1f}')} no período anterior."
    if change <= -SESSOES["queda_alta"] or change <= -SESSOES["queda_media"]:
        sev = "alta" if change <= -SESSOES["queda_alta"] else "média"
        return [_insight("risco", sev, "queda_sessoes", f"Queda de sessões ({_br(f'{change:+.0f}')}%)", detail,
                         round(change, 1), ref)], None
    if change >= SESSOES["alta_destaque"]:
        return [_insight("destaque", "baixa", "alta_sessoes", f"Sessões em alta ({_br(f'{change:+.0f}')}%)", detail,
                         round(change, 1), ref)], None
    return [], None


def rule_clicks_trend(daily: pd.DataFrame):
    """Queda (risco) ou alta (destaque) de cliques no Search Console (usa só dias que têm dados do Search Console)."""
    name = "tendência de cliques (Search Console)"
    gsc = daily[daily["cliques"].notna()]
    if gsc.empty:
        return [], f"{name}: não há dados do Search Console no período."
    end = gsc["data"].max()
    recent, previous = _windows(gsc, end)
    if len(recent) < MIN_DIAS_JANELA or len(previous) < MIN_DIAS_JANELA:
        return [], (f"{name}: precisa de {MIN_DIAS_JANELA}+ dias em cada janela de {JANELA_DIAS} dias "
                    f"(há {len(recent)} e {len(previous)}).")
    if previous["cliques"].sum() < CLIQUES["min_base"]:
        return [], f"{name}: volume baixo demais no período anterior (menos de {CLIQUES['min_base']} cliques)."

    now, before = recent["cliques"].mean(), previous["cliques"].mean()
    change = _pct(now, before)
    ref = f"{_day(recent['data'].min())} a {_day(end)} vs {_day(previous['data'].min())} a {_day(previous['data'].max())}"
    detail = f"Média de {_br(f'{now:,.1f}')} cliques/dia contra {_br(f'{before:,.1f}')} no período anterior."
    if change <= -CLIQUES["queda_media"]:
        sev = "alta" if change <= -CLIQUES["queda_alta"] else "média"
        return [_insight("risco", sev, "queda_cliques", f"Queda de cliques no Google ({_br(f'{change:+.0f}')}%)", detail,
                         round(change, 1), ref)], None
    if change >= CLIQUES["alta_destaque"]:
        return [_insight("destaque", "baixa", "alta_cliques", f"Cliques no Google em alta ({_br(f'{change:+.0f}')}%)",
                         detail, round(change, 1), ref)], None
    return [], None


def _weighted_position(df: pd.DataFrame):
    valid = df[(df["impressoes"] > 0) & df["posicao_media"].notna()]
    total = valid["impressoes"].sum()
    return float((valid["posicao_media"] * valid["impressoes"]).sum() / total) if total else None


def rule_position_trend(daily: pd.DataFrame):
    """Piora (risco) ou melhora (destaque) da posição média no Google (ponderada por impressões)."""
    name = "tendência de posição média"
    gsc = daily[daily["cliques"].notna()]
    if gsc.empty:
        return [], f"{name}: não há dados do Search Console no período."
    end = gsc["data"].max()
    recent, previous = _windows(gsc, end)
    if recent["impressoes"].sum() < POSICAO["min_impressoes"] or previous["impressoes"].sum() < POSICAO["min_impressoes"]:
        return [], f"{name}: impressões insuficientes (mínimo {POSICAO['min_impressoes']} em cada janela)."
    now, before = _weighted_position(recent), _weighted_position(previous)
    if now is None or before is None:
        return [], f"{name}: sem posição calculável."

    diff = now - before          # positivo = posição piorou (número maior = mais longe do topo)
    ref = f"{_day(recent['data'].min())} a {_day(end)} vs {_day(previous['data'].min())} a {_day(previous['data'].max())}"
    detail = f"Posição média {_br(f'{now:.1f}')} contra {_br(f'{before:.1f}')} no período anterior (1 = topo)."
    if diff >= POSICAO["piora_media"]:
        sev = "alta" if diff >= POSICAO["piora_alta"] else "média"
        return [_insight("risco", sev, "piora_posicao", f"Posição média piorou ({_br(f'{diff:+.1f}')} posições)", detail,
                         round(diff, 1), ref)], None
    if diff <= -POSICAO["melhora_destaque"]:
        return [_insight("destaque", "baixa", "melhora_posicao", f"Posição média melhorou ({_br(f'{diff:+.1f}')} posições)",
                         detail, round(diff, 1), ref)], None
    return [], None


def rule_days_without_data(daily: pd.DataFrame):
    """Dias recentes com zero em tudo no GA4: possível falha da tag ou da coleta."""
    if daily.empty:
        return [], None
    end = daily["data"].max()
    recent = daily[daily["data"] > end - pd.Timedelta(days=SEM_DADOS["janela_dias"])]
    missing = recent[recent["sem_dados"]]
    if missing.empty:
        return [], None
    n = len(missing)
    sev = "alta" if n >= SEM_DADOS["alta_a_partir_de"] else "média"
    days = ", ".join(_day(d) for d in missing["data"].head(5))
    detail = (f"{n} dia(s) com zero em todas as métricas nos últimos {SEM_DADOS['janela_dias']} dias ({days}). "
              "Confira se a tag do GA4 está funcionando no site e se a coleta rodou.")
    return [_insight("risco", sev, "dias_sem_dados", f"{n} dia(s) sem dados no GA4", detail, float(n),
                     f"até {_day(end)}")], None


def rule_history_gaps(daily: pd.DataFrame, start: date, end: date):
    """Buracos no histórico do banco: datas sem nenhuma linha (a coleta não rodou a tempo)."""
    expected = pd.date_range(start, end, freq="D")
    missing = expected.difference(pd.DatetimeIndex(daily["data"]))
    if len(missing) == 0:
        return [], None

    ranges, run_start, previous = [], missing[0], missing[0]
    for day in missing[1:]:
        if (day - previous).days > 1:
            ranges.append((run_start, previous))
            run_start = day
        previous = day
    ranges.append((run_start, previous))

    shown = "; ".join(_day(a) if a == b else f"{_day(a)} a {_day(b)}" for a, b in ranges[:5])
    extra = f" (e mais {len(ranges) - 5} intervalos)" if len(ranges) > 5 else ""
    recent = missing.max() >= pd.Timestamp(end) - pd.Timedelta(days=30)
    detail = (f"Faltam {len(missing)} dia(s) no histórico: {shown}{extra}. "
              "Rode a coleta (etapas 02, 03, 05 e 06) e a etapa 07 com mais frequência (no máximo a cada ~3 semanas).")
    return [_insight("risco", "alta" if recent else "média", "lacuna_historico",
                     f"Buracos no histórico ({len(missing)} dia(s))", detail, float(len(missing)),
                     f"{_day(start)} a {_day(end)}")], None


def rule_stale_data(last_date: date, today: date):
    """Banco desatualizado: a última data gravada está muito longe de hoje."""
    lag = (today - last_date).days
    if lag <= DESATUALIZADO["media_dias"]:
        return [], None
    sev = "alta" if lag > DESATUALIZADO["alta_dias"] else "média"
    return [_insight("risco", sev, "dados_desatualizados", f"Dados desatualizados ({lag} dias)",
                     f"A última data no banco é {_day(last_date)}. Rode a coleta e a etapa 07.", float(lag),
                     f"hoje: {_day(today)}")], None


def rule_channel_concentration(channels: pd.DataFrame):
    """Dependência de um único canal de tráfego."""
    name = "concentração por canal"
    total = channels["sessoes"].sum() if not channels.empty else 0
    if total < CONCENTRACAO["min_sessoes"]:
        return [], f"{name}: poucas sessões por canal no período (menos de {CONCENTRACAO['min_sessoes']})."
    top = channels.sort_values("sessoes", ascending=False).iloc[0]
    share = float(top["sessoes"] / total * 100)
    if share < CONCENTRACAO["media_pct"]:
        return [], None
    sev = "alta" if share >= CONCENTRACAO["alta_pct"] else "média"
    return [_insight("risco", sev, "concentracao_canal", f"Dependência do canal {top['canal']} ({_br(f'{share:.0f}')}%)",
                     f"{_br(f'{share:.0f}')}% das sessões do período vêm de um único canal. "
                     "Se ele cair, o tráfego total cai junto.", round(share, 1), "últimos 30 dias do banco")], None


def _ctr_target(position: float):
    for max_position, target in CTR_ALVO:
        if position <= max_position:
            return target
    return None


def _opportunity_severity(potential: float) -> str:
    return "alta" if potential >= 30 else "média" if potential >= 10 else "baixa"


def rule_low_ctr(queries: pd.DataFrame):
    """Oportunidade: aparece bem posicionado e muito visto, mas poucos clicam (título/descrição fracos)."""
    if queries.empty:
        return [], "CTR baixo: não há consultas do Search Console no banco."
    df = queries[(queries["impressoes"] >= CTR_BAIXO["min_impressoes"]) & (queries["posicao_media"] <= CTR_ALVO[-1][0])].copy()
    df["alvo"] = df["posicao_media"].map(_ctr_target)
    df["potencial"] = (df["alvo"] - df["ctr"]) * df["impressoes"]
    df = df[df["potencial"] >= CTR_BAIXO["min_cliques_potenciais"]].sort_values("potencial", ascending=False)

    items = []
    for _, r in df.head(CTR_BAIXO["top"]).iterrows():
        position = _br(f"{r['posicao_media']:.1f}")
        ctr_now = _br(f"{r['ctr'] * 100:.1f}")
        ctr_goal = _br(f"{r['alvo'] * 100:.0f}")
        extra_clicks = _br(f"{r['potencial']:.0f}")
        detail = (f"{int(r['impressoes'])} impressões na posição {position}, mas CTR de {ctr_now}% "
                  f"(referência mínima ~{ctr_goal}%). Melhorar o título e a descrição de {r['pagina']} "
                  f"pode render cerca de {extra_clicks} cliques a mais no período.")
        items.append(_insight("oportunidade", _opportunity_severity(r["potencial"]), "ctr_baixo",
                              f"CTR baixo para \"{r['consulta']}\"", detail, round(float(r["potencial"]), 1),
                              f"{_day(r['periodo_inicio'])} a {_day(r['periodo_fim'])}"))
    return items, None


def rule_near_first_page(queries: pd.DataFrame):
    """Oportunidade: consultas na 2ª página (posições 11-20) com bastante visualização."""
    if queries.empty:
        return [], "quase na 1ª página: não há consultas do Search Console no banco."
    cfg = PAGINA_2
    df = queries[(queries["posicao_media"] > cfg["pos_min"]) & (queries["posicao_media"] <= cfg["pos_max"])
                 & (queries["impressoes"] >= cfg["min_impressoes"])].copy()
    df["potencial"] = df["impressoes"] * cfg["ctr_alvo"] - df["cliques"]
    df = df[df["potencial"] >= cfg["min_cliques_potenciais"]].sort_values("potencial", ascending=False)

    items = []
    for _, r in df.head(cfg["top"]).iterrows():
        position = _br(f"{r['posicao_media']:.1f}")
        extra_clicks = _br(f"{r['potencial']:.0f}")
        detail = (f"{int(r['impressoes'])} impressões na posição {position} (2ª página do Google). "
                  f"Levar {r['pagina']} para a 1ª página pode render cerca de {extra_clicks} cliques a mais.")
        items.append(_insight("oportunidade", _opportunity_severity(r["potencial"]), "quase_primeira_pagina",
                              f"Quase na 1ª página: \"{r['consulta']}\"", detail, round(float(r["potencial"]), 1),
                              f"{_day(r['periodo_inicio'])} a {_day(r['periodo_fim'])}"))
    return items, None


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def generate_insights(conn, today: date | None = None) -> tuple[pd.DataFrame, list[str], date]:
    """Lê o banco (só SELECT), roda todas as regras e devolve (insights, avisos, última_data_do_banco)."""
    today = today or date.today()
    available = load_date_range(conn)
    if available is None:
        raise GA4ProjectError("O banco está vazio. Rode a coleta e a ETAPA 07 antes (python 07-banco-dados\\main.py).")
    first, last = available

    start = max(first, last - timedelta(days=HISTORICO["janela_dias"] - 1))
    daily = load_daily(conn, start, last)
    channels = load_channels(conn, max(first, last - timedelta(days=29)), last)
    queries = load_top_queries(conn, 1000)

    results = [
        rule_sessions_trend(daily),
        rule_clicks_trend(daily),
        rule_position_trend(daily),
        rule_days_without_data(daily),
        rule_history_gaps(daily, start, last),
        rule_stale_data(last, today),
        rule_channel_concentration(channels),
        rule_low_ctr(queries),
        rule_near_first_page(queries),
    ]
    items = [item for found, _ in results for item in found]
    skipped = [note for _, note in results if note]

    df = pd.DataFrame(items, columns=[c for c in COLUMNS if c != "gerado_em"])
    df["gerado_em"] = today
    if not df.empty:
        df["_s"] = df["severidade"].map(SEVERITY_RANK)
        df["_t"] = df["tipo"].map(TYPE_RANK)
        df["_i"] = df["impacto"].abs().fillna(0)
        df = df.sort_values(["_t", "_s", "_i"], ascending=[True, True, False]).drop(columns=["_s", "_t", "_i"])
    return df.reset_index(drop=True)[COLUMNS], skipped, last


def format_report(df: pd.DataFrame, skipped: list[str], last_date: date, today: date) -> str:
    """Relatório em texto para o terminal."""
    lines = [f"Gerado em {_day(today)} | dados do banco até {_day(last_date)}"]
    counts = df["tipo"].value_counts()
    lines.append(f"Resumo: {counts.get('risco', 0)} risco(s), {counts.get('oportunidade', 0)} oportunidade(s), "
                 f"{counts.get('destaque', 0)} destaque(s)")

    titles = {"risco": "RISCOS", "oportunidade": "OPORTUNIDADES", "destaque": "DESTAQUES"}
    for kind, title in titles.items():
        part = df[df["tipo"] == kind]
        if part.empty:
            continue
        lines += ["", f"=== {title} ==="]
        for _, r in part.iterrows():
            lines.append(f"[{r['severidade'].upper()}] {r['titulo']}")
            lines.append(f"    {r['detalhe']}")
            lines.append(f"    Referência: {r['referencia']}")
    if df.empty:
        lines += ["", "Nenhum alerta com as regras e limites atuais."]
    if skipped:
        lines += ["", "=== REGRAS NÃO AVALIADAS (dados insuficientes) ==="] + [f"- {note}" for note in skipped]
    return "\n".join(lines)
