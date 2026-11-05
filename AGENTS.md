# Guia de trabalho — Game Promo Ranker

Estas instruções valem para todo o repositório e complementam as instruções globais do ambiente. Pessoas e agentes devem preservar contratos existentes, dados persistidos e alterações de outros colaboradores.

## Missão e leitura inicial

O produto ajuda a descobrir promoções e decidir com evidência: preço regional, avaliações, histórico, origem e validade. Também reúne lançamentos, jogos grátis, Epic, Game Pass, financiamento coletivo e eventos. Popularidade, desconto e score não comprovam qualidade absoluta; assinatura não equivale a compra.

Antes de alterar comportamento, leia [README.md](README.md), [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md) e a seção pertinente de [GUIDE.md](GUIDE.md). Confira o código e os testes quando houver divergência; corrija também o documento afetado. Estado de uma coleta, incidentes e evidências de uma publicação pertencem a registros de operação, não a este guia.

## Mapa do sistema

| Superfície | Responsabilidade / fonte de verdade |
| --- | --- |
| `app.py` | Flask, rotas `/api/*`, caminhos configuráveis por ambiente e `/healthz`; serve snapshots, sem coletar todo o catálogo em cada visita. |
| `static/index.html`, `static/app.js`, `static/styles.css` | Interface realmente servida por `/`; `static/discovery.js` e `static/releases.js` complementam as abas. O `index.html` da raiz não é servido por essa rota. |
| `static/motion.js`, `static/vendor/anime.umd.min.js` | Integração Anime.js, movimento reduzido e cancelamento. |
| `steam_sale_ranker.py`, `rerank_snapshot.py` | Coleta Steam, componentes do score e recálculo sem renovar a data da coleta. |
| `price_history_store.py`, `price_history_view.py` | Validação e escrita atômica do histórico; apresentação compartilhada nas APIs. |
| `steam_history_daily.py`, `steam_historical_import.py` | Preços atuais Steam Brasil e importação histórica Steam/BRL por appid exato. |
| `refresh_daily.py` | Ordem dos coletores, execução independente e `data/refresh_status.json`; consulte `JOBS` antes de adicionar uma fonte. |
| `discovery.py`, `catarse.py`, `steam_releases.py`, `free_games.py`, `epic_deals.py`, `gamepass*.py` | Coletores e enriquecimento de suas respectivas fontes; contratos e limites em `GUIDE.md`. |
| `test_*.py`, `tests/` | Testes `unittest` de domínio, coletores, APIs, histórico e release. |
| `Dockerfile`, `Dockerfile.gen`, `deploy/` | Aplicação Gunicorn e gerador separados; entrega e agendamento. |

Não crie banco, bundler ou framework para uma mudança que o modelo atual de snapshots resolve. Mudanças arquiteturais precisam de motivação e migração explícitas.

## Comandos locais

Execute na raiz. Python 3.12 é a base das imagens Docker; `requirements.txt` declara dependências diretas e `requirements.lock` fixa o ambiente reproduzível. No PowerShell:

```powershell
./scripts/bootstrap.ps1
./.venv/Scripts/python.exe app.py
```

Abra `http://localhost:8000`. Sem snapshots, APIs podem informar indisponibilidade; isso não autoriza inventar dados. O servidor local usa debug: não o exponha publicamente. Para gerar dados reais, os comandos abaixo acessam fontes externas e escrevem em `data/`; respeite limites e preserve o histórico existente:

```powershell
python refresh_daily.py --pages 20 --data-dir data
python steam_sale_ranker.py 20 --json data/games.json
python steam_history_daily.py --data-dir data
python steam_historical_import.py --json data/steam_price_history.json
python rerank_snapshot.py --file data/games.json
```

Nos comandos `python` seguintes ao setup, ative o ambiente ou use o executável dele. `--pages` é compatibilidade legada: não limita a coleta Steam às primeiras vinte páginas. Prefira o orquestrador para atualização completa. Não execute dois escritores sobre o mesmo diretório de dados; teste coletores com fixtures ou diretório temporário separado.

Verificação local sem coleta:

```powershell
python -m unittest discover
python verify_release.py
git diff --check
```

`./scripts/check.ps1` (Windows) e `./scripts/check.sh` (Linux/macOS) reúnem testes, contrato, sintaxe JavaScript e diff. `./deploy/ship.ps1 -NoDeploy` executa o mesmo gate usado antes da publicação. Todos preferem `.venv`; os scripts também aceitam `-Python` ou `GAMEPROMO_PYTHON`, conforme a plataforma. A publicação real continua restrita ao operador com preflight e SSH configurados. Para JS novo ou alterado fora da lista, execute também `node --check caminho/do/arquivo.js`. Verifique opções de ferramentas no código/`--help` antes de executá-las.

## Invariantes de produto e dados

- **Identidade e região:** compare a mesma edição, loja, país e moeda. Steam usa appid, Brasil e BRL; não associe `/sub/`, bundles ou nomes aproximados a reviews/preços de outro produto. Não converta mínima USD/CheapShark em histórico regional.
- **Ranking:** preserve score explicável e componentes separados. Fórmula e limiares ficam em `GUIDE.md`, `steam_sale_ranker.py` e `test_ranking.py`. Alterar pesos exige casos representativos, versão de score e revisão dos consumidores; filtros e modo cards/tabela preservam a ordenação escolhida e o ranking global padrão.
- **Persistência:** `data/steam_price_history.json` é persistente, com `games` observado e `historical` importado. Valores são centavos inteiros não negativos, com timestamps válidos e fuso. Mínimas nunca aumentam nem desaparecem quando o preço sobe, o jogo sai da lista ou uma fonte falha. Ausência/erro não vira zero; zero explícito é válido. Corrupção deve interromper a escrita, preservando o original. Use os validadores e escrita atômica existentes.
- **Origem do histórico:** uma observação não comprova mínima de todos os tempos. Importação externa só aceita Steam (`shop_id=61`), BR/BRL e appid exato; não fabrica observações diárias nem renova a cotação atual. Preserve proveniência, cobertura e datas. Caches observados e séries legados continuam distintos da cobertura externa.
- **Falha e validade:** coleta Steam vazia/incompleta não substitui o snapshot válido. Uma fonte falhar não impede as demais; o orquestrador registra falha e termina com erro. Não renove `generated_at` ao servir, filtrar ou recalcular ranking. Preços vencidos perdem selos/destaques conforme as janelas de cada fonte, mantendo aviso e histórico salvo.
- **UI:** cards e tabela mantêm a mesma semântica: roxo para baixa histórica verificada e amarelo até 10% acima dela, sujeitos à validade; primeiro registro observado não ganha esse destaque. Game Pass verde exige preço/catálogo/mensalidade válidos conforme `gamepass_view.py` e testes. Preserve favoritos, tema, filtros e preferências locais; ações devem atualizar a interface sem F5.
- **Movimento e acessibilidade:** use Anime.js na superfície alterada, respeite `prefers-reduced-motion`, foco e limpeza das instâncias. Preserve o estilo em funcionalidades/correções; redesign segue as instruções globais de concepção e aprovação visual. Valide a UI real no navegador integrado em desktop e 390 px.

## Segurança, Git e produção

Não versione snapshots privados, perfis, chaves Steam, credenciais SSH, logs com URLs sensíveis, `.venv` ou arquivos temporários. Revise `git status` e o diff: nem todo artefato sensível tem regra em `.gitignore`. Chave Steam opcional só deve transitar na consulta necessária; não a persista nem a reproduza em exemplos, logs ou links compartilhados. Valide dados externos e escape conteúdo inserido na UI.

Antes de editar, confirme checkout, branch, upstream e alterações alheias; não reverta ou faça stash delas para limpar o trabalho. Use branch de trabalho conforme o fluxo da tarefa. O bootstrap ativa `.githooks/pre-push`, que bloqueia o envio quando o gate local falha; não ignore, remova nem use `--no-verify` para contornar erro. Antes de publicar, integre o upstream sem reescrever histórico compartilhado e deixe mudanças revisadas e commitadas.

A entrega canônica é `./deploy/ship.ps1`; consulte o script e `GUIDE.md` para modos parciais. O wrapper executa preflight de produção, push e release remota com lock, verificação de revisão e imagens de rollback. Não substitua por comandos SSH/Compose avulsos. `.codex/release-contract.json`, `verify_release.py` e `tests/test_release_contract.py` são contratos executáveis: atualize-os junto de funcionalidade durável aceita, sem remover verificações para contornar falhas.

Preserve o volume `steam_data`. Deploy não autoriza apagar dados, remover volumes ou fazer limpeza destrutiva. Alteração de formato persistido exige backup restaurável, migração, validação e rollback. Uma release só está confirmada após revisão esperada, container saudável, `/healthz` público e contrato de dados frescos; execução bem-sucedida local não prova produção. Descubra configuração e rollback reais antes de operar fora do ambiente já cadastrado.

## Adicionar funcionalidades e concluir

1. Identifique fonte, schema, API, UI e persistência afetados; preserve compatibilidade ou descreva migração antes de implementá-la.
2. Para nova fonte, defina identidade, região, proveniência, cobertura, validade, limite de consultas e comportamento de falha. Integre `refresh_daily.JOBS`, imagem do gerador e entrega quando necessário.
3. Acrescente testes que provem comportamento e regressões reais no módulo correspondente, usando mocks/fixtures para serviços externos. Mudança documental pequena pede checagem de links/comandos, sem criar teste que replique texto.
4. Execute os checks pertinentes e o contrato de release; faça inspeção desktop/390 px quando houver UI. Atualize os guias e contratos afetados no mesmo conjunto de mudanças.
5. Informe resultado, comandos efetivamente executados, evidências e limites pendentes. Não declare coleta, teste visual ou publicação que não tenha observado.
