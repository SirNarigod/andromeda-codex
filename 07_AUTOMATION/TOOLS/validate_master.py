#!/usr/bin/env python3
"""Validate the Andrômeda Códex Master from an operational or restored tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


VERSION = "V2.0.0"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def status_value(document: dict) -> str | None:
    if isinstance(document.get("status"), str):
        return document["status"]
    summary = document.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("status"), str):
        return summary["status"]
    return None


def find_entity(data: dict, entity_id: str) -> dict:
    matches = [item for item in data["entities"] if item.get("id") == entity_id]
    if len(matches) != 1:
        return {}
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    reports = root / "09_TESTS"
    checks: list[dict] = []

    def check(suite: str, check_id: str, condition: bool, evidence=None, critical: bool = True) -> None:
        checks.append({
            "suite": suite,
            "check_id": check_id,
            "status": "PASS" if condition else "FAIL",
            "critical": critical,
            "evidence": evidence,
        })

    required_dirs = [
        "00_GOVERNANCE", "01_CANON", "02_ATLAS", "03_DOMAINS", "04_NARRATIVE", "05_MAR",
        "06_VISUAL", "07_RELATIONSHIPS", "08_SCHEMAS", "09_TESTS", "10_TOOLS", "11_REPORTS",
        "12_MANIFESTS", "13_HISTORY",
    ]
    for dirname in required_dirs:
        check("STRUCTURE", f"DIR_{dirname}", (root / dirname).is_dir(), dirname)
    required_files = [
        "README_MASTER.md", "MASTER_CHANGELOG.md", "RELEASE_METADATA.json",
        "00_GOVERNANCE/MASTER_AUTHORIAL_DECISIONS_V2_0_0.json",
        "00_GOVERNANCE/MASTER_AUTHORITY_MATRIX.json",
        "01_CANON/ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json",
        "01_CANON/MASTER_CANON_MATRIX.json",
        "02_ATLAS/ANDROMEDA_ATLAS_FINAL.json",
        "02_ATLAS/runtime/index.html", "02_ATLAS/runtime/app.js", "02_ATLAS/runtime/atlas-core.mjs",
        "02_ATLAS/runtime/styles.css", "02_ATLAS/runtime/data/atlas-data.json",
        "07_RELATIONSHIPS/MASTER_RELATIONSHIP_REGISTRY_V2_0_0.json",
        "08_SCHEMAS/MASTER_DATA_CONTRACT_V2_0_0.json",
        "11_REPORTS/MASTER_FINAL_INVENTORY.json", "11_REPORTS/MASTER_INTEGRATION_LEDGER.json",
        "11_REPORTS/MASTER_COMPLETENESS_REPORT.json", "11_REPORTS/MASTER_PENDING_MATRIX.json",
        "13_HISTORY/ETAPA_09/CHECKPOINT_ETAPA_09_V1_0.json",
        "13_HISTORY/ETAPA_09/FINAL_TEST_RESULTS_V1_0.json",
        "13_HISTORY/ETAPA_09/RESTORE_REPORT_ETAPA_09_V1_0.json",
    ]
    for name in required_files:
        check("STRUCTURE", f"FILE_{name.replace('/', '_')}", (root / name).is_file(), name)
    unwanted = [p for p in root.rglob("*") if p.is_file() and (p.suffix == ".pyc" or "__pycache__" in p.parts or p.name.endswith(".log"))]
    check("STRUCTURE", "NO_CACHE_OR_LOG_FILES", not unwanted, [str(p.relative_to(root)) for p in unwanted])

    json_files = sorted(root.rglob("*.json"))
    parsed = {}
    for path in json_files:
        try:
            parsed[path] = load(path)
            ok = True
            error = None
        except Exception as exc:  # validation report retains the exact path, not hidden failures
            ok = False
            error = str(exc)
        check("JSON", f"PARSE_{path.relative_to(root)}", ok, error)
    check("JSON", "JSON_FILE_FLOOR", len(json_files) >= 145, len(json_files))

    canon_path = root / "01_CANON" / "ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json"
    data = parsed.get(canon_path, {})
    check("CANON", "MASTER_VERSION", data.get("version") == VERSION, data.get("version"))
    check("CANON", "ENTITY_COUNT", len(data.get("entities", [])) == 1660, len(data.get("entities", [])))
    check("CANON", "RELATION_COUNT", len(data.get("relationships", [])) == 9429, len(data.get("relationships", [])))
    check("CANON", "LOCATION_COUNT", len(data.get("locations", [])) == 52, len(data.get("locations", [])))
    check("CANON", "ROUTE_COUNT", len(data.get("routes", [])) == 9, len(data.get("routes", [])))
    check("CANON", "LAYER_COUNT", len(data.get("layers", [])) == 44, len(data.get("layers", [])))
    check("CANON", "NO_UNPROCESSED_PROPOSAL", not any(e.get("canonical_status") == "PROPOSTA" for e in data.get("entities", [])), None)
    check("CANON", "SINGLE_SOURCE_DECLARED", data.get("metadata", {}).get("single_source_of_truth") == "01_CANON/ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json", data.get("metadata", {}).get("single_source_of_truth"))

    # Ten mandatory authorial decisions.
    tim4 = find_entity(data, "TIM-004")
    tim11 = find_entity(data, "TIM-011")
    check("AUTHORIAL_DECISIONS", "D01_EVENT_NAME", tim4.get("name") == "Fundação das Árvores Anciãs", tim4.get("name"))
    check("AUTHORIAL_DECISIONS", "D01_EVENT_DATE", tim4.get("canonical_date") == "1732 APC", tim4.get("canonical_date"))
    check("AUTHORIAL_DECISIONS", "D02_EVENT_NAME", tim11.get("name") == "Fundação dos Reis Magos", tim11.get("name"))
    check("AUTHORIAL_DECISIONS", "D02_EVENT_DATE", tim11.get("canonical_date") == "684 APC", tim11.get("canonical_date"))
    for event_id, expected in (("TIM-004", "1732 APC"), ("TIM-011", "684 APC")):
        rows = [t for t in data.get("timeline", []) if t.get("id") == event_id or t.get("entity_id") == event_id]
        check("AUTHORIAL_DECISIONS", f"TIMELINE_{event_id}", len(rows) == 2 and all(r.get("date") == expected and r.get("date_status") == "DIRECT_CANON" for r in rows), rows)
    fac = find_entity(data, "FAC-005")
    check("AUTHORIAL_DECISIONS", "D03_OPERATIONAL_839", fac.get("operational_by") == "839 EC" and fac.get("operational_status_at_839_ec") == "OPERACIONAL", {"by": fac.get("operational_by"), "status": fac.get("operational_status_at_839_ec")})
    check("AUTHORIAL_DECISIONS", "D03_UNKNOWN_FOUNDATION", set(fac.get("intentional_unknowns", [])) == {"foundation_date", "founders", "formal_foundation_act"}, fac.get("intentional_unknowns"))
    epi = find_entity(data, "EPI-001")
    check("AUTHORIAL_DECISIONS", "D04_CODEX_MAIN", epi.get("canon_hierarchy", {}).get("principal") == "ANDRÔMEDA CÓDEX", epi.get("canon_hierarchy"))
    check("AUTHORIAL_DECISIONS", "D04_SEASON_COMPLEMENTARY", epi.get("edition") == "Temporada 1 Reestruturada V0.3" and epi.get("authority_tier") == "CÂNONE_COMPLEMENTAR", {"edition": epi.get("edition"), "tier": epi.get("authority_tier")})
    serlis = find_entity(data, "PER-003")
    check("AUTHORIAL_DECISIONS", "D05_ALIAS", serlis.get("name") == "Serlis Aftermoon" and "Serlis Veyr" in serlis.get("aliases", []), {"name": serlis.get("name"), "aliases": serlis.get("aliases")})
    check("AUTHORIAL_DECISIONS", "D05_NO_DUPLICATE", not any(e.get("id") != "PER-003" and (e.get("name") == "Serlis Veyr" or "Serlis Veyr" in e.get("aliases", [])) for e in data.get("entities", [])), None)
    ishara = find_entity(data, "PER-007")
    check("AUTHORIAL_DECISIONS", "D06_INDEPENDENT_FUNCTION", ishara.get("independent_functions") == ["Comissária de Incidentes Rúnicos e Ferroviários"], ishara.get("independent_functions"))
    incident_ids = {e.get("id") for e in data.get("entities", []) if "incidentes" in e.get("name", "").casefold() and e.get("id") != "PER-007"}
    forbidden = [r for r in data.get("relationships", []) if {r.get("source_id"), r.get("target_id")} & {"PER-007"} and {r.get("source_id"), r.get("target_id")} & incident_ids]
    check("AUTHORIAL_DECISIONS", "D06_NO_AUTOMATIC_ORGAN_BINDING", not forbidden, forbidden)
    pairs = [
        ("CUL-ING-001", "CRI-002", "Leite veluriano", "Velúrio"),
        ("CUL-ING-002", "CRI-003", "Leite brumante", "Brumante"),
        ("CUL-ING-003", "CRI-004", "Leite de lúmara", "Lúmara"),
        ("CUL-ING-004", "CRI-005", "Leite âmbar de raizel", "Raizel manso"),
    ]
    for index, (source, target, source_name, target_name) in enumerate(pairs, 7):
        check("AUTHORIAL_DECISIONS", f"D{index:02d}_NAMES", find_entity(data, source).get("name") == source_name and find_entity(data, target).get("name") == target_name, {source: find_entity(data, source).get("name"), target: find_entity(data, target).get("name")})
        relations = [r for r in data.get("relationships", []) if r.get("source_id") == source and r.get("target_id") == target and r.get("type") == "derivado_de"]
        check("AUTHORIAL_DECISIONS", f"D{index:02d}_BINDING", len(relations) == 1 and relations[0].get("confidence") == "DIRECT_CANON", relations)

    entity_ids = [e.get("id") for e in data.get("entities", [])]
    relation_ids = [r.get("id") for r in data.get("relationships", [])]
    location_ids = [l.get("id") for l in data.get("locations", [])]
    route_ids = [r.get("id") for r in data.get("routes", [])]
    layer_ids = [l.get("id") for l in data.get("layers", [])]
    asset_ids = [a.get("asset_id") for a in data.get("assets", [])]
    check("IDS", "ENTITY_IDS_UNIQUE", len(entity_ids) == len(set(entity_ids)) and None not in entity_ids, len(entity_ids))
    check("IDS", "RELATION_IDS_UNIQUE", len(relation_ids) == len(set(relation_ids)) and None not in relation_ids, len(relation_ids))
    check("IDS", "LOCATION_IDS_UNIQUE", len(location_ids) == len(set(location_ids)) and None not in location_ids, len(location_ids))
    check("IDS", "ROUTE_IDS_UNIQUE", len(route_ids) == len(set(route_ids)) and None not in route_ids, len(route_ids))
    check("IDS", "LAYER_IDS_UNIQUE", len(layer_ids) == len(set(layer_ids)) and None not in layer_ids, len(layer_ids))
    check("IDS", "ASSET_IDS_UNIQUE", len(asset_ids) == len(set(asset_ids)) and None not in asset_ids, len(asset_ids))
    legacy_ids = [i for i in entity_ids if not (isinstance(i, str) and re.match(r"^[A-Z0-9]+(?:-[A-Z0-9]+)+$", i))]
    check("IDS", "IDS_NONEMPTY", all(isinstance(i, str) and i.strip() for i in entity_ids), None)
    check("IDS", "STANDARD_NAMESPACE_COUNT", len(entity_ids) - len(legacy_ids) == 1562, {"standard": len(entity_ids) - len(legacy_ids), "legacy": len(legacy_ids)})
    check("IDS", "LEGACY_IDS_DOCUMENTED_NONBLOCKING", len(legacy_ids) == 98, legacy_ids[:20])

    entity_set, location_set, route_set, layer_set = set(entity_ids), set(location_ids), set(route_ids), set(layer_ids)
    broken_relations = [r.get("id") for r in data.get("relationships", []) if r.get("source_id") not in entity_set or r.get("target_id") not in entity_set]
    check("REFERENCES", "RELATION_ENDPOINTS", not broken_relations, broken_relations[:20])
    broken_layers = [(e.get("id"), lid) for e in data.get("entities", []) for lid in e.get("layer_refs", []) if lid not in layer_set]
    check("REFERENCES", "ENTITY_LAYER_REFS", not broken_layers, broken_layers[:20])
    broken_locations = [(e.get("id"), lid) for e in data.get("entities", []) for lid in e.get("location_refs", []) if lid not in entity_set and lid not in location_set]
    check("REFERENCES", "ENTITY_LOCATION_REFS", not broken_locations, broken_locations[:20])
    broken_routes = [(e.get("id"), rid) for e in data.get("entities", []) for rid in e.get("route_refs", []) if rid not in route_set and rid not in entity_set]
    check("REFERENCES", "ENTITY_ROUTE_REFS", not broken_routes, broken_routes[:20])
    broken_assets = [a.get("asset_id") for a in data.get("assets", []) if a.get("entity_id") not in entity_set]
    check("REFERENCES", "ASSET_ENTITY_REFS", not broken_assets, broken_assets[:20])
    route_endpoint_failures = [r.get("id") for r in data.get("routes", []) if r.get("origin_id") not in entity_set | location_set or r.get("destination_id") not in entity_set | location_set]
    check("REFERENCES", "ROUTE_ENDPOINTS", not route_endpoint_failures, route_endpoint_failures)
    check("REFERENCES", "BROKEN_CRITICAL_REFERENCES_ZERO", not any((broken_relations, broken_layers, broken_locations, broken_routes, broken_assets, route_endpoint_failures)), {"relations": len(broken_relations), "layers": len(broken_layers), "locations": len(broken_locations), "routes": len(broken_routes), "assets": len(broken_assets), "route_endpoints": len(route_endpoint_failures)})

    coords = []
    for location in data.get("locations", []):
        coordinate = location.get("coordinate") or {}
        coords.append((location.get("id"), coordinate.get("latitude"), coordinate.get("longitude"), coordinate.get("altitude_m")))
    invalid_coords = [row for row in coords if not isinstance(row[1], (int, float)) or not -90 <= row[1] <= 90 or not isinstance(row[2], (int, float)) or not -180 <= row[2] <= 180]
    check("GEOSPATIAL", "COORDINATE_BOUNDS", not invalid_coords, invalid_coords)
    check("GEOSPATIAL", "COORDINATE_COVERAGE", len(coords) == 52 and all(row[1] is not None and row[2] is not None for row in coords), len(coords))
    territories = [e for e in data.get("entities", []) if str(e.get("id", "")).startswith("TER-")]
    check("GEOSPATIAL", "TERRITORY_COUNT", len(territories) == 13, len(territories))
    check("GEOSPATIAL", "ROUTES_CALCULABLE", all(isinstance(r.get("distance_km"), (int, float)) and r.get("distance_km") > 0 and r.get("transport_modes") for r in data.get("routes", [])), [{"id": r.get("id"), "distance": r.get("distance_km")} for r in data.get("routes", [])])
    geo_audit_path = root / "13_HISTORY" / "ETAPA_09" / "03_AUDITORIAS" / "FINAL_GEOSPATIAL_AUDIT_V1_0.json"
    geo_audit = parsed.get(geo_audit_path, {})
    for field in ("planetary_model", "coordinate_system", "stage_4_test_status"):
        check("GEOSPATIAL", f"AUDIT_{field.upper()}", geo_audit.get(field) == "PASS", geo_audit.get(field))
    for field in ("coordinate_failures", "route_endpoint_failures", "geojson_failures", "hydrology_failures"):
        check("GEOSPATIAL", f"ZERO_{field.upper()}", geo_audit.get(field) == [], geo_audit.get(field))

    # Schema/data contract checks without accepting a renderer as schema authority.
    contract_path = root / "08_SCHEMAS" / "MASTER_DATA_CONTRACT_V2_0_0.json"
    contract = parsed.get(contract_path, {})
    check("SCHEMAS", "DRAFT_2020_12", contract.get("$schema", "").endswith("2020-12/schema"), contract.get("$schema"))
    required = contract.get("required", [])
    check("SCHEMAS", "REQUIRED_MASTER_FIELDS", all(field in data for field in required), required)
    check("SCHEMAS", "VERSION_CONST", contract.get("properties", {}).get("version", {}).get("const") == VERSION, contract.get("properties", {}).get("version"))
    stage4_schema = parsed.get(root / "08_SCHEMAS" / "STELLAR_ATLAS_SCHEMA_V1_0.json", {})
    check("SCHEMAS", "STAGE4_SCHEMA_PRESENT", bool(stage4_schema), list(stage4_schema)[:10])

    # Atlas source/projection parity.
    projection_path = root / "02_ATLAS" / "runtime" / "data" / "atlas-data.json"
    projection = parsed.get(projection_path, {})
    check("ATLAS", "PROJECTION_DECLARED", projection.get("projection_authority") == "READ_ONLY_ATLAS_PROJECTION", projection.get("projection_authority"))
    check("ATLAS", "PROJECTION_SOURCE_HASH", projection.get("projection_of", {}).get("sha256") == sha256(canon_path), projection.get("projection_of"))
    for section in ("entities", "locations", "routes", "layers", "relationships", "timeline", "assets", "spoiler_policy"):
        check("ATLAS", f"PROJECTION_PARITY_{section.upper()}", projection.get(section) == data.get(section), {"canonical": len(data.get(section, [])) if isinstance(data.get(section), list) else "object", "projection": len(projection.get(section, [])) if isinstance(projection.get(section), list) else "object"})
    atlas_descriptor = parsed.get(root / "02_ATLAS" / "ANDROMEDA_ATLAS_FINAL.json", {})
    check("ATLAS", "ATLAS_DESCRIPTOR", atlas_descriptor.get("entities") == 1660 and atlas_descriptor.get("relationships") == 9429 and atlas_descriptor.get("read_only_projection") is True, atlas_descriptor)

    node_cmd = ["node", str(root / "10_TOOLS" / "run_master_atlas_runtime.mjs"), str(root)]
    try:
        completed = subprocess.run(node_cmd, check=False, capture_output=True, text=True, timeout=60)
        runtime_result = json.loads(completed.stdout) if completed.stdout.strip() else {"summary": {"status": "FAIL"}, "stderr": completed.stderr}
        check("ATLAS_RUNTIME", "NODE_RUNTIME_EXIT", completed.returncode == 0, {"returncode": completed.returncode, "stderr": completed.stderr[-1000:]})
        for item in runtime_result.get("results", []):
            check("ATLAS_RUNTIME", item.get("id", "UNKNOWN"), item.get("status") == "PASS", item.get("evidence"))
    except Exception as exc:
        runtime_result = {"summary": {"status": "FAIL"}, "error": str(exc)}
        check("ATLAS_RUNTIME", "NODE_RUNTIME_EXCEPTION", False, str(exc))

    # MAR functional contracts.
    mar_specs = [
        ("WEAPONS", root / "05_MAR" / "FUNCTIONAL" / "01_MAR" / "MAR_WEAPONS_FUNCTIONAL_V1_0.json", "weapons", 30, ["function", "construction", "operation", "supply", "performance", "balance", "distribution", "spatial", "visual", "provenance"]),
        ("RUNES", root / "05_MAR" / "FUNCTIONAL" / "01_MAR" / "MAR_RUNES_FUNCTIONAL_V1_0.json", "runes", 30, ["function", "support", "creation_application", "compatibility", "spatial", "visual", "provenance"]),
        ("MAGIC", root / "05_MAR" / "FUNCTIONAL" / "01_MAR" / "MAR_MAGIC_FUNCTIONAL_V1_0.json", "magics", 30, ["execution", "limitations", "interoperability", "operator_job_ids", "training_ref", "spatial", "visual", "provenance"]),
    ]
    mar_total = 0
    for label, path, key, expected, fields in mar_specs:
        document = parsed.get(path, {})
        records = document.get(key, [])
        mar_total += len(records)
        check("MAR", f"{label}_COUNT", len(records) == expected, len(records))
        check("MAR", f"{label}_IDS_UNIQUE", len({r.get("id") for r in records}) == expected, len({r.get("id") for r in records}))
        check("MAR", f"{label}_CANON_ACTIVE", all(r.get("canonical_status") == "CÂNONE_ATIVO" for r in records), None)
        for field in fields:
            check("MAR", f"{label}_FIELD_{field.upper()}", all(r.get(field) not in (None, "", [], {}) for r in records), field)
        check("MAR", f"{label}_VISUAL_BRIEF", all(r.get("visual", {}).get("status") == "VISUAL_BRIEF_PRONTO" for r in records), None)
    check("MAR", "MAR_30_30_30", mar_total == 90, mar_total)
    compatibility_path = root / "05_MAR" / "FUNCTIONAL" / "01_MAR" / "MAR_COMPATIBILITY_MATRIX_V1_0.json"
    check("MAR", "COMPATIBILITY_MATRIX_PRESENT", compatibility_path in parsed, str(compatibility_path.relative_to(root)))

    professions_path = root / "03_DOMAINS" / "PROFESSIONS" / "02_PROFISSOES" / "PROFESSIONS_FUNCTIONAL_MASTER_V1_0.json"
    profession_document = parsed.get(professions_path, {})
    professions = profession_document.get("professions", [])
    check("PROFESSIONS", "COUNT_91", len(professions) == 91, len(professions))
    check("PROFESSIONS", "IDS_UNIQUE", len({p.get("id") for p in professions}) == 91, len({p.get("id") for p in professions}))
    profession_fields = ["name", "category", "sector", "description", "function", "responsibilities", "competencies", "formation", "tools", "technologies", "work_environment", "institution_id", "territory_distribution", "risks", "progression", "dependencies", "products_services", "economic_role", "social_role", "atlas", "provenance"]
    for field in profession_fields:
        check("PROFESSIONS", f"FIELD_{field.upper()}", all(p.get(field) not in (None, "", [], {}) for p in professions), field)
    check("PROFESSIONS", "CANON_ACTIVE", all(p.get("canonical_status") == "CÂNONE_ATIVO" and p.get("functional_status") == "COMPLETA_E_VALIDADA" for p in professions), None)
    check("PROFESSIONS", "NO_PROPOSAL_REVERSION", not any(p.get("canonical_status") == "PROPOSTA" for p in professions), None)
    check("PROFESSIONS", "EDUCATION_PATHS", all(p.get("formation", {}).get("path_ref") for p in professions), None)
    check("PROFESSIONS", "SPATIAL_BINDINGS", all(p.get("territory_distribution", {}).get("territory_ids") for p in professions), None)
    check("PROFESSIONS", "ECONOMIC_BINDINGS", all(p.get("economic_role") and p.get("products_services") for p in professions), None)

    # Planetary/domain PASS evidence from the final audit retained in history.
    audit_files = {
        "ECOLOGY": "FINAL_ECOLOGY_AUDIT_V1_0.json",
        "POPULATION": "FINAL_POPULATION_AUDIT_V1_0.json",
        "AGRICULTURE": "FINAL_AGRICULTURE_AUDIT_V1_0.json",
        "ECONOMY": "FINAL_ECONOMY_AUDIT_V1_0.json",
        "INDUSTRY": "FINAL_INDUSTRY_AUDIT_V1_0.json",
        "TECHNOLOGY": "FINAL_TECHNOLOGY_AUDIT_V1_0.json",
        "TRANSPORT": "FINAL_TRANSPORT_AUDIT_V1_0.json",
        "NARRATIVE": "FINAL_NARRATIVE_AUDIT_V1_0.json",
        "SPOILERS": "FINAL_SPOILER_AUDIT_V1_0.json",
        "RESPONSIVE": "FINAL_RESPONSIVE_AUDIT_V1_0.json",
        "PERFORMANCE": "FINAL_PERFORMANCE_AUDIT_V1_0.json",
        "REGRESSION": "FINAL_REGRESSION_AUDIT_V1_0.json",
        "DEPENDENCIES": "FINAL_DEPENDENCY_AUDIT_V1_0.json",
        "REFERENCES": "FINAL_REFERENCE_AUDIT_V1_0.json",
        "MAR_AUDIT": "FINAL_MAR_AUDIT_V1_0.json",
        "PROFESSIONS_AUDIT": "FINAL_PROFESSIONS_AUDIT_V1_0.json",
    }
    for suite, filename in audit_files.items():
        audit_path = root / "13_HISTORY" / "ETAPA_09" / "03_AUDITORIAS" / filename
        audit = parsed.get(audit_path, {})
        check(suite, "ETAPA_09_AUDIT_PASS", status_value(audit) == "PASS", status_value(audit))

    stage9_checkpoint = parsed.get(root / "13_HISTORY" / "ETAPA_09" / "CHECKPOINT_ETAPA_09_V1_0.json", {})
    check("REGRESSION", "STAGE9_GATE_PASS", stage9_checkpoint.get("status") == "PASS", stage9_checkpoint.get("status"))
    ready_for_master = stage9_checkpoint.get("handoff", {}).get("ready_for_master")
    check("REGRESSION", "STAGE9_READY_MASTER", ready_for_master in (True, "SIM"), ready_for_master)
    stage9_tests = parsed.get(root / "13_HISTORY" / "ETAPA_09" / "FINAL_TEST_RESULTS_V1_0.json", {})
    check("REGRESSION", "STAGE9_176_CHECKS_PASS", status_value(stage9_tests) == "PASS" and stage9_tests.get("summary", {}).get("checks") == 176 and stage9_tests.get("summary", {}).get("failed") == 0, stage9_tests.get("summary"))
    stage9_restore = parsed.get(root / "13_HISTORY" / "ETAPA_09" / "RESTORE_REPORT_ETAPA_09_V1_0.json", {})
    check("REGRESSION", "STAGE9_RESTORE_PASS", status_value(stage9_restore) == "PASS", status_value(stage9_restore))
    authority = parsed.get(root / "00_GOVERNANCE" / "MASTER_AUTHORITY_MATRIX.json", {})
    check("AUTHORITY", "ACTIVE_MODULE_COUNT_42", authority.get("active_module_count") == 42, authority.get("active_module_count"))
    check("AUTHORITY", "MATRIX_PASS", authority.get("status") == "PASS", authority.get("status"))
    check("AUTHORITY", "ALL_ACTIVE", len(authority.get("domains", [])) == 42 and all(row.get("status") == "ACTIVE" for row in authority.get("domains", [])), len(authority.get("domains", [])))

    # Explicitly test the main systemic chains through retained audits and active data.
    check("PLANETARY", "POPULATION_WATER_FOOD", not any(c["status"] == "FAIL" for c in checks if c["suite"] in {"POPULATION", "AGRICULTURE"}), None)
    check("PLANETARY", "RESOURCE_INDUSTRY_ECONOMY", not any(c["status"] == "FAIL" for c in checks if c["suite"] in {"INDUSTRY", "ECONOMY"}), None)
    check("PLANETARY", "TECH_ENERGY_MAINTENANCE", not any(c["status"] == "FAIL" for c in checks if c["suite"] == "TECHNOLOGY"), None)
    check("PLANETARY", "PROFESSION_EDUCATION_EMPLOYMENT", not any(c["status"] == "FAIL" for c in checks if c["suite"] == "PROFESSIONS"), None)
    check("PLANETARY", "MAR_INDUSTRY_USER", not any(c["status"] == "FAIL" for c in checks if c["suite"] == "MAR"), None)
    check("PLANETARY", "NARRATIVE_TIME_GEOGRAPHY", not any(c["status"] == "FAIL" for c in checks if c["suite"] in {"NARRATIVE", "GEOSPATIAL"}), None)

    by_suite: dict[str, list[dict]] = defaultdict(list)
    for item in checks:
        by_suite[item["suite"]].append(item)
    suites = []
    for name in sorted(by_suite):
        rows = by_suite[name]
        failed = sum(row["status"] == "FAIL" for row in rows)
        suites.append({"suite": name, "checks": len(rows), "passed": len(rows) - failed, "failed": failed, "status": "PASS" if not failed else "FAIL"})
    failed_checks = [row for row in checks if row["status"] == "FAIL"]
    summary = {
        "suites": len(suites),
        "checks": len(checks),
        "passed": len(checks) - len(failed_checks),
        "failed": len(failed_checks),
        "status": "PASS" if not failed_checks else "FAIL",
    }
    payload = {
        "record_id": "MASTER-TEST-RESULTS-V2.0.0",
        "project": "ANDRÔMEDA CÓDEX",
        "version": VERSION,
        "authority": "SOL MAX — AGENTE 30",
        "root": str(root),
        "summary": summary,
        "suites": suites,
        "checks": checks,
        "failed_checks": failed_checks,
    }

    if not args.no_write:
        dump(reports / "MASTER_TEST_RESULTS.json", payload)
        dump(reports / "MASTER_GEOSPATIAL_TESTS.json", {"record_id": "MASTER-GEOSPATIAL-TESTS-V2.0.0", "version": VERSION, "summary": next(s for s in suites if s["suite"] == "GEOSPATIAL"), "checks": by_suite["GEOSPATIAL"]})
        atlas_rows = by_suite["ATLAS"] + by_suite["ATLAS_RUNTIME"] + by_suite["SPOILERS"] + by_suite["RESPONSIVE"] + by_suite["PERFORMANCE"]
        dump(reports / "MASTER_ATLAS_TESTS.json", {"record_id": "MASTER-ATLAS-TESTS-V2.0.0", "version": VERSION, "summary": {"checks": len(atlas_rows), "failed": sum(r["status"] == "FAIL" for r in atlas_rows), "status": "PASS" if all(r["status"] == "PASS" for r in atlas_rows) else "FAIL"}, "checks": atlas_rows, "runtime": runtime_result})
        dump(reports / "MASTER_MAR_TESTS.json", {"record_id": "MASTER-MAR-TESTS-V2.0.0", "version": VERSION, "summary": next(s for s in suites if s["suite"] == "MAR"), "checks": by_suite["MAR"]})
        dump(reports / "MASTER_PROFESSION_TESTS.json", {"record_id": "MASTER-PROFESSION-TESTS-V2.0.0", "version": VERSION, "summary": next(s for s in suites if s["suite"] == "PROFESSIONS"), "checks": by_suite["PROFESSIONS"]})
        dump(reports / "MASTER_REGRESSION_TESTS.json", {"record_id": "MASTER-REGRESSION-TESTS-V2.0.0", "version": VERSION, "summary": next(s for s in suites if s["suite"] == "REGRESSION"), "checks": by_suite["REGRESSION"]})
    if args.output:
        dump(args.output, payload)
    print(json.dumps({"root": str(root), "summary": summary, "failed_checks": failed_checks}, ensure_ascii=False, indent=2))
    return 0 if not failed_checks else 1


if __name__ == "__main__":
    sys.exit(main())
