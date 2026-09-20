# Game Promo Ranker · manutenção

[← README](../README.md)

## Fluxo de mudança

1. Identifique o componente na tabela de arquitetura do README.
2. Confirme o contrato nos arquivos de entrada e manifests; documentação não substitui o código.
3. Faça a alteração em um branch, preservando dados locais e arquivos de origem.
4. Execute as verificações relacionadas ao fluxo e revise `git diff --check`.
5. Descreva evidências e limites; publicar documentação não equivale a publicar uma aplicação.

## Contrato de dados

Snapshots e histórico vivem em `data/`. Agende `refresh_daily.py` no ambiente de execução; abrir a página não executa todo o catálogo. Uma primeira observação local não comprova a mínima histórica. Wishlist pública pode ser consultada sem chave; biblioteca possuída usa chave Steam opcional, que não deve ser salva em URLs compartilhadas.

## Execução e distribuição

Abra http://localhost:8000. A coleta acessa serviços externos e pode demorar ou falhar parcialmente. O servidor de desenvolvimento usa debug e não deve ser exposto à internet.

O início rápido descreve desenvolvimento local. Antes de expor o serviço, revise a configuração de hospedagem específica do repositório, permissões, persistência e procedimento de atualização. Segredos e dados de usuários não pertencem aos exemplos nem ao Git.

## Diagnóstico inicial

| Sintoma | Primeiro ponto a conferir |
| --- | --- |
| Promoção vencida ainda aparece | Confira generated_at, data/refresh_status.json e a janela de validade; uma falha preserva o último snapshot. |
| Histórico não mostra recorde | Uma única observação não comprova mínima histórica. Confira região BRL, edição e fonte da comparação. |
| Uma fonte falhou | refresh_daily.py registra resultados independentes; investigue a fonte sem apagar os demais snapshots. |

## Limites de interpretação

Fontes podem restringir consultas ou publicar dados incompletos. O ranking não mede qualidade absoluta. Compare apenas a mesma edição, região e moeda; assinaturas são acesso temporário, não compra. O guia técnico detalha as janelas de validade e a diferença entre preços observados e históricos.

## Registro da interface de promoções

A recuperação de setembro de 2026 preservou a composição existente e restaurou a semântica visual: roxo identifica preço na baixa histórica e amarelo identifica preço até 10% acima dela. O primeiro preenchimento útil dos resultados usa Anime.js 4.5.0; a animação é cancelável, não se repete em atualizações de fundo e vira feedback imediato quando `prefers-reduced-motion` está ativo. A produção foi conferida em 1440 px e 390 px, sem rolagem horizontal, com filtros, cards e tabela preservados.

## Base desta documentação

A apresentação foi confrontada com os seguintes arquivos e diretórios do checkout. Essa revisão foi estática; não executou o produto, coletores, instalações ou deploys.

- [app.py](../app.py) — Rotas Flask e leitura dos snapshots.
- [refresh_daily.py](../refresh_daily.py) — Orquestra coletores e registra a situação de cada fonte.
- [steam_sale_ranker.py](../steam_sale_ranker.py) — Coleta e pontuação das promoções Steam.
- [price_history_store.py](../price_history_store.py) — Persistência do histórico de preços.
- [index.html](../index.html) — Interface; complementada por static/.
- [deploy/ship.ps1](../deploy/ship.ps1) — Entrega orquestrada; não necessária para leitura local.
