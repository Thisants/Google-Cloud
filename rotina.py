"""Rotina de coleta para TODOS os clientes (ou alguns), pensada para crescer.

Decisões para aguentar mais e mais clientes:
  - FALHA ISOLADA: um cliente com problema (sem acesso, cota, site fora) vira um registro de erro; os outros seguem;
  - PARALELISMO LIMITADO: `workers` clientes ao mesmo tempo (cada um com a sua conexão ao banco), para não estourar as cotas do Google;
  - ORDEM JUSTA: quem foi coletado com sucesso há mais tempo vai primeiro, então uma rodada interrompida não deixa sempre os mesmos para trás;
  - HISTÓRICO: cada execução de cada cliente fica registrada na tabela `execucoes` (quando, status, linhas, mensagem);
  - INSIGHTS PRONTOS: depois de coletar, os insights do cliente são calculados UMA vez e guardados (API e dashboard só leem).
"""
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ga_project.clientes import Cliente, get_cliente, list_clientes
from ga_project.coleta import collect_cliente
from ga_project.dashboard_data import fetch_df
from ga_project.database import _sql
from ga_project.errors import GA4ProjectError
from ga_project.insights import refresh_insights

MAX_MESSAGE = 500


@dataclass
class ClienteResultado:
    slug: str
    status: str                                   # "ok" | "erro"
    linhas: dict = field(default_factory=dict)
    mensagem: str = ""
    segundos: float = 0.0
    insights: int = 0


def select_clientes(conn, slugs: list[str] | None = None) -> list[Cliente]:
    """Clientes ATIVOS (padrão) ou os slugs pedidos (erro claro se algum não existir)."""
    if not slugs:
        return list_clientes(conn, only_active=True)
    return [get_cliente(conn, slug) for slug in slugs]


def order_by_staleness(conn, clientes: list[Cliente]) -> list[Cliente]:
    """Quem teve a última coleta bem-sucedida há mais tempo (ou nunca) vem primeiro."""
    df = fetch_df(conn, "SELECT cliente_id, MAX(fim) AS ultima FROM execucoes "
                        "WHERE tipo = 'coleta' AND status = 'ok' GROUP BY cliente_id")
    last = {row["cliente_id"]: str(row["ultima"]) for _, row in df.iterrows()}
    return sorted(clientes, key=lambda c: (c.slug in last, last.get(c.slug, ""), c.slug))


def record_execution(conn, slug: str, status: str, message: str, rows: int, start: datetime, end: datetime) -> None:
    """Registra a execução. Nunca derruba a rotina: se o registro falhar, só segue."""
    try:
        conn.cursor().execute(
            _sql(conn, "INSERT INTO execucoes (cliente_id, tipo, status, mensagem, linhas, inicio, fim) "
                       "VALUES (:c, 'coleta', :status, :msg, :linhas, :inicio, :fim)"),
            {"c": slug, "status": status, "msg": message[:MAX_MESSAGE], "linhas": rows, "inicio": start, "fim": end},
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _run_one(connect_fn, cliente: Cliente, ga4_client, gsc_service_factory, dias, today, fontes, with_insights,
             sleep) -> ClienteResultado:
    started, t0 = datetime.now(timezone.utc), time.monotonic()
    conn = connect_fn()
    try:
        try:
            saved = collect_cliente(conn, cliente, ga4_client=ga4_client, gsc_service_factory=gsc_service_factory,
                                    dias=dias, today=today, fontes=fontes, sleep=sleep)
            message, n_insights = "", 0
            if with_insights:
                try:
                    n_insights = refresh_insights(conn, cliente.slug, today)
                except Exception as exc:                   # insights com problema não invalidam a coleta
                    message = f"coleta ok; insights falharam: {exc}"
            result = ClienteResultado(cliente.slug, "ok", saved, message, time.monotonic() - t0, n_insights)
        except Exception as exc:                            # isola QUALQUER falha deste cliente
            try:
                conn.rollback()
            except Exception:
                pass
            text = str(exc) if isinstance(exc, GA4ProjectError) else f"{type(exc).__name__}: {exc}"
            result = ClienteResultado(cliente.slug, "erro", {}, text, time.monotonic() - t0)
        record_execution(conn, cliente.slug, result.status, result.mensagem, sum(result.linhas.values()), started,
                         datetime.now(timezone.utc))
        return result
    finally:
        conn.close()


def run_clientes(connect_fn, clientes: list[Cliente], *, ga4_client, gsc_service_factory, dias: int = 30,
                 workers: int = 2, today: date | None = None, fontes=("ga4", "gsc"), with_insights: bool = True,
                 sleep=time.sleep) -> list[ClienteResultado]:
    """Coleta todos os clientes dados. Devolve um resultado por cliente (na ordem em que foram processados)."""
    if workers < 1:
        raise GA4ProjectError("workers precisa ser pelo menos 1.")
    conn = connect_fn()
    try:
        ordered = order_by_staleness(conn, clientes)
    finally:
        conn.close()
    args = (ga4_client, gsc_service_factory, dias, today, fontes, with_insights, sleep)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_one, connect_fn, cliente, *args) for cliente in ordered]
        return [future.result() for future in futures]


def format_summary(results: list[ClienteResultado]) -> str:
    """Resumo em texto: uma linha por cliente e totais."""
    if not results:
        return "Nenhum cliente para processar."
    lines = ["", "=== Resumo da rotina ==="]
    for r in results:
        if r.status == "ok":
            extra = f" | {r.insights} insight(s)" if r.insights else ""
            lines.append(f"  OK    {r.slug:<24} {sum(r.linhas.values()):>6} linhas  {r.segundos:5.1f}s{extra}"
                         + (f"  ({r.mensagem})" if r.mensagem else ""))
        else:
            lines.append(f"  ERRO  {r.slug:<24} {r.mensagem}")
    failed = [r for r in results if r.status != "ok"]
    lines.append(f"\n{len(results) - len(failed)} de {len(results)} cliente(s) com sucesso.")
    if failed:
        lines.append("Com erro: " + ", ".join(r.slug for r in failed) + ". Os demais NÃO foram afetados.")
    return "\n".join(lines)


def all_ok(results: list[ClienteResultado]) -> bool:
    return all(r.status == "ok" for r in results)
