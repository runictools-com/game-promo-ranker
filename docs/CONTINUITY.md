# Continuidade em outro computador

O GitHub é a fonte do código, documentação, contratos e infraestrutura declarativa. O volume `steam_data` é a fonte do histórico e dos snapshots operacionais. Um clone sozinho preserva toda a implementação, mas não transporta o estado diário.

## Preparar um clone

Requisitos: Git, Python 3.12 e Node.js 24. Docker é necessário apenas para builds e operação por containers.

```powershell
git clone https://github.com/runictools-com/game-promo-ranker.git
cd game-promo-ranker
./scripts/bootstrap.ps1
./scripts/check.ps1
```

Linux/macOS:

```sh
git clone https://github.com/runictools-com/game-promo-ranker.git
cd game-promo-ranker
./scripts/bootstrap.sh
./scripts/check.sh
```

Leia `AGENTS.md` antes de editar. Ele identifica fontes de verdade, invariantes e critérios de pronto. A interface servida é `static/index.html`; o `index.html` da raiz é legado e não deve receber mudanças isoladas.

## Código versus estado operacional

O Git guarda código e configuração sanitizada. Estes itens ficam fora do repositório:

- `data/`: snapshots, caches, séries e histórico de preços;
- favoritos, tema e preferências do navegador (`localStorage`);
- chaves Steam, credenciais SSH e configuração local do preflight;
- backups e logs.

Para iniciar sem estado anterior, execute `python refresh_daily.py --pages 20 --data-dir data`. Isso consulta fontes externas e pode levar tempo. Não apresenta o mesmo histórico acumulado da produção.

## Exportar e verificar `steam_data`

No host autorizado, crie um arquivo fora do repositório:

```sh
stamp=$(date +%Y%m%d-%H%M%S)
docker exec gamepromo tar -C /app/data -czf - . > "steam_data_${stamp}.tgz"
tar -tzf "steam_data_${stamp}.tgz" >/dev/null
sha256sum "steam_data_${stamp}.tgz" > "steam_data_${stamp}.tgz.sha256"
git -C /home/deploy/steam-sale-ranker rev-parse HEAD > "steam_data_${stamp}.revision.txt"
```

Transfira os três arquivos por canal privado. Não use GitHub, issue, chat ou URL pública para o arquivo. Antes de restaurar, confira o SHA-256, a revisão registrada e faça uma cópia do destino atual.

Restauração local em diretório vazio:

```sh
mkdir -p data
tar -C data -xzf steam_data_YYYYMMDD-HHMMSS.tgz
python verify_release.py --data-dir data --require-fresh
```

Restaurar o volume de produção é uma operação separada e deliberada: exige backup restaurável do volume atual, container parado ou coordenação de escritores e verificação posterior de `/healthz`. Não execute restore de produção apenas porque este guia existe.

## Publicação

`deploy/ship.ps1 -NoDeploy` é portátil quando `.venv` existe ou `GAMEPROMO_PYTHON`/`-Python` aponta para um Python válido. A publicação real também depende do preflight, cadastro local do projeto e credencial SSH do operador; esses itens não pertencem ao Git.

O Compose de produção está versionado, mas pressupõe rede externa `web` e volume externo `steam_data`. Uma publicação só está confirmada quando GitHub, checkout remoto e label da imagem apontam para a mesma revisão, o container está saudável e `/healthz` confirma catálogo e histórico frescos.
