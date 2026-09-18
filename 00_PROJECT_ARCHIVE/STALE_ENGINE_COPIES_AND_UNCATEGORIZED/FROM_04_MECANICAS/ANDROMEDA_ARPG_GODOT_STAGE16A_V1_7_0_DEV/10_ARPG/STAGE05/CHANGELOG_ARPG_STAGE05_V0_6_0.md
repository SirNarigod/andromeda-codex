# ARPG Stage 05 — Itemization V0.6.0

## Added
- Universal item definition snapshot over the existing 84-entry runtime catalog.
- Owner-generic inventories for player profiles, runtime entities and Country NPC identities.
- Stack quantities, unique item instances, deterministic rarity/quality/affix rolls, durability and empty socket framework.
- Equipment slots and combat-stat integration for equipped, non-broken items.
- Stage05 consumable use backed by real item stacks and Stage04 cooldown authority.
- Deterministic item events, replay protection, transfers and persistence.

## Preserved
- Master V2.0.1 remains READ_ONLY.
- Stage04 placeholder consumables remain compatibility-only for regression.
- Legacy Commerce/Country inventory is not deleted or silently replaced in this stage.

## Deferred
- Authored Singular item identities.
- Rune/socket installation rules.
- Loot sources/drop tables.
- Gathering/work production.
- Crafting and economic repair cost.
- Final art.
