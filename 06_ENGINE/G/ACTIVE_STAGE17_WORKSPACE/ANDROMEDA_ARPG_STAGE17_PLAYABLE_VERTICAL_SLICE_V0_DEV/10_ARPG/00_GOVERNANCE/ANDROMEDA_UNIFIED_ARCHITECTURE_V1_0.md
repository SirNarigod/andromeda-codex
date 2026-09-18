# Andrômeda — Arquitetura Unificada V1.0

**Status**: `AUTHOR_APPROVED` (auditoria completa, 13/09) · **Autoridade**: documento de consolidação/referência — não substitui nenhum contrato numerado (`ARPG_*_CONTRACT_V*.json`), nem `ARPG_AUTHORIAL_DECISIONS_V0_1_0..V0_3_0`, nem `STAGE16B_BASELINE_PROVENANCE.json`. Em caso de conflito, o contrato/decisão específico vence; este documento é o mapa, não a lei.

**Árvore ativa confirmada**: `06_ENGINE\G\ACTIVE_STAGE17_WORKSPACE\ANDROMEDA_ARPG_STAGE17_PLAYABLE_VERTICAL_SLICE_V0_DEV\` (Stage16B fechado/read-only, Stage17 é o workspace de desenvolvimento vivo).

## Por que este documento existe
Auditoria real (3 varreduras read-only) confirmou: o backend Python (`01_RUNTIME`, 99 arquivos, autoridade 100% server-side) e o conteúdo/lore (MAR, classes, veículos, economia, corrupção) já são ricos e majoritariamente funcionais/testados. O risco não era falta de sistemas — era duplicar o que já existe por falta de um mapa único. Este documento é esse mapa.

## Arquitetura

```
ANDRÔMEDA
├── CORE AUTHORITY
│   ├── Authority/Persistence   → living_runtime.py (LivingRuntime)
│   ├── HTTP Bridge             → stage16b_authority_api.py + andromeda_authority_adapter.py
│   ├── Commands/Idempotency    → living_runtime.py (tabelas idempotency/events)
│   ├── Snapshots/Recovery      → arpg_save_recovery_core.py
│   └── Validation              → ValidationError/ConflictError (living_runtime.py)
│
├── WORLD / LIVING SYSTEM
│   ├── Planet/Regions/Territories → country_scale.py (CountryScaleSystem) — hoje só TER-011
│   ├── Ecology                 → ecology_brain.py
│   ├── Population/NPC brain    → agent_brain.py
│   ├── Economy                 → arpg_economy_crafting_core.py + vendor_wealth_economy.py + commerce_system.py
│   └── Dynamic Events          → consequence_engine.py + world_orchestrator.py
│
├── ENVIRONMENT SYSTEM
│   ├── Terrestrial             → continuous_movement.py (domínio GROUND)
│   ├── Aquatic/Submerged/Flying→ movement_multimodal.py (Stage17, NOT_CANON)
│   └── Special Biomes          → country_scale.py (BIO-ROOT-DEEP) + Raiz Profunda (ver Special Ecosystems)
│
├── CHARACTER SYSTEM
│   ├── ClassDefinition (dado)  → MAR_PLAYABLE_CLASSES_LORE_DEV_V1_0.json + MAR_CLASS_ARMAMENT_MATRIX_DEV_V1_0.json
│   ├── Attributes/Identity     → arpg_actor_core.py, character_core.py
│   ├── NPCs/Criaturas          → MAR_NPC_ROSTER_*.json + bestiário (04_MECANICAS/CRIATURAS) + ecology_brain.py
│   └── Corrupted Entities      → ZUM-001..010 (NPCs conscientes) + classe Corrompidos
│
├── MOVEMENT SYSTEM
│   ├── Ground/Aquatic/Submerged/Flying → continuous_movement.py + movement_multimodal.py
│   └── Vehicle Movement        → vehicle_movement.py (física livre) + arpg_mobility_infrastructure_core.py (rotas fixas Stage10)
│
├── MAR — ARMAMENT SYSTEM
│   └── 96 armas / 5 famílias por classe (Nativos=Corpo-a-corpo, Soldados=Fogo, Androids=Tecnologia,
│       Magos=Magia, Corrompidos=Corrupção controlada) — 04_MECANICAS/ITENS_E_ARMAS/*.json
│
├── COMBAT SYSTEM
│   ├── Long/Mid/ECQ/In-Fighting/Clinch → combat_distance_states.py (Stage17, ainda não plugado no core)
│   ├── Ataque/Defesa/Distância  → arpg_combat_core.py + combat_system.py
│   └── Projétil/balística       → projectile_system.py
│
├── VEHICLE SYSTEM
│   ├── Land/Aquatic/Submerged/Flying → vehicle_movement.py (vehicleDomainFor)
│   └── Distance Tracking        → spatial_coordinates.py + streaming_system.py
│
├── INTERACTION SYSTEM
│   ├── Objects/Resources        → object_environment.py + arpg_gathering_work_core.py
│   ├── Construction             → STELLAR_BUILDING_PIECES_CATALOG (conteúdo; sem runtime próprio ainda)
│   ├── Production               → STELLAR_PRODUCTION_RECIPES_DEV_V1_0.json + arpg_economy_crafting_core.py
│   └── Loot                     → arpg_ground_loot_core.py
│
└── SPECIAL ECOSYSTEMS
    └── Raiz Profunda            → conteúdo rico (gate autoral + NPCs + recursos + classe jogável),
                                    sem sistema de runtime dedicado ainda — ver auditoria completa
```

## Regra fundamental
Sistemas são genéricos por função (`MovementSystem`, `CombatSystem`, `ArmamentSystem`) — nunca duplicados por classe (nunca `SoldierSystem`/`MageSystem`). Cada classe (Nativos/Soldados/Androids/Magos/Corrompidos) é dado de configuração consumido pelos sistemas acima, nunca um sistema próprio.

## Não recriar
`living_runtime.py`, `country_scale.py`, `continuous_movement.py`, `combat_system.py`/`arpg_combat_core.py`, `arpg_economy_crafting_core.py`, `arpg_item_core.py`, `arpg_skill_core.py`, `agent_brain.py`/`ecology_brain.py`, `arpg_mobility_infrastructure_core.py`, `arpg_gathering_work_core.py`, `arpg_water_bag_survival_core.py`, o cliente Godot completo em `13_GODOT_ARPG_STAGE17`, e todo o conteúdo MAR/classes/veículos/economia já catalogado.

## Duplicados/conflitos conhecidos (não resolvidos ainda)
1. 3 camadas de combate com versionamento inconsistente (ver auditoria completa) — aditivas, não redundantes, mas sem ponto único de verdade documentado.
2. `ARPG_SKILL_SYSTEM_CONTRACT_V0.7.0` ainda declara o modelo de classe `V0_1_0` (emergente), já substituído por `V0_2_0`/`V0_3_0` (5 classes fixas).
3. Bestiário tem 2 esquemas de "criatura corrompida" não coordenados (variante `CORROMPIDA` vs `CRI-020..026`).
4. Sistemas Stage17 "NOT_CANON" portam fórmulas manualmente de outros cores (documentado nos próprios arquivos) — dívida técnica conhecida, não bug.

## Gaps identificados (não implementados nesta rodada)
**Integração** (baixo risco): plugar `combat_distance_states.py` no `arpg_combat_core.py`; atualizar o contrato de Skill; criar `skill_client.gd`; formalizar contrato de Água/Sobrevivência; reconciliar os 2 esquemas de criatura corrompida.
**Vertical slice** (médio risco): stats concretos de combate por arma MAR no runtime; runtime de Construção; crossref completo dos 23 veículos.
**Futuro**: Raiz Profunda como sistema de runtime dedicado; planeta completo; demais expansões.

Auditoria completa (tabela de sistemas, achados detalhados, plano de fases): ver sessão de auditoria de 13/09 — relatório mantido no histórico da conversa, não duplicado aqui.
