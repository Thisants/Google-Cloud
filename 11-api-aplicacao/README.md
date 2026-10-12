# ETAPA 11 — API REST + rotina de atualização

Esta etapa tem duas partes:
- **A) API REST (FastAPI):** outros programas (um site, uma planilha, um app) consultam os dados do banco por HTTP. **Somente leitura.**
- **B) Rotina de atualização:** um comando que roda coleta → banco → insights, que você pode **agendar no Windows**. É ela que mantém o histórico crescendo sozinho.

---
## A) API REST

### Rotas
Todas, menos `/health`, exigem o cabeçalho `X-API-Key: <sua chave>`.

| Rota | O que devolve |
|---|---|
| `GET /health` | `{"status": "ok"}` (sem chave, sem dados) |
| `GET /v1/cobertura` | intervalo de datas do banco e últimas cargas |
| `GET /v1/resumo?inicio=AAAA-MM-DD&fim=AAAA-MM-DD` | KPIs do período com variação |
| `GET /v1/diario?inicio=...&fim=...` | métricas dia a dia (até 120 dias) |
| `GET /v1/canais?inicio=...&fim=...` | sessões por canal |
| `GET /v1/consultas?limite=20` | consultas e páginas do Search Console |
| `GET /v1/insights` | riscos e oportunidades (etapa 09) |
| `POST /v1/perguntar` | pergunta ao agente de IA (etapa 10). **Desligado por padrão** |

As rotas de dados reaproveitam as mesmas funções de leitura do agente da etapa 10: uma única fonte de verdade, com as mesmas validações.

### Segurança (leia)
- **Só este computador:** por padrão a API escuta em `127.0.0.1`. Outros computadores da rede **não** conseguem acessar. Se você mudar `API_HOST` para aceitar a rede, o programa avisa: a API **não tem HTTPS**, então a chave trafegaria sem criptografia.
- **Chave obrigatória:** sem a chave certa no cabeçalho, nada de dados (resposta 401, e o banco nem é aberto). A chave é comparada em tempo constante. A API **não sobe** sem `API_KEY` de pelo menos 24 caracteres.
- **A chave vai no cabeçalho, nunca na URL** (URLs aparecem em logs).
- **Somente leitura:** não existe rota que grave ou apague dados.
- **Erros sem vazamento:** se o banco cair, o cliente recebe só "Banco de dados indisponível" (503); o detalhe fica no log do servidor.
- **IA desligada por padrão** (`API_ENABLE_AGENT=false`), porque cada pergunta gera custo na Anthropic. Quando ligada, há **limite por hora** (padrão: 20) e a pergunta tem no máximo 1.000 caracteres.
- **Não existe login por usuário:** quem tem a chave acessa tudo. Não compartilhe a chave, e se vazar, gere outra e troque no `.env`.
- Não publique esta API na internet sem HTTPS e sem uma camada de proteção na frente (fora do escopo desta etapa).

### Configuração
1. Gere a chave: `python 11-api-aplicacao\main.py --gerar-chave`
2. Cole a linha `API_KEY=...` no `.env`. (Opcional: `API_ENABLE_AGENT=true` para ligar a IA; exige `ANTHROPIC_API_KEY`.)
3. Instale as dependências novas: `pip install -r requirements.txt`

### Como executar
```powershell
.venv\Scripts\Activate.ps1
python 11-api-aplicacao\main.py
```
Abra `http://127.0.0.1:8000/docs`: é a documentação interativa. Clique em **Authorize**, cole a chave e teste as rotas (inclusive o `POST /v1/perguntar`). `Ctrl+C` encerra.

Exemplos pelo PowerShell:
```powershell
$h = @{ "X-API-Key" = "COLE_SUA_CHAVE" }
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/cobertura" -Headers $h
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/resumo?inicio=2026-09-14&fim=2026-09-20" -Headers $h
```

### Códigos de resposta
| Código | Significado |
|---|---|
| 200 | deu certo |
| 400 | parâmetro inválido (ex.: data inicial depois da final, período maior que 120 dias) |
| 401 | chave ausente ou inválida |
| 403 | agente de IA desligado |
| 422 | formato inválido (ex.: data que não é AAAA-MM-DD) |
| 429 | limite de perguntas por hora atingido |
| 502 | falha ao consultar a IA |
| 503 | banco de dados indisponível |

---
## B) Rotina de atualização (agendável)

### O que faz
`python 11-api-aplicacao\atualizar_tudo.py` roda, **nesta ordem**: 02 coleta GA4 → 03 tratamento → 05 Search Console → 06 integração → 07 grava no PostgreSQL → 09 insights.
- **Se uma etapa falha, as seguintes não rodam** (para não gravar dados velhos como se fossem novos) e o programa sai com código 1.
- A etapa 10 (IA) fica de fora de propósito: ela tem custo.
- Tudo que aparece na tela também é gravado em `logs\atualizacao_AAAA-MM-DD.log`.
- `--so-banco` roda só 07 e 09 (usa os CSVs que já existem).

### Agendar no Windows (Agendador de Tarefas)
Os nomes dos menus podem variar um pouco.
1. Abra o **Agendador de Tarefas** → **Criar Tarefa Básica…**
2. Nome: `Atualizar analytics`. Gatilho: **Diariamente** (ou semanalmente), por exemplo às 07:00.
3. Ação: **Iniciar um programa**, com:
   - **Programa/script:** o caminho completo do Python do seu ambiente virtual, por exemplo `C:\...\Google Cloud\.venv\Scripts\python.exe`
   - **Adicione argumentos:** `11-api-aplicacao\atualizar_tudo.py`
   - **Iniciar em:** o caminho completo da pasta "Google Cloud"
4. Concluir. Depois, nas propriedades da tarefa, na aba **Configurações**, marque a opção de executar a tarefa o quanto antes **se uma execução agendada for perdida** (PC desligado no horário).
5. **Teste:** clique com o botão direito na tarefa → **Executar**, e confira `logs\atualizacao_AAAA-MM-DD.log`.

Requisitos: o computador ligado (ou ligado depois, com a opção do passo 4), o serviço do PostgreSQL rodando e o `.env` preenchido. **Frequência:** diária ou semanal; nunca mais espaçada que ~3 semanas, senão abrem buracos no histórico (a etapa 09 avisa se isso acontecer).

---
## Arquivos
| Arquivo | Função |
|---|---|
| `main.py` | Sobe a API (`--gerar-chave` cria uma chave forte). |
| `atualizar_tudo.py` | Roda a rotina de atualização e grava o log. |
| `../src/ga_project/api.py` | As rotas (FastAPI). |
| `../src/ga_project/api_core.py` | Configuração, comparação segura da chave e limite por hora (sem FastAPI). |
| `../src/ga_project/pipeline.py` | Ordem das etapas, parada na falha e resumo. |
| `../tests/test_api.py`, `test_api_core.py`, `test_pipeline.py` | Testes. |

## Limitações
- **A API foi testada sem o FastAPI real:** a lógica das rotas (chave, erros, limite) foi exercitada com um FastAPI simulado, e `tests/test_api.py` (que usa o `TestClient` de verdade) roda **na sua máquina** depois do `pip install -r requirements.txt`. É a primeira verificação do funcionamento real do FastAPI.
- Sem HTTPS, sem login por usuário e com uma única chave. O limite de perguntas fica em memória (zera quando a API reinicia).
- O servidor é o do uvicorn em modo simples: serve para uso pessoal/local, não para muito tráfego.
- A rotina depende de o computador estar ligado; não avisa por e-mail se falhar (veja o log e o histórico do Agendador).
