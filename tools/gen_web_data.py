"""Gera web/src/data/*.json a partir do conteudo canonico (somente leitura).

Copia/transforma (projecao de subconjuntos) - NUNCA edita as fontes.
Uso: python3 tools/gen_web_data.py   (ou: npm run gen:data, dentro de web/)
"""
import glob
import hashlib
import json
import os
import statistics as _st

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)  # raiz do repositorio
OUTD = os.path.join(BASE, "web", "src", "data")
os.makedirs(OUTD, exist_ok=True)

SOURCES = []  # (path_relativo, sha256) para o manifesto


def load(rel):
    p = os.path.join(BASE, rel)
    with open(p, encoding="utf-8") as f:
        raw = f.read()
    SOURCES.append((rel, hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]))
    return json.loads(raw)


def pick(d, *ks):
    for k in ks:
        if d.get(k) is not None:
            return d[k]
    return None


D = {}
# territorios
ts = load("01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_TERRAIN_TRAVEL_SYSTEM_DEV_V1_0.json")
coords = {}
try:
    ci = load("01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_REGION_COORDINATE_INDEX_DEV_V1_0.json")
    for r in ci.get("regions", []):
        c = r.get("coordinate_center", {})
        coords[r["region_id"]] = [c.get("longitude", 0), c.get("latitude", 0)]
except Exception:
    pass
D["territories"] = [{"id": t["territory_id"], "name": t.get("title", t["territory_id"]),
                     "terrain": t.get("terrain_type"), "transport": t.get("primary_transport_mode"),
                     "xy": coords.get(t["territory_id"], [0, 0])}
                    for t in ts["territory_terrain_profile"]]
if not any(t["id"] == "TER-020" for t in D["territories"]):
    D["territories"].append({"id": "TER-020", "name": "Região Autônoma de Nérion",
                             "terrain": "URBANO_TECNOLOGICO", "transport": "TERRESTRE", "xy": [0, 0]})
# rotas
rn = load("01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_ROUTE_NETWORK_DEV_V1_0.json")
D["routes"] = [{"id": r["route_id"], "name": r.get("name"), "from": r.get("from"),
                "to": r.get("to"), "mode": r.get("transport_mode"), "scale": r.get("scale")}
               for r in rn.get("routes", [])]
# paisagens
ls = load("01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/STELLAR_LANDSCAPE_FEATURES_INDEX_DEV_V1_0.json")
D["landscapes"] = [{"id": f["feature_id"], "name": f.get("name"), "type": f.get("feature_type"),
                    "sub": f.get("subregion_id"), "ter": f.get("territory_id")} for f in ls["features"]]
# criaturas
bs = load("04_MECANICAS/CRIATURAS/MAR_BESTIARY_GAMEPLAY_STATS_DEV_V1_0.json")
D["creatures"] = [{"id": c["creature_id"], "name": c.get("name"), "tier": c.get("threat_tier"),
                   "hp": c["stats"]["hp"], "df": c["stats"]["defense"], "sp": c["stats"]["speed"],
                   "th": c["stats"]["threat"], "grp": c.get("group_structure"),
                   "act": c.get("primary_action"), "yield": c.get("resource_yield"),
                   "trait": (c.get("special_trait") or "")[:160], "hab": c.get("habitat_ref")}
                  for c in bs["creatures"]]
# npcs taticos
D["npcs"] = []
for f in sorted(glob.glob(os.path.join(BASE, "04_MECANICAS", "NPCS", "MAR_NPC_ROSTER_*.json"))):
    SOURCES.append((os.path.relpath(f, BASE), "glob"))
    d = json.load(open(f, encoding="utf-8"))
    for n in d.get("npcs", []):
        pb = n.get("power_budget", {}) or {}
        D["npcs"].append({"id": n.get("npc_id"), "name": n.get("name"),
                          "cls": n.get("class_name"), "tier": n.get("tier"), "role": n.get("role"),
                          "hp": pb.get("hp"), "sp": pb.get("speed"), "dg": pb.get("damage_mod"),
                          "ar": pb.get("armor"), "wp": n.get("weapon_ids", []),
                          "ps": (n.get("passive_skill") or {}).get("name"),
                          "as": (n.get("active_skill") or {}).get("name"),
                          "sub": n.get("subregion_id")})
zr = load("04_MECANICAS/NPCS/MAR_CORRUPTED_NPC_ROSTER_DEV_V1_0.json")
for n in zr.get("npcs", []):
    pb = n.get("power_budget", {}) or {}
    D["npcs"].append({"id": n.get("npc_id"), "name": n.get("name"), "cls": "Corrompidos(ZUM)",
                      "tier": n.get("tier"), "role": "ASSALTO", "hp": pb.get("hp"),
                      "sp": pb.get("speed"), "dg": pb.get("damage_mod"), "ar": pb.get("armor"),
                      "ps": (n.get("passive_skill") or {}).get("name"),
                      "as": (n.get("active_skill") or {}).get("name"), "sub": n.get("subregion_id")})
# civis
try:
    cv = load("04_MECANICAS/NPCS/STELLAR_MINOR_NPC_CATALOG_DEV_V1_0.json")
    cl = cv.get("minor_npcs", [])
    D["civilians"] = [{"id": c.get("civ_id"), "name": c.get("name"), "job": c.get("job_ref"),
                       "est": c.get("assigned_est"), "tier": c.get("mastery_tier")} for c in cl]
except Exception:
    D["civilians"] = []
# classes + atributos (medianas da matriz) + PV base
cl = load("01_LORE/CANON_DERIVADO_ATIVO/SOCIEDADES/CLASSES/MAR_PLAYABLE_CLASSES_LORE_DEV_V1_0.json")
_CLS_PREF = {"Nativos": "NAT", "Soldados": "SOL", "Androids": "AND", "Magos": "MAG", "Corrompidos": "COR"}
D["classes"] = [{"id": c.get("class_name"), "name": c.get("class_name"),
                 "desc": (c.get("identity", "") or "")[:220],
                 "fam": c.get("armament_family"), "pref": _CLS_PREF.get(c.get("class_name"))}
                for c in cl.get("classes", [])]
_WFULL = {}


def _wfull(o):
    if isinstance(o, dict):
        if "weapon_id" in o and o["weapon_id"] not in _WFULL:
            _WFULL[o["weapon_id"]] = o.get("stats", {}) or {}
        else:
            for v in o.values():
                _wfull(v)
    elif isinstance(o, list):
        for v in o:
            _wfull(v)


for f in sorted(glob.glob(os.path.join(BASE, "04_MECANICAS", "ITENS_E_ARMAS", "*.json"))):
    try:
        _wfull(json.load(open(f, encoding="utf-8")))
    except Exception:
        pass
_ATTR = {}
_mx = load("04_MECANICAS/ITENS_E_ARMAS/MAR_CLASS_ARMAMENT_MATRIX_DEV_V1_0.json")
for c in _mx.get("classes", []):
    ss = [_WFULL[i] for i in c.get("weapon_ids", []) if i in _WFULL]
    if not ss:
        continue
    med = lambda k: round(_st.median([x.get(k) or 0 for x in ss]))
    _ATTR[c.get("class_name")] = {"FOR": med("power"), "AGI": med("handling"), "VIT": med("durability"),
                                  "TEC": med("tech_affinity"), "MAG": med("magic_affinity"), "DEF": med("defense")}
_HP = {"Nativos": 28, "Soldados": 30, "Androids": 28, "Magos": 28, "Corrompidos": 28}
for c in D["classes"]:
    c["attrs"] = _ATTR.get(c["name"], {"FOR": 40, "AGI": 40, "VIT": 40, "TEC": 40, "MAG": 40, "DEF": 40})
    c["hp"] = _HP.get(c["name"], 28)
# mochilas
D["packs"] = [{"id": "EQP-002", "slots": 20, "derived": False},
              {"id": "MOCHILA-MEDIA", "name": "Mochila de Viagem", "slots": 35, "price": "MÉDIO",
               "cat": "EQUIP/Logística", "wt": 1.1, "desc": "Mochila ampliada de couro e armação leve.",
               "fx": {"pack": 35}, "derived": True},
              {"id": "MOCHILA-GRANDE", "name": "Mochila de Expedição", "slots": 50, "price": "ALTO",
               "cat": "EQUIP/Logística", "wt": 1.9, "desc": "Mochila de expedição com armação reforçada.",
               "fx": {"pack": 50}, "derived": True}]
# habilidades
def _skfx(sid, kind):
    if kind == "PASSIVE":
        if any(k in sid for k in ["AUTORREPARO", "CASCA", "FLUXO", "COURACA"]):
            return {"regen_pct": 2, "when": "hp<50"}
        if any(k in sid for k in ["BLINDAGEM", "RESISTENCIA", "INSTINTO", "RESILIENCIA", "MIRA"]):
            return {"dr": 0.20, "when": "hp<30"}
        if any(k in sid for k in ["PLACAS", "PELE", "COLETE"]):
            return {"dr": 0.08}
        return {"sp_regen": 10}
    if any(k in sid for k in ["PICO", "FURIA", "RAJADA", "CONVERGENCIA", "SURTO"]):
        return {"buff": 0.25}
    if any(k in sid for k in ["REPARO", "SEIVA", "BENCAO", "CATAPLASMA", "CURA"]):
        return {"heal_pct": 30, "ally": True}
    if any(k in sid for k in ["SOBRECARGA", "INVESTIDA", "IMPULSO", "REFORCO", "AVANCO_RADICULAR"]):
        return {"move": 4, "buff": 0.30}
    return {"move": 6, "cleanse": ["RAIZ"]}


D["skills"] = []
_sseen = set()
for f in sorted(glob.glob(os.path.join(BASE, "04_MECANICAS", "NPCS", "MAR_NPC_ROSTER_*.json"))):
    try:
        _nd = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    for n in _nd.get("npcs", []):
        for k in ["active_skill", "passive_skill"]:
            s = n.get(k)
            if isinstance(s, dict) and s.get("skill_id") not in _sseen:
                _sseen.add(s["skill_id"])
                _cd = s.get("cooldown_s")
                D["skills"].append({"id": s.get("skill_id"), "name": s.get("name"), "kind": s.get("skill_kind"),
                                    "cls": str(s.get("skill_id", "")).split("-")[0],
                                    "cost": s.get("resource_cost"), "cdr": max(1, round(_cd / 6)) if _cd else None,
                                    "fx": _skfx(s.get("skill_id", ""), s.get("skill_kind")),
                                    "desc": s.get("effect")})
# armas
mx = D["_mx"] = None
mx = load("04_MECANICAS/ITENS_E_ARMAS/MAR_CLASS_ARMAMENT_MATRIX_DEV_V1_0.json")
D["arsenal"] = {"total_weapons": mx.get("total_weapon_count"), "total_npcs": mx.get("total_npc_count"),
                "by_class": mx.get("classes", [])}
del D["_mx"]
# quests
D["quests"] = []
for f in sorted(glob.glob(os.path.join(BASE, "04_MECANICAS", "QUESTS_DINAMICAS", "*.json"))):
    SOURCES.append((os.path.relpath(f, BASE), "glob"))
    q = json.load(open(f, encoding="utf-8"))
    D["quests"].append({"id": q.get("record_id"), "title": q.get("title"), "loc": q.get("locality"),
                        "premise": (q.get("premise") or "")[:260],
                        "phases": [p.get("id") for p in q.get("phases", [])],
                        "res": [{"id": r.get("id"), "t": r.get("title")} for r in q.get("resolutions", [])]})
# construcoes
D["est"] = []
for f in sorted(glob.glob(os.path.join(BASE, "01_LORE", "CANON_DERIVADO_ATIVO", "CONSTRUCOES", "EST-*.json"))):
    e = json.load(open(f, encoding="utf-8"))
    D["est"].append({"id": e.get("est_id"), "name": e.get("name"), "type": e.get("building_type"),
                     "loc": e.get("parent_locality"), "sub": e.get("parent_subregion"),
                     "ter": e.get("parent_political_unit"),
                     "fn": (e.get("function") or "")[:140]})
# AGZ + minerais + bandas + speeds + varga
D["agz"] = [{"id": z.get("agz_id"), "t": z.get("title"), "ter": z.get("parent_political_unit")}
            for z in load("01_LORE/CANON_DERIVADO_ATIVO/AGRICULTURA/AGZ_INDEX_DEV_V1_0.json")["zones"]]
D["agz"] += [{"id": z.get("agz_id"), "t": z.get("title"), "ter": z.get("parent_political_unit")}
             for z in load("01_LORE/CANON_DERIVADO_ATIVO/AGRICULTURA/AGZ_EXTENSION_098_103_DEV_V1_0.json")["zones"]]
ml = load("04_MECANICAS/ECONOMIA_E_RECURSOS/MINERAL_RESOURCE_LOCALITY_LINKS_DEV_V1_0.json")
D["minerals"] = [{"id": r["resource_id"], "n": r["resource_name"], "prim": r.get("primary_territory"),
                  "sec": r.get("secondary_territories", [])} for r in ml["resources"]]
D["bands"] = [{"n": "CLINCH", "m": 1.0, "melee": 1.15, "ranged": 0, "evm": 0.7, "grapple": True},
              {"n": "IN_FIGHTING", "m": 2.75, "melee": 1.05, "ranged": 0.5, "evm": 0.85},
              {"n": "ECQ", "m": 6.0, "melee": 0.9, "ranged": 0.75, "evm": 1.0, "longpen": 0.7},
              {"n": "MID_RANGE", "m": 20.0, "melee": 0, "ranged": 1.0, "evm": 1.1},
              {"n": "LONG_RANGE", "m": 999.0, "melee": 0, "ranged": 1.0, "evm": 1.15, "sniper": 1.1}]
D["speeds"] = {"pe": "4-5 km/h", "carroca": "10-15", "trem": "35-60", "nave": "40-80"}
D["weapons"] = []
seen = set()


def _walk(o, acc):
    if isinstance(o, dict):
        if "weapon_id" in o and o["weapon_id"] not in seen:
            seen.add(o["weapon_id"])
            st, ph = o.get("stats", {}) or {}, o.get("physics", {}) or {}
            acc.append({"id": o.get("weapon_id"), "name": o.get("name"),
                        "cls": o.get("class_name"), "fam": (o.get("family") or "").split("(")[0].strip(),
                        "pow": st.get("power"), "rch": st.get("reach"), "hdl": st.get("handling"),
                        "ovr": st.get("overall"), "wt": o.get("weight_kg"),
                        "traj": ph.get("trajectory_type"), "imp": ph.get("impact_type"),
                        "area": ph.get("area_effect"), "tier": o.get("runification_tier"),
                        "prod": o.get("produced_at")})
        else:
            for v in o.values():
                _walk(v, acc)
    elif isinstance(o, list):
        for v in o:
            _walk(v, acc)


for f in sorted(glob.glob(os.path.join(BASE, "04_MECANICAS", "ITENS_E_ARMAS", "*.json"))):
    try:
        _walk(json.load(open(f, encoding="utf-8")), D["weapons"])
    except Exception:
        pass
D["varga"] = load("01_LORE/CANON_DERIVADO_ATIVO/GEOGRAFIA/TERRAS_LIVRES/SUBREGIOES/VARGA_VERTICAL_SLICE_MAP_V1.json")["points_of_interest"]
# itens
D["items"] = []
_med = load("04_MECANICAS/ECONOMIA_E_RECURSOS/STELLAR_MEDICINE_CATALOG_DEV_V1_0.json").get("medicines", [])
for x in _med:
    cat = x.get("category", "")
    fx = {"heal_pct": 30} if cat == "CURATIVO" else ({"cure": ["ESPORO"]} if "TOXINA" in cat else {"none": True})
    D["items"].append({"id": x.get("med_id"), "name": x.get("name"), "cat": "MEDICAMENTO/" + cat,
                       "wt": x.get("weight_kg"), "price": x.get("price_tier"), "prod": x.get("produced_at"),
                       "desc": x.get("description"), "link": x.get("notable_link"), "fx": fx})
_eq = load("04_MECANICAS/ECONOMIA_E_RECURSOS/STELLAR_SUPPORT_EQUIPMENT_DEV_V1_0.json").get("equipment", [])
for x in _eq:
    fx = {"heal_pct": 30, "cure": ["ESPORO"]} if x.get("equip_id") == "EQP-001" else {"none": True}
    D["items"].append({"id": x.get("equip_id"), "name": x.get("name"), "cat": "EQUIP/" + x.get("category", ""),
                       "wt": x.get("weight_kg"), "price": x.get("price_tier"), "prod": x.get("produced_at"),
                       "desc": x.get("description"), "link": x.get("notable_link"), "fx": fx})
_ar = load("04_MECANICAS/ECONOMIA_E_RECURSOS/STELLAR_ARMOR_CATALOG_DEV_V1_0.json").get("armors", [])
for x in _ar:
    D["items"].append({"id": x.get("armor_id"), "name": x.get("name"), "cat": "ARMADURA/" + x.get("class_name", ""),
                       "wt": x.get("weight_kg"), "price": x.get("price_tier"), "prod": x.get("produced_at_name"),
                       "desc": x.get("description"), "link": x.get("produced_at_name"),
                       "fx": {"armor": x.get("armor_bonus"), "cls": x.get("class_name"), "tier": x.get("tier")}})
_kit = load("04_MECANICAS/ITENS_E_ARMAS/VARGA_STARTER_KIT_V1.json").get("items", [])
for x in _kit:
    D["items"].append({"id": x.get("id"), "name": x.get("title"), "cat": "KIT_VARGA/" + x.get("type", ""),
                       "wt": None, "price": None, "prod": None,
                       "desc": x.get("use"), "link": None, "fx": {"none": True}})
_cur = load("04_MECANICAS/ECONOMIA_E_RECURSOS/STELLAR_CURRENCY_SYSTEM_DEV_V1_0.json")
D["currencies"] = [{"id": "CUR-000", "name": "Stavias", "ter": None, "strength": "UNIVERSAL", "mint": None}]
for c in _cur.get("territorial_currencies", []):
    D["currencies"].append({"id": c.get("currency_id"), "name": c.get("unit_name"), "ter": c.get("territory_id"),
                            "strength": c.get("strength_tier"), "mint": c.get("mint_authority")})
_eco = load("04_MECANICAS/ECONOMIA_E_RECURSOS/STELLAR_SYSTEMIC_ECONOMY_STATE_DEV_V1_0.json").get("territory_states", [])
D["econ"] = [{"ter": t.get("territory_id"), "food": t.get("food_security"), "short": t.get("shortage_pressure")} for t in _eco]
D["commerce"] = {"tiers": ["BAIXO", "MÉDIO", "ALTO", "MUITO_ALTO"],
                 "runtime_prices": {"BAIXO": 10, "MÉDIO": 25, "ALTO": 60, "MUITO_ALTO": 150},
                 "note": "RUNTIME_ONLY (lei: PRICES_CURRENCY_STOCKS_AND_INVENTORIES_ARE_RUNTIME_ONLY). Tiers do repo; números editáveis pelo mestre."}
_fa = load("01_LORE/CANON_MASTER_V2/FAUNA/MASTER_FAUNA_DISTRIBUTION_V2_0_0.json")["data"]["distributions"]
D["fauna"] = [{"cri": x["entity_id"], "ter": x["distribution_primary"]["territory_id"],
               "also": x.get("distribution_secondary_territory_ids") or [],
               "bio": x.get("biome_ids") or []}
              for x in _fa if str(x.get("entity_id", "")).startswith("CRI-")]
_enc = load("04_MECANICAS/INIMIGOS_E_COMBATE/STELLAR_ENCOUNTER_CATALOG_V1_0.json")
D["enc_profiles"] = [{"id": p.get("id"), "src": p.get("source"), "title": p.get("title"), "mode": p.get("mode"),
                      "disp": p.get("default_disposition"), "trig": p.get("trigger_context", []),
                      "nonviol": p.get("nonviolent_options", []), "story": p.get("story_yield")}
                     for p in _enc.get("profiles", [])]
D["loot"] = {"table": {"PASSIVO": 5, "HOSTIL": 15},
             "note": "RUNTIME_ONLY (mesma lei dos preços). Vestígio narrativo (yield) + stavias de referência; mestre ajusta."}
for _it in D["items"]:
    if _it["id"] == "EQP-002":
        _it["fx"] = {"pack": 20}
D["items"].extend([{"id": p["id"], "name": p["name"], "cat": p["cat"], "wt": p["wt"], "price": p["price"],
                    "prod": None, "desc": p["desc"], "link": None, "fx": p["fx"]}
                   for p in D["packs"] if p.get("derived")])
D["items"].append({"id": "KIT-VARGA", "name": "Kit de Varga (bundle)", "cat": "KIT_VARGA/BUNDLE",
                   "wt": 1.0, "price": "MÉDIO", "prod": None,
                   "desc": "Lâmina de travessia + arma curta de serviço + kit de contenção de campo.",
                   "link": None, "fx": {"kit": ["VARGA-ITEM-001", "VARGA-ITEM-002", "VARGA-ITEM-003"]}})
D["conditions"] = [
    {"id": "CONTENCAO", "icon": "⛓", "name": "Contenção não-letal (WPN-CNT)", "dur": None, "atk": -4, "evm": 0.7, "dot": 0,
     "desc": "IMPACTO_NÃO_LETAL; imobiliza (sem mover/dragar); evasão ×0.7; ataques -4; CD 12 (FOR) para soltar por rodada."},
    {"id": "OFUSCADO", "icon": "✨", "name": "Ofuscamento (WPN-FLA)", "dur": 1, "atk": -5, "evm": 1.0, "dot": 0,
     "desc": "Luz/som SEM_IMPACTO_FÍSICO; próximo ataque -5; consome-se ao atacar ou no fim da rodada."},
    {"id": "ESPORO", "icon": "☣", "name": "Contaminação de esporos (WPN-PRO)", "dur": 3, "atk": 0, "evm": 1.0, "dot": 2,
     "desc": "PERFURAÇÃO_E_CONTAMINAÇÃO; 2 de dano por rodada; expira em 3 rodadas."},
    {"id": "RAIZ", "icon": "🌿", "name": "Perfuração radicular (WPN-RAD)", "dur": 3, "atk": 0, "evm": 0.7, "dot": 2,
     "desc": "Raiz de corrompido; não move; evasão ×0.7; 2 de dano por rodada; expira em 3."},
]

D["meta"] = {"fase": "web-m1", "counts": {k: len(v) for k, v in D.items() if isinstance(v, list)}}

# escrita: um JSON por secao + manifesto
for key, val in D.items():
    with open(os.path.join(OUTD, key + ".json"), "w", encoding="utf-8") as f:
        json.dump(val, f, ensure_ascii=False, indent=1)
manifest = {"generator": "tools/gen_web_data.py",
            "sources": [{"path": p, "sha16": h} for p, h in SOURCES],
            "counts": D["meta"]["counts"]}
with open(os.path.join(OUTD, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=1)
print("OK", OUTD, D["meta"]["counts"])
