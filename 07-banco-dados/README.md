# ETAPA 07 — Banco de dados PostgreSQL (armazenamento permanente)

## Objetivo
Guardar os dados **para sempre** em um banco PostgreSQL. Hoje os CSVs são sobrescritos a cada coleta; o banco **acumula**.

## Como a permanência funciona
- **Gravar sem duplicar:** cada tabela tem uma chave (por exemplo, a data). Se a linha já existe, ela é **atualizada** (o GA4 corrige números recentes); se não existe, é inserida. Rodar duas vezes dá o mesmo resultado.
- **Nunca apagar:** nenhum comando do projeto faz `DELETE`. Quando a janela de 30 dias anda, os dias antigos continuam no banco.
- **Rastreável:** `criado_em` (quando a linha entrou) e `atualizado_em` (última correção), e a tabela `carga_log` registra cada carga.
- **Só fatos:** guardamos os dados coletados. Números derivados (como o cruzamento da etapa 06) são calculados depois, a partir das tabelas.

> **Importante:** o banco só acumula o que for gravado nele. Rode a coleta (etapas 02, 03, 05, 06) e a etapa 07 **pelo menos a cada 3 semanas**. Se passar de 30 dias sem coletar, os dias do intervalo ficam sem registro.

## Tabelas
| Tabela | Chave | Origem |
|---|---|---|
| `ga4_diario` | `data` | ETAPA 03 (usuários, sessões, páginas vistas, `sem_dados`) |
| `ga4_sessoes_canal` | `data` + `canal` + `origem` | ETAPA 06 (sessões por canal e origem) |
| `gsc_diario` | `data` | ETAPA 05 (cliques, impressões, CTR, posição) |
| `gsc_consulta_pagina` | período + `consulta` + `pagina` | ETAPA 05 (foto de cada período de 30 dias) |
| `carga_log` | (registro de cargas) | automático |

## Arquivos
| Arquivo | Função |
|---|---|
| `main.py` | Conecta, cria as tabelas, grava os CSVs e mostra um resumo. |
| `../src/ga_project/database.py` | Conexão, tabelas, upsert, resumo. |
| `../src/ga_project/carga.py` | Lê cada CSV e manda para a tabela certa. |
| `../tests/test_database.py` | Testes (usam SQLite em memória: não precisam de PostgreSQL). |

## Configuração (uma vez só)

### 1) Instalar o PostgreSQL no Windows
1. Baixe o instalador em postgresql.org → Download → Windows.
2. Na instalação, **anote a senha** do superusuário `postgres`; mantenha a porta `5432` e deixe marcadas as ferramentas de linha de comando.

### 2) Criar o banco e um usuário só para o projeto
Abra **SQL Shell (psql)** (instalado junto), aperte Enter nas perguntas de servidor/banco/porta/usuário, digite a senha do `postgres` e rode:

```sql
CREATE USER analytics_app WITH PASSWORD 'uma_senha_forte_aqui';
CREATE DATABASE analytics OWNER analytics_app;
```
Use uma senha forte e diferente da do `postgres`.

### 3) `.env`
Adicione ao seu `.env` (o modelo está no `.env.example`):
```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=analytics
DB_USER=analytics_app
DB_PASSWORD=uma_senha_forte_aqui
```
Não precisa tratar caracteres especiais na senha.

### 4) Dependência nova
```powershell
pip install -r requirements.txt
```
Se o `psycopg` falhar na instalação por causa da versão do Python, crie o `.venv` com um Python 3.12 ou 3.13.

### Banco na nuvem (em vez do seu PC)
Se preferir um PostgreSQL gerenciado, use a URL que o serviço fornece em `DATABASE_URL` no `.env` (ela tem prioridade sobre as linhas `DB_*`). O código é o mesmo.

## Como executar
```powershell
.venv\Scripts\Activate.ps1
python 07-banco-dados\main.py
pytest
```
Rode as etapas 03, 05 e 06 antes: a 07 lê os CSVs que elas geraram (CSV ausente = tabela pulada, com aviso).

## Saída esperada (valores ilustrativos)
```
Conectado ao PostgreSQL.
Tabelas conferidas/criadas.

Gravando os CSVs das etapas anteriores:
  ga4_diario: 30 linhas gravadas
  ga4_sessoes_canal: 60 linhas gravadas
  gsc_diario: 30 linhas gravadas
  gsc_consulta_pagina: 2 linhas gravadas

=== O que há no banco agora ===
             tabela  linhas primeira_data ultima_data
         ga4_diario      30    2026-09-09  2026-10-08
...
```
Rodando de novo: os números **não** mudam (não duplica).

## Consultas para conferir (pgAdmin ou psql)
```sql
SELECT COUNT(*), MIN(data), MAX(data) FROM ga4_diario;

SELECT g.data, g.sessoes, s.cliques, s.impressoes
FROM ga4_diario g JOIN gsc_diario s ON s.data = g.data
ORDER BY g.data DESC LIMIT 10;

SELECT * FROM carga_log ORDER BY executado_em DESC LIMIT 10;
```

## Backup (o que torna o banco realmente permanente)
Um banco só no seu PC se perde se o PC quebrar. Faça backup e **guarde uma cópia fora do computador** (HD externo ou nuvem). No PowerShell, na raiz do projeto (ajuste o número da versão do PostgreSQL):

```powershell
mkdir backups
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -h localhost -U analytics_app -d analytics -F c -f backups\analytics_2026-10-11.dump
```
Para restaurar: `pg_restore` (com a mesma pasta `bin`). A pasta `backups/` é ignorada pelo Git (os dumps contêm dados reais do negócio).

## Limitações
- **Esta versão foi testada com SQLite** (que entende o mesmo SQL de gravação). A conexão real com o PostgreSQL só é verificada na primeira execução na sua máquina.
- O relatório de consulta + página é uma **foto de cada período** (o Search Console, neste relatório, não separa por dia). Períodos que se sobrepõem geram linhas parecidas em fotos diferentes.
- `ga4_diario` guarda o relatório por data da etapa 03. Dimensões extras do GA4 (página, país, dispositivo) ainda não são coletadas.
- Não há coleta automática: você roda os scripts. Agendar a rotina (Agendador de Tarefas do Windows) pode ser uma etapa futura.
- URLs/consultas gigantes (mais de ~2.000 caracteres) podem ser recusadas pelo índice do PostgreSQL.
