"""Verificação de acesso de cada cliente (primeira coisa a fazer ao cadastrar um cliente novo).

Faz uma consulta MÍNIMA (1 dia, 1 métrica) no GA4 e no Search Console do cliente. Se o cliente ainda não adicionou
o e-mail da conta de serviço como Leitor, a mensagem de erro do Google é traduzida e mostrada.
"""
from ga_project.analytics_client import fetch_report, last_n_days_range
from ga_project.clientes import Cliente
from ga_project.errors import GA4ProjectError
from ga_project.search_console import fetch_search_analytics, gsc_date_range


def check_ga4(ga4_client, property_id: str) -> tuple[bool, str]:
    start, end = last_n_days_range(1)
    try:
        fetch_report(ga4_client, property_id, ["date"], ["sessions"], start, end)
        return True, "OK"
    except GA4ProjectError as exc:
        return False, str(exc)


def check_gsc(service, site_url: str) -> tuple[bool, str]:
    start, end = gsc_date_range(1, 3)
    try:
        fetch_search_analytics(service, site_url, start, end, ["date"], max_rows=1)
        return True, "OK"
    except GA4ProjectError as exc:
        return False, str(exc)


def verify_cliente(cliente: Cliente, ga4_client, gsc_service_factory) -> dict:
    """{'ga4': (ok, mensagem) | None, 'gsc': (ok, mensagem) | None}. None = fonte não configurada para o cliente."""
    result = {"ga4": None, "gsc": None}
    if cliente.ga4_property_id:
        result["ga4"] = check_ga4(ga4_client, cliente.ga4_property_id)
    if cliente.gsc_site_url:
        result["gsc"] = check_gsc(gsc_service_factory(), cliente.gsc_site_url)
    return result


def format_access_report(results: dict[str, dict], service_email: str | None) -> str:
    lines = ["=== Acesso dos clientes ==="]
    pending = []
    for slug, res in results.items():
        parts = []
        for source, label in (("ga4", "GA4"), ("gsc", "Search Console")):
            value = res[source]
            parts.append(f"{label}: não configurado" if value is None else f"{label}: {'OK' if value[0] else 'SEM ACESSO'}")
            if value is not None and not value[0]:
                pending.append((slug, label, value[1]))
        lines.append(f"  {slug:<24} " + " | ".join(parts))
    if pending:
        lines.append("\nPendências:")
        lines += [f"  - {slug} ({label}): {message}" for slug, label, message in pending]
        if service_email:
            lines.append(f"\nPeça ao cliente para adicionar este e-mail como LEITOR no GA4 e no Search Console: {service_email}")
    else:
        lines.append("\nTodos os clientes verificados estão com acesso.")
    return "\n".join(lines)
