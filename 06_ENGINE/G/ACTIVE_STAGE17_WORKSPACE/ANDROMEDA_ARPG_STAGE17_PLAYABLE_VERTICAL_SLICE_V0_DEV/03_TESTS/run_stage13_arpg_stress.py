import json,os,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'01_RUNTIME'))
from integrated_arpg_engine_v13 import IntegratedARPGEngineV13
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');OUT=Path(os.environ.get('STAGE13_STRESS_OUT',str(R/'04_REPORTS/ARPG_STAGE13/ARPG_STAGE13_STRESS_V1_4_0.json')));OUT.parent.mkdir(parents=True,exist_ok=True)
checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
with tempfile.TemporaryDirectory() as td:
 db=os.path.join(td,'stress.sqlite');e=IntegratedARPGEngineV13(db,master_release_path=MASTER);r=e.create_world('s13:stress',131316);w=r['world']['world_instance_id'];ec=e.economy_arpg(w);i=e.items_arpg(w);market=next(v for v in ec.list_vendors() if v['location_ref']=='POI-002');profiles=[]
 for n in range(4):
  p=e.arpg(w).create_profile(f's13:stress:{n}',origin_mode='CREATED',display_name=f'S{n}')['profile']['profile_ref'];profiles.append(p);ec.ensure_wallet(p,1500);i.grant_item(p,'ECO-GOOD-000006',4,event_ref=f's:g:{n}:g');i.grant_item(p,'ECO-GOOD-000001',4,event_ref=f's:g:{n}:m');i.grant_item(p,'ECO-GOOD-000017',2,event_ref=f's:g:{n}:gr')
 for n,p in enumerate(profiles):
  for k in range(3):
   q=ec.price_quote(p,market['vendor_ref'],'ITEM-FRUIT',1,event_ref=f's:q:{n}:{k}');x=ec.execute_trade(q['quote']['quote_ref'],event_ref=f's:t:{n}:{k}');ck(f'buy:{n}:{k}',x['status']=='PASS');y=ec.execute_trade(q['quote']['quote_ref'],event_ref=f's:t:{n}:{k}');ck(f'replay:{n}:{k}',y.get('idempotent_replay') is True)
  c=ec.craft(p,'CRFT-S13-GRILO-TOSTADO',event_ref=f's:c:{n}');ck(f'craft:{n}',c['status']=='PASS');st=ec.ensure_stash(p);d=ec.stash_deposit(p,'ITEM-FRUIT',1,event_ref=f's:sd:{n}');ck(f'stash:{n}',d['status']=='PASS')
 ck('verify',ec.verify()['status']=='PASS');before=[(p,ec.wallet(p),i.inventory_snapshot(ec.ensure_stash(p))) for p in profiles];e.runtime.close();e2=IntegratedARPGEngineV13(db,master_release_path=MASTER);e2.resume_world(w);ec2=e2.economy_arpg(w);i2=e2.items_arpg(w);after=[(p,ec2.wallet(p),i2.inventory_snapshot(ec2.ensure_stash(p))) for p in profiles];ck('restore',before==after);ck('health-restored',e2.health_arpg_v13(w)['status']=='PASS');e2.runtime.close()
failed=[x for x in checks if x['status']=='FAIL'];rep={'record_id':'ARPG-STAGE13-STRESS-V1.4.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','profiles':4,'trades':12,'replays':12,'crafts':4,'stashes':4,'failures':failed};OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2));print(json.dumps({'status':rep['status'],'checks':rep['checks'],'failed':rep['failed']}));raise SystemExit(0 if not failed else 1)
