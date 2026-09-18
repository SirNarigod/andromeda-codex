from __future__ import annotations
import copy, json, zipfile
from pathlib import Path
from typing import Any

WEAPON_PATH='ANDROMEDA_CODEX_MASTER/05_MAR/FUNCTIONAL/01_MAR/MAR_WEAPONS_FUNCTIONAL_V1_0.json'
REACH_SCORE={'TOQUE':35,'CURTO':55,'MÉDIO':70}
COST_TIER={'BAIXO':1,'MÉDIO':2,'MEDIO':2,'ALTO':3}


def clamp(v,lo=0,hi=100): return max(lo,min(hi,int(round(v))))

def tier(v): return 'BAIXO' if v<55 else ('MÉDIO' if v<66 else 'ALTO')

class MARCanonBalance:
    """Author-approved fictional gameplay stat layer for MAR weapons.

    It adds game balance metadata only; it does not replace qualitative canon fields or
    provide real-world weapon construction/usage instructions.
    """
    VERSION='V1.1-CANON-DEV'
    AUTHORITY='CÂNONE_AUTORIZADO_PELO_AUTOR_2026-08-15'
    def __init__(self, master_release_path:str|Path):
        self.master_release_path=str(master_release_path)
        with zipfile.ZipFile(self.master_release_path) as z:
            self.source=json.loads(z.read(WEAPON_PATH).decode('utf-8'))
        self.records=[self._balance(w) for w in self.source['weapons']]

    def _balance(self,w:dict[str,Any])->dict[str,Any]:
        p=w['performance']; subtype=str(w.get('subtype','campo')).lower()
        control=int(p['control'])*10; stability=int(p['stability'])*10; mobility=int(p['mobility'])*10; durability=int(p['durability'])*10
        reach=REACH_SCORE.get(str(p['reach']).upper(),50)
        if subtype=='controle':
            power=0.42*control+0.18*stability+0.18*reach+0.22*durability
            defense=0.55*stability+0.45*durability
            utility=0.62*control+0.38*mobility
        elif subtype=='proteção':
            power=0.22*control+0.13*reach+0.30*stability+0.35*durability
            defense=0.38*stability+0.62*durability+8
            utility=0.45*control+0.30*stability+0.25*mobility
        else:
            power=0.30*control+0.24*reach+0.18*stability+0.28*mobility
            defense=0.48*stability+0.52*durability
            utility=0.35*control+0.20*reach+0.45*mobility
        magic_refs=(w.get('construction') or {}).get('magic_refs') or []
        rune_refs=(w.get('construction') or {}).get('rune_refs') or []
        tech_refs=(w.get('construction') or {}).get('technology_refs') or []
        magic_aff=clamp(28+len(magic_refs)*12+len(rune_refs)*8+control*.12)
        tech_aff=clamp(30+len(tech_refs)*14+stability*.14+durability*.10)
        handling=clamp(mobility*.65+control*.35)
        defense=clamp(defense); utility=clamp(utility); power=clamp(power)
        rarity={'COMUM_INSTITUCIONAL':'BAIXO','CONTROLADO':'MÉDIO','ESPECIALIZADO':'ALTO'}.get((w.get('balance') or {}).get('rarity'),'MÉDIO')
        score=clamp(power*.22+defense*.18+utility*.18+handling*.14+magic_aff*.14+tech_aff*.14)
        # Every weapon has a role profile; no single stat is allowed to erase trade-offs.
        strength=max({'power':power,'defense':defense,'utility':utility,'handling':handling,'magic_affinity':magic_aff,'tech_affinity':tech_aff},key=lambda k:{'power':power,'defense':defense,'utility':utility,'handling':handling,'magic_affinity':magic_aff,'tech_affinity':tech_aff}[k])
        weakness=min({'power':power,'defense':defense,'utility':utility,'handling':handling,'magic_affinity':magic_aff,'tech_affinity':tech_aff},key=lambda k:{'power':power,'defense':defense,'utility':utility,'handling':handling,'magic_affinity':magic_aff,'tech_affinity':tech_aff}[k])
        return {
            'weapon_id':w['id'],'name':w['name'],'canonical_status':'CÂNONE_AUTORIZADO',
            'source_weapon_status':w.get('canonical_status'),'gameplay_scale':'NORMALIZED_0_100',
            'class':tier(score),'relative_cost':p['relative_cost'],'cost_tier':COST_TIER.get(p['relative_cost'],2),
            'stats':{'power':power,'defense':defense,'utility':utility,'handling':handling,'durability':clamp(durability),'reach':reach,'magic_affinity':magic_aff,'tech_affinity':tech_aff,'overall':score},
            'balance_role':{'subtype':subtype,'primary_strength':strength,'primary_weakness':weakness,'advantage':(w.get('balance') or {}).get('advantage'),'limitation':(w.get('balance') or {}).get('limitation')},
            'safety':'FICTIONAL_GAME_STATS_ONLY',
        }

    def validate(self)->dict[str,Any]:
        failures=[]
        if len(self.records)!=30: failures.append('WEAPON_COUNT_NOT_30')
        ids=[r['weapon_id'] for r in self.records]
        if len(set(ids))!=len(ids): failures.append('DUP_WEAPON_ID')
        for r in self.records:
            for k,v in r['stats'].items():
                if not isinstance(v,int) or not 0<=v<=100: failures.append(f'STAT_RANGE:{r["weapon_id"]}:{k}')
            if r['class'] not in ('BAIXO','MÉDIO','ALTO'): failures.append('CLASS_INVALID:'+r['weapon_id'])
            if r['relative_cost'] not in ('BAIXO','MÉDIO','ALTO'): failures.append('COST_INVALID:'+r['weapon_id'])
            if r['balance_role']['primary_strength']==r['balance_role']['primary_weakness']: failures.append('NO_TRADEOFF:'+r['weapon_id'])
        # Detect pathological domination: one record strictly >= every other in all major dimensions.
        keys=('power','defense','utility','handling','durability','reach','magic_affinity','tech_affinity')
        for a in self.records:
            if all(any(b['stats'][k]>a['stats'][k] for k in keys) for b in self.records if b is not a):
                pass
            dominated_all=True
            for b in self.records:
                if b is a: continue
                if not all(a['stats'][k]>=b['stats'][k] for k in keys): dominated_all=False; break
            if dominated_all: failures.append('DOMINANT_WEAPON:'+a['weapon_id'])
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'count':len(self.records),'class_counts':{t:sum(r['class']==t for r in self.records) for t in ('BAIXO','MÉDIO','ALTO')}}

    def export(self)->dict[str,Any]:
        return {'schema_version':'1.1.0','record_id':'MAR-CANON-GAMEPLAY-STATS-V1.1','title':'MAR — Status canônicos balanceados para RPG isométrico','authority':self.AUTHORITY,'canonical_status':'CÂNONE_AUTORIZADO','master_integration_status':'PENDING_NEXT_MASTER_CONSOLIDATION','source_master':'V2.0.1_READ_ONLY','weapons':copy.deepcopy(self.records),'count':len(self.records),'validation':self.validate()}
