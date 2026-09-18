# Catálogo de Regras Causais (Ação → Reação) — Andrômeda

## O motor "Blueprint" já existe: `ConsequenceEngine`

Arquivo: `01_RUNTIME/consequence_engine.py`, instanciado em `self.consequences` desde `IntegratedLivingEngineV11` — herdado por toda a cadeia até `IntegratedARPGEngineV16A` (o motor de produção). É o equivalente a um Event Graph do Blueprint: você registra uma **regra**, e o motor aplica automaticamente sempre que o evento-gatilho acontece.

### Esquema de uma regra (`register_rule`)

| Campo | O que faz |
|---|---|
| `trigger_event_type` | o evento que dispara a regra (ex.: `"ITEM_LOOTED"`) |
| `relation_type` + `direction` | de qual relação canônica (`MASTER_RELATIONSHIP_REGISTRY`) a regra puxa o alvo — `OUTGOING`/`INCOMING`/`BOTH` |
| `derived_event_type` | o evento novo gerado como reação |
| `consequences` | lista de operações (`SET`/`TRANSITION`/`INCREMENT`/`DECREMENT`/`SCHEDULE_RECOVERY`) sobre `field_path`, nunca com `target_ref` fixo — o alvo vem da relação, não é hardcoded |
| `offline_policy` | `ACTIVE_ONLY` (só roda com jogador presente) ou `ROUTINE_SAFE` (roda mesmo offline) |
| `max_depth` (1–8) | trava contra cascata infinita (regra gera evento que dispara outra regra, até N níveis) |
| `priority`, `status` (`ACTIVE`/`DISABLED`) | ordem e liga/desliga sem apagar |

Eventos como `WORLD_DESTRUCTION`/`WAR_ESCALATION`/`RANDOM_PERMADEATH`/`MAJOR_CONFLICT` nunca disparam em `ROUTINE_SAFE` — proteção contra o mundo mudar sozinho de forma catastrófica enquanto ninguém olha.

## Achado real (não suposição): hoje isso está vazio em produção

Busquei todo lugar que chama `register_rule(` no projeto inteiro. Resultado: **só em `test_consequence_engine.py` e `run_stage05_extended_regression.py`**. Nenhum lugar do motor de produção (`integrated_arpg_engine_v16a.py`, `andromeda_authority_adapter.py`) registra uma regra real.

Ou seja: o motor de causa→efeito existe, está testado, está ligado — mas a tabela `causal_rules` fica **vazia** quando o jogo roda de verdade. Nenhuma das conexões entre sistemas já feitas nesta sessão (corrupção→fauna, skill→combate, economia→facção) passa por aqui — são todas chamadas diretas de função em Python, não regras declarativas. Funcionam, mas são "fiação exposta", não um grafo organizado e ligável/desligável como um Blueprint.

## O que existe hoje, por fora do ConsequenceEngine (fiação direta)

| Ação | Reação | Onde |
|---|---|---|
| Raiz Profunda expande subregião de fronteira | migra fauna entre territórios | `fauna_territorial_migration.py` chamado direto por `root_corruption_system.py` |
| Banda de distância de combate (`combat_distance_states`) | modificador de dano/ataque | `arpg_combat_core.py` chama `distance_modifiers_for_pair()` direto |
| Travessia de fronteira (`REQUEST_CROSS_TERRITORY_TRAVEL`) | transferência de perfil/inventário/wallet | `cross_territory_transfer.py` chamado direto pelo adapter |
| `WorldSystems` (economia/facção) | projeção filtrada por território ativo | `_economy_faction_projection()` no adapter, recalcula a cada snapshot |

Nenhuma dessas passa por `trigger_event_type`/`derived_event_type` — são acopladas ponto-a-ponto no código, não descobríveis num catálogo central.

## Proposta pra "mais rico e organizado" (não implementado ainda — só o plano)

1. **Migrar as 4 conexões acima pra regras declarativas** no `ConsequenceEngine`, com `register_rule()` chamado no boot do engine (não em teste) — vira 1 lugar só pra ver/ligar/desligar cada conexão.
2. **Registrar as relações que faltam**, hoje sistemas-ilha:
   - Dano ao jogador → sem regra afetando reputação de facção (matar NPC de uma facção deveria custar reputação).
   - Corrupção/clima → sem regra afetando preço de vendor (`vendor_wealth_economy.py` já existe, só falta o gatilho).
   - Gathering/mineração → sem regra reduzindo densidade regional em `country_scale.py` (hoje só reduz `remaining_units` do nó local, nunca reflete na macro-economia).
3. Cada regra nova ganha teste próprio (padrão já usado: `LivingRuntime(":memory:")` + evento sintético + assert no evento derivado).

## Verificação
- Achado confirmado por grep direto no código, não por inferência: `register_rule(` só aparece em 2 arquivos de teste.
- Cadeia de herança confirmada: `IntegratedARPGEngineV16A(IntegratedARPGEngineV15)` → ... → `IntegratedLivingEngineV11` (onde `self.consequences=ConsequenceEngine(...)` é criado).
