import pathlib
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "01_RUNTIME"))

from arpg_ground_loot_core import GroundLootCore


class FakeInventory:
    def __init__(self):
        self.received = []
        self.reject = False
    def grant_item(self, owner_ref, item_ref, quantity, *, event_ref, rarity=None, quality=None):
        if self.reject:
            return {"status":"REJECTED","reason":"INVENTORY_CAPACITY_EXCEEDED"}
        self.received.append((owner_ref,item_ref,quantity,rarity,quality,event_ref))
        return {"status":"PASS","item_ref":item_ref,"granted":quantity}


class Stage16AGroundLootTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.core = GroundLootCore(self.conn, "WORLD-16A")
        self.inv = FakeInventory()

    def tearDown(self):
        self.conn.close()

    def spawn(self, source_kind="ORE", item_ref="ITEM-IRON", item_kind="MINERAL", quantity=3, event_ref="spawn:1"):
        return self.core.spawn_drop(
            source_ref="SRC-1", source_kind=source_kind, item_ref=item_ref, item_kind=item_kind,
            quantity=quantity, candidate_position={"iso_x_m":1,"iso_y_m":2,"altitude_m":0}, event_ref=event_ref,
        )

    def settle(self, ref, reachable=True, event_ref="settle:1"):
        return self.core.confirm_settled(ref, settled_position={"iso_x_m":1.1,"iso_y_m":2.1,"altitude_m":0}, reachable=reachable, event_ref=event_ref)

    def test_spawn_is_world_first_and_unsettled(self):
        out=self.spawn(); d=out["drop"]
        self.assertTrue(d["physical_world_first"])
        self.assertFalse(d["direct_to_inventory"])
        self.assertFalse(d["settled"])

    def test_spawn_idempotent(self):
        a=self.spawn(event_ref="same"); b=self.spawn(event_ref="same")
        self.assertEqual(a["drop_ref"], b["drop_ref"])
        self.assertTrue(b["idempotent_replay"])

    def test_all_authorized_physical_sources(self):
        kinds=["ENEMY","TREE","ROCK","ORE","FLORA","AGRICULTURE","HUNTING","FISHING","CONTAINER","PRODUCTION","PLAYER_DROP"]
        for i,k in enumerate(kinds):
            out=self.spawn(source_kind=k,event_ref=f"spawn:{i}:{k}")
            self.assertEqual(out["status"],"PASS",k)

    def test_pickup_requires_settle(self):
        ref=self.spawn()["drop_ref"]
        out=self.core.pickup(ref,profile_ref="P1",physical_distance_m=0.1,reachable_now=True,event_ref="pickup:1",grant_item=self.inv.grant_item)
        self.assertEqual(out["reason"],"DROP_NOT_SETTLED")

    def test_pickup_never_over_half_meter(self):
        ref=self.spawn()["drop_ref"]; self.settle(ref)
        out=self.core.pickup(ref,profile_ref="P1",physical_distance_m=0.5001,reachable_now=True,event_ref="pickup:2",grant_item=self.inv.grant_item)
        self.assertEqual(out["reason"],"PICKUP_DISTANCE_EXCEEDED")
        self.assertEqual(self.core.drop(ref)["state"],"ACTIVE")

    def test_unreachable_drop_not_collected(self):
        ref=self.spawn()["drop_ref"]; self.settle(ref,reachable=False)
        out=self.core.pickup(ref,profile_ref="P1",physical_distance_m=0.1,reachable_now=True,event_ref="pickup:3",grant_item=self.inv.grant_item)
        self.assertEqual(out["reason"],"GROUND_LOOT_UNREACHABLE")

    def test_inventory_rejection_keeps_drop(self):
        ref=self.spawn()["drop_ref"]; self.settle(ref); self.inv.reject=True
        out=self.core.pickup(ref,profile_ref="P1",physical_distance_m=0.2,reachable_now=True,event_ref="pickup:4",grant_item=self.inv.grant_item)
        self.assertEqual(out["status"],"REJECTED")
        self.assertTrue(out["drop_remains_active"])
        self.assertEqual(self.core.drop(ref)["state"],"ACTIVE")

    def test_successful_pickup_preserves_stack_quantity(self):
        ref=self.spawn(quantity=7)["drop_ref"]; self.settle(ref)
        out=self.core.pickup(ref,profile_ref="P1",physical_distance_m=0.5,reachable_now=True,event_ref="pickup:5",grant_item=self.inv.grant_item)
        self.assertEqual(out["status"],"PASS")
        self.assertEqual(out["quantity"],7)
        self.assertEqual(self.core.drop(ref)["state"],"COLLECTED")
        self.assertEqual(self.inv.received[0][2],7)

    def test_icon_is_by_type_not_item_id(self):
        a=self.spawn(item_ref="ITEM-IRON",item_kind="MINERAL",event_ref="icon:a")["drop"]
        b=self.spawn(item_ref="ITEM-QUARTZ",item_kind="MINERAL",event_ref="icon:b")["drop"]
        self.assertEqual(a["icon_category"],b["icon_category"])
        self.assertEqual(a["icon_category"],"ICON_MINERAL")

    def test_active_drops_excludes_collected(self):
        a=self.spawn(event_ref="active:a")["drop_ref"]
        b=self.spawn(event_ref="active:b")["drop_ref"]
        self.settle(a,event_ref="active:settle")
        self.core.pickup(a,profile_ref="P1",physical_distance_m=0.1,reachable_now=True,event_ref="active:pickup",grant_item=self.inv.grant_item)
        refs=[d["drop_ref"] for d in self.core.active_drops()]
        self.assertNotIn(a,refs); self.assertIn(b,refs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
