"""Testes de vendor_wealth_economy.py - harness leve (sem MASTER_V2 zip, sem
ARPGEconomyCraftingCore real - so LivingRuntime + FakeEconomy duck-typed, mesmo
espirito de CombatDistanceStateMachine recebendo `movement` sem exigir o
ContinuousMovementSystem inteiro)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "01_RUNTIME"))

from living_runtime import LivingRuntime, ConflictError
from vendor_wealth_economy import (
    VendorWealthEconomy, tier_for_territory, WEALTH_MULTIPLIER_BY_WELFARE,
    BASE_VENDOR_WALLET, OFFLINE_CATCHUP_CAP_S,
)


class FakeEconomy:
    """So o que VendorWealthEconomy le/escreve - uma carteira em memoria por owner_ref,
    mesma forma de arpg_economy_crafting_core.wallet()/._set_balance()."""
    def __init__(self):
        self._balances = {}

    def wallet(self, owner_ref):
        return {"owner_ref": owner_ref, "balance": self._balances.get(owner_ref, 2000.0), "currency": "CREDIT_RUNTIME_NOT_CANON"}

    def _set_balance(self, owner_ref, balance):
        if balance < -1e-9:
            raise ValueError("negative wallet balance forbidden")
        self._balances[owner_ref] = round(float(balance), 4)


class TierForTerritoryTests(unittest.TestCase):
    def test_alto_welfare_territory(self):
        welfare, mult = tier_for_territory("TER-008")
        self.assertEqual(welfare, "ALTO")
        self.assertEqual(mult, 1.5)

    def test_baixo_welfare_territory(self):
        welfare, mult = tier_for_territory("TER-002")
        self.assertEqual(welfare, "BAIXO")
        self.assertEqual(mult, 0.6)

    def test_medio_welfare_territory(self):
        welfare, mult = tier_for_territory("TER-011")
        self.assertEqual(welfare, "MEDIO")
        self.assertEqual(mult, 1.0)

    def test_unknown_territory_defaults_to_medio(self):
        welfare, mult = tier_for_territory("TER-999")
        self.assertEqual(welfare, "MEDIO")
        self.assertEqual(mult, 1.0)


class VendorWealthEconomyTests(unittest.TestCase):
    def setUp(self):
        self.runtime = LivingRuntime(":memory:")
        world = self.runtime.create_world("test-owner", 1201)
        self.wid = world["world_instance_id"]
        self.economy = FakeEconomy()
        self.system = VendorWealthEconomy(self.runtime, self.wid, self.economy)

    def test_register_vendor_alto_tier_tops_up_above_base(self):
        r = self.system.register_vendor("SHOP-1", "TER-008", event_ref="REG-1")
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["welfare_tier"], "ALTO")
        self.assertAlmostEqual(r["wallet_cap"], BASE_VENDOR_WALLET * 1.5)
        self.assertTrue(r["topped_up"])
        self.assertAlmostEqual(self.economy.wallet("SHOP-1")["balance"], 3000.0)

    def test_register_vendor_baixo_tier_never_reduces_existing_balance(self):
        # vendedor ja tem 2000.0 (default do FakeEconomy, espelha create_vendor real)
        r = self.system.register_vendor("SHOP-2", "TER-002", event_ref="REG-1")
        self.assertEqual(r["welfare_tier"], "BAIXO")
        self.assertAlmostEqual(r["wallet_cap"], BASE_VENDOR_WALLET * 0.6)  # 1200.0
        self.assertFalse(r["topped_up"])  # 2000 ja esta acima do teto de 1200 - nao reduz
        self.assertAlmostEqual(self.economy.wallet("SHOP-2")["balance"], 2000.0)

    def test_register_vendor_medio_tier_no_change_needed(self):
        r = self.system.register_vendor("SHOP-3", "TER-011", event_ref="REG-1")
        self.assertAlmostEqual(r["wallet_cap"], BASE_VENDOR_WALLET)
        self.assertFalse(r["topped_up"])  # ja estava exatamente no teto

    def test_replenish_restores_proportional_to_elapsed_time(self):
        self.system.register_vendor("SHOP-1", "TER-011", event_ref="REG-1", now_wallclock_s=1000.0)
        self.economy._set_balance("SHOP-1", 0.0)  # vendedor gastou tudo comprando do jogador
        # 3h depois (10800s, dentro do teto de captura de 6h) - 1/8 do dia -> recupera 1/8 do teto (250.0)
        r = self.system.replenish("SHOP-1", event_ref="REP-1", now_wallclock_s=1000.0 + 10800.0)
        self.assertEqual(r["status"], "PASS")
        self.assertAlmostEqual(r["restored"], 250.0, places=4)
        self.assertAlmostEqual(r["balance_after"], 250.0, places=4)
        self.assertFalse(r["elapsed_s_capped"])

    def test_replenish_never_exceeds_wallet_cap(self):
        self.system.register_vendor("SHOP-1", "TER-002", event_ref="REG-1", now_wallclock_s=1000.0)  # cap=1200
        self.economy._set_balance("SHOP-1", 1199.0)
        # bastante tempo depois - tentaria recuperar muito mais que 1.0, mas o teto e 1200
        r = self.system.replenish("SHOP-1", event_ref="REP-1", now_wallclock_s=1000.0 + 999999.0)
        self.assertAlmostEqual(r["balance_after"], 1200.0, places=4)
        self.assertAlmostEqual(r["restored"], 1.0, places=4)

    def test_replenish_caps_elapsed_time_at_offline_catchup_cap(self):
        self.system.register_vendor("SHOP-1", "TER-011", event_ref="REG-1", now_wallclock_s=1000.0)
        self.economy._set_balance("SHOP-1", 0.0)
        far_future = 1000.0 + OFFLINE_CATCHUP_CAP_S * 10  # bem alem do teto de captura
        r = self.system.replenish("SHOP-1", event_ref="REP-1", now_wallclock_s=far_future)
        self.assertTrue(r["elapsed_s_capped"])
        expected_restore = OFFLINE_CATCHUP_CAP_S * (BASE_VENDOR_WALLET / 86400.0)
        self.assertAlmostEqual(r["restored"], expected_restore, places=4)

    def test_replenish_unknown_vendor_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.system.replenish("SHOP-NUNCA-REGISTRADO", event_ref="REP-1")

    def test_idempotent_replay_register_vendor(self):
        first = self.system.register_vendor("SHOP-1", "TER-008", event_ref="REG-X")
        second = self.system.register_vendor("SHOP-1", "TER-008", event_ref="REG-X")
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])

    def test_idempotent_replay_replenish_does_not_double_apply(self):
        self.system.register_vendor("SHOP-1", "TER-011", event_ref="REG-1", now_wallclock_s=1000.0)
        self.economy._set_balance("SHOP-1", 0.0)
        args = dict(event_ref="REP-X", now_wallclock_s=1000.0 + 43200.0)
        first = self.system.replenish("SHOP-1", **args)
        second = self.system.replenish("SHOP-1", **args)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        # replay nao reaplica o delta - saldo real continua o mesmo de depois da 1a chamada
        self.assertAlmostEqual(self.economy.wallet("SHOP-1")["balance"], first["balance_after"], places=4)

    def test_idempotent_conflict_different_payload(self):
        self.system.register_vendor("SHOP-1", "TER-011", event_ref="REG-1")
        with self.assertRaises(ConflictError):
            self.system.register_vendor("SHOP-1", "TER-008", event_ref="REG-1")

    def test_state_returns_tier_and_live_balance(self):
        self.system.register_vendor("SHOP-1", "TER-008", event_ref="REG-1")
        s = self.system.state("SHOP-1")
        self.assertEqual(s["vendor_ref"], "SHOP-1")
        self.assertEqual(s["welfare_tier"], "ALTO")
        self.assertAlmostEqual(s["current_balance"], 3000.0)

    def test_verify_passes_with_multiple_vendors_across_tiers(self):
        self.system.register_vendor("SHOP-ALTO", "TER-008", event_ref="R1")
        self.system.register_vendor("SHOP-MEDIO", "TER-011", event_ref="R2")
        self.system.register_vendor("SHOP-BAIXO", "TER-002", event_ref="R3")
        self.system.replenish("SHOP-ALTO", event_ref="P1")
        result = self.system.verify()
        self.assertEqual(result["status"], "PASS", result["failures"])
        self.assertEqual(result["vendors"], 3)
        self.assertEqual(result["events"], 4)


if __name__ == "__main__":
    unittest.main()
