# ETAPA 02 — Coleta de dados do GA4 (últimos 30 dias)

## Objetivo
Consultar o GA4 e entregar os últimos 30 dias como **DataFrame** (mostrado no terminal) e como **CSV** em `dados/`.

| Item | Valor |
|---|---|
| Dimensão | `date` |
| Métricas | `activeUsers`, `sessions`, `screenPageViews` |
| Período | 30 dias completos, terminando **ontem** (hoje ainda está incompleto no GA4) |

## Arquivos
| Arquivo | Função |
|---|---|
| `main.py` | Ponto de entrada. Só orquestra: lê config → cria cliente → consulta → mostra → salva. Define DIMENSIONS/METRICS/DAYS no topo. |
| `../src/ga_project/analytics_client.py` | Toda a lógica de coleta e transformação (reutilizável nas próximas etapas). |
| `../src/ga_project/auth.py` | Cria o cliente autenticado (reaproveitado da etapa 01). |
| `../src/ga_project/config.py` | Lê `.env` e valida Property ID e credencial. |
| `../src/ga_project/errors.py` | Exceção própria (`GA4ProjectError`) para erros esperados. |
| `dados/analytics_30_dias.csv` | Resultado (gerado; **ignorado pelo Git**). |

## Funções (analytics_client.py)
- `last_n_days_range(n_days, today)` → calcula (início, fim). Fim = ontem.
- `build_request(...)` → monta o `RunReportRequest` (propriedade, dimensões, métricas, datas).
- `_run_report(client, request)` → envia ao GA4 e traduz erros (403, 400, 404, 401, 429) em mensagens claras.
- `response_to_dataframe(response)` → resposta da API → DataFrame; converte `date` para data e métricas para número; ordena por data.
- `fetch_report(...)` → função principal: build_request → _run_report → response_to_dataframe.
- `fill_missing_dates(df, start, end)` → o GA4 não retorna dias sem dados; esta função cria esses dias com 0.
- `save_csv(df, path)` → salva em CSV (`utf-8-sig`), criando a pasta se preciso.

## Como executar (Windows, terminal do VS Code, na raiz do projeto)
```powershell
.venv\Scripts\Activate.ps1
python 02-coleta-dados\main.py
```

## Saída esperada (valores ilustrativos)
```
Consultando GA4 (propriedade 123456789) de 2026-08-31 a 2026-09-29...

      date  activeUsers  sessions  screenPageViews
2026-08-31           48        60              131
2026-09-01           52        66              147
...
2026-09-29           52        66              147

30 linhas | colunas: date, activeUsers, sessions, screenPageViews
CSV salvo em: ...\02-coleta-dados\dados\analytics_30_dias.csv
```

## Testes
```powershell
pytest
```
Os testes usam uma resposta **falsa** da API: não precisam de internet nem de credencial.

## Limitações desta etapa
- Sem paginação (30 linhas cabem em uma página; a função avisa se houver mais).
- Datas calculadas no relógio do seu computador; se o fuso da propriedade GA4 for diferente, o último dia pode divergir.
- Dados recentes podem ser ajustados pelo GA4 nas 24–48 h seguintes.
- O CSV usa vírgula; no Excel em português pode ser necessário importar via *Dados > De Texto/CSV*.
