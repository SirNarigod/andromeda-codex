from __future__ import annotations

"""Stage16B mutable, non-canonical literal dialogue text provider.

CONTENT SEED only -- never a command surface, never a gameplay decision.
See andromeda_authority_adapter.py's REQUEST_NPC_DIALOGUE handler for the
transport/validation that consumes this (G16B-19B).

This module exists because the real, protected Stage12 core
(01_RUNTIME/arpg_narrative_culture_core.py, ARPGNarrativeCultureCore,
AUTHORITY='ANDROMEDA_ARPG_STAGE12_NARRATIVE_CULTURE_QUESTS') already has a
real DIALOGUE_BRIEFS table (anchor_ref, speech_acts, source_refs) but its
own dialogue_brief() explicitly returns 'exact_dialogue_text_canonical':
False and carries no literal text field at all -- it is a structured brief,
not a renderable line. Rather than touch that protected/frozen core to add
a text field (forbidden this round -- see G16B-19A section 24), this small
Stage16B-owned table supplies ONE short, original, honestly-labeled literal
line per dialogue_ref, bound to a brief that must already resolve for real
via ARPGNarrativeCultureCore.dialogue_brief() before this table is ever
consulted (see _request_npc_dialogue()).

G16B-19A's read-only preflight recommended pairing DLG-S12-FRONTIER
(anchor CIT-001) with the NPC nearest the player's spawn. G16B-19B's own
read-only inspection (see closure report) found that CountryScaleSystem's
procedural cities/NPCs are NOT keyed by canonical location refs like
CIT-001 -- there is no real per-NPC spatial correlation to a specific
dialogue anchor. This table therefore does not attempt to fabricate that
correlation: DLG-S12-FRONTIER is bound to whichever single real, eligible
NPC the adapter resolves (see Stage16BAuthorityAdapter._select_dialogue_eligible_npc),
independent of that NPC's procedural block/city placement. Extending this
to multiple NPCs with distinct content is explicitly out of scope here.
"""

from typing import Any

COPY_AUTHORITY = "GAMEPLAY_PLACEHOLDER_COPY_NOT_CANON_DIALOGUE"

# dialogue_ref -> literal content. Text is original Stage16B placeholder
# copy, NOT canonical dialogue (see COPY_AUTHORITY, matching the real
# brief's own copy_authority value exactly). Kept intentionally to one
# entry -- this round's scope is the minimum needed to close the G16B-19
# DIALOGUE step, not a dialogue content library.
DIALOGUE_CONTENT: dict[str, dict[str, Any]] = {
    "DLG-S12-FRONTIER": {
        "line": (
            "Bem-vindo a Varga. Se for seguir estrada afora, conheca o "
            "povoado antes -- ajuda a nao se perder por aqui."
        ),
        "related_quest_ref": "QST-S12-VARGA-ORIENTATION",
        "copy_authority": COPY_AUTHORITY,
    },
}


def resolve_dialogue_content(dialogue_ref: str) -> dict[str, Any] | None:
    """Return a fresh copy of the literal Stage16B content bound to a real
    dialogue_ref, or None if this table has no entry for it. Never mutates,
    never decides which dialogue_ref applies -- that is the caller's job.
    """
    entry = DIALOGUE_CONTENT.get(str(dialogue_ref))
    if entry is None:
        return None
    return dict(entry)
