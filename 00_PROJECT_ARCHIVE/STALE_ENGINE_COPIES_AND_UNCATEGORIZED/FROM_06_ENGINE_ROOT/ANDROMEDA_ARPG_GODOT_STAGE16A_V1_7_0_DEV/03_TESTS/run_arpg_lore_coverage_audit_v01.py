from __future__ import annotations
import json, os, zipfile
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip')
COVERAGE=os.path.join(ROOT,'10_ARPG','STAGE07','ANDROMEDA_LORE_GAMEPLAY_COVERAGE_V0_1_0.json')
PLAN=os.path.join(ROOT,'10_ARPG','STAGE07','ARPG_STAGE_PLAN_V0_5_0.json')
CANON='ANDROMEDA_CODEX_MASTER/01_CANON/ANDROMEDA_CODEX_CANON_MASTER_V2_0_0.json'
TERR='ANDROMEDA_CODEX_MASTER/03_DOMAINS/GEOSPATIAL/02_GEOGRAFIA/STELLAR_TERRITORIES_V1_0.json'

def main():
    checks=[]
    def ck(n,c,d=None): checks.append({'name':n,'status':'PASS' if c else 'FAIL','detail':d})
    with zipfile.ZipFile(MASTER,'r') as z:
        canon=json.loads(z.read(CANON)); terr=json.loads(z.read(TERR))
    cov=json.load(open(COVERAGE,encoding='utf-8')); plan=json.load(open(PLAN,encoding='utf-8'))
    master_ids={e['id'] for e in canon['entities']}; bound=[r['entity_id'] for r in cov['entity_bindings']]; bound_ids=set(bound)
    ck('master_entities_1660',len(master_ids)==1660,len(master_ids)); ck('coverage_bindings_1660',len(bound)==1660,len(bound)); ck('coverage_unique',len(bound_ids)==1660,len(bound_ids)); ck('no_missing_entities',master_ids==bound_ids,{'missing':sorted(master_ids-bound_ids)[:10],'extra':sorted(bound_ids-master_ids)[:10]})
    ck('locations_count',cov['coverage_scope']['locations']==len(canon['locations'])==52); ck('routes_count',cov['coverage_scope']['routes']==len(canon['routes'])==9); ck('layers_count',cov['coverage_scope']['layers']==len(canon['layers'])==44); ck('timeline_count',cov['coverage_scope']['timeline_records']==len(canon['timeline'])==93); ck('relationships_count',cov['coverage_scope']['relationships']==len(canon['relationships'])==9429); ck('entity_unmapped_zero',cov['coverage_scope']['entity_unmapped']==0)
    valid_stages={s['index'] for s in plan['stages']}; ck('plan_23_stages',plan['stage_count']==23 and len(plan['stages'])==23); ck('all_binding_stages_exist',all(r['primary_stage'] in valid_stages for r in cov['entity_bindings']))
    req=plan['requested_capabilities']; expected={'fishing':9,'hunting':9,'mining':9,'wood_flora':9,'professions_player_npc':9,'vehicles':10,'roads':10,'bridges':10,'transport':10,'biomes_complete_individual':8,'technology':11,'machines':11,'robots':11}
    ck('requested_capabilities_complete',all(req.get(k)==v for k,v in expected.items()),req)
    fishing=cov['requested_systems']['fishing']; ter=next((x for x in terr.get('territories',[]) if x.get('id')=='TER-004'),None); ck('fishing_source_ter004',ter is not None); ck('fishing_canonical_evidence',ter is not None and 'pesca' in str(ter.get('economic_role','')).lower(),ter.get('economic_role') if ter else None); ck('fishing_not_fake_entity',fishing['entity_count']==0 and fishing['canonical_support']=='SUPPORTED_BY_GEOSPATIAL_TERRITORY')
    ck('hunting_profession_present','JOB-EXPL-CAC-001' in master_ids); ck('vehicles_supported',cov['requested_systems']['vehicles']['entity_count']>0); ck('roads_bridges_supported',cov['requested_systems']['roads_bridges']['entity_count']>0); ck('biomes_supported',cov['requested_systems']['biomes']['entity_count']>0); ck('tech_machine_robot_supported',cov['requested_systems']['technology_machines_robots']['entity_count']>0); ck('mining_resources_supported',cov['requested_systems']['mining_resources']['entity_count']>0); ck('flora_supported',cov['requested_systems']['flora_wood']['entity_count']>0); ck('fauna_supported',cov['requested_systems']['fauna']['entity_count']>0)
    ck('art_last',plan['stages'][-1]['folder']=='22_VISUAL_PIPELINE' and plan['stages'][-1]['status'].startswith('BLOCKED'))
    failed=[x for x in checks if x['status']=='FAIL']; out={'record_id':'ANDROMEDA-LORE-GAMEPLAY-COVERAGE-AUDIT-V0.1.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed}; print(json.dumps(out,ensure_ascii=False,indent=2)); return 0 if not failed else 1
if __name__=='__main__': raise SystemExit(main())
