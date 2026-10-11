# ETAPA 06 — Integração GA4 + Search Console

## Objetivo
Cruzar as duas fontes **pela data** e responder: *quando o Google me mostra mais, chega mais gente pelo Google?*

| Fonte | O que mede | Coluna no cruzamento |
|---|---|---|
| Search Console | pessoas que **clicaram** no seu resultado do Google | `gsc_cliques` |
| GA4 | **sessões** que chegaram por busca orgânica do Google | `ga4_sessoes_organicas_google` |

## Entradas e saídas
| | Caminho |
|---|---|
| Entrada 1 (ao vivo) | GA4: sessões por data × canal × origem (usa a credencial) |
| Entrada 2 | `05-search-console/dados/gsc_30_dias_por_data.csv` (gerado pela ETAPA 05) |
| Saída | `06-integracao-fontes/dados/` (3 CSVs, ignorados pelo Git) |

**Rode a ETAPA 05 e a ETAPA 06 no mesmo dia**, para os dois cobrirem o mesmo período (30 dias, terminando 3 dias atrás).

## Arquivos gerados
| Arquivo | Conteúdo |
|---|---|
| `ga4_sessoes_por_canal_30_dias.csv` | GA4 bruto padronizado: `data`, `canal`, `origem`, `sessoes` |
| `integrado_por_data.csv` | uma linha por dia com GA4 + Search Console lado a lado |
| `indicadores_integracao.csv` | totais, proporções e correlações do período |

## Colunas do `integrado_por_data.csv`
| Coluna | Significado |
|---|---|
| `ga4_sessoes_total` | todas as sessões do dia (todos os canais) |
| `ga4_sessoes_organicas_google` | sessões do canal "Organic Search" com origem "google" |
| `gsc_cliques`, `gsc_impressoes`, `gsc_ctr`, `gsc_posicao_media` | Search Console |
| `pct_organico_google` | % das sessões que vieram da busca orgânica do Google |
| `sessoes_por_clique` | sessões orgânicas do GA4 ÷ cliques do Search Console |

## Funções (integracao.py)
- `rename_ga4_channels(df)` → nomes padronizados do relatório bruto.
- `summarize_ga4_by_date(df, start, end)` → uma linha por dia; dia sem sessões vira 0.
- `channel_totals(df)` → sessões e % por canal.
- `read_gsc_by_date_csv(path)` → lê o CSV da ETAPA 05 (erro claro se faltar).
- `merge_sources(ga4_daily, gsc_daily)` → junta pela data (só dias nas duas fontes) e calcula as colunas derivadas.
- `integration_summary(merged)` → indicadores do período.

## Como executar (Windows, terminal do VS Code, na raiz do projeto)
```powershell
.venv\Scripts\Activate.ps1
python 05-search-console\main.py
python 06-integracao-fontes\main.py
pytest
```
Não há nova configuração nem nova dependência.

## Como ler os indicadores
- `pct_sessoes_organicas_google`: quanto do seu tráfego depende da busca do Google.
- `sessoes_organicas_por_clique`: perto de 1 é o esperado. Muito **abaixo de 1** pode indicar sessões não registradas no GA4 (consentimento de cookies, bloqueadores). Muito **acima de 1** pede investigação (por exemplo, contagens diferentes ou fuso de datas).
- `correlacao_*`: de -1 a 1. Perto de 1 = sobem e descem juntos. Com ~30 dias é só um **indicador**, não prova de causa.

## Limitações
- **Cruzamento só por data.** Cruzar por **página** (qual página ganhou visitas por qual busca) exige um novo relatório do GA4 por página de entrada e normalizar as URLs. Fica para uma próxima melhoria.
- **Fuso:** Search Console usa o horário do Pacífico (EUA); o GA4 usa o fuso da propriedade. Pode haver deslocamento de 1 dia.
- **Dia zerado no GA4:** não dá para distinguir "zero visitas" de falha de coleta; esses dias distorcem as correlações.
- **Orgânico = Google:** só contamos origem "google". Outros buscadores (Bing etc.) entram no total, mas não no orgânico do Google.
- Os valores do GA4 e do Search Console **nunca batem exatamente**; observe tendência e proporção.
