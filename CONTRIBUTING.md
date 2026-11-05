# Contribuir

Leia `AGENTS.md`, `README.md` e a seção pertinente de `GUIDE.md` antes de alterar comportamento. Trabalhe a partir de `main` atualizado, mantenha cada mudança revisável e não reescreva o histórico compartilhado.

## Fluxo

1. Crie uma branch e preserve alterações alheias.
2. Atualize código, testes, documentação e `.codex/release-contract.json` quando a funcionalidade durável mudar.
3. Execute `./scripts/check.ps1` no Windows ou `./scripts/check.sh` no Linux/macOS.
4. Para UI, valide no navegador integrado em desktop e 390 px, incluindo `prefers-reduced-motion` quando houver movimento.
5. Descreva comportamento, evidência executada e limitações. Não inclua snapshots, chaves, dados de perfil ou backups no commit.

Mudanças de ranking precisam manter componentes explicáveis e versão do score. Mudanças de dados persistentes exigem migração, backup e rollback. Uma fonte externa nova precisa declarar identidade, região, proveniência, cobertura, validade, limites e comportamento de falha.
