from __future__ import annotations

from typing import Any

from living_runtime import NotFoundError

# ============================================================================
# ARPG_STAGE17_CROSS_TERRITORY_TRANSFER_NOT_CANON
#
# Fase 8.3 (14/09): primitivo que faltava pra viagem fisica real entre
# territorios - hoje cada territorio "malha completa" (fase 8.3, ver
# arpg_world_core.py) vive num IntegratedARPGEngineV16A PROPRIO e independente
# (db/LivingRuntime separado), nao um mundo-filho sob o mesmo runtime como o
# PlanetSystem de fase 7.2 (esse continua servindo a camada macro/agregada,
# nao a sessao viva do jogador). Nao existia nenhum jeito de mover um profile
# entre 2 engines - este arquivo fecha essa lacuna, autocontido, reaproveitando
# so a API publica ja existente de cada engine (create_profile/grant_item/
# ensure_wallet), nunca SQL cru direto nas tabelas do outro motor.
#
# Escopo honesto: transfere identidade (profile_ref preservado via
# create_profile(profile_ref=...), fase 8.3), inventario base (stacks
# empilhaveis) e carteira. NAO copia: item_instances individuais com
# durabilidade/raridade exata (limitacao documentada, nao escondida), skills
# aprendidas, progresso de quest, cooldowns de combate - isso fica pra
# trabalho futuro se o jogo precisar de paridade completa entre territorios.
# ============================================================================

AUTHORITY = "ARPG_STAGE17_CROSS_TERRITORY_TRANSFER_NOT_CANON"
VERSION = "V0.1.0-PRE-GODOT"


def transfer_profile(
    source_engine: Any,
    source_world_instance_id: str,
    dest_engine: Any,
    dest_world_instance_id: str,
    source_profile_ref: str,
) -> dict[str, Any]:
    """Idempotente por natureza (nao por event_ref): se o profile_ref ja existe
    no motor de destino, a transferencia e tratada como ja concluida
    (idempotent_replay=True) - nao ha necessidade de tabela de eventos propria
    porque a existencia do profile no destino JA E o registro do que
    aconteceu."""
    dest_arpg = dest_engine.arpg(dest_world_instance_id)
    if any(p["profile_ref"] == source_profile_ref for p in dest_arpg.list_profiles()):
        return {
            "status": "PASS",
            "profile_ref": source_profile_ref,
            "idempotent_replay": True,
            "authority": AUTHORITY,
        }

    src_arpg = source_engine.arpg(source_world_instance_id)
    src_profile = next(
        (p for p in src_arpg.list_profiles() if p["profile_ref"] == source_profile_ref), None
    )
    if src_profile is None:
        return {"status": "REJECTED", "reason": "SOURCE_PROFILE_NOT_FOUND", "authority": AUTHORITY}

    created = dest_arpg.create_profile(
        src_profile["controller_scope"],
        origin_mode="CREATED",
        display_name=src_profile["display_name"],
        profile_ref=source_profile_ref,
    )
    dest_profile = created.get("profile", created)

    src_items = source_engine.items_arpg(source_world_instance_id)
    dest_items = dest_engine.items_arpg(dest_world_instance_id)
    # Itens de fixture/dev (ex.: S16B-DEV-CLOTHES-*, injetados so pelo
    # bootstrap de desenvolvimento do adapter) podem nao existir no catalogo
    # de definicoes do motor de destino, que nunca passou por esse mesmo
    # bootstrap - pular e registrar, nunca deixar a viagem inteira falhar por
    # causa de 1 item que so existe no lado de origem.
    snapshot = src_items.inventory_snapshot(source_profile_ref)
    transferred_stacks: dict[str, int] = {}
    skipped_items: list[str] = []
    for item_ref, quantity in (snapshot.get("stacks") or {}).items():
        quantity = int(quantity)
        if quantity <= 0:
            continue
        try:
            dest_items.grant_item(
                source_profile_ref, item_ref, quantity,
                event_ref=f"XFER:{source_profile_ref}:{item_ref}",
            )
            transferred_stacks[item_ref] = quantity
        except NotFoundError:
            skipped_items.append(item_ref)
    transferred_instances = 0
    for inst in snapshot.get("instances") or []:
        try:
            dest_items.grant_item(
                source_profile_ref, inst["item_ref"], 1,
                event_ref=f"XFER:{source_profile_ref}:INST:{inst.get('instance_ref', transferred_instances)}",
                rarity=inst.get("rarity"), quality=inst.get("quality"),
            )
            transferred_instances += 1
        except NotFoundError:
            skipped_items.append(inst["item_ref"])

    src_economy = source_engine.economy_arpg(source_world_instance_id)
    dest_economy = dest_engine.economy_arpg(dest_world_instance_id)
    src_wallet = src_economy.wallet(source_profile_ref)
    dest_economy.ensure_wallet(source_profile_ref, starting_balance=float(src_wallet["balance"]))

    return {
        "status": "PASS",
        "profile_ref": source_profile_ref,
        "dest_profile": dest_profile,
        "transferred_stacks": transferred_stacks,
        "transferred_instances": transferred_instances,
        "transferred_balance": float(src_wallet["balance"]),
        "skipped_items": skipped_items,
        "idempotent_replay": False,
        "authority": AUTHORITY,
    }
