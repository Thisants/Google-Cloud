# google-analytics-project

Projeto de análise de dados do Google Analytics 4 construído em etapas.

## Visão geral
```
Fontes Google (agora)            Camada analítica           Saídas
GA4  ───────────────┐
Search Console ─────┼──►  Analytics Agêntico  ──►  Oportunidades · Financeiro · Público · Riscos
Google Meu Negócio ─┘
```
Google Ads e Meta ficam **fora do escopo por enquanto**.

| Etapa | Status |
|---|---|
| 01 Conexão com GA4 | ✅ funcionando |
| 02 Coleta (30 dias → DataFrame + CSV) | ✅ concluída |
| 03 Tratamento (limpar e organizar o CSV) | ✅ concluída |
| 04 Análise (resumo, dia da semana, comparação) | ✅ concluída |
| 05 Search Console (coleta dos últimos 30 dias) | ✅ esta versão |
| 06 Integração de fontes (GA4 + Search Console) | ⏳ |
| 07 Banco de dados **PostgreSQL** (armazenamento permanente) | ⏳ |
| 08 a 12 (dashboard, insights, analytics agêntico, API, documentação) | ⏳ |

## Tecnologias
Python 3.11+ · google-analytics-data (GA4 Data API) · google-api-python-client (Search Console API) · pandas · python-dotenv · pytest

## Estrutura
```
google-analytics-project/
├── src/ga_project/          # código reutilizável (auth, config, coleta)
├── 01-conexao-google/       # etapa 01
├── 02-coleta-dados/         # etapa 02 (main.py, README, dados/)
├── 03-tratamento/           # etapa 03 (main.py, README, dados/)
├── 04-analise/              # etapa 04 (main.py, README, dados/)
├── 05-search-console/       # etapa 05 (main.py, README, dados/)
├── tests/
├── credenciais/             # JSON da Service Account (ignorado pelo Git)
├── .env.example · .gitignore · pyproject.toml · requirements.txt
```
> O código compartilhado fica em `src/ga_project/` porque Python não consegue importar de pastas como `01-conexao-google` (começam com número e têm hífen).

## Configuração
1. Google Cloud: projeto criado, **Google Analytics Data API** ativada, Service Account com chave JSON.
2. GA4 → Administrador → Acesso à propriedade: adicione o e-mail da Service Account como **Leitor**.
3. Salve o JSON em `credenciais/` (a pasta é ignorada pelo Git).
4. Copie `.env.example` para `.env` e preencha `GA4_PROPERTY_ID` e `GOOGLE_APPLICATION_CREDENTIALS`.
5. (Etapa 05) Ative a **Google Search Console API** no mesmo projeto, adicione o e-mail da Service Account como usuário na propriedade do Search Console e preencha `GSC_SITE_URL` no `.env`. Detalhes em `05-search-console/README.md`.

## Instalação (Windows / PowerShell no VS Code)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
Se o PowerShell bloquear a ativação: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Execução
```powershell
python 02-coleta-dados\main.py
python 03-tratamento\main.py
python 04-analise\main.py
python 05-search-console\main.py
pytest
```

## Segurança
- Nenhum segredo no código: tudo via `.env` + arquivo JSON local.
- `.gitignore` bloqueia `.env`, `credenciais/`, JSONs de credencial e CSVs/dados reais.
- Antes de cada commit: `git status` — nada de `.env`, `.json` de credencial ou CSV deve aparecer.
- Se a chave vazar: apague-a no Google Cloud e gere outra.

## Limitações
- Só 30 dias. GA4: apenas `date` + 3 métricas (as etapas 03 e 04 usam só esse relatório). Search Console: relatórios por data e por consulta + página.
- Os CSVs são sobrescritos a cada execução: o armazenamento permanente virá com o PostgreSQL (etapa 07).
- Sem dashboard.
- Dados do GA4 podem demorar até 24–48 h para estabilizar.
