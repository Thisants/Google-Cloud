"""API REST multi-cliente (FastAPI) lendo do PostgreSQL. SOMENTE LEITURA.

Como a segurança funciona:
  - cada chave (cabeçalho X-API-Key) pertence a UM cliente ou é de administrador; o banco guarda só o hash;
  - chave de cliente só enxerga o PRÓPRIO cliente (qualquer outro slug responde 404, como se não existisse);
  - só a chave de administrador vê a carteira (todos os clientes);
  - pedido sem chave no formato certo é recusado SEM abrir conexão com o banco;
  - limite de pedidos por minuto POR CHAVE (um cliente barulhento não atrapalha os outros);
  - respostas de listas são paginadas (o tamanho da resposta não cresce com a carteira);
  - a API pode (e deve) conectar com um usuário do PostgreSQL só com SELECT (API_DB_USER / API_DB_PASSWORD).
"""
import json
import logging
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from ga_project.agent import Agent, create_client, load_agent_settings
from ga_project.agent_tools import MAX_QUERIES, _records, execute_tool
from ga_project.api_core import MAX_PAGE, ApiSettings, LimiterRegistry, can_access
from ga_project.apikeys import looks_like_key, verify_key
from ga_project.clientes import Cliente, count_clientes, get_cliente, list_clientes
from ga_project.dashboard_data import load_carteira
from ga_project.database import connect
from ga_project.errors import GA4ProjectError
from ga_project.insights import load_saved_insights

logger = logging.getLogger("ga_project.api")


class PerguntaIn(BaseModel):
    pergunta: str = Field(..., min_length=3, max_length=1000, description="Pergunta sobre os dados do cliente.")


def _cliente_dict(c: Cliente) -> dict:
    return {"slug": c.slug, "nome": c.nome, "ativo": c.ativo, "ga4_property_id": c.ga4_property_id,
            "gsc_site_url": c.gsc_site_url, "enviar_consultas_ia": c.enviar_consultas_ia}


def _default_agent_factory(settings_for_agent=None):
    def factory(conn, cliente: Cliente, allow_queries: bool):
        s = load_agent_settings()
        return Agent(create_client(s), conn, cliente_id=cliente.slug, cliente_nome=cliente.nome, model=s.model,
                     allow_queries=allow_queries)
    return factory


def create_app(settings: ApiSettings, connect_fn=None, agent_factory=None, today_fn=date.today) -> FastAPI:
    connect_fn = connect_fn or (lambda: connect("api"))
    agent_factory = agent_factory or _default_agent_factory()
    request_limits = LimiterRegistry(settings.requests_per_minute, 60)
    agent_limits = LimiterRegistry(settings.agent_max_per_hour, 3600)

    app = FastAPI(title="Analytics multi-cliente (GA4 + Search Console)", version="2.0",
                  docs_url="/docs" if settings.docs else None, redoc_url=None,
                  openapi_url="/openapi.json" if settings.docs else None)
    key_header = APIKeyHeader(name="X-API-Key", auto_error=False,
                              description="Chave da API (criada com gerenciar_clientes.py key-add).")

    # ---------- autenticação ----------
    def auth_ctx(provided: Optional[str] = Security(key_header)):
        """Valida a chave e entrega (conexão, dono da chave). Uma conexão por pedido, fechada no fim."""
        if not looks_like_key(provided):                         # lixo é descartado sem tocar no banco
            raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.",
                                headers={"WWW-Authenticate": "ApiKey"})
        try:
            conn = connect_fn()
        except GA4ProjectError:
            logger.exception("Falha ao conectar ao banco")        # o detalhe vai só para o log do servidor
            raise HTTPException(status_code=503, detail="Banco de dados indisponível.")
        try:
            info = verify_key(conn, provided)
            if info is None:
                raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.",
                                    headers={"WWW-Authenticate": "ApiKey"})
            if not request_limits.allow(info.id):
                raise HTTPException(status_code=429, detail="Limite de pedidos por minuto atingido.",
                                    headers={"Retry-After": "60"})
            yield conn, info
        finally:
            conn.close()

    def admin_ctx(ctx=Depends(auth_ctx)):
        if ctx[1].papel != "admin":
            raise HTTPException(status_code=403, detail="Somente chaves de administrador.")
        return ctx

    def scoped(slug: str, ctx=Depends(auth_ctx)):
        """Garante que a chave pode ver ESTE cliente. Outro cliente = 404 (não revela que ele existe)."""
        conn, info = ctx
        if not can_access(info, slug):
            raise HTTPException(status_code=404, detail="Cliente não encontrado.")
        try:
            cliente = get_cliente(conn, slug)
        except GA4ProjectError:
            raise HTTPException(status_code=404, detail="Cliente não encontrado.")
        return conn, info, cliente

    def call_tool(name: str, args: dict, conn, slug: str) -> dict:
        try:
            return json.loads(execute_tool(name, args, conn, True, today_fn(), cliente_id=slug))
        except GA4ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            logger.exception("Erro ao consultar os dados do cliente %s", slug)
            raise HTTPException(status_code=500, detail="Erro interno ao consultar os dados.")

    # ---------- sistema e conta ----------
    @app.get("/health", tags=["Sistema"])
    def health():
        return {"status": "ok"}

    @app.get("/v1/me", tags=["Conta"])
    def me(ctx=Depends(auth_ctx)):
        _, info = ctx
        return {"chave": info.id, "papel": info.papel, "cliente": info.cliente_id, "nome": info.nome}

    @app.get("/v1/clientes", tags=["Conta"])
    def clientes(limite: int = Query(50, ge=1, le=MAX_PAGE), offset: int = Query(0, ge=0), ctx=Depends(auth_ctx)):
        conn, info = ctx
        if info.papel == "admin":
            items, total = list_clientes(conn, limit=limite, offset=offset), count_clientes(conn)
        else:
            items, total = [get_cliente(conn, info.cliente_id)], 1
        return {"total": total, "limite": limite, "offset": offset, "clientes": [_cliente_dict(c) for c in items]}

    @app.get("/v1/carteira", tags=["Administração"])
    def carteira(limite: int = Query(50, ge=1, le=MAX_PAGE), offset: int = Query(0, ge=0), ctx=Depends(admin_ctx)):
        """Visão geral dos clientes ATIVOS (tráfego, riscos, última rodada). Paginada."""
        conn, _ = ctx
        items = list_clientes(conn, only_active=True, limit=limite, offset=offset)
        rows = _records(load_carteira(conn, [c.slug for c in items], today_fn()))
        names = {c.slug: c.nome for c in items}
        for row in rows:
            row["nome"] = names.get(row["cliente_id"])
        return {"total": count_clientes(conn, only_active=True), "limite": limite, "offset": offset, "clientes": rows}

    # ---------- dados de UM cliente ----------
    @app.get("/v1/clientes/{slug}/cobertura", tags=["Dados"])
    def cobertura(slug: str, sc=Depends(scoped)):
        return call_tool("get_data_coverage", {}, sc[0], slug)

    @app.get("/v1/clientes/{slug}/resumo", tags=["Dados"])
    def resumo(slug: str, inicio: date = Query(..., description="AAAA-MM-DD"), fim: date = Query(..., description="AAAA-MM-DD"),
               sc=Depends(scoped)):
        return call_tool("get_period_summary", {"inicio": inicio.isoformat(), "fim": fim.isoformat()}, sc[0], slug)

    @app.get("/v1/clientes/{slug}/diario", tags=["Dados"])
    def diario(slug: str, inicio: date = Query(..., description="AAAA-MM-DD"), fim: date = Query(..., description="AAAA-MM-DD"),
               sc=Depends(scoped)):
        return call_tool("get_daily_metrics", {"inicio": inicio.isoformat(), "fim": fim.isoformat()}, sc[0], slug)

    @app.get("/v1/clientes/{slug}/canais", tags=["Dados"])
    def canais(slug: str, inicio: date = Query(..., description="AAAA-MM-DD"), fim: date = Query(..., description="AAAA-MM-DD"),
               sc=Depends(scoped)):
        return call_tool("get_channel_breakdown", {"inicio": inicio.isoformat(), "fim": fim.isoformat()}, sc[0], slug)

    @app.get("/v1/clientes/{slug}/consultas", tags=["Dados"])
    def consultas(slug: str, limite: int = Query(20, ge=1, le=MAX_QUERIES), sc=Depends(scoped)):
        return call_tool("get_top_queries", {"limite": limite}, sc[0], slug)

    @app.get("/v1/clientes/{slug}/insights", tags=["Dados"])
    def insights(slug: str, sc=Depends(scoped)):
        """Insights já calculados pela rotina (leitura rápida; não recalcula)."""
        conn, _, cliente = sc
        df = load_saved_insights(conn, cliente.slug)
        generated = None if df.empty else str(df["gerado_em"].iloc[0])
        items = [] if df.empty else _records(df.drop(columns=["gerado_em"]))
        return {"cliente": cliente.slug, "gerado_em": generated, "insights": items}

    # ---------- IA (desligada por padrão) ----------
    @app.post("/v1/clientes/{slug}/perguntar", tags=["IA"])
    def perguntar(slug: str, body: PerguntaIn, sc=Depends(scoped)):
        conn, info, cliente = sc
        if not settings.enable_agent:
            raise HTTPException(status_code=403, detail="Agente de IA desativado (API_ENABLE_AGENT=false no .env).")
        if not agent_limits.allow(info.id):
            raise HTTPException(status_code=429, detail=f"Limite de {settings.agent_max_per_hour} perguntas por hora atingido.",
                                headers={"Retry-After": "3600"})
        allow_queries = settings.allow_queries and cliente.enviar_consultas_ia      # privacidade POR CLIENTE
        try:
            agent = agent_factory(conn, cliente, allow_queries)
        except GA4ProjectError:
            logger.exception("IA não configurada")
            raise HTTPException(status_code=503, detail="IA não configurada no servidor.")
        try:
            answer = agent.ask(body.pergunta)
        except GA4ProjectError as exc:
            raise HTTPException(status_code=502, detail=f"Falha ao consultar a IA: {exc}")
        return {"cliente": cliente.slug, "resposta": answer,
                "uso": {"tokens_entrada": agent.input_tokens, "tokens_saida": agent.output_tokens,
                        "ferramentas": agent.tool_calls}}

    return app
