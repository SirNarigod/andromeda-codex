# CYCLE 02 — ECONOMY + ITEMS + PRICING

Status: **PASS (V1.1.0-DEV)**

## Mudanças aplicadas

- Localidade econômica resolvida por `destino -> território -> população`.
- POIs e nós industriais entram como snapshots auxiliares `READ_ONLY`; o contrato histórico de 58 snapshots do WorldSystems foi preservado.
- Produtos recebem categoria runtime sem alterar a Master. Segurança alimentar passa a consumir apenas escassez de `FOOD`.
- `CommerceSystem` adicionado com catálogo MAR imutável, carteira, inventário, vendedor e estoque runtime.
- `PriceResolver` transforma `relative_cost` qualitativo em preço numérico runtime usando mercado local, escassez, logística/rotas, demanda, regulação, condição e relação comercial.
- Compra/venda são transações atômicas; quote expirada ou stale é rejeitada.
- Ledger de transações pode ser reconstruído a partir dos eventos confirmados.
- Primeiro defeito detectado durante os testes (`INCREMENT/DECREMENT` usando `value` em vez de `amount`) foi corrigido antes do checkpoint.

## Validação

- WorldSystems original: 51/51 PASS.
- Integration Hub: 6/6 PASS.
- Localidade econômica V1.1: 6/6 PASS.
- Commerce V1.1: 9/9 PASS.
- Escopo afetado: **72/72 PASS**.

A Master V2.0.1 não foi alterada. Nenhum preço numérico foi promovido a cânone.
