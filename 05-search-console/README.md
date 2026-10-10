# ETAPA 05 — Coleta do Google Search Console

## Objetivo
Coletar os últimos 30 dias do Search Console (o que as pessoas buscam no Google e como o seu site aparece) e salvar em CSV.
Esta etapa **só coleta e organiza**; cruzar com o GA4 é a ETAPA 06.

| Relatório | Dimensões | Para que serve |
|---|---|---|
| Por data | `date` | tendência diária de cliques e impressões |
| Por consulta + página | `query`, `page` | quais buscas levam a quais páginas (base para encontrar oportunidades) |

Métricas: `clicks` (cliques), `impressions` (impressões), `ctr`, `position` (posição média).

## Configuração (uma vez só)
Os nomes dos menus do Google podem variar um pouco.

1. **Google Cloud** → APIs e serviços → Biblioteca → procure **Google Search Console API** → **Ativar** (no mesmo projeto do GA4).
2. **Search Console** (search.google.com/search-console) → escolha a propriedade do site → **Configurações** → **Usuários e permissões** → **Adicionar usuário**:
   - e-mail: o `client_email` do seu JSON (termina em `.iam.gserviceaccount.com`);
   - permissão: **Restrita** (só leitura, é suficiente).
3. No `.env`, preencha `GSC_SITE_URL` **exatamente como aparece no Search Console**:
   - propriedade de domínio: `sc-domain:exemplo.com.br`
   - prefixo de URL: `https://www.exemplo.com.br/` (com a barra final)
4. Reinstale as dependências (entrou uma nova): `pip install -r requirements.txt`

## Arquivos
| Arquivo | Função |
|---|---|
| `main.py` | Orquestra: configura → consulta os 2 relatórios → mostra → salva. |
| `../src/ga_project/search_console.py` | Toda a lógica do Search Console (reutilizável). |
| `../tests/test_search_console.py` | Testes automáticos (sem internet e sem credencial). |
| `dados/` | CSVs gerados (ignorados pelo Git). |

## Funções (search_console.py)
- `get_site_url()` → lê e valida `GSC_SITE_URL`.
- `gsc_date_range(n_days, lag_days)` → período dos últimos 30 dias, terminando 3 dias atrás.
- `create_gsc_service(credentials_path)` → cliente autenticado (somente leitura).
- `_execute_query(...)` → envia a consulta e traduz erros (403, 404, 400, 429) em mensagens claras.
- `rows_to_dataframe(rows, dimensions)` → resposta da API → DataFrame com tipos corretos.
- `fetch_search_analytics(...)` → consulta com **paginação** (a API devolve até 25.000 linhas por vez).
- `build_date_report(df, start, end)` → uma linha por dia; nomes padronizados.
- `build_query_page_report(df)` → ordena por cliques; nomes padronizados.

## Colunas dos CSVs
| Original (API) | Coluna final |
|---|---|
| `date` | `data` |
| `query` | `consulta` |
| `page` | `pagina` |
| `clicks` | `cliques` |
| `impressions` | `impressoes` |
| `ctr` | `ctr` (fração: 0,034 = 3,4%) |
| `position` | `posicao_media` (1 = topo) |

## Como executar (Windows, terminal do VS Code, na raiz do projeto)
```powershell
.venv\Scripts\Activate.ps1
python 05-search-console\main.py
pytest
```

## Saída esperada (valores ilustrativos)
```
Consultando Search Console (sc-domain:exemplo.com.br) de 2026-09-07 a 2026-10-06...

=== Por data ===
      data  cliques  impressoes    ctr  posicao_media
2026-09-07        4         110 0.0364            6.8
...
Total no período: 160 cliques | 4170 impressões

=== Top 10 consultas + páginas por cliques (de 3 linhas) ===
...
```

## Limitações
- **Atraso de dados:** o Search Console leva ~2-3 dias para consolidar; por isso o período termina 3 dias atrás.
- **Fuso:** as datas do Search Console seguem o horário do Pacífico (EUA), o GA4 segue o fuso da propriedade. Pode haver diferença de 1 dia ao cruzar (ETAPA 06).
- **Consultas anônimas:** o Google omite consultas raras do relatório por consulta; a soma das consultas fica **menor** que o total por data.
- **Dia sem impressões:** vira 0 cliques/0 impressões, com CTR e posição vazios.
- **Histórico:** o Search Console guarda só ~16 meses; por isso o banco permanente (ETAPA 07) é importante.
- Relatório por consulta + página limitado às 5.000 linhas com mais cliques.
