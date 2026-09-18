# Andromeda Codex — relatório de reorganização

Gerado em: 2026-09-06T21:49:54.495621+00:00

## Resultado

- Validação: APROVADA
- Documentos observados: 4096
- Documentos operacionais preservados: 1169
- Duplicatas eliminadas no conteúdo limpo: 2927
- Arquivos no pacote limpo: 3574
- ZIPs verificados recursivamente: 21; falhas de CRC: 0

## Distribuição por categoria

- 01_LORE: 10
- 02_REGRAS: 93
- 03_EPISODIOS: 238
- 04_MECANICAS: 109
- 05_CRIACAO_PROCEDURAL: 42
- 06_ENGINE: 3080

## Erros de validação

- Nenhum.

## Artefatos entregues

- `ANDROMEDA_CODEX_CLEAN.zip`: conteúdo deduplicado e classificado.
- `ANDROMEDA_CODEX_EVIDENCE.zip`: fontes originais, baselines e relatórios.
- `ANDROMEDA_MANIFEST.json`: rastreabilidade de origem, hash e classificação.
- `ARCHIVE_VERIFICATION.json`: verificação CRC direta dos ZIPs, inclusive aninhados.

## Nota de extração

Cinco avisos do manifesto inicial foram causados por caminhos temporários longos no Windows durante a extração, não por corrupção dos arquivos. A verificação direta posterior confirmou CRC de todos os 21 ZIPs sem falhas.
