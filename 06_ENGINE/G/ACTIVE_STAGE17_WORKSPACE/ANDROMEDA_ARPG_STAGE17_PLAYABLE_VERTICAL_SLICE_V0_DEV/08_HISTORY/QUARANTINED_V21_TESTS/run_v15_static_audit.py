from __future__ import annotations
import sys,json,hashlib,shutil
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
BASE=Path('/mnt/data/V15_WORK/base/ANDROMEDA_LIVING_COUNTRY_SCALE_V1_4_0')
MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_1_0_RELEASE.zip'); EXPECTED_MASTER='9677b10890c24dfc04916178a2b9fd40a9ea131f2a13c1ec8255186ab203a98b'
sys.path.insert(0,str(ROOT/'01_RUNTIME'))
from integrated_engine_v15 import IntegratedLivingEngineV15
checks=[]
def ck(n,ok,d=''):checks.append({'name':n,'status':'PASS' if ok else 'FAIL','detail':d})
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ck('MASTER_V2_1_HASH',MASTER.exists() and sha(MASTER)==EXPECTED_MASTER,sha(MASTER) if MASTER.exists() else 'missing')
mods=[];missing=[]
for p in (BASE/'01_RUNTIME').glob('*.py'):
 q=ROOT/'01_RUNTIME'/p.name
 if not q.exists():missing.append(p.name)
 elif sha(p)!=sha(q):mods.append(p.name)
ck('NO_INHERITED_RUNTIME_MISSING',not missing,','.join(missing))
ck('RUNTIME_MODIFICATION_ALLOWLIST',set(mods)<={'streaming_system.py','dungeon_graph_v2.py'},','.join(sorted(mods)))
new_expected={'environment_simulation.py','continuous_movement.py','navigation_pathfinding.py','collision_interaction.py','player_discovery.py','godot_adapter_v15.py','integrated_engine_v15.py'}
new={p.name for p in (ROOT/'01_RUNTIME').glob('*.py') if not (BASE/'01_RUNTIME'/p.name).exists()}
ck('NEW_RUNTIME_MODULES_EXACT',new==new_expected,','.join(sorted(new)))
syntax=[]
for p in (ROOT/'01_RUNTIME').glob('*.py'):
 try:compile(p.read_text(encoding='utf-8'),str(p),'exec')
 except Exception as e:syntax.append(f'{p.name}:{e}')
ck('RUNTIME_SYNTAX',not syntax,';'.join(syntax))
# Godot client static contract
script=ROOT/'06_GODOT_LIVING_V1_5/LivingWorldClient.gd';txt=script.read_text(encoding='utf-8') if script.exists() else ''
ck('GODOT_CLIENT_SCRIPT_PRESENT',script.exists())
for cmd in ('MOVE_VECTOR','INTERACT','DISCOVER','PATH_PLAN','DUNGEON_MOVE'):ck('GODOT_COMMAND_'+cmd,cmd in txt)
ck('GODOT_CLIENT_NO_PLAYER_REF_FIELD','player_ref' not in txt)
gate_script=ROOT/'06_GODOT_LIVING_V1_5/GodotRuntimeGate.gd'; project=ROOT/'06_GODOT_LIVING_V1_5/project.godot'
ck('GODOT_RUNTIME_GATE_SCRIPT_PRESENT',gate_script.exists())
ck('GODOT_PROJECT_PRESENT',project.exists())
ck('GODOT_RUNTIME_GATE_MARKER',gate_script.exists() and 'ANDROMEDA_GODOT_V1_5_RUNTIME_GATE: PASS' in gate_script.read_text(encoding='utf-8'))
# Future country gate
gate=json.loads((ROOT/'09_CODEX_EXPANSION/V1_5_0_DEV/FUTURE_COUNTRY_GATE_V1_5_0.json').read_text())
ck('ONE_COUNTRY_ONLY',gate.get('active_country_count')==1 and gate.get('active_pilot_country_ref')=='TER-011',str(gate.get('active_country_count')))
ck('FUTURE_COUNTRIES_LOCKED',gate.get('status')=='LOCKED' and all(not x.get('implemented') for x in gate.get('reserved_archetypes',[])))
# Transient hygiene (ignore reports only if extension not transient)
bad=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and ('__pycache__' in p.parts or p.suffix in {'.pyc','.pyo','.tmp','.db','.sqlite','.sqlite3'})]
ck('NO_TRANSIENT_ARTIFACTS',not bad,'|'.join(bad[:30]))
# live integrated world
E=IntegratedLivingEngineV15(':memory:',master_release_path=str(MASTER))
try:
 r=E.create_world('v15-static',1201,load_relationships=False);wid=r['world']['world_instance_id'];c=E.country(wid);h=E.health_v15(wid)
 ck('HEALTH_V15',h['status']=='PASS',str(h.get('failures')))
 ck('COUNTRY_SINGLE_REF',c.world['country'].get('id')=='CTR-PILOT-001' and c.world['country'].get('source_territory_id')=='TER-011' and c.world['country'].get('kenua_story_binding')=='NOT_ASSIGNED_BY_MASTER',str({k:c.world['country'].get(k) for k in ('id','source_territory_id','kenua_story_binding')}))
 n=next(x for x in c._all_npc_records() if x['class']=='WARRIOR');g=E.godot(wid);ck('SESSION_BIND',g.bind_session('STATIC-S',n['id'])['status']=='PASS');s=g.client_snapshot('STATIC-S');ck('CLIENT_SNAPSHOT',s['status']=='PASS' and s.get('server_authoritative') is True)
 ck('MOTION_VERIFY',E.movement(wid).verify()['status']=='PASS');ck('NAV_VERIFY',E.navigation(wid).verify()['status']=='PASS');ck('ENV_VERIFY',E.environment(wid).verify()['status']=='PASS');ck('DISCOVERY_VERIFY',E.discovery(wid).verify()['status']=='PASS');ck('SESSION_VERIFY',g.verify()['status']=='PASS')
 # same-chunk dungeon redaction
 d=next(d for st in c.world['country']['states'] for b in st['blocks'] for d in b.get('dungeons',[]));E.movement(wid).sync_to_geodetic(n['id'],d['coordinate_center'],reason='AUDIT');ch=E.spatial(wid).chunk_for_geodetic(d['coordinate_center']['longitude'],d['coordinate_center']['latitude'])['chunk_id'];E.streaming(wid).transfer(n['id'],ch);ss=g.snapshot(n['id']);refs={x.get('entity_ref') for x in ss['chunk']['entities']};ck('UNDISCOVERED_DUNGEON_REDACTED',d['id'] not in refs and not any(rm['id'] in refs for rm in d['graph_v2']['rooms']))
finally:E.close()
failed=[x for x in checks if x['status']=='FAIL'];rep={'record_id':'V15-STATIC-AUDIT','version':'V1.5.0-DEV','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed,'checks_detail':checks}
out=ROOT/'04_REPORTS/V1_5_0/V15_STATIC_AUDIT.json';out.write_text(json.dumps(rep,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:rep[k] for k in ('checks','passed','failed','status','failures')},ensure_ascii=False));raise SystemExit(1 if failed else 0)
