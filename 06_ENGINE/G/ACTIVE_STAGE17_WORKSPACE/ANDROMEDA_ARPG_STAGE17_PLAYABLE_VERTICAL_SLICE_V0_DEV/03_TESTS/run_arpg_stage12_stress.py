import argparse,json,os,tempfile
from integrated_arpg_engine_v12 import IntegratedARPGEngineV12
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--output',default='04_REPORTS/ARPG_STAGE12/ARPG_STAGE12_STRESS_V1_3_0.json');a=ap.parse_args();checks=[]
 def ck(n,c,d=None): checks.append({'check':n,'status':'PASS' if c else 'FAIL','detail':d}); assert c,n
 e=IntegratedARPGEngineV12(':memory:',master_release_path=MASTER);r=e.create_world('s12:stress',121221);wid=r['world']['world_instance_id'];n=e.narrative_arpg(wid);i=e.items_arpg(wid);profiles=[]
 for x in range(4): profiles.append(e.arpg(wid).create_profile(f's12:stress:{x}',origin_mode='CREATED',display_name=f'Stress{x}')['profile']['profile_ref'])
 for idx,pref in enumerate(profiles):
  # orientation + supply for each profile
  q='QST-S12-VARGA-ORIENTATION';n.accept_quest(pref,q,event_ref=f's:{idx}:oa');n.submit_objective(pref,q,'VISIT-VARGA',evidence={'canonical_ref':'CIT-001'},event_ref=f's:{idx}:ob');a1=n.turn_in_quest(pref,q,event_ref=f's:{idx}:oc');a2=n.turn_in_quest(pref,q,event_ref=f's:{idx}:oc');ck(f'orientation_{idx}',a1['status']=='PASS');ck(f'orientation_replay_{idx}',a2.get('idempotent_replay') is True)
  q='QST-S12-FRONTIER-SUPPLY';n.accept_quest(pref,q,event_ref=f's:{idx}:sa');i.grant_item(pref,'MIN-IRON',2,event_ref=f's:{idx}:iron');n.submit_objective(pref,q,'HAVE-IRON',evidence={},event_ref=f's:{idx}:sb');b1=n.turn_in_quest(pref,q,event_ref=f's:{idx}:sc');b2=n.turn_in_quest(pref,q,event_ref=f's:{idx}:sc');ck(f'supply_{idx}',b1['status']=='PASS');ck(f'supply_replay_{idx}',b2.get('idempotent_replay') is True);rep=n.reputation(pref);ck(f'context_rep_{idx}',rep.get('LOCAL_FAMILIARITY')==1 and rep.get('FRONTIER_RELIABILITY')==2);ck(f'quest_count_{idx}',len(n.list_quests(pref))==2)
 ck('culture_stable',len(n.culture_profile()['practice_refs'])==26);ck('factions_guarded',all(not x['territorial_control_claimed'] for x in n.faction_profile()));ck('spoilers_guarded','TIM-032' not in [x['canonical_ref'] for x in n.global_narrative_anchors(1)]);ck('health',e.health_arpg_v12(wid)['status']=='PASS')
 # independent same-seed canonical projection equality (no UUID dependence)
 e2=IntegratedARPGEngineV12(':memory:',master_release_path=MASTER);r2=e2.create_world('s12:stress:mirror',121221);n2=e2.narrative_arpg(r2['world']['world_instance_id']);ck('same_seed_quest_templates',n.list_quest_templates()==n2.list_quest_templates());ck('same_seed_culture',n.culture_profile()==n2.culture_profile());e2.close();e.close();fail=[x for x in checks if x['status']!='PASS'];out={'record_id':'ARPG-STAGE12-STRESS-V1.3.0','profiles':len(profiles),'checks':len(checks),'passed':len(checks)-len(fail),'failed':len(fail),'status':'PASS' if not fail else 'FAIL','results':checks};os.makedirs(os.path.dirname(a.output),exist_ok=True);json.dump(out,open(a.output,'w',encoding='utf-8'),ensure_ascii=False,indent=2);print(json.dumps({k:out[k] for k in ('profiles','checks','passed','failed','status')}))
if __name__=='__main__': main()
