# Game Promo Ranker

Aplicação Python/Flask para descobrir promoções Steam, campanhas de financiamento e eventos de jogos no Brasil.

- Aplicação: https://gamepromo.runictools.com/
- Repositório: https://github.com/runictools-com/game-promo-ranker

## Promoções Steam

O ranking global equilibra desconto, quantidade de reviews e percentual positivo:

```text
volume = 0.25 + 0.75 × min(1, log10(1 + reviews) / 5)
score = 10 × Wilson95³ × volume × (0.40 + 0.60 × desconto) × fator_histórico
```

`Wilson95` é o limite inferior de confiança da proporção de avaliações positivas. Ao cubo, exige boa aprovação para disputar o topo. O volume de reviews tem peso explícito e logarítmico, saturado em 100 mil: jogos muito jogados recebem mais peso sem crescimento ilimitado. A versão 4 impede que uma amostra mínima perfeita supere jogos muito avaliados e bem recebidos apenas por ter desconto maior. Não mede qualidade absoluta nem elimina manipulação de reviews. Entram jogos com pelo menos **100 avaliações** e **15% de desconto**.

O desconto usa uma fração entre 0 e 1. Quando existem pelo menos duas datas de preço BRL observado, o fator histórico é `0.90 + 0.10 × min(1, menor_observado / preço_atual)`. Sem histórico suficiente, o fator é neutro: `1`. Qualidade Wilson, oferta e componentes ficam separados no JSON.

A coleta percorre até o fim a ordenação da Steam Brasil que contém jogos avaliados em promoção. O JSON registra o total informado pela fonte, as páginas lidas e se o catálogo terminou; uma interrupção preserva o snapshot anterior. Produtos `/sub/` e bundles são rejeitados para não misturar preço de edição com avaliações do jogo base. Hentai e o descritor de conteúdo sexual adulto explícito são excluídos; conteúdo mature geral e nudez não são bloqueados indiscriminadamente.

Cards e tabela preservam o ranking global. Há busca por nome, gênero, recurso/categoria, tags da comunidade para incluir todas ou excluir qualquer uma, orçamento, desconto, avaliação e pérolas pouco conhecidas. Estas últimas exigem 100–4.999 avaliações e Wilson de pelo menos 0,85. Gostos, favoritos, tema e modo de exibição ficam no navegador. Gêneros, categorias e compatibilidade Steam Deck têm cache com validade de 30 dias e cobertura explícita.

### Histórico de preço

`steam_price_history.json` é o registro persistente unificado das mínimas Steam BRL, em centavos. Ele aparece nas promoções, nos jogos do Game Pass com Steam identificado e nos lançamentos que já têm preço. A primeira observação já mostra um valor, identificado como primeiro registro; somente um preço estritamente menor substitui a mínima. Aumento, igualdade, expiração do snapshot ou saída da lista não apagam a mínima.

`steam_history_daily.py` verifica diariamente todos os appids conhecidos, incluindo jogos fora das promoções e lançamentos ainda sem preço, por consultas em lotes à Steam Brasil. Ausência de preço ou falha da fonte nunca vira zero. Preço zero explícito é válido. O registro mantém início do acompanhamento, data da mínima quando conhecida e última consulta bem-sucedida. Falhas preservam o arquivo; corrupção é recusada para evitar perder registros. O cron executa a verificação mesmo se outro coletor falhar. Use `deploy/ship.ps1 -HistoryOnly` para publicar e executar apenas essa coleta.

O histórico novo é exclusivamente **observado na Steam Brasil em BRL**, em `observed_lows_br_app_v2.json` e `price_series_br_app_v2.json` (até 365 pontos). A primeira observação não recebe selo de recorde. Uma comparação só aparece com pelo menos duas datas conhecidas; não representa a mínima de todos os tempos. A série acompanha os preços coletados, sem garantir observação diária de cada jogo.

Valores antigos derivados de USD/CheapShark não são reutilizados como preços regionais. Não há conversão sintética nem comparação multi-loja baseada nesses valores. A aba Epic só compara valores BRL compatíveis com dados Steam recentes e títulos correspondentes.

Nas promoções Steam, cards e linhas ficam roxos quando o preço atual coincide com uma baixa histórica verificada e amarelos quando estão até 10% acima dela. O destaque não é aplicado ao primeiro valor apenas observado localmente, evitando apresentar uma observação recente como mínima de todos os tempos.

Falha ou coleta Steam vazia preserva o snapshot anterior e retorna erro ao orquestrador. Após 36 horas, a interface avisa que as ofertas podem ter vencido e retira os selos de preço. `NEW` significa novo no catálogo coletado em relação à geração anterior, não prova de início da promoção.

## Radar e agenda

### PC Game Pass e preço Steam

A aba mostra a mensalidade regular brasileira do PC Game Pass e o preço atual Steam dos títulos com correspondência exata de nome/edição. Cards verdes exigem preço BRL estritamente maior que um mês, preço e disponibilidade conferidos nas últimas 36 horas e mensalidade verificada nos últimos 30 dias. Preço desconhecido ou antigo não produz destaque. Compra Steam e acesso temporário pela assinatura são apresentados como opções distintas.

`gamepass_prices.py` verifica IDs ativos no catálogo Microsoft mesmo quando DisplayCatalog limita a atualização de títulos/capas. Reutiliza preços Steam recentes e consulta jogos restantes, com cache e limite de consultas; não compara edições diferentes por aproximação de nome. A coleta roda diariamente após o catálogo. `deploy/ship.ps1 -GamepassPricesOnly` publica e executa só essa atualização.

A aba de financiamento coleta diariamente amostras públicas de Meeplestarter, Gamefound, Kickstarter e Catarse. No Catarse, a categoria Jogos é filtrada por evidência de boardgame/jogo de cartas na própria campanha (texto ou link Ludopedia/BGG); RPG, jogos digitais, acessórios e late pledges são excluídos. Valores em centavos são convertidos para reais e o critério usa contribuidores reais, nunca seguidores. A cobertura é a amostra publicada na categoria, não todo o catálogo. Uma campanha precisa estar ativa, ter atingido a meta e reunir pelo menos 100 apoiadores no Brasil ou 300 internacionalmente. O score privilegia a quantidade de apoiadores e limita o efeito de metas simbólicas. Tração não comprova qualidade do jogo nem entrega futura. Frete, impostos, idioma e atendimento ao Brasil precisam ser conferidos na campanha.

O radar também separa jogos disponíveis do itch.io com avaliações suficientes; não os apresenta como campanhas. Fontes bloqueadas ou sem dados verificáveis aparecem com sua limitação. Campanhas e indies vencidos são ocultados até nova coleta.

A agenda combina eventos datados de curadoria com calendário público estruturado, mantendo fonte e validade. É possível filtrar estado, cidade, assunto e período. Datas sem hora respeitam o fim do dia brasileiro; informações antigas são sinalizadas. A cobertura é parcial: lista vazia não significa ausência de eventos na região.

## Lançamentos Steam

A aba consulta três listas: próximos por data, próximos populares e lançados recentemente. São até seis páginas de 100 resultados por lista, com deduplicação e cobertura informada. Datas vagas, como trimestre ou “em breve”, continuam imprecisas; não recebem dia inventado. A popularidade da lista de origem não é uma nota de qualidade para um jogo ainda não lançado.

Também permanecem as abas de jogos grátis, promoções Epic e catálogo Game Pass, sujeitas à disponibilidade de suas fontes.

## Perfil e privacidade

A consulta de wishlist pública não exige API key. Remover jogos já possuídos usa uma chave Steam opcional. O código da aplicação usa a chave somente na requisição e não a persiste; não salve URLs com chave nem as compartilhe. Favoritos e preferências são locais ao navegador, sem sincronização entre dispositivos. Perfis privados e restrições da Steam podem impedir a consulta.

## Executar e atualizar

```bash
python -m pip install -r requirements.txt
python refresh_daily.py --pages 20 --data-dir data
python app.py
```

O argumento `--pages` foi mantido por compatibilidade com os agendamentos existentes. O coletor principal percorre até o fim a ordenação de jogos avaliados em promoção informada pela Steam, em vez de limitar a lista às primeiras páginas. `refresh_daily.py` executa independentemente os coletores Steam, radar, lançamentos, grátis, Epic e Game Pass. Registra resultados em `data/refresh_status.json`; uma falha não interrompe as demais fontes, mas faz a execução terminar com erro. Agende esse comando diariamente no ambiente de execução. Flask serve os arquivos gerados; não busca todo o catálogo a cada visita.

Para atualizar somente Steam:

```bash
python steam_sale_ranker.py 20 --json data/games.json
```

## Validação e publicação

No ambiente Windows configurado, o caminho de entrega é:

```powershell
./deploy/ship.ps1 -NoDeploy  # testes, sintaxe JavaScript e diff
./deploy/ship.ps1            # exige alterações revisadas e commitadas
```

A entrega completa executa testes, preflight de produção, push, build da aplicação e do gerador, atualização dos coletores e verificações de saúde/revisão. O volume `steam_data` mantém os snapshots. O script preserva imagens identificadas para rollback e não remove volumes. A existência deste procedimento não indica que uma publicação já tenha ocorrido.

## Rotas

| Rota | Conteúdo |
|---|---|
| `GET /` | Aplicação |
| `GET /api/games` | Promoções Steam e componentes do ranking |
| `GET /api/discovery` | Campanhas, indies, eventos e cobertura |
| `GET /api/releases` | Lançamentos Steam |
| `GET /api/free-games` | Grátis atuais, próximos e histórico |
| `GET /api/epic-games` | Promoções Epic |
| `GET /api/gamepass` | Catálogo Game Pass |
| `GET /api/steam-user?profile=...&key=...` | Wishlist e biblioteca; chave opcional |
| `GET /healthz` | Saúde da aplicação |


### Baixa histórica Steam Brasil

`steam_historical_import.py` importa diariamente a mínima histórica Steam (loja 61), país BR e moeda BRL pelo endpoint público `prices/v2` do Augmented Steam/IsThereAnyDeal. AppIDs são exatos, sem busca por nomes. Lotes de 50 têm intervalo de 3 segundos; falhas interrompem a rodada preservando os lotes salvos. O arquivo persistente `data/steam_price_history.json` mantém valor, data, fonte e tentativas dos jogos sem cobertura. Importações nunca aumentam uma mínima salva; preços novos menores registrados pela Steam passam a ser a mínima. Cards e tabela mostram o histórico disponível mesmo quando a fonte cai; sem cobertura, indicam pendência em vez de inventar preço. O histórico externo complementa o histórico observado descrito acima.
