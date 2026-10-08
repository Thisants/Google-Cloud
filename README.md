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
| 03 Tratamento (limpar e organizar o CSV) | ✅ esta versão |
| 04 em diante | ⏳ não iniciadas |

## Tecnologias
Python 3.11 · google-analytics-data (GA4 Data API) · pandas · python-dotenv · pytest

## Estrutura
```
google-analytics-project/
├── src/ga_project/          # código reutilizável (auth, config, coleta)
├── 01-conexao-google/       # etapa 01
├── 02-coleta-dados/         # etapa 02 (main.py, README, dados/)
├── 03-tratamento/           # etapa 03 (main.py, README, dados/)
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
pytest
```

## Segurança
- Nenhum segredo no código: tudo via `.env` + arquivo JSON local.
- `.gitignore` bloqueia `.env`, `credenciais/`, JSONs de credencial e CSVs/dados reais.
- Antes de cada commit: `git status` — nada de `.env`, `.json` de credencial ou CSV deve aparecer.
- Se a chave vazar: apague-a no Google Cloud e gere outra.

## Limitações
- Só GA4, só 30 dias, só `date` + 3 métricas (a etapa 03 trata apenas esse relatório).
- Sem paginação, sem banco, sem dashboard.
- Dados do GA4 podem demorar até 24–48 h para estabilizar.
