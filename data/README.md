# Dados locais e persistentes

Este diretório é preenchido pelos coletores e montado como o volume `steam_data` em produção. Os snapshots, caches e históricos reais não entram no Git porque mudam diariamente e podem conter estado operacional volumoso.

Um clone novo funciona depois de executar `python refresh_daily.py --pages 20 --data-dir data`, mas essa coleta não recria observações históricas antigas. Para continuar com o mesmo histórico, transfira um backup privado seguindo [docs/CONTINUITY.md](../docs/CONTINUITY.md).

Nunca substitua `steam_price_history.json` por uma coleta vazia, converta ausência de preço em zero ou publique backups do volume no repositório.
