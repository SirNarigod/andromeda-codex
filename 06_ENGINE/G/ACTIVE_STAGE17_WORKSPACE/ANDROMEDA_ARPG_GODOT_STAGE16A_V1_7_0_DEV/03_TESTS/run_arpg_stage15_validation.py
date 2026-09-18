from __future__ import annotations
import json, os, shutil, sqlite3, tempfile, time
from pathlib import Path
from integrated_arpg_engine_v15 import IntegratedARPGEngineV15

MASTER=os.environ.get('ANDROMEDA_MASTER','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=os.environ.get('ARPG_STAGE15_VALIDATION_OUT')
checks=[]
def ck(name, cond, detail=None):
    checks.append({'name':name,'status':'PASS' if cond else 'FAIL','detail':detail})
    if not cond: raise AssertionError(f'{name}:{detail}')

root=Path(tempfile.mkdtemp(prefix='andromeda_s15_val_'))
try:
    db=root/'world.sqlite'; saves=root/'saves'
    e=IntegratedARPGEngineV15(str(db),master_release_path=MASTER,save_root=saves)
    r=e.create_world('stage15:validation',1515001); wid=r['world']['world_instance_id']
    ck('bootstrap_health',r['arpg_health']['status']=='PASS')
    p=e.arpg(wid).create_profile('local:stage15',display_name='Stage15 Tester')['profile']; pr=p['profile_ref']
    ck('profile_created',bool(pr))
    rec=e.save_recovery(wid)
    ck('recovery_profile_default',rec.ensure_profile(pr)['last_safe_waypoint_ref']=='WP-CANON-CIT-001')
    # Death before inventory materialization must be safe.
    inv_pre=e.runtime.conn.execute('SELECT 1 FROM arpg_item_inventories WHERE world_instance_id=? AND owner_ref=?',(wid,pr)).fetchone()
    ck('inventory_not_materialized_initially',inv_pre is None)
    ch=e.character(wid).state(pr); xp0=ch['experience']
    e.character(wid).apply_health_change(pr,-10**9,event_ref='s15:kill:1',source_type='TEST')
    ck('death_reached',e.character(wid).state(pr)['vitals']['life_state']=='DEAD')
    dr=rec.recover_death(pr,event_ref='s15:recover:1')
    ck('death_recovery_pass',dr['status']=='PASS' and dr['left_dungeon'])
    ck('xp_preserved_on_death',e.character(wid).state(pr)['experience']==xp0)
    ck('empty_inventory_preserved',dr['inventory_preserved'])
    ck('respawn_varga',dr['waypoint_ref']=='WP-CANON-CIT-001')
    dr2=rec.recover_death(pr,event_ref='s15:recover:1')
    ck('death_replay_idempotent',dr2.get('idempotent_replay') is True)
    # Materialized inventory survives later recovery.
    e.items_arpg(wid).grant_item(pr,'ITEM-FOOD',3,event_ref='s15:food')
    inv_hash=e.runtime.conn.execute('SELECT payload_hash FROM arpg_item_inventories WHERE world_instance_id=? AND owner_ref=?',(wid,pr)).fetchone()[0]
    e.character(wid).apply_health_change(pr,-10**9,event_ref='s15:kill:2',source_type='TEST')
    dr3=rec.recover_death(pr,event_ref='s15:recover:2')
    inv_hash2=e.runtime.conn.execute('SELECT payload_hash FROM arpg_item_inventories WHERE world_instance_id=? AND owner_ref=?',(wid,pr)).fetchone()[0]
    ck('materialized_inventory_preserved',dr3['inventory_preserved'] and inv_hash==inv_hash2)
    # Manual save + rotation.
    s1=rec.create_snapshot('slot1',kind='MANUAL'); ck('snapshot_current_created',s1['status']=='PASS')
    ck('snapshot_current_valid',rec.verify_slot('slot1')['status']=='PASS')
    e.character(wid).award_experience(pr,250,event_ref='s15:xp:after-save')
    xp_after=e.character(wid).state(pr)['experience']
    s2=rec.create_snapshot('slot1',kind='AUTOSAVE'); ck('snapshot_rotation_created',s2['status']=='PASS')
    ck('previous_generation_valid',rec.verify_slot('slot1',generation='previous')['status']=='PASS')
    current_db,current_meta=rec._paths('slot1','current'); prev_db,prev_meta=rec._paths('slot1','previous')
    ck('rotation_paths_distinct',current_db!=prev_db and current_meta!=prev_meta)
    # Corrupt current: verification must fail, previous must remain valid.
    corrupt_backup=root/'current.good.sqlite'; shutil.copy2(current_db,corrupt_backup)
    b=bytearray(current_db.read_bytes()); pos=min(max(100,len(b)//2),max(100,len(b)-1)); b[pos]=(b[pos]+1)%256; current_db.write_bytes(bytes(b))
    bad=rec.verify_slot('slot1'); ck('corruption_detected',bad['status']=='FAIL' and 'SHA256_MISMATCH' in bad['failures'],bad)
    ck('previous_survives_corruption',rec.verify_slot('slot1',generation='previous')['status']=='PASS')
    rb=rec.rollback_slot('slot1'); ck('rollback_promotes_previous',rb['status']=='PASS')
    ck('rollback_current_valid',rec.verify_slot('slot1')['status']=='PASS')
    # Restored previous must predate XP award.
    restored=root/'restored.sqlite'; rec.restore_slot_to('slot1',restored)
    e.runtime.close()
    e2=IntegratedARPGEngineV15(str(restored),master_release_path=MASTER,save_root=root/'restored_saves')
    t=time.perf_counter(); rr=e2.resume_world(wid); elapsed=time.perf_counter()-t
    ck('linear_resume_health',rr['arpg_health']['status']=='PASS' and rr['resume_strategy']=='LINEAR_REHYDRATION_SINGLE_GLOBAL_HEALTH')
    ck('resume_under_60s',elapsed<60,round(elapsed,3))
    ck('rollback_restored_older_xp',e2.character(wid).state(pr)['experience']<xp_after,(e2.character(wid).state(pr)['experience'],xp_after))
    ck('restored_world_integrity',e2.save_recovery(wid).verify()['status']=='PASS')
    e2.runtime.close()
    passed=sum(x['status']=='PASS' for x in checks)
    result={'status':'PASS' if passed==len(checks) else 'FAIL','checks':len(checks),'passed':passed,'failed':len(checks)-passed,'results':checks}
    if OUT: Path(OUT).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','checks','passed','failed')},ensure_ascii=False))
finally:
    shutil.rmtree(root,ignore_errors=True)
