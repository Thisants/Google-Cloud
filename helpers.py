"""Apoio dos testes multi-cliente: banco em memória/arquivo e dados fictícios por cliente."""
import sqlite3
from datetime import date, datetime

import pandas as pd

from ga_project.clientes import ensure_cliente
from ga_project.database import create_schema, save_dataframe

sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" "))

START = date(2026, 9, 1)


def fresh_db():
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    return conn


def file_connect(path):
    """connect_fn para testes com várias threads: cada chamada abre uma conexão nova no mesmo arquivo."""
    return lambda: sqlite3.connect(str(path), timeout=30, check_same_thread=False)


def expected_sessions(base: int, days: int) -> int:
    return sum(base + i for i in range(days))


def populate(conn, slug, *, days=20, base=100, nome=None, start=START, sessions_only_ga4=False):
    """Cadastra o cliente e grava dados fictícios: sessoes do dia i = base + i. Devolve a última data."""
    ensure_cliente(conn, slug, nome or f"Cliente {slug}")
    dates = pd.date_range(start, periods=days)
    end = dates[-1].date()
    ga4 = pd.DataFrame({"data": dates, "usuarios_ativos": base // 2, "sessoes": [base + i for i in range(days)],
                        "visualizacoes_pagina": base * 2, "sem_dados": False})
    save_dataframe(conn, "ga4_diario", ga4, start, end, cliente_id=slug)
    channels = pd.DataFrame({"data": list(dates) * 2, "canal": ["Organic Search"] * days + ["Direct"] * days,
                             "origem": ["google"] * days + ["(direct)"] * days,
                             "sessoes": [(base + i) // 2 for i in range(days)] * 2})
    save_dataframe(conn, "ga4_sessoes_canal", channels, start, end, cliente_id=slug)
    if not sessions_only_ga4:
        gsc = pd.DataFrame({"data": dates, "cliques": base // 10, "impressoes": base * 3, "ctr": 0.033, "posicao_media": 7.5})
        save_dataframe(conn, "gsc_diario", gsc, start, end, cliente_id=slug)
        queries = pd.DataFrame([(f"consulta-{slug}", f"/pagina-{slug}", base // 10, base * 3, 0.033, 7.5, start, end)],
                               columns=["consulta", "pagina", "cliques", "impressoes", "ctr", "posicao_media",
                                        "periodo_inicio", "periodo_fim"])
        save_dataframe(conn, "gsc_consulta_pagina", queries, start, end, cliente_id=slug)
    return end
