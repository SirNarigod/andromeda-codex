from __future__ import annotations
from typing import Any

from integrated_engine_v12 import IntegratedLivingEngineV12
from country_living_bridge import CountryLivingDomainBridge
from living_runtime import ValidationError


class IntegratedLivingEngineV13(IntegratedLivingEngineV12):
    """Country↔Living integration root.

    Country Scale owns spatial aggregation/projection. Living domain engines own mutable
    commerce/combat/social consequences. Numeric runtime state remains non-canonical.
    """

    VERSION = "V1.3.0"
    AUTHORITY = "INTEGRATED_LIVING_V1_3_COUNTRY_DOMAIN_BRIDGE"

    def __init__(self, db_path=':memory:', *, master_release_path):
        super().__init__(db_path, master_release_path=master_release_path)
        self.country_bridges: dict[str, CountryLivingDomainBridge] = {}

    def create_world(self, owner_scope: str, seed: int, *, mode='PRIVATE', ticks_per_day=24,
                     population_reference_seed=1000, load_relationships=True,
                     country_territory_id='TER-011') -> dict[str, Any]:
        if self.runtime.master_version != 'V2.0.1':
            raise ValidationError('Andromeda ARPG foundation requires sealed Master V2.0.1')
        report = super().create_world(
            owner_scope, seed, mode=mode, ticks_per_day=ticks_per_day,
            population_reference_seed=population_reference_seed,
            load_relationships=load_relationships,
            country_territory_id=country_territory_id,
        )
        # V1.1/V1.2 compatibility remains canonical-only (30 MAR weapons).
        # Country/ARPG V1.3+ explicitly opts into 54 author-approved gameplay-derived records.
        report['commerce'] = self.commerce.load_catalog(self.master_release_path, include_gameplay_derived=True)
        wid = report['world']['world_instance_id']
        bridge = CountryLivingDomainBridge(self, wid, self.country(wid))
        self.country_bridges[wid] = bridge
        integrity = bridge.full_integrity_check()
        report['version'] = self.VERSION
        report['authority'] = self.AUTHORITY
        report['country_living_bridge'] = {
            'status': integrity['status'],
            'authority': bridge.AUTHORITY,
            'integrity': integrity,
            'parallel_purchase_path': 'DISABLED',
            'parallel_hunt_path': 'DISABLED',
        }
        report['master_runtime_binding'] = {
            'detected_master_version': self.runtime.master_version,
            'detected_master_sha256': self.runtime.master_release_sha256,
            'authority': 'READ_ONLY_MASTER_BASELINE',
        }
        if integrity['status'] != 'PASS':
            raise ValidationError(f"V1.3 bridge bootstrap failed: {integrity['failures']}")
        return report

    def bridge(self, world_instance_id: str) -> CountryLivingDomainBridge:
        return self.country_bridges[world_instance_id]

    def health_v13(self, world_instance_id: str) -> dict[str, Any]:
        base = self.health_v12(world_instance_id)
        bridge = self.bridge(world_instance_id).full_integrity_check()
        failures = []
        if base['status'] != 'PASS':
            failures += ['V12:' + x for x in base.get('failures', [])]
        if bridge['status'] != 'PASS':
            failures += ['BRIDGE:' + x for x in bridge.get('failures', [])]
        world = self.runtime.get_world(world_instance_id)
        baseline = world.get('baseline') or {}
        if baseline.get('master_version') != self.runtime.master_version:
            failures.append('MASTER_VERSION_WORLD_RUNTIME_DIVERGENCE')
        if baseline.get('release_sha256') != self.runtime.master_release_sha256:
            failures.append('MASTER_HASH_WORLD_RUNTIME_DIVERGENCE')
        return {
            'status': 'PASS' if not failures else 'FAIL',
            'failures': failures,
            'v12': base,
            'bridge': bridge,
            'master_version': self.runtime.master_version,
            'master_release_sha256': self.runtime.master_release_sha256,
            'authority': self.AUTHORITY,
        }
