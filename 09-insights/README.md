# ETAPA 09 — Detecção de problemas e oportunidades

## Objetivo
Ler os dados do PostgreSQL e **apontar automaticamente** o que merece atenção, com o número que gerou cada alerta.
São **regras simples e explicáveis** (sem IA). A IA entra na ETAPA 10, em cima destes resultados.
Esta etapa só **lê** o banco (SELECT).

| Tipo | Significado |
|---|---|
| **risco** | algo que pede atenção (queda, falha de coleta, dependência de um canal) |
| **oportunidade** | onde um esforço pode render cliques a mais |
| **destaque** | boa notícia (crescimento, melhora de posição) |

Severidade: **alta**, **média** ou **baixa**. Nas oportunidades, depende de quantos cliques extras podem render.

## As 9 regras
| Regra | Tipo | Dispara quando |
|---|---|---|
| `queda_sessoes` / `alta_sessoes` | risco / destaque | sessões/dia dos últimos 7 dias vs 7 anteriores: queda ≥ 20% (média) ou ≥ 35% (alta); alta ≥ 20% |
| `queda_cliques` / `alta_cliques` | risco / destaque | cliques/dia no Search Console: queda ≥ 25% (média) ou ≥ 40% (alta); alta ≥ 25% |
| `piora_posicao` / `melhora_posicao` | risco / destaque | posição média (ponderada por impressões) piora ≥ 2 posições (média) ou ≥ 4 (alta); melhora ≥ 2 |
| `dias_sem_dados` | risco | dias com zero em tudo no GA4 nos últimos 14 dias (≥ 3 = alta): possível falha da tag ou da coleta |
| `lacuna_historico` | risco | datas sem nenhuma linha no banco (últimos 90 dias): a coleta não rodou a tempo |
| `dados_desatualizados` | risco | última data do banco a mais de 7 dias de hoje (> 14 = alta) |
| `concentracao_canal` | risco | um canal com ≥ 70% das sessões (≥ 85% = alta) |
| `ctr_baixo` | oportunidade | consulta na 1ª página (posição ≤ 10), com ≥ 100 impressões e CTR abaixo da referência da faixa |
| `quase_primeira_pagina` | oportunidade | consulta nas posições 11 a 20, com ≥ 100 impressões |

**Proteções contra alarme falso:** as tendências exigem pelo menos 5 dias com dados em cada janela e um volume mínimo (50 sessões ou 20 cliques no período anterior). Quando uma regra **não pode ser avaliada**, o relatório diz por quê, em vez de fingir que está tudo bem.

## Como ajustar os limites
Todos os números ficam no topo de `src/ga_project/insights.py` (`SESSOES`, `CLIQUES`, `POSICAO`, `CTR_ALVO` etc.). Edite, rode de novo e compare. Os valores atuais são um **ponto de partida**, não verdades absolutas.

## Arquivos
| Arquivo | Função |
|---|---|
| `main.py` | Conecta ao banco, roda as regras, mostra o relatório e salva o CSV. |
| `../src/ga_project/insights.py` | As regras e o relatório (reutilizável pela API e pelo agente nas próximas etapas). |
| `../tests/test_insights.py` | Testes das regras com dados fictícios. |
| `dados/insights.csv` | Resultado (gerado; ignorado pelo Git). |

## Funções (insights.py)
- `rule_sessions_trend`, `rule_clicks_trend`, `rule_position_trend` → tendências (7 dias vs 7 anteriores).
- `rule_days_without_data`, `rule_history_gaps`, `rule_stale_data` → qualidade e atualização dos dados.
- `rule_channel_concentration` → dependência de canal.
- `rule_low_ctr`, `rule_near_first_page` → oportunidades no Search Console.
- `generate_insights(conn, today)` → carrega o banco, roda tudo e devolve `(tabela_de_insights, avisos, última_data)`.
- `format_report(...)` → relatório em texto.

Cada regra devolve `(lista_de_insights, aviso)`.

## Colunas do `insights.csv`
`tipo`, `severidade`, `regra`, `titulo`, `detalhe`, `impacto` (variação em % ou cliques potenciais), `referencia` (período ou página), `gerado_em`.

## Como executar (Windows, terminal do VS Code, na raiz do projeto)
```powershell
.venv\Scripts\Activate.ps1
python 09-insights\main.py
pytest
```
Não há dependência nova nem configuração nova. O banco precisa ter dados (etapa 07).

## Saída esperada (valores ilustrativos)
```
Gerado em 11/10/2026 | dados do banco até 08/10/2026
Resumo: 1 risco(s), 2 oportunidade(s), 0 destaque(s)

=== RISCOS ===
[ALTA] Queda de sessões (-41%)
    Média de 45,0 sessões/dia contra 76,4 no período anterior.
    Referência: 02/10/2026 a 08/10/2026 vs 25/09/2026 a 01/10/2026

=== OPORTUNIDADES ===
[ALTA] CTR baixo para "tinta acrílica"
    1000 impressões na posição 2,0, mas CTR de 1,0% (referência mínima ~8%). Melhorar o título e a descrição de /tintas pode render cerca de 70 cliques a mais no período.
```

## Limitações
- **São regras, não diagnóstico.** Um alerta diz **onde olhar**, não **por quê** aconteceu.
- **Os limites são um ponto de partida.** Ajuste ao tamanho e à sazonalidade do seu negócio.
- **As referências de CTR por posição (8% / 4% / 2%) são aproximadas**, não são dados do Google.
- **Sazonalidade não é considerada:** a comparação é sempre contra os 7 dias anteriores.
- **Cobre Riscos e Oportunidades.** *Financeiro* depende de receita (o GA4 só traz se houver e-commerce ou eventos de compra) e *Público* depende de relatórios por país, cidade e dispositivo, que ainda não coletamos.
- Os insights **não são guardados no banco**: são recalculados a cada execução, a partir dos dados permanentes.
- Sem agendamento nem envio automático (e-mail, WhatsApp): você roda o script.
