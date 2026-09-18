from __future__ import annotations
import ast, hashlib, json, math, os, sys, tempfile
from pathlib import Path
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]; RUNTIME=ROOT/'01_RUNTIME'; sys.path.insert(0,str(RUNTIME))
from integrated_arpg_engine_v02 import IntegratedARPGEngineV02
from integrated_arpg_engine_v03 import IntegratedARPGEngineV03
from living_runtime import ConflictError, ValidationError
from arpg_combat_core import DAMAGE_TYPES
MASTER=Path(os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'))
MASTER_SHA='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2'
checks=[]; metrics={}
def ck(name,ok,detail=None): checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for c in iter(lambda:f.read(1024*1024),b''): h.update(c)
    return h.hexdigest()
def colocate(e,wid,a,b):
    ps=e.movement(wid).state(a); geo=e.spatial(wid).isometric_to_geodetic(ps['iso_x_m'],ps['iso_y_m'],ps['altitude_m']); e.movement(wid).sync_to_geodetic(b,geo,reason='STAGE03_VALIDATION_COLOCATE')

def next_target(e,wid,avatar,protected=None,combat_targetable=True):
    for n in e.country(wid)._all_npc_records():
        if n['id']==avatar: continue
        p=n.get('protection') or {}
        if protected is not None and bool(p.get('protected'))!=protected: continue
        if combat_targetable is not None and bool(p.get('combat_targetable',True))!=combat_targetable: continue
        return n['id']
    raise AssertionError('target not found')

master_before=sha(MASTER); ck('MASTER_HASH',master_before==MASTER_SHA,master_before)
syntax=[]
for p in sorted(RUNTIME.glob('*.py')):
    try: ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
    except Exception as exc: syntax.append(f'{p.name}:{exc}')
ck('RUNTIME_SYNTAX',not syntax,syntax)
contract=json.loads((ROOT/'02_CONTRACTS/ARPG_STAGE03/ARPG_COMBAT_CORE_CONTRACT_V0_4_0.json').read_text())
ck('CONTRACT_STAGE',contract.get('stage')=='03/18')
ck('CONTRACT_NONCANON',contract.get('authority')=='GAMEPLAY_DERIVED_NOT_CANON')
ck('CONTRACT_SERVER_AUTH',contract.get('server_authoritative') is True)
ck('CONTRACT_DETERMINISTIC',contract.get('deterministic_rng') is True)
ck('CONTRACT_PVP_OFF',contract.get('pvp_enabled') is False)
ck('CONTRACT_DAMAGE_TYPES',set(contract.get('damage_types',[]))==set(DAMAGE_TYPES))
ck('CONTRACT_PLAYER_HP_AUTH',contract.get('player_health_authority')=='CHARACTER_CORE_ONLY')
ck('CONTRACT_EQUIPMENT_DEFERRED',contract.get('deferred',{}).get('equipment_modifiers')=='STAGE05')
ck('CONTRACT_SKILLS_DEFERRED',contract.get('deferred',{}).get('skills')=='STAGE07')
ck('CONTRACT_HOSTILITY_DEFERRED',contract.get('deferred',{}).get('enemy_ai_and_hostility')=='STAGE08')
ck('CONTRACT_ART_DEFERRED','STAGE18' in contract.get('deferred',{}).get('art',''))

with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'stage03.sqlite')
    e=IntegratedARPGEngineV03(db,master_release_path=str(MASTER)); rep=e.create_world('stage03-validation',3303,load_relationships=False)
    wid=rep['world']['world_instance_id']; arpg=e.arpg(wid); ch=e.character(wid); combat=e.combat_arpg(wid)
    ck('WORLD_VERSION',rep.get('version')=='ARPG-V0.4.0',rep.get('version'))
    ck('BOOT_HEALTH',e.health_arpg_v03(wid)['status']=='PASS',e.health_arpg_v03(wid).get('failures'))
    p=arpg.create_profile('local:stage03',origin_mode='CREATED',display_name='Stage03 Hero')['profile']
    cp=arpg.create_profile('local:stage03b',origin_mode='CREATED',display_name='Stage03 Peer')['profile']
    combat.ensure_player(p['profile_ref']); combat.ensure_player(cp['profile_ref'])
    ps=combat.player_stats(p['profile_ref'])
    ck('PLAYER_COMBAT_BOUND',combat.ensure_player(p['profile_ref'])['profile_ref']==p['profile_ref'])
    ck('PLAYER_STATS_POSITIVE',all(float(ps[k])>0 for k in ('armor','evasion','accuracy','base_damage','attacks_per_second','attack_interval_s')))
    ck('PLAYER_RANGE',math.isclose(ps['range_m'],2.75))
    ck('PLAYER_FORMULA_VERSION',ps['formula_version']=='ARPG_COMBAT_FORMULAS_V0_4_0')
    ck('NO_EQUIPMENT_MODS',ps['equipment_modifiers']=='DEFERRED_STAGE05')
    ck('NO_SKILL_MODS',ps['skill_modifiers']=='DEFERRED_STAGE07')
    target=next_target(e,wid,p['avatar_ref'],protected=False,combat_targetable=True); colocate(e,wid,p['avatar_ref'],target)
    enemy=combat.ensure_enemy(target)
    ck('ENEMY_DERIVED',enemy['authority']=='GAMEPLAY_DERIVED_NOT_CANON')
    ck('ENEMY_HEALTH_VALID',enemy['life_state']=='ALIVE' and 0<enemy['health']<=enemy['max_health'])
    ck('ENEMY_PERMADEATH_BLOCKED',enemy['permanent_death']=='BLOCKED_STAGE03')
    ck('ENEMY_HOSTILITY_DEFERRED','STAGE08' in enemy['hostility_authority'])
    # Non-combat NPC click remains context only.
    seq=1
    context=arpg.submit_command(p['controller_scope'],p['profile_ref'],seq,'POINTER_PRIMARY',{'target_ref':target})
    ck('NPC_CONTEXT_DEFAULT',context['status']=='PASS' and context['route']=='NPC_CONTEXT')
    ck('NPC_COMBAT_EXPLICIT_POLICY',context.get('combat_activation_policy')=='EXPLICIT_COMBAT_INTENT_UNTIL_STAGE08_HOSTILITY')
    # Explicit attack route.
    seq+=1
    attack=arpg.submit_command(p['controller_scope'],p['profile_ref'],seq,'POINTER_PRIMARY',{'target_ref':target,'combat_intent':True})
    ck('COMMAND_COMBAT_ROUTE',attack['route']=='COMBAT' and attack['resolved_action']=='BASIC_ATTACK',attack)
    ck('ATTACK_RESULT',attack['result']['status']=='PASS')
    ck('HIT_CHANCE_BOUNDS',20<=attack['result']['hit_chance_pct']<=98)
    ck('CRIT_CHANCE_BOUNDS',0<=attack['result']['crit_chance_pct']<=50)
    ck('DAMAGE_NONNEGATIVE',attack['result']['damage']['final']>=0)
    # Command replay must not damage twice.
    health_after=combat.ensure_enemy(target)['health']
    replay=arpg.submit_command(p['controller_scope'],p['profile_ref'],seq,'POINTER_PRIMARY',{'target_ref':target,'combat_intent':True})
    ck('COMMAND_REPLAY',replay.get('idempotent_replay') is True)
    ck('COMMAND_REPLAY_NO_DOUBLE_HIT',combat.ensure_enemy(target)['health']==health_after)
    # Direct combat event replay/conflict.
    combat.tick_player(p['profile_ref'],1.0)
    direct=combat.player_attack(p['profile_ref'],target,event_ref='validation:direct')
    direct_after=combat.ensure_enemy(target)['health']
    dreplay=combat.player_attack(p['profile_ref'],target,event_ref='validation:direct')
    ck('COMBAT_EVENT_REPLAY',dreplay.get('idempotent_replay') is True and combat.ensure_enemy(target)['health']==direct_after)
    conflict=False
    try: combat.player_attack(p['profile_ref'],target,event_ref='validation:direct',damage_type='FIRE')
    except ConflictError: conflict=True
    ck('COMBAT_EVENT_CONFLICT',conflict)
    # Cooldown and recovery.
    cd=combat.player_attack(p['profile_ref'],target,event_ref='validation:cooldown')
    ck('ATTACK_COOLDOWN_GUARD',cd['status']=='REJECTED' and cd['reason']=='ATTACK_COOLDOWN',cd)
    combat.tick_player(p['profile_ref'],1.0)
    ck('ATTACK_COOLDOWN_RECOVERY',combat.overlay(p['avatar_ref'])['attack_cooldown_remaining_s']==0.0)
    # Range guard.
    pst=e.movement(wid).state(p['avatar_ref']); far=e.spatial(wid).isometric_to_geodetic(pst['iso_x_m']+100,pst['iso_y_m'],pst['altitude_m']); e.movement(wid).sync_to_geodetic(target,far,reason='VALIDATION_FAR')
    farout=combat.player_attack(p['profile_ref'],target,event_ref='validation:far')
    ck('RANGE_GUARD',farout['status']=='REJECTED' and farout['reason']=='TARGET_OUT_OF_RANGE')
    colocate(e,wid,p['avatar_ref'],target)
    # PVP off.
    pvp=combat.player_attack(p['profile_ref'],cp['avatar_ref'],event_ref='validation:pvp')
    ck('PVP_GUARD',pvp['status']=='REJECTED' and pvp['reason']=='PVP_DISABLED')
    # Protected and non-targetable semantics.
    protected=next_target(e,wid,p['avatar_ref'],protected=True,combat_targetable=True); colocate(e,wid,p['avatar_ref'],protected)
    pe=combat.ensure_enemy(protected); pe['health']=0.05; combat._save_row('arpg_enemy_combat_state',protected,pe); combat.tick_player(p['profile_ref'],1.0)
    prot_hit=None
    for i in range(25):
        out=combat.player_attack(p['profile_ref'],protected,event_ref=f'validation:protected:{i}')
        if out['status']=='PASS' and out['hit']: prot_hit=out; break
        combat.tick_player(p['profile_ref'],1.0)
    ck('PROTECTED_TARGET_HIT_FOUND',prot_hit is not None)
    ck('PROTECTED_IDENTITY_NONLETHAL',bool(prot_hit and prot_hit['protected_defeat_blocked'] and not prot_hit['lethal'] and combat.ensure_enemy(protected)['health']==1.0))
    blocked=next_target(e,wid,p['avatar_ref'],protected=True,combat_targetable=False); colocate(e,wid,p['avatar_ref'],blocked); combat.tick_player(p['profile_ref'],1.0)
    bout=combat.player_attack(p['profile_ref'],blocked,event_ref='validation:not-targetable')
    ck('NON_TARGETABLE_GUARD',bout['status']=='REJECTED' and bout['reason']=='TARGET_NOT_COMBAT_TARGETABLE')
    # Damage model caps.
    phys=combat._resolve_damage(raw_damage=100,damage_type='PHYSICAL',attacker_level=1,target_armor=10**9,target_resistance=0,critical=False,crit_multiplier=1.5)
    fire_hi=combat._resolve_damage(raw_damage=100,damage_type='FIRE',attacker_level=1,target_armor=0,target_resistance=500,critical=False,crit_multiplier=1.5)
    fire_neg=combat._resolve_damage(raw_damage=100,damage_type='FIRE',attacker_level=1,target_armor=0,target_resistance=-500,critical=False,crit_multiplier=1.5)
    ck('ARMOR_CAP_75',phys['mitigation_pct']==75.0)
    ck('RESIST_CAP_75',fire_hi['mitigation_pct']==75.0)
    ck('NEG_RESIST_FLOOR_MINUS50',fire_neg['mitigation_pct']==-50.0 and fire_neg['final']==150.0)
    badtype=False
    try: combat.player_attack(p['profile_ref'],target,event_ref='validation:badtype',damage_type='VOID')
    except ValidationError: badtype=True
    ck('DAMAGE_TYPE_GUARD',badtype)
    # Enemy -> player uses CharacterCore HP authority.
    colocate(e,wid,p['avatar_ref'],target); est=combat.ensure_enemy(target)
    if est['life_state']!='ALIVE': est['life_state']='ALIVE'; est['health']=est['max_health']; combat._save_row('arpg_enemy_combat_state',target,est)
    combat.tick_actor(target,1.0)
    ck('ENEMY_STAGGER_RECOVERY',combat.overlay(target)['stagger_remaining_s']==0.0)
    before_hp=ch.state(p['profile_ref'])['vitals']['health']; enemy_hit=None
    for i in range(30):
        out=combat.enemy_attack_player(target,p['profile_ref'],event_ref=f'validation:enemy:{i}')
        if out['status']=='PASS' and out['hit']: enemy_hit=out; break
    ck('ENEMY_ATTACK_HIT_FOUND',enemy_hit is not None)
    after_hp=ch.state(p['profile_ref'])['vitals']['health']
    ck('PLAYER_HP_CHARACTER_AUTH',enemy_hit is not None and after_hp<before_hp and math.isclose(after_hp,enemy_hit['health_after']))
    # Status core on enemy.
    est=combat.ensure_enemy(target)
    if est['life_state']!='ALIVE': est['life_state']='ALIVE'; est['health']=est['max_health']; combat._save_row('arpg_enemy_combat_state',target,est)
    ap=combat.apply_status(target,status_ref='VALIDATION_DOT',duration_s=1.0,magnitude_per_s=4.0,damage_type='TOXIC',source_ref=p['avatar_ref'],event_ref='validation:status')
    ck('STATUS_APPLY',ap['status']=='PASS')
    eb=combat.ensure_enemy(target)['health']; t1=combat.tick_actor(target,0.5); ea=combat.ensure_enemy(target)['health']
    ck('STATUS_DOT_DAMAGE',math.isclose(eb-ea,2.0,abs_tol=1e-6))
    t2=combat.tick_actor(target,0.5); ck('STATUS_EXPIRES',len(t2['statuses'])==0)
    # Snapshot + verify.
    seq+=1; arpg.submit_command(p['controller_scope'],p['profile_ref'],seq,'SELECT_TARGET',{'target_ref':target})
    snap=arpg.client_snapshot(p['profile_ref'])
    ck('SNAPSHOT_COMBAT',snap.get('combat',{}).get('formula_version')=='ARPG_COMBAT_FORMULAS_V0_4_0')
    ck('SNAPSHOT_TARGET',snap.get('combat',{}).get('selected_target',{}).get('actor_ref')==target)
    ck('COMBAT_VERIFY',combat.verify()['status']=='PASS',combat.verify().get('failures'))
    ck('ENGINE_VERIFY',e.health_arpg_v03(wid)['status']=='PASS',e.health_arpg_v03(wid).get('failures'))
    metrics['combat_events']=len(combat.event_history()); metrics['enemy_states']=combat.verify()['enemy_states']; metrics['overlays']=combat.verify()['overlays']
    before_enemy=combat.ensure_enemy(target); before_overlay=combat.overlay(p['avatar_ref']); before_char=ch.state(p['profile_ref']); e.close()
    e=IntegratedARPGEngineV03(db,master_release_path=str(MASTER)); resumed=e.resume_world(wid); combat2=e.combat_arpg(wid)
    ck('RESUME_WORLD',resumed['status']=='PASS')
    ck('RESUME_ENEMY_STATE',combat2.ensure_enemy(target)==before_enemy)
    ck('RESUME_PLAYER_OVERLAY',combat2.overlay(p['avatar_ref'])==before_overlay)
    ck('RESUME_CHARACTER_STATE',e.character(wid).state(p['profile_ref'])==before_char)
    ck('RESUME_VERIFY',e.health_arpg_v03(wid)['status']=='PASS',e.health_arpg_v03(wid).get('failures')); e.close()

# Stage02 -> Stage03 upgrade compatibility.
with tempfile.TemporaryDirectory() as td:
    db=os.path.join(td,'upgrade.sqlite'); e2=IntegratedARPGEngineV02(db,master_release_path=str(MASTER)); rep=e2.create_world('stage02-upgrade03',3304,load_relationships=False); wid=rep['world']['world_instance_id']; p=e2.arpg(wid).create_profile('local:upgrade03',origin_mode='CREATED',display_name='Upgrade03')['profile']; cstate=e2.character(wid).state(p['profile_ref']); e2.close()
    e3=IntegratedARPGEngineV03(db,master_release_path=str(MASTER)); rep3=e3.resume_world(wid); ck('STAGE02_SAVE_UPGRADE',rep3['status']=='PASS' and e3.character(wid).state(p['profile_ref'])==cstate)
    ck('UPGRADE_COMBAT_BOOTSTRAP',e3.combat_arpg(wid).ensure_player(p['profile_ref'])['actor_ref']==p['avatar_ref'])
    ck('UPGRADE_HEALTH',e3.health_arpg_v03(wid)['status']=='PASS',e3.health_arpg_v03(wid).get('failures')); e3.close()

ck('MASTER_UNCHANGED',sha(MASTER)==master_before==MASTER_SHA,sha(MASTER))
trans=[str(p.relative_to(ROOT)) for p in ROOT.rglob('*') if p.is_file() and ('__pycache__' in p.parts or p.suffix.lower() in {'.pyc','.pyo','.sqlite','.db','.tmp'})]
ck('NO_TRANSIENT_ARTIFACTS',not trans,trans[:30])
failed=[c for c in checks if c['status']=='FAIL']
report={'record_id':'ARPG-STAGE03-VALIDATION-V0.4.0','stage':'03/18','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed,'metrics':metrics,'canon_mutations':0,'player_health_authority':'CHARACTER_CORE_ONLY','art_pipeline':'LOCKED'}
out=ROOT/'04_REPORTS/ARPG_STAGE03/ARPG_STAGE03_VALIDATION_V0_4_0.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:report[k] for k in ('record_id','checks','passed','failed','status','metrics')},ensure_ascii=False))
if failed: print(json.dumps(failed,ensure_ascii=False,indent=2))
raise SystemExit(1 if failed else 0)
