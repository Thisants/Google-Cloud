"""API REST (FastAPI) sobre os dados do banco (ETAPA 11). SOMENTE LEITURA.

Rotas (todas, menos /health, exigem o cabeçalho  X-API-Key: <sua chave>):
  GET  /health                 verificação de vida (sem chave)
  GET  /v1/cobertura           intervalo de datas e últimas cargas
  GET  /v1/resumo              KPIs de um período (inicio, fim)
  GET  /v1/diario              métricas dia a dia (inicio, fim)
  GET  /v1/canais              sessões por canal (inicio, fim)
  GET  /v1/consultas           consultas e páginas do Search Console (limite)
  GET  /v1/insights            riscos e oportunidades (ETAPA 09)
  POST /v1/perguntar           pergunta ao agente de IA (ETAPA 10; desligado por padrão e com limite por hora)

Reaproveita as MESMAS funções de leitura do agente (agent_tools): uma única fonte de verdade.
A chave vai no cabeçalho, nunca na URL (URLs aparecem em logs).
"""
import json
import logging
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from ga_project.agent import Agent, create_client, load_agent_settings
from ga_project.agent_tools import MAX_QUERIES, execute_tool
from ga_project.api_core import ApiSettings, RateLimiter, keys_match
from ga_project.database import connect
from ga_project.errors import GA4ProjectError

logger = logging.getLogger("ga_project.api")


class PerguntaIn(BaseModel):
    pergunta: str = Field(min_length=3, max_length=1000, description="Pergunta em português sobre os dados.")


def create_app(settings: ApiSettings, connect_fn=connect, agent_factory=None) -> FastAPI:
    """Monta a aplicação. connect_fn e agent_factory podem ser trocados nos testes."""
    app = FastAPI(
        title="API de Analytics (GA4 + Search Console)",
        version="1.0.0",
        description="Dados do PostgreSQL em modo somente leitura. Envie a chave no cabeçalho X-API-Key.",
    )
    key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Valor de API_KEY do .env")
    limiter = RateLimiter(settings.agent_max_per_hour)

    if agent_factory is None and settings.enable_agent:
        agent_settings = load_agent_settings()          # falha logo na partida se faltar a chave da Anthropic

        def agent_factory(conn):
            return Agent(create_client(agent_settings), conn, model=agent_settings.model,
                         allow_queries=settings.allow_queries)

    # ---- dependências ----
    def require_key(provided: Optional[str] = Security(key_header)) -> None:
        if not keys_match(provided, settings.api_key):
            raise HTTPException(status_code=401, detail="Chave de API ausente ou inválida.",
                                headers={"WWW-Authenticate": "ApiKey"})

    def get_conn():
        try:
            conn = connect_fn()
        except GA4ProjectError:
            logger.exception("Falha ao conectar ao banco")      # o detalhe fica só no log do servidor
            raise HTTPException(status_code=503, detail="Banco de dados indisponível.")
        try:
            yield conn
        finally:
            conn.close()

    def call_tool(name: str, args: dict, conn) -> dict:
        try:
            return json.loads(execute_tool(name, args, conn, True, date.today()))
        except GA4ProjectError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception:
            logger.exception("Erro na consulta %s", name)
            raise HTTPException(status_code=500, detail="Erro interno ao consultar os dados.")

    protected = [Depends(require_key)]

    # ---- rotas ----
    @app.get("/health", tags=["Sistema"])
    def health():
        return {"status": "ok"}

    @app.get("/v1/cobertura", dependencies=protected, tags=["Dados"])
    def cobertura(conn=Depends(get_conn)):
        return call_tool("get_data_coverage", {}, conn)

    @app.get("/v1/resumo", dependencies=protected, tags=["Dados"])
    def resumo(inicio: date = Query(..., description="AAAA-MM-DD"), fim: date = Query(..., description="AAAA-MM-DD"),
               conn=Depends(get_conn)):
        return call_tool("get_period_summary", {"inicio": inicio.isoformat(), "fim": fim.isoformat()}, conn)

    @app.get("/v1/diario", dependencies=protected, tags=["Dados"])
    def diario(inicio: date = Query(..., description="AAAA-MM-DD"), fim: date = Query(..., description="AAAA-MM-DD"),
               conn=Depends(get_conn)):
        return call_tool("get_daily_metrics", {"inicio": inicio.isoformat(), "fim": fim.isoformat()}, conn)

    @app.get("/v1/canais", dependencies=protected, tags=["Dados"])
    def canais(inicio: date = Query(..., description="AAAA-MM-DD"), fim: date = Query(..., description="AAAA-MM-DD"),
               conn=Depends(get_conn)):
        return call_tool("get_channel_breakdown", {"inicio": inicio.isoformat(), "fim": fim.isoformat()}, conn)

    @app.get("/v1/consultas", dependencies=protected, tags=["Dados"])
    def consultas(limite: int = Query(20, ge=1, le=MAX_QUERIES), conn=Depends(get_conn)):
        return call_tool("get_top_queries", {"limite": limite}, conn)

    @app.get("/v1/insights", dependencies=protected, tags=["Dados"])
    def insights(conn=Depends(get_conn)):
        return call_tool("get_insights", {}, conn)

    @app.post("/v1/perguntar", dependencies=protected, tags=["IA"])
    def perguntar(body: PerguntaIn, conn=Depends(get_conn)):
        if not settings.enable_agent:
            raise HTTPException(status_code=403, detail="Agente de IA desativado (API_ENABLE_AGENT=false no .env).")
        if not limiter.allow():
            raise HTTPException(status_code=429,
                                detail=f"Limite de {settings.agent_max_per_hour} perguntas por hora atingido.")
        agent = agent_factory(conn)                       # um agente novo por pergunta: sem memória compartilhada
        try:
            answer = agent.ask(body.pergunta)
        except GA4ProjectError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        return {
            "resposta": answer,
            "uso": {"tokens_entrada": agent.input_tokens, "tokens_saida": agent.output_tokens,
                    "ferramentas": agent.tool_calls},
        }

    return app
