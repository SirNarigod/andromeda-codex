# Andrômeda ARPG — Stage 05 Itemization V0.6.0

Stage 05 defines the universal item and inventory authority for the ARPG runtime.

## Scope
- 84 runtime item definitions projected from the existing catalog.
- 30 identities sourced from the READ_ONLY Master and 54 gameplay-derived DEV records.
- Shared inventory contract for player profiles and Country NPCs.
- Stack items, unique instances, equipment, durability, quality, deterministic rarity/affixes and empty sockets.
- Combat modifiers from equipped, non-broken items.
- Stage05 consumables backed by item stacks and Stage04 cooldown authority.

## Canon Guard
Rarity labels, numeric item stats, quality, affixes, capacity and runtime instance data are gameplay derivations. They do not rewrite canonical identity. Singular items and rune/socket installation require later authored/system-specific rules.

## Gathering / Work
Stage09 must use this same item contract for ores, wood, flora-derived resources, tools and NPC production. A parallel gathering inventory is forbidden.

## Art
No final art dependency. Placeholder-ready.
