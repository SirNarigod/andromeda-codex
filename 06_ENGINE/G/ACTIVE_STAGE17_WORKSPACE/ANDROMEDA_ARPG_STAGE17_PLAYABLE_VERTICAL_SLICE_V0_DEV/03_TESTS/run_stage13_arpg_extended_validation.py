import json,os,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'01_RUNTIME'))
from integrated_arpg_engine_v13 import IntegratedARPGEngineV13
MASTER=os.environ.get('ANDROMEDA_MASTER_RELEASE','/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip');OUT=Path(os.environ.get('STAGE13_VALIDATION_OUT',str(R/'04_REPORTS/ARPG_STAGE13/ARPG_STAGE13_VALIDATION_V1_4_0.json')));OUT.parent.mkdir(parents=True,exist_ok=True)
checks=[]
def ck(n,o,d=None):checks.append({'name':n,'status':'PASS' if o else 'FAIL','detail':d})
e=IntegratedARPGEngineV13(':memory:',master_release_path=MASTER);r=e.create_world('s13:validation',131315);w=r['world']['world_instance_id'];ec=e.economy_arpg(w);i=e.items_arpg(w);m=e.mobility_arpg(w);t=e.technology_arpg(w);p=e.arpg(w).create_profile('s13:validation',origin_mode='CREATED',display_name='Val')['profile']['profile_ref'];ec.ensure_wallet(p,2000)
ck('health',e.health_arpg_v13(w)['status']=='PASS');ck('vendors-three',len(ec.list_vendors())==3);ck('recipes-four',len(ec.list_recipes())==4);ck('culinary-projections-four',sum(1 for x in ec.CULINARY_REFS if i.definition(x)['canonical_identity'])==4)
for ref in ['POI-002','POI-003','POI-006','INDN-008']:ck('canon:'+ref,ec.canonical_snapshot(ref) is not None)
ck('currency-runtime-only',ec.CURRENCY=='CREDIT_RUNTIME_NOT_CANON');ck('merchant-not-invented',all(not x['merchant_identity_claimed'] for x in ec.list_vendors()))
market=next(v for v in ec.list_vendors() if v['location_ref']=='POI-002'); workshop=next(v for v in ec.list_vendors() if v['location_ref']=='POI-003')
q=ec.price_quote(p,market['vendor_ref'],'ITEM-GRAIN',1,event_ref='v:q1');ck('quote-positive',q['quote']['total_price']>0);ck('quote-no-auto-buy',i.inventory_snapshot(p)['stacks'].get('ITEM-GRAIN',0)==0);b=ec.execute_trade(q['quote']['quote_ref'],event_ref='v:t1');ck('buy-pass',b['status']=='PASS');ck('buy-inventory',i.inventory_snapshot(p)['stacks'].get('ITEM-GRAIN',0)==1)
rep=ec.execute_trade(q['quote']['quote_ref'],event_ref='v:t1');ck('buy-replay',rep.get('idempotent_replay') is True);ck('buy-no-double',i.inventory_snapshot(p)['stacks'].get('ITEM-GRAIN',0)==1)
q2=ec.price_quote(p,market['vendor_ref'],'ITEM-GRAIN',1,direction='SELL',event_ref='v:q2');s=ec.execute_trade(q2['quote']['quote_ref'],event_ref='v:t2');ck('sell-pass',s['status']=='PASS')
row=e.runtime.conn.execute('SELECT demand_index,units_bought,units_sold FROM arpg_economy_market WHERE world_instance_id=? AND location_ref=? AND item_ref=?',(w,'POI-002','ITEM-GRAIN')).fetchone();ck('market-ledger',row['units_bought']>=1 and row['units_sold']>=1,dict(row))
m.set_bridge_condition('POI-046',0);qb=ec.price_quote(p,market['vendor_ref'],'ITEM-FRUIT',1,event_ref='v:bq');ck('bridge-logistics',qb['quote']['factors']['logistics']==1.25);m.set_bridge_condition('POI-046',100)
st=ec.ensure_stash(p);i.grant_item(p,'ITEM-GRAIN',2,event_ref='v:sg');ec.stash_deposit(p,'ITEM-GRAIN',1,event_ref='v:sd');ck('stash-deposit',i.inventory_snapshot(st)['stacks'].get('ITEM-GRAIN',0)==1);ec.stash_withdraw(p,'ITEM-GRAIN',1,event_ref='v:sw');ck('stash-withdraw',i.inventory_snapshot(st)['stacks'].get('ITEM-GRAIN',0)==0)
for ref,qty in [('ECO-GOOD-000006',3),('ECO-GOOD-000001',3),('ECO-GOOD-000017',1)]:i.grant_item(p,ref,qty,event_ref='v:g:'+ref)
for rr in ec.RECIPES:
 x=ec.craft(p,rr,event_ref='v:c:'+rr);ck('craft:'+rr,x['status']=='PASS',x)
ck('culinary-output-count',sum(i.inventory_snapshot(p)['stacks'].get(x,0) for x in ec.CULINARY_REFS)>=4)
cat=ec.list_crafting_catalog();ck('tech-catalog-visible',len(cat['stage11_technology'])>=4)
i.grant_item(p,'MIN-COPPER',2,event_ref='v:tc');i.grant_item(p,'MIN-QUARTZ',1,event_ref='v:tq');mach=next(x for x in t.list_machines() if t.machine_profile(x['profile_ref'])['machine_class']=='FABRICATION');tc=ec.craft_dispatch(p,'RECIPE-CIRCUIT-STAGE11',machine_ref=mach['machine_ref'],event_ref='v:tech');ck('tech-dispatch',tc['status']=='PASS')
g=i.grant_item(p,'WPN-001',1,event_ref='v:w');ir=g['instance_refs'][0];i.apply_durability_loss(p,ir,20,event_ref='v:wear');pre=i.instance(ir)['durability'];rp=ec.repair_service(p,workshop['vendor_ref'],ir,event_ref='v:repair');ck('repair-pass',rp['status']=='PASS');ck('repair-restored',i.instance(ir)['durability']>pre)
npc=next(e.country(w)._all_npc_records())['id'];ec.ensure_wallet(npc,100);i.grant_item(npc,'ITEM-GRAIN',1,event_ref='v:ng');nq=ec.price_quote(npc,market['vendor_ref'],'ITEM-GRAIN',1,direction='SELL',event_ref='v:nq');nt=ec.execute_trade(nq['quote']['quote_ref'],event_ref='v:nt');ck('npc-trade',nt['status']=='PASS')
ck('economy-verify',ec.verify()['status']=='PASS');ck('item-verify',i.verify()['status']=='PASS');ck('stage12-health',e.health_arpg_v12(w)['status']=='PASS');ck('no-canon-price',ec.market_snapshot()['numeric_prices_canonical'] is False)
failed=[x for x in checks if x['status']=='FAIL'];rep={'record_id':'ARPG-STAGE13-VALIDATION-V1.4.0','checks':len(checks),'passed':len(checks)-len(failed),'failed':len(failed),'status':'PASS' if not failed else 'FAIL','failures':failed};OUT.write_text(json.dumps(rep,ensure_ascii=False,indent=2));print(json.dumps({'status':rep['status'],'checks':rep['checks'],'failed':rep['failed']}));e.close();raise SystemExit(0 if not failed else 1)
