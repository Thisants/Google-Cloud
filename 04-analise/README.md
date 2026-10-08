# ETAPA 04 — Análise descritiva

## Objetivo
Responder, com números, **o que aconteceu** nos últimos 30 dias: totais, médias, melhores e piores dias, padrão por dia da semana e comparação entre semanas.
Esta etapa **não precisa de internet nem de credencial do Google**.

| | Caminho |
|---|---|
| Entrada | `03-tratamento/dados/analytics_30_dias_tratado.csv` |
| Saída | `04-analise/dados/` (4 CSVs, ignorados pelo Git) |

## O que a análise faz
1. **Métricas derivadas:** `sessoes_por_usuario`, `paginas_por_sessao` e `media_movel_7d_sessoes`.
2. **Resumo por métrica:** total, média diária, máximo e mínimo (com a data).
3. **Média por dia da semana** (segunda … domingo).
4. **Comparação:** média diária dos últimos 7 dias vs os 7 dias anteriores, com variação em %.

## Regra importante: dias sem dados
Um dia com 0 em **todas** as métricas (`sem_dados = True`) é tratado como falha de coleta, não como "zero visitas".
Esses dias ficam **fora** das médias, máximos, mínimos e comparações. Se o seu site realmente pode ficar um dia inteiro sem acesso, essa regra precisa ser revista.

## Arquivos
| Arquivo | Função |
|---|---|
| `main.py` | Orquestra: lê o CSV tratado → analisa → mostra as tabelas → salva os CSVs. |
| `../src/ga_project/analise.py` | Funções de análise (reutilizáveis). |
| `../tests/test_analise.py` | Testes automáticos. |

## Funções (analise.py)
- `read_treated_csv(path)` → lê o CSV da etapa 03; erro claro se faltar ou estiver incompleto.
- `add_derived_metrics(df)` → métricas calculadas (divisão por zero vira vazio, nunca erro).
- `summarize(df)` → resumo por métrica.
- `by_weekday(df)` → média por dia da semana.
- `compare_periods(df, window=7)` → últimos 7 dias vs 7 anteriores; devolve `None` se houver menos de 14 dias.
- `analyze(df)` → roda tudo e devolve um dicionário com os resultados.

## Arquivos gerados em `04-analise/dados/`
| Arquivo | Conteúdo |
|---|---|
| `metricas_diarias.csv` | dados tratados + métricas derivadas |
| `resumo.csv` | resumo por métrica |
| `por_dia_semana.csv` | média por dia da semana |
| `comparacao_7_dias.csv` | últimos 7 dias vs anteriores |

## Como executar (Windows, terminal do VS Code, na raiz do projeto)
```powershell
.venv\Scripts\Activate.ps1
python 04-analise\main.py
pytest
```

## Saída esperada (valores ilustrativos)
```
Período analisado: 2026-08-31 a 2026-09-29 (30 dias)
Dias sem dados (fora das médias): 0

=== Resumo por métrica ===
             metrica  total  media_diaria  maximo data_maximo  minimo data_minimo
     usuarios_ativos   1478          51.0      72  2026-09-29      22  2026-09-13
...
=== Média diária: 2026-09-23 a 2026-09-29 (atual) vs 2026-09-16 a 2026-09-22 (anterior) ===
             metrica  media_anterior  media_atual variacao_pct
     usuarios_ativos            51.9         56.3        +8.5%
```

## Limitações
- Com 30 dias, cada dia da semana aparece só 4–5 vezes: o padrão semanal é uma **indicação**, não uma conclusão.
- Só 3 métricas e nenhuma dimensão (canal, página, país, dispositivo): não dá para dizer **por que** algo mudou.
- Não há detecção automática de problemas/oportunidades (ETAPA 09) nem gráficos (ETAPA 08).
- Sem teste estatístico: uma variação de +8% pode ser só oscilação normal.
