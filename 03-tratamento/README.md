# ETAPA 03 — Tratamento (limpar e organizar)

## Objetivo
Pegar o CSV bruto da ETAPA 02 e entregar um CSV **confiável e padronizado**, pronto para a análise (ETAPA 04).
Esta etapa **não precisa de internet nem de credencial**. Ela só lê e escreve arquivos locais.

| | Caminho |
|---|---|
| Entrada | `02-coleta-dados/dados/analytics_30_dias.csv` |
| Saída | `03-tratamento/dados/analytics_30_dias_tratado.csv` (ignorado pelo Git) |

## O que o tratamento faz
1. Confere se as colunas esperadas existem.
2. Converte tipos (data → data; métricas → número inteiro).
3. Remove linhas com data inválida; troca métrica inválida por 0.
4. Avisa sobre valores negativos (não altera).
5. Remove datas repetidas (mantém a última).
6. Ordena por data e cria os dias ausentes com 0.
7. Padroniza os nomes das colunas.
8. Adiciona `dia_semana` e `sem_dados`.

Cada correção feita aparece no **relatório de qualidade** impresso no terminal.

## Colunas da saída
| Coluna | Origem | Observação |
|---|---|---|
| `data` | `date` | tipo data |
| `dia_semana` | calculada | segunda … domingo |
| `usuarios_ativos` | `activeUsers` | inteiro |
| `sessoes` | `sessions` | inteiro |
| `visualizacoes_pagina` | `screenPageViews` | inteiro |
| `sem_dados` | calculada | `True` se o dia teve 0 em todas as métricas |

## Arquivos
| Arquivo | Função |
|---|---|
| `main.py` | Orquestra: lê o CSV bruto → trata → mostra relatório e tabela → salva. |
| `../src/ga_project/tratamento.py` | Funções de tratamento (reutilizáveis). |
| `../tests/test_tratamento.py` | Testes automáticos. |

## Funções (tratamento.py)
- `read_raw_csv(path)` → lê o CSV da etapa 02, com erro claro se faltar ou estiver vazio.
- `check_columns(df)` → confere as colunas esperadas.
- `clean(df)` → limpeza completa; devolve `(dados, avisos)`.
- `rename_columns(df)` → nomes padronizados.
- `add_calendar_columns(df)` → `dia_semana` e `sem_dados`.
- `treat(df_raw)` → pipeline completo (as quatro acima, em ordem).

## Como executar (Windows, terminal do VS Code, na raiz do projeto)
```powershell
.venv\Scripts\Activate.ps1
python 03-tratamento\main.py
pytest
```

## Saída esperada (valores ilustrativos)
```
CSV bruto lido: ...\02-coleta-dados\dados\analytics_30_dias.csv (30 linhas)

Relatório de qualidade:
  Nenhum problema encontrado.

      data dia_semana  usuarios_ativos  sessoes  visualizacoes_pagina  sem_dados
2026-08-31     segunda               48       60                   131      False
...
30 linhas | colunas: data, dia_semana, usuarios_ativos, sessoes, visualizacoes_pagina, sem_dados
CSV tratado salvo em: ...\03-tratamento\dados\analytics_30_dias_tratado.csv
```

## Limitações
- Trata só o relatório por data (`date` + 3 métricas). Outros relatórios terão regras próprias.
- Não detecta valores "estranhos" (picos, quedas): isso é análise (ETAPA 04).
- Não corrige dados negativos: apenas avisa.
