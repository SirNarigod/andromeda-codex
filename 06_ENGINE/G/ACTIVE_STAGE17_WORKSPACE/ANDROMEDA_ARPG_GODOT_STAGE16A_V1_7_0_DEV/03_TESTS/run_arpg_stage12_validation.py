import argparse,json,os,tempfile
from integrated_arpg_engine_v12 import IntegratedARPGEngineV12
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',default='04_REPORTS/ARPG_STAGE12/ARPG_STAGE12_VALIDATION_V1_3_0.json');a=ap.parse_args();checks=[]
 def ck(name,cond,detail=None): checks.append({'check':name,'status':'PASS' if cond else 'FAIL','detail':detail}); assert cond,name
 e=IntegratedARPGEngineV12(':memory:',master_release_path=MASTER);r=e.create_world('s12:validation',121220);wid=r['world']['world_instance_id'];n=e.narrative_arpg(wid);i=e.items_arpg(wid);m=e.mobility_arpg(wid);t=e.technology_arpg(wid);p=e.arpg(wid).create_profile('s12:validation',origin_mode='CREATED',display_name='Validation')['profile'];pref=p['profile_ref']
 ck('health',e.health_arpg_v12(wid)['status']=='PASS');cp=n.culture_profile();ck('culture_identity',cp['culture_identity_ref']=='SOC-PROP-FND-011');ck('culture_count',len(cp['practice_refs'])==26);ck('language_guard',cp['official_language_ref'] is None);ck('belief_guard',cp['official_religion_ref'] is None);ck('reputation_contextual',cp['reputation_model'].startswith('CONTEXTUAL'))
 for ref in cp['practice_refs']: ck('culture_ref_'+ref,n.canonical_snapshot(ref)['canonical_status'] in ('CÂNONE_ATIVO','VALIDADO'))
 for f in n.faction_profile(): ck('faction_guard_'+f['canonical_ref'],not f['territorial_control_claimed'])
 anchors=n.global_narrative_anchors(1);ck('global_anchor_count',len(anchors)==3);ck('spoiler3_hidden',all(x['spoiler_level']<=1 for x in anchors));ck('no_auto_spatialize',all(not x['auto_spatialize'] for x in anchors))
 ck('quest_count',len(n.list_quest_templates())==5);ck('dialogue_count',len(n.list_dialogue_briefs())==3)
 # Execute three representative quests against real system state.
 q='QST-S12-VARGA-ORIENTATION';n.accept_quest(pref,q,event_ref='v:o:a');ck('orientation_objective',n.submit_objective(pref,q,'VISIT-VARGA',evidence={'canonical_ref':'CIT-001'},event_ref='v:o:b')['status']=='PASS');ck('orientation_turnin',n.turn_in_quest(pref,q,event_ref='v:o:c')['status']=='PASS')
 q='QST-S12-BRIDGE-CONTINUITY';n.accept_quest(pref,q,event_ref='v:b:a');m.set_bridge_condition('POI-046',0);ck('bridge_rejects_down',n.submit_objective(pref,q,'BRIDGE-OPERATIONAL',evidence={},event_ref='v:b:bad')['status']=='REJECTED');m.set_bridge_condition('POI-046',100);ck('bridge_accepts_up',n.submit_objective(pref,q,'BRIDGE-OPERATIONAL',evidence={},event_ref='v:b:ok')['status']=='PASS')
 q='QST-S12-WORKSHOP-CIRCUIT';n.accept_quest(pref,q,event_ref='v:t:a');i.grant_item(pref,'MIN-COPPER',2,event_ref='v:t:c');i.grant_item(pref,'MIN-QUARTZ',1,event_ref='v:t:q');fab=next(x for x in t.list_machines() if t.machine_profile(x['profile_ref'])['machine_class']=='FABRICATION');t.run_recipe(pref,fab['machine_ref'],'RECIPE-CIRCUIT-STAGE11',event_ref='v:t:recipe');ck('tech_objective_real_state',n.submit_objective(pref,q,'HAVE-CIRCUIT',evidence={},event_ref='v:t:obj')['status']=='PASS')
 ck('verify_final',n.verify()['status']=='PASS');e.close();fail=[x for x in checks if x['status']!='PASS'];out={'record_id':'ARPG-STAGE12-VALIDATION-V1.3.0','checks':len(checks),'passed':len(checks)-len(fail),'failed':len(fail),'status':'PASS' if not fail else 'FAIL','results':checks};os.makedirs(os.path.dirname(a.output),exist_ok=True);json.dump(out,open(a.output,'w',encoding='utf-8'),ensure_ascii=False,indent=2);print(json.dumps({k:out[k] for k in ('checks','passed','failed','status')}))
if __name__=='__main__': main()
