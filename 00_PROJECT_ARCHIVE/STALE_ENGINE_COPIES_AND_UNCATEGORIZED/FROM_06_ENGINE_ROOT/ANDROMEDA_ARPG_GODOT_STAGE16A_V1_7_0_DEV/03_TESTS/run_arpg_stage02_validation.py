from __future__ import annotations
import ast, hashlib, json, os, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'01_RUNTIME'
sys.path.insert(0,str(RUNTIME))
from integrated_arpg_engine_v01 import IntegratedARPGEngineV01
from integrated_arpg_engine_v02 import IntegratedARPGEngineV02
from living_runtime import ConflictError, ValidationError
from character_core import CharacterCore, CORE_ATTRIBUTES
MASTER=Path('/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
MASTER_SHA='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
checks=[]; metrics={}
def ck(name,ok,detail=None): checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
def sha(p):
    h=hashlib.sha256();
    with open(p,'rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
master_before=sha(MASTER)
ck('MASTER_HASH',master_before==MASTER_SHA,master_before)
syntax=[]
for p in sorted(RUNTIME.glob('*.py')):
    try: ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
    except Exception as exc: syntax.append(f'{p.name}:{exc}')
ck('RUNTIME_SYNTAX',not syntax,syntax)
contract=json.loads((ROOT/'02_CONTRACTS/ARPG_STAGE02/ARPG_CHARACTER_CORE_CONTRACT_V0_3_0.json').read_text())
ck('CONTRACT_STAGE',contract.get('stage')=='02/18')
ck('CONTRACT_NUMERIC_NONCANON',contract.get('authority')=='GAMEPLAY_DERIVED_NOT_CANON')
ck('CONTRACT_CLASSIFICATION_DEFERRED',contract.get('deferred',{}).get('skills_and_classification')=='STAGE07')
ck('CONTRACT_RESPAWN_DEFERRED',contract.get('deferred',{}).get('death_respawn_resolution')=='STAGE13')
ck('CONTRACT_ART_DEFERRED','STAGE18' in contract.get('deferred',{}).get('art',''))

with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'stage02.sqlite')
    e=IntegratedARPGEngineV02(db,master_release_path=str(MASTER))
    report=e.create_world('stage02-validation',2202,load_relationships=False)
    wid=report['world']['world_instance_id']; arpg=e.arpg(wid); ch=e.character(wid)
    ck('WORLD_VERSION',report.get('version')=='ARPG-V0.3.0',report.get('version'))
    ck('BOOT_HEALTH',e.health_arpg_v02(wid)['status']=='PASS',e.health_arpg_v02(wid).get('failures'))
    p=arpg.create_profile('local:author02',origin_mode='CREATED',display_name='Validation Stage02')['profile']
    s=ch.state(p['profile_ref'])
    ck('PROFILE_CHARACTER_BOUND',s['profile_ref']==p['profile_ref'] and s['avatar_ref']==p['avatar_ref'])
    ck('LEVEL_START',s['level']==1)
    ck('XP_START',s['experience']==0 and s['unspent_attribute_points']==0)
    ck('CORE_ATTRIBUTES',set(s['attributes'])==set(CORE_ATTRIBUTES))
    ck('BASE_ATTRIBUTES',all(v==10 for v in s['attributes'].values()))
    ck('LIFE_ALIVE',s['vitals']['life_state']=='ALIVE')
    ck('HEALTH_FULL',s['vitals']['health']==s['derived']['max_health'])
    ck('RESOURCE_FULL',s['vitals']['resource']==s['derived']['max_resource'])
    ck('EMERGENT_CLASS_UNSET',s['build_evidence']['emergent_class'] is None)
    ck('NUMERIC_AUTHORITY',s['numeric_authority']=='GAMEPLAY_DERIVED_NOT_CANON')
    cp=arpg.create_profile('local:canon02',origin_mode='CANONICAL',canonical_ref='PER-002')['profile']
    cs=ch.state(cp['profile_ref'])
    ck('CANON_ID_PRESERVED',cp['display_name']=='Kenua Vaarn' and cs['canonical_ref']=='PER-002')
    ck('CANON_STATS_NOT_INVENTED',cs['attributes']==s['attributes'] and cs['numeric_authority']=='GAMEPLAY_DERIVED_NOT_CANON')
    need=ch.xp_to_next(1)
    ck('XP_CURVE_POSITIVE',need>0)
    xp=ch.award_experience(p['profile_ref'],need,event_ref='validation:xp:1')
    s2=ch.state(p['profile_ref'])
    ck('LEVEL_UP',xp['level_after']==2 and s2['level']==2)
    ck('LEVEL_POINTS',s2['unspent_attribute_points']==5)
    replay=ch.award_experience(p['profile_ref'],need,event_ref='validation:xp:1')
    ck('XP_IDEMPOTENT',replay.get('idempotent_replay') is True and ch.state(p['profile_ref'])['level']==2)
    conflict=False
    try: ch.award_experience(p['profile_ref'],need+1,event_ref='validation:xp:1')
    except ConflictError: conflict=True
    ck('XP_EVENT_CONFLICT',conflict)
    before=ch.state(p['profile_ref'])
    alloc=ch.allocate_attributes(p['profile_ref'],{'VITALITY':3,'POWER':2},event_ref='validation:attr:1')
    after=ch.state(p['profile_ref'])
    ck('ATTR_SPEND',alloc['unspent_attribute_points']==0)
    ck('ATTR_VALUES',after['attributes']['VITALITY']==13 and after['attributes']['POWER']==12)
    ck('DERIVED_RECALC',after['derived']['max_health']>before['derived']['max_health'])
    ck('BUILD_EVIDENCE',after['build_evidence']['attribute_investment']['VITALITY']==3 and after['build_evidence']['emergent_class'] is None)
    overspend=False
    try: ch.allocate_attributes(p['profile_ref'],{'POWER':1},event_ref='validation:attr:no')
    except ConflictError: overspend=True
    ck('ATTR_OVERSPEND_GUARD',overspend)
    bad=False
    try: ch.allocate_attributes(p['profile_ref'],{'LUCK':1},event_ref='validation:attr:bad')
    except ValidationError: bad=True
    ck('UNKNOWN_ATTR_GUARD',bad)
    h0=ch.state(p['profile_ref'])['vitals']['health']
    dmg=ch.apply_health_change(p['profile_ref'],-20,event_ref='validation:hp:1')
    ck('HEALTH_CHANGE',dmg['health_after']==h0-20)
    r0=ch.state(p['profile_ref'])['vitals']['resource']
    res=ch.apply_resource_change(p['profile_ref'],-15,event_ref='validation:res:1')
    ck('RESOURCE_CHANGE',res['resource_after']==r0-15)
    regen=ch.tick_profile(p['profile_ref'],1.0); reg=ch.state(p['profile_ref'])
    ck('REGEN_TICK',regen['changed'] and reg['vitals']['health']>dmg['health_after'] and reg['vitals']['resource']>res['resource_after'])
    kill=ch.apply_health_change(p['profile_ref'],-999999,event_ref='validation:hp:dead')
    ck('DEATH_STATE',kill['life_state']=='DEAD' and ch.state(p['profile_ref'])['vitals']['health']==0)
    move=arpg.submit_command(p['controller_scope'],p['profile_ref'],1,'MOVE_POINTER',{'iso_x_m':1.0,'iso_y_m':1.0})
    ck('DEAD_MOVE_GUARD',move['status']=='REJECTED' and move['reason']=='CHARACTER_DEAD')
    ck('DEAD_COMMAND_RECORDED',len(arpg.command_history(p['profile_ref']))==1 and arpg.command_history(p['profile_ref'])[0]['client_sequence']==1)
    deadtick=arpg.tick(p['profile_ref'],delta_s=0.1)
    ck('DEAD_TICK',deadtick['frame_state']=='DEAD')
    no_revive=False
    try: ch.apply_health_change(p['profile_ref'],10,event_ref='validation:hp:no-revive')
    except ConflictError: no_revive=True
    ck('RESPAWN_NOT_PREMATURE',no_revive)
    snap=arpg.client_snapshot(p['profile_ref'])
    ck('SNAPSHOT_CHARACTER',snap.get('character',{}).get('profile_ref')==p['profile_ref'])
    ck('SNAPSHOT_NO_ART',snap.get('character',{}).get('art_dependency')=='NONE_PLACEHOLDER_READY')
    ck('CHAR_VERIFY',ch.verify()['status']=='PASS',ch.verify().get('failures'))
    ck('ENGINE_VERIFY',e.health_arpg_v02(wid)['status']=='PASS',e.health_arpg_v02(wid).get('failures'))
    metrics['events']=len(ch.event_history(p['profile_ref']))
    before_state=ch.state(p['profile_ref'])
    e.close()
    e=IntegratedARPGEngineV02(db,master_release_path=str(MASTER))
    resumed=e.resume_world(wid); ch2=e.character(wid)
    ck('RESUME_WORLD',resumed['status']=='PASS')
    ck('RESUME_STATE_EXACT',ch2.state(p['profile_ref'])==before_state)
    ck('RESUME_VERIFY',e.health_arpg_v02(wid)['status']=='PASS',e.health_arpg_v02(wid).get('failures'))
    e.close()

# Upgrade compatibility: a Stage01 save with profiles receives Stage02 state deterministically on resume.
with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'upgrade.sqlite')
    e1=IntegratedARPGEngineV01(db,master_release_path=str(MASTER)); rep=e1.create_world('stage01-upgrade',2204,load_relationships=False); wid=rep['world']['world_instance_id']
    p=e1.arpg(wid).create_profile('local:upgrade',origin_mode='CREATED',display_name='Upgrade Hero')['profile']; e1.close()
    e2=IntegratedARPGEngineV02(db,master_release_path=str(MASTER)); rep2=e2.resume_world(wid)
    us=e2.character(wid).state(p['profile_ref'])
    ck('STAGE01_SAVE_UPGRADE',rep2['status']=='PASS' and us['level']==1 and us['avatar_ref']==p['avatar_ref'])
    ck('UPGRADE_HEALTH',e2.health_arpg_v02(wid)['status']=='PASS',e2.health_arpg_v02(wid).get('failures')); e2.close()

ck('MASTER_UNCHANGED',sha(MASTER)==master_before==MASTER_SHA,sha(MASTER))
trans=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and ('__pycache__' in p.parts or p.suffix.lower() in {'.pyc','.pyo','.sqlite','.db','.tmp'})]
ck('NO_TRANSIENT_ARTIFACTS',not trans,trans[:20])
failed=[c for c in checks if c['status']=='FAIL']
report={'record_id':'ARPG-STAGE02-VALIDATION-V0.3.0','stage':'02/18','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed,'metrics':metrics,'canon_mutations':0,'numeric_authority':'GAMEPLAY_DERIVED_NOT_CANON','art_pipeline':'LOCKED'}
out=ROOT/'04_REPORTS/ARPG_STAGE02/ARPG_STAGE02_VALIDATION_V0_3_0.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:report[k] for k in ('record_id','checks','passed','failed','status','metrics')},ensure_ascii=False))
if failed: print(json.dumps(failed,ensure_ascii=False,indent=2))
raise SystemExit(1 if failed else 0)
