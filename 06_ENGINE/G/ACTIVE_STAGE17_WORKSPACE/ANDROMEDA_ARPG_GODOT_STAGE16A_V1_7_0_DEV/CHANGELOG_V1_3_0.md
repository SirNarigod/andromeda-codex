# CHANGELOG V1.3.0

## ADDED
- Master V2.1.0 Country Scale canonical contracts and 54-item Country catalog.
- `CountryLivingDomainBridge`.
- `IntegratedLivingEngineV13`.
- Dual-baseline runtime support for historical V2.0.1 and current V2.1.0.

## CHANGED
- Country purchases delegate to `CommerceSystem` when the bridge is attached.
- Country fauna hunting delegates to `CombatSystem`, corpse harvest and social-memory propagation.
- Ecology/Consequence/Atlas baseline checks now reuse verified baseline authority instead of hard-coded historical hashes.

## FIXED
- Witness memory/list contract mismatch.
- Witness NPC iterator shape mismatch.
- Master V2.1 bootstrap rejection from stale module hashes.
- V1.3 health baseline lookup.
- Child weapon purchase/equip/initiated-combat protection gap.
- Auditor schema/hygiene issues.

- Seeded combat determinism across clean UUID reallocation/restoration; runtime UUIDs no longer influence combat rolls.
- V1.3 release-readiness auditor supersedes obsolete Stage14 V1.0 baseline hash assumptions.

## CANON
Master V2.1.0 promotes the authorized structural hierarchy, names/catalogs, scene/dungeon contract and MAR gameplay balance. Exact runtime stocks/prices/positions remain non-canonical.
