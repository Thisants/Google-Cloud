"""Dados FICTÍCIOS de demonstração (ETAPA 12).

Para quê: mostrar o projeto (dashboard, insights, API, agente) em prints e entrevistas SEM expor dados reais
do negócio. Os números são inventados, determinísticos (mesma semente = mesmos dados) e já trazem situações
que as regras da etapa 09 detectam: queda forte nas últimas 7 datas, um dia sem dados no GA4, posição média
piorando, consultas com CTR baixo e consultas na 2ª página do Google.

Nada aqui acessa o Google nem a internet.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ga_project.database import save_dataframe

SITE = "https://www.lojademo.com.br"
WEEKDAY_FACTORS = np.array([1.05, 1.10, 1.10, 1.05, 0.95, 0.60, 0.55])     # segunda ... domingo
# (canal, origem, participação nas sessões). O "Direct" recebe o resto para a soma fechar exatamente.
CHANNELS = [
    ("Organic Search", "google", 0.52),
    ("Organic Search", "bing", 0.04),
    ("Referral", "parceiro-demo.com.br", 0.08),
    ("Organic Social", "instagram.com", 0.07),
    ("Paid Search", "google", 0.05),
]
# (consulta, página, impressões, posição média, CTR) — situações típicas para as regras da etapa 09
QUERIES = [
    ("tinta acrílica branca 18l", "/produtos/tinta-acrilica-branca", 2400, 2.3, 0.012),     # CTR baixo, topo
    ("cimento cp2 50kg preço", "/produtos/cimento-cp2", 1800, 1.6, 0.210),                  # saudável
    ("porcelanato 60x60 cinza", "/produtos/porcelanato-60x60", 1500, 4.4, 0.018),           # CTR baixo
    ("argamassa ac3 20kg", "/produtos/argamassa-ac3", 900, 8.2, 0.009),                     # CTR baixo, 1ª página
    ("rejunte flexível cinza", "/produtos/rejunte-flexivel", 1200, 12.5, 0.004),            # 2ª página
    ("massa corrida pva 25kg", "/produtos/massa-corrida", 800, 15.1, 0.003),                # 2ª página
    ("piso vinílico click", "/produtos/piso-vinilico", 600, 18.7, 0.002),                   # 2ª página
    ("furadeira de impacto 650w", "/produtos/furadeira-impacto", 700, 3.1, 0.095),          # saudável
    ("trena 5 metros", "/produtos/trena-5m", 450, 1.9, 0.180),                              # saudável
]


def _ints(values) -> np.ndarray:
    return np.maximum(np.round(values), 0).astype(int)


def build_demo_data(today: date, days: int = 120, seed: int = 42) -> dict:
    """Gera os dados fictícios no formato das tabelas do banco (etapa 07).

    GA4 vai até ontem; o Search Console termina 3 dias antes de hoje (atraso real dessa fonte).
    """
    if days < 30:
        raise ValueError("Use pelo menos 30 dias para a demonstração fazer sentido.")
    rng = np.random.default_rng(seed)

    # ---------- GA4 por dia ----------
    end = today - timedelta(days=1)
    dates = pd.date_range(end - timedelta(days=days - 1), end)
    n = len(dates)
    t = np.arange(n)
    weekly = WEEKDAY_FACTORS[dates.dayofweek.to_numpy()]
    drop = np.where(t >= n - 7, 0.58, 1.0)                              # queda forte nas últimas 7 datas
    sessions = _ints(140 * (1 + 0.002 * t) * weekly * rng.normal(1.0, 0.05, n) * drop)
    sessions[n - 10] = 0                                                # um dia sem dados (falha de coleta simulada)
    ga4 = pd.DataFrame({
        "data": dates,
        "usuarios_ativos": _ints(sessions * 0.8),
        "sessoes": sessions,
        "visualizacoes_pagina": _ints(sessions * 2.3),
        "sem_dados": sessions == 0,
    })

    # ---------- GA4 por canal ----------
    rows = []
    for day, total in zip(dates, sessions):
        if total == 0:
            continue                                                    # a API não devolve linhas de dias sem sessões
        counts = [int(total * share * rng.normal(1.0, 0.08)) for _, _, share in CHANNELS]
        rows += [(day, canal, origem, c) for (canal, origem, _), c in zip(CHANNELS, counts) if c > 0]
        rows.append((day, "Direct", "(direct)", int(total) - sum(counts)))
    channels = pd.DataFrame(rows, columns=["data", "canal", "origem", "sessoes"])

    # ---------- Search Console por dia ----------
    gsc_end = today - timedelta(days=3)
    gdates = pd.date_range(gsc_end - timedelta(days=days - 1), gsc_end)
    gn = len(gdates)
    gt = np.arange(gn)
    last7 = gt >= gn - 7
    gweekly = WEEKDAY_FACTORS[gdates.dayofweek.to_numpy()]
    clicks = _ints(95 * (1 + 0.002 * gt) * gweekly * rng.normal(1.0, 0.06, gn) * np.where(last7, 0.62, 1.0))
    ctr = 0.032 * rng.normal(1.0, 0.05, gn)
    impressions = np.maximum(_ints(clicks / ctr), clicks + 1)
    position = np.round(7.6 + rng.normal(0, 0.25, gn) + np.where(last7, 3.2, 0.0), 1)   # posição piorando
    gsc = pd.DataFrame({
        "data": gdates, "cliques": clicks, "impressoes": impressions,
        "ctr": np.round(clicks / impressions, 4), "posicao_media": position,
    })

    # ---------- Search Console por consulta + página (foto dos últimos 30 dias) ----------
    start30 = (gsc_end - timedelta(days=29)).isoformat()
    period_start, period_end = date.fromisoformat(start30), gsc_end
    q_rows = [
        (q, SITE + page, int(round(impr * ctr_q)), impr, round(round(impr * ctr_q) / impr, 4), pos)
        for q, page, impr, pos, ctr_q in QUERIES
    ]
    for i in range(20):                                                 # cauda longa: muitas consultas pequenas
        impr = int(rng.integers(20, 90))
        clk = int(rng.integers(0, 6))
        q_rows.append((f"consulta de cauda longa {i + 1}", f"{SITE}/produtos/item-{i + 1}", clk, impr,
                       round(clk / impr, 4), round(float(rng.uniform(5, 40)), 1)))
    queries = pd.DataFrame(q_rows, columns=["consulta", "pagina", "cliques", "impressoes", "ctr", "posicao_media"])
    queries["periodo_inicio"] = period_start
    queries["periodo_fim"] = period_end

    return {
        "ga4_diario": ga4, "ga4_sessoes_canal": channels, "gsc_diario": gsc, "gsc_consulta_pagina": queries,
        "periodos": {"ga4": (dates[0].date(), end), "gsc": (gdates[0].date(), gsc_end)},
    }


def save_demo_data(conn, data: dict) -> dict[str, int]:
    """Grava os dados fictícios no banco (upsert: pode rodar de novo sem duplicar). Devolve linhas por tabela."""
    ga4_start, ga4_end = data["periodos"]["ga4"]
    gsc_start, gsc_end = data["periodos"]["gsc"]
    plan = [
        ("ga4_diario", ga4_start, ga4_end),
        ("ga4_sessoes_canal", ga4_start, ga4_end),
        ("gsc_diario", gsc_start, gsc_end),
        ("gsc_consulta_pagina", gsc_end - timedelta(days=29), gsc_end),
    ]
    return {table: save_dataframe(conn, table, data[table], start, end) for table, start, end in plan}
