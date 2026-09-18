"""S17 (16/09): ConsequenceEngine now supports a per-relation weight
(`weight_from_relation_metadata` on a consequence template, read from that
matched relation's own `metadata` dict) -- the exact gap that stopped the
kill/death->faction-reputation bridges (system_causal_bridges.py) from
being expressed as declarative rules: previously every target under one
rule got the SAME event-sourced amount, with no way to scale it per-target
(e.g. "each faction reacts proportional to ITS OWN influence").

This does not migrate those bridges (still composed functions, deliberately
-- see ANDROMEDA_CAUSAL_RULES_CATALOG_V1_0.md for why that stays the right
call for now); it proves the engine CAN now express that shape, end to end,
with two targets that must receive two DIFFERENT amounts from one rule.
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime, ValidationError, new_runtime_id, clock_point
from consequence_engine import ConsequenceEngine

MASTER = os.environ.get("ANDROMEDA_MASTER_RELEASE", "/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip")


def make_entity(rt, world, *, kind="OBJECT", data=None):
    clock = rt.get_clock(world["world_instance_id"])
    state = {
        "state_id": new_runtime_id("state"),
        "world_instance_id": world["world_instance_id"],
        "timeline_id": world["timeline_id"],
        "entity_runtime_id": new_runtime_id(kind.lower()),
        "origin": "RUNTIME_BORN",
        "entity_kind": kind,
        "lifecycle": "ACTIVE",
        "version": 0,
        "updated_at": clock_point(clock["day"], clock["tick"]),
        "data": copy.deepcopy(data or {}),
    }
    rt.register_entity(world["world_instance_id"], state)
    return state


def root_action(rt, world, actor_ref, event_type, *, parameters=None):
    c = rt.get_clock(world["world_instance_id"])
    a = {
        "action_id": new_runtime_id("action"),
        "intent_id": new_runtime_id("intent"),
        "world_instance_id": world["world_instance_id"],
        "timeline_id": world["timeline_id"],
        "actor_ref": actor_ref,
        "action_type": event_type,
        "parameters": copy.deepcopy(parameters or {}),
        "precondition_snapshot": {},
        "idempotency_key": new_runtime_id("idem"),
        "created_at": clock_point(c["day"], c["tick"]),
        "status": "SCHEDULED",
    }
    return rt.apply_action(world["world_instance_id"], a, []), a


class WeightedRelationConsequenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "world.db")
        self.rt = LivingRuntime(self.db, master_release_path=MASTER)
        self.world = self.rt.create_world("weighted-relation-test", 999, ticks_per_day=24)
        self.eng = ConsequenceEngine(self.rt)

    def tearDown(self):
        self.eng.detach_auto_propagation()
        self.rt.close()
        self.tmp.cleanup()

    def _entity(self, **kwargs):
        return make_entity(self.rt, self.world, **kwargs)

    def test_two_targets_receive_different_amounts_from_one_rule(self):
        actor = self._entity(kind="ACTOR")
        weak_faction = self._entity(kind="FACTION_RUNTIME", data={"value": 0.0})
        strong_faction = self._entity(kind="FACTION_RUNTIME", data={"value": 0.0})

        self.eng.register_relation(
            self.world["world_instance_id"], actor["entity_runtime_id"],
            weak_faction["entity_runtime_id"], "PRESENT_IN",
            metadata={"weight": 0.2},
        )
        self.eng.register_relation(
            self.world["world_instance_id"], actor["entity_runtime_id"],
            strong_faction["entity_runtime_id"], "PRESENT_IN",
            metadata={"weight": 0.9},
        )

        self.eng.register_rule(
            self.world["world_instance_id"],
            {
                "name": "kill->weighted-reaction",
                "trigger_event_type": "HOSTILE_KILL",
                "relation_type": "PRESENT_IN",
                "direction": "OUTGOING",
                "derived_event_type": "FACTION_REACTED",
                "priority": 0,
                "max_depth": 4,
                "offline_policy": "ACTIVE_ONLY",
                "consequences": [
                    {
                        "operation": "INCREMENT",
                        "field_path": "data.value",
                        "amount_from_event": "payload.parameters.base_amount",
                        "weight_from_relation_metadata": "weight",
                    }
                ],
            },
        )

        result, _ = root_action(
            self.rt, self.world, actor["entity_runtime_id"], "HOSTILE_KILL",
            parameters={"base_amount": 10.0},
        )
        self.eng.propagate_from_event(self.world["world_instance_id"], result["event_id"])

        weak_after = self.rt.get_entity(self.world["world_instance_id"], weak_faction["entity_runtime_id"])
        strong_after = self.rt.get_entity(self.world["world_instance_id"], strong_faction["entity_runtime_id"])
        self.assertAlmostEqual(2.0, weak_after["data"]["value"])
        self.assertAlmostEqual(9.0, strong_after["data"]["value"])
        self.assertNotEqual(weak_after["data"]["value"], strong_after["data"]["value"])

    def test_relation_without_weight_metadata_defaults_to_one(self):
        actor = self._entity(kind="ACTOR")
        faction = self._entity(kind="FACTION_RUNTIME", data={"value": 0.0})
        self.eng.register_relation(
            self.world["world_instance_id"], actor["entity_runtime_id"],
            faction["entity_runtime_id"], "PRESENT_IN",
        )
        self.eng.register_rule(
            self.world["world_instance_id"],
            {
                "name": "kill->unweighted-reaction",
                "trigger_event_type": "HOSTILE_KILL",
                "relation_type": "PRESENT_IN",
                "direction": "OUTGOING",
                "derived_event_type": "FACTION_REACTED",
                "priority": 0,
                "max_depth": 4,
                "offline_policy": "ACTIVE_ONLY",
                "consequences": [
                    {
                        "operation": "INCREMENT",
                        "field_path": "data.value",
                        "amount_from_event": "payload.parameters.base_amount",
                        "weight_from_relation_metadata": "weight",
                    }
                ],
            },
        )
        result, _ = root_action(
            self.rt, self.world, actor["entity_runtime_id"], "HOSTILE_KILL",
            parameters={"base_amount": 5.0},
        )
        self.eng.propagate_from_event(self.world["world_instance_id"], result["event_id"])
        after = self.rt.get_entity(self.world["world_instance_id"], faction["entity_runtime_id"])
        self.assertAlmostEqual(5.0, after["data"]["value"])

    def test_non_numeric_weight_metadata_rejected(self):
        actor = self._entity(kind="ACTOR")
        faction = self._entity(kind="FACTION_RUNTIME", data={"value": 0.0})
        self.eng.register_relation(
            self.world["world_instance_id"], actor["entity_runtime_id"],
            faction["entity_runtime_id"], "PRESENT_IN",
            metadata={"weight": "not-a-number"},
        )
        self.eng.register_rule(
            self.world["world_instance_id"],
            {
                "name": "kill->bad-weight",
                "trigger_event_type": "HOSTILE_KILL",
                "relation_type": "PRESENT_IN",
                "direction": "OUTGOING",
                "derived_event_type": "FACTION_REACTED",
                "priority": 0,
                "max_depth": 4,
                "offline_policy": "ACTIVE_ONLY",
                "consequences": [
                    {
                        "operation": "INCREMENT",
                        "field_path": "data.value",
                        "amount_from_event": "payload.parameters.base_amount",
                        "weight_from_relation_metadata": "weight",
                    }
                ],
            },
        )
        # The rule engine swallows per-target template failures as a
        # recorded propagation stop rather than raising out of apply_action
        # (see TEMPLATE_RESOLUTION_FAILED handling) -- confirm the faction's
        # value was never touched, i.e. the bad weight really did block that
        # one consequence rather than silently applying amount*1.
        result, _ = root_action(
            self.rt, self.world, actor["entity_runtime_id"], "HOSTILE_KILL",
            parameters={"base_amount": 5.0},
        )
        summary = self.eng.propagate_from_event(self.world["world_instance_id"], result["event_id"])
        self.assertEqual("COMPLETED", summary["status"])
        after = self.rt.get_entity(self.world["world_instance_id"], faction["entity_runtime_id"])
        self.assertEqual(0.0, after["data"]["value"])


if __name__ == "__main__":
    unittest.main()
