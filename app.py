"""ETAPA 08 - Dashboard (Streamlit), lendo do PostgreSQL.

Executar (na raiz do projeto, com o ambiente virtual ativo):
    streamlit run 08-dashboard/app.py
O navegador abre em http://localhost:8501  (se pedir e-mail no terminal, aperte Enter).

O dashboard SÓ LÊ do banco. Para atualizar os dados: rode as etapas de coleta e a 07 e clique em "Atualizar dados".
"""
import sys
from datetime import timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
for candidate in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    path = str(candidate)
    if candidate.exists() and path not in sys.path:
        sys.path.insert(0, path)

import streamlit as st

from ga_project.dashboard_data import (
    compute_kpis,
    fmt_delta,
    fmt_value,
    load_channels,
    load_daily,
    load_date_range,
    load_last_loads,
    load_top_queries,
    previous_period,
)
from ga_project.database import connect
from ga_project.errors import GA4ProjectError

CACHE_SECONDS = 300  # os dados ficam em cache por 5 minutos (ou até clicar em "Atualizar dados")


@st.cache_data(ttl=CACHE_SECONDS)
def get_date_range():
    conn = connect()
    try:
        return load_date_range(conn)
    finally:
        conn.close()


@st.cache_data(ttl=CACHE_SECONDS)
def get_data(start, end):
    """Carrega tudo o que a tela precisa (uma conexão por carga)."""
    prev_start, prev_end = previous_period(start, end)
    conn = connect()
    try:
        return {
            "daily": load_daily(conn, start, end),
            "previous": load_daily(conn, prev_start, prev_end),
            "channels": load_channels(conn, start, end),
            "queries": load_top_queries(conn, 20),
            "loads": load_last_loads(conn),
        }
    finally:
        conn.close()


def show_kpis(kpis):
    columns = st.columns(len(kpis))
    for column, kpi in zip(columns, kpis):
        column.metric(kpi["label"], fmt_value(kpi["value"], kpi["kind"]), fmt_delta(kpi["delta"], kpi["delta_kind"]))


def refresh_data():
    st.cache_data.clear()
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def main():
    st.set_page_config(page_title="Analytics — GA4 + Search Console", layout="wide")
    st.title("Analytics: GA4 + Search Console")

    # 1) Banco disponível e com dados?
    try:
        available = get_date_range()
    except GA4ProjectError as exc:
        st.error(str(exc))
        st.stop()
    if available is None:
        st.warning("O banco está vazio. Rode as etapas de coleta e depois a ETAPA 07 (python 07-banco-dados\\main.py).")
        st.stop()
    first, last = available

    # 2) Filtros (barra lateral)
    with st.sidebar:
        st.header("Filtros")
        default_start = max(first, last - timedelta(days=29))
        period = st.date_input("Período", value=(default_start, last), min_value=first, max_value=last)
        if st.button("Atualizar dados"):
            refresh_data()
        st.caption(f"Dados disponíveis: {first:%d/%m/%Y} a {last:%d/%m/%Y}")
    if len(period) != 2:
        st.info("Selecione a data inicial e a data final no filtro lateral.")
        st.stop()
    start, end = period

    # 3) Dados
    try:
        data = get_data(start, end)
    except GA4ProjectError as exc:
        st.error(str(exc))
        st.stop()
    daily = data["daily"]
    if daily.empty:
        st.info("Não há dados nesse período.")
        st.stop()

    st.caption(
        f"Período: {start:%d/%m/%Y} a {end:%d/%m/%Y} ({len(daily)} dias). "
        "Variações comparam com o período anterior de mesmo tamanho (só aparecem se ele estiver completo)."
    )
    show_kpis(compute_kpis(daily, data["previous"]))

    missing_days = int(daily["sem_dados"].sum())
    if missing_days:
        st.warning(f"{missing_days} dia(s) sem dados no GA4 (zero em tudo): ficam fora das médias.")

    # 4) Abas
    tab_geral, tab_gsc, tab_canais, tab_consultas, tab_dados = st.tabs(
        ["Visão geral", "Search Console", "Canais", "Consultas", "Dados"]
    )

    with tab_geral:
        st.subheader("Sessões por dia")
        st.line_chart(daily.set_index("data")[["sessoes", "sessoes_organicas_google"]])
        st.subheader("Usuários ativos e páginas vistas por dia")
        st.line_chart(daily.set_index("data")[["usuarios_ativos", "visualizacoes_pagina"]])

    with tab_gsc:
        st.caption("O Search Console tem atraso de ~3 dias: os últimos dias do período podem aparecer sem dados.")
        st.subheader("Cliques por dia")
        st.line_chart(daily.set_index("data")[["cliques"]])
        st.subheader("Impressões por dia")
        st.line_chart(daily.set_index("data")[["impressoes"]])
        st.subheader("Posição média por dia (1 = topo; menor é melhor)")
        st.line_chart(daily.set_index("data")[["posicao_media"]])

    with tab_canais:
        st.subheader("Sessões por canal no período")
        if data["channels"].empty:
            st.info("Sem dados de canais no período.")
        else:
            st.bar_chart(data["channels"].set_index("canal")["sessoes"])
            st.dataframe(data["channels"], hide_index=True)

    with tab_consultas:
        queries = data["queries"]
        st.subheader("Principais consultas e páginas (Search Console)")
        if queries.empty:
            st.info("Sem dados de consultas no banco.")
        else:
            row = queries.iloc[0]
            st.caption(f"Foto do período {row['periodo_inicio']} a {row['periodo_fim']} (mais recente gravada).")
            st.dataframe(queries.drop(columns=["periodo_inicio", "periodo_fim"]), hide_index=True)

    with tab_dados:
        st.subheader("Dados diários")
        st.dataframe(daily, hide_index=True)
        st.download_button(
            "Baixar CSV",
            data=daily.to_csv(index=False).encode("utf-8-sig"),
            file_name="dados_diarios.csv",
            mime="text/csv",
        )

    # 5) Rodapé: atualização do banco
    loads = data["loads"]
    if not loads.empty:
        with st.expander("Última atualização do banco"):
            st.dataframe(loads, hide_index=True)


main()
