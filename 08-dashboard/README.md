# ETAPA 08 — Dashboard (Streamlit)

## Objetivo
Uma página no navegador, com filtros, mostrando os dados **que estão no PostgreSQL** (etapa 07): KPIs, gráficos, canais e consultas do Search Console.
O dashboard **só lê** o banco. Não grava e não apaga nada.

## Antes de começar
O banco precisa ter dados: rode a coleta (etapas 02, 03, 05, 06) e a etapa 07. Banco vazio mostra um aviso na tela.

## Arquivos
| Arquivo | Função |
|---|---|
| `app.py` | A tela (Streamlit): filtros, KPIs, abas e gráficos. |
| `../src/ga_project/dashboard_data.py` | Consultas ao banco, cálculo dos KPIs e formatação (tudo que não é tela). |
| `../tests/test_dashboard_data.py` | Testes dos cálculos e consultas (sem Streamlit e sem PostgreSQL). |

## Funções (dashboard_data.py)
- `fetch_df(conn, sql, params)` → executa um SELECT e devolve DataFrame.
- `load_date_range(conn)` → primeira e última data do banco.
- `load_daily(conn, inicio, fim)` → uma linha por dia: GA4 + sessões orgânicas do Google + Search Console.
- `load_channels(conn, inicio, fim)` → sessões por canal.
- `load_top_queries(conn, limite)` → melhores consultas + páginas da foto mais recente do Search Console.
- `load_last_loads(conn)` → data da última carga de cada tabela.
- `previous_period(inicio, fim)` e `pct_change(atual, anterior)` → período anterior e variação em %.
- `compute_kpis(atual, anterior)` → os 7 KPIs com a variação.
- `fmt_value(...)` e `fmt_delta(...)` → formatação brasileira (1.234,5).

## O que aparece na tela
- **Barra lateral:** filtro de período (padrão: últimos 30 dias do banco), botão **Atualizar dados** e o intervalo disponível.
- **KPIs:** sessões, sessões orgânicas do Google, usuários ativos (média por dia), páginas vistas, cliques, impressões e CTR. Cada um mostra a variação contra o período anterior de mesmo tamanho.
- **Abas:** Visão geral · Search Console · Canais · Consultas · Dados (com botão para baixar o CSV).

## Como ler os KPIs
- **Usuários ativos é uma média por dia**, não uma soma: somar usuários de dias diferentes contaria a mesma pessoa várias vezes.
- **A variação só aparece** quando o período anterior está completo (mesmo número de dias no banco). Se faltar, o campo fica vazio, para não enganar.
- **CTR** = cliques ÷ impressões do período; a variação é em pontos percentuais (pp).
- **Dias sem dados no GA4** (zero em tudo) ficam fora das médias, e a tela avisa quantos são.
- O Search Console tem atraso de ~3 dias: os últimos dias do período podem aparecer sem cliques e impressões.

## Como executar (Windows, terminal do VS Code, na raiz do projeto)
```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run 08-dashboard\app.py
pytest
```
O navegador abre em `http://localhost:8501`. Se o terminal pedir um e-mail na primeira vez, aperte Enter. Para encerrar, `Ctrl+C` no terminal.

## Problemas comuns
| Mensagem na tela / terminal | O que fazer |
|---|---|
| "Não consegui conectar ao PostgreSQL" | Confira se o PostgreSQL está ligado e os `DB_*` do `.env` (veja o README da etapa 07). |
| "O banco está vazio" | Rode as etapas de coleta e depois `python 07-banco-dados\main.py`. |
| Porta ocupada | `streamlit run 08-dashboard\app.py --server.port 8502` |
| `streamlit` não é reconhecido | O `.venv` não está ativo, ou faltou o `pip install -r requirements.txt`. |

## Segurança
- Roda **só no seu computador** (localhost). Não abra a porta para a internet: o dashboard mostra dados reais do negócio e não tem login.
- A senha do banco fica no `.env`, nunca na tela nem no código.

## Limitações
- Esta versão foi testada **sem Streamlit e sem PostgreSQL**: os cálculos e as consultas, com SQLite; a lógica da tela, com um Streamlit simulado. A aparência real só é vista rodando na sua máquina.
- Os dados se atualizam quando você roda a coleta e a etapa 07: o dashboard não coleta sozinho.
- Cruzamento só por data (por página fica para uma melhoria futura).
- Sem análise automática de problemas e oportunidades: isso é a ETAPA 09.
