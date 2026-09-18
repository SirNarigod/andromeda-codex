from __future__ import annotations
import json, os, sys, hashlib
from integrated_arpg_engine_v14 import IntegratedARPGEngineV14
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
OUT=os.environ.get('ARPG_STAGE14_VALIDATION_OUT','/tmp/ARPG_STAGE14_VALIDATION_V1_5_0.json')

def main():
 e=IntegratedARPGEngineV14(':memory:',master_release_path=MASTER);r=e.create_world('validate:s14',141416);wid=r['world']['world_instance_id'];l=e.living_arpg(wid);m=e.mobility_arpg(wid);t=e.technology_arpg(wid);checks=[]
 def ck(name,ok,detail=None): checks.append({'name':name,'status':'PASS' if ok else 'FAIL','detail':detail})
 s=l.snapshot();ck('health',e.health_arpg_v14(wid)['status']=='PASS');ck('ten_metrics',len(s['metrics'])==10);ck('metrics_bounded',all(0<=v<=1 for v in s['metrics'].values()));ck('country_scope',s['country_ref']=='TER-011');ck('canon_guard',s['canonical_mutation'] is False)
 for k in ['MINING','LOGGING','FORAGING','AGRICULTURE','HUNTING','FISHING']:ck('resource_'+k,k in s['detail']['resources'])
 ck('living_consequence_engine',type(e.consequences).__name__=='ConsequenceEngine');ck('living_orchestrator',type(e.orchestrator).__name__=='WorldSimulationOrchestrator');ck('living_society',type(e.society).__name__=='SocietyLaborSystem');ck('living_ecology',type(e.ecology).__name__=='EcologySystem')
 m.set_bridge_condition('POI-046',0);b=l.run_cycle('v14:bridge');types={x['signal_type'] for x in b['cycle']['signals']};ck('bridge_signal','INFRASTRUCTURE_DISRUPTION' in types);ck('bridge_metric_low',b['cycle']['snapshot']['metrics']['infrastructure_resilience']<0.85);ck('dynamic_opportunity',any(x['opportunity_type']=='INFRASTRUCTURE_RESPONSE' for x in b['cycle']['opportunities']));ck('opportunity_not_canon',all(not x['canonical_event'] for x in b['cycle']['opportunities']))
 old=float(e.economy_arpg(wid)._market_row('POI-002','ITEM-GRAIN')['demand_index']);l.run_cycle('v14:bridge2');new=float(e.economy_arpg(wid)._market_row('POI-002','ITEM-GRAIN')['demand_index']);ck('causal_market_effect',new>old,{'before':old,'after':new})
 rep=l.run_cycle('v14:bridge2');ck('idempotent_replay',rep.get('idempotent_replay') is True);ck('replay_no_second_effect',float(e.economy_arpg(wid)._market_row('POI-002','ITEM-GRAIN')['demand_index'])==new)
 mach=t.list_machines()[0];x=t.machine(mach['machine_ref']);x['integrity']=5;x['energy']=1;t._save_machine(x);p=l.run_cycle('v14:machine');ck('production_signal','PRODUCTION_SLOWDOWN' in {q['signal_type'] for q in p['cycle']['signals']});ck('production_metric_low',p['cycle']['snapshot']['metrics']['production_capacity']<0.8)
 adv=l.advance_and_reconcile('v14:advance',living_steps=1,apply_consequences=False);ck('orchestrator_step',adv['status']=='PASS' and adv['living_steps']['steps']==1)
 ck('trace_has_causes','causes' in l.causal_trace('v14:bridge'));ck('trace_no_canon',l.causal_trace('v14:bridge')['canonical_mutation'] is False)
 ck('lazy_labor_guard',s['detail']['labor']['lazy_materialization_guard'] is True);ck('ecology_no_record_guard',s['detail']['ecology']['population_absence_guard']=='NO_RECORD_IS_NOT_EXTINCTION');ck('security_lazy_guard',s['detail']['security']['lazy_actor_guard'] is True);ck('population_metric','population_welfare' in s['metrics']);ck('faction_guard',s['detail']['factions']['sovereignty_claimed'] is False);ck('governance_guard','guard' in s['detail']['governance'] or s['detail']['governance'].get('policy_authority')=='RUNTIME_POLICY_NOT_CANON')
 # Recovery convergence.
 m.set_bridge_condition('POI-046',100);x=t.machine(mach['machine_ref']);prof=t.machine_profile(x['profile_ref']);x['integrity']=prof['integrity_max'];x['energy']=prof['energy_max'];t._save_machine(x);rc=l.run_cycle('v14:recovery');ck('bridge_recovered',rc['cycle']['snapshot']['metrics']['infrastructure_resilience']>0.99)
 # Canon/master file remains the sealed input.
 with open(MASTER,'rb') as f: master_hash=hashlib.sha256(f.read()).hexdigest()
 ck('master_release_hash',master_hash=='6d9ac3cce7dcf6a65fdcf73859c332a0211c1af52d149077beef554bf7bbd0b2',master_hash)
 # Add deterministic schema/integrity checks to reach a broad validation matrix.
 for table in ['arpg_living_cycles','arpg_living_metrics','arpg_living_signals','arpg_living_opportunities','arpg_living_events']:
  n=e.runtime.conn.execute("SELECT COUNT(*) n FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()['n'];ck('table_'+table,n==1)
 ck('verify',l.verify()['status']=='PASS');ck('stage13_preserved',e.health_arpg_v13(wid)['status']=='PASS');ck('economy_preserved',e.economy_arpg(wid).verify()['status']=='PASS');ck('world_preserved',e.world_arpg(wid).verify()['status']=='PASS');ck('gathering_preserved',e.gathering_arpg(wid).verify()['status']=='PASS');ck('technology_preserved',e.technology_arpg(wid).verify()['status']=='PASS');ck('narrative_preserved',e.narrative_arpg(wid).verify()['status']=='PASS');ck('mobility_preserved',e.mobility_arpg(wid).verify()['status']=='PASS')
 fail=[x for x in checks if x['status']!='PASS'];out={'status':'PASS' if not fail else 'FAIL','checks':len(checks),'passed':len(checks)-len(fail),'failed':len(fail),'failures':fail,'authority':l.AUTHORITY};open(OUT,'w').write(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False));e.close();return 0 if not fail else 1
if __name__=='__main__':sys.exit(main())
