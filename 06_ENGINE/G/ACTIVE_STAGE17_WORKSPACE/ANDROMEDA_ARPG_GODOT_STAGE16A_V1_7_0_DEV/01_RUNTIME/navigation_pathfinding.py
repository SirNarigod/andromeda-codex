from __future__ import annotations
import heapq, math
from typing import Any

class NavigationPathfindingSystem:
    VERSION='V1.5.0'; AUTHORITY='LIVING_COUNTRY_RUNTIME_PATHFINDING'
    def __init__(self,country:Any,spatial:Any,lod:Any,environment:Any):
        self.country=country; self.spatial=spatial; self.lod=lod; self.environment=environment
    def _blocks(self): return [b for st in self.country.world['country']['states'] for b in st['blocks']]
    def _dist(self,a,b):
        x1,y1=self.spatial._local_xy(a['coordinate_center']['longitude'],a['coordinate_center']['latitude'])
        x2,y2=self.spatial._local_xy(b['coordinate_center']['longitude'],b['coordinate_center']['latitude'])
        return math.hypot(x2-x1,y2-y1)/1000.0
    def _block_for_point(self,lon,lat):
        for b in self._blocks():
            x0,y0,x1,y1=map(float,b['bounding_region'])
            if x0-1e-9<=float(lon)<=x1+1e-9 and y0-1e-9<=float(lat)<=y1+1e-9:return b
        return None
    def _bridge_state(self,b):
        bridges=list(b.get('bridges') or [])
        if not bridges:return {'blocked':False,'multiplier':1.0,'status':'NONE'}
        statuses={str(x.get('status','ACTIVE')).upper() for x in bridges}
        if 'DESTROYED' in statuses:return {'blocked':True,'multiplier':math.inf,'status':'DESTROYED'}
        if 'DAMAGED' in statuses:return {'blocked':False,'multiplier':1.6,'status':'DAMAGED'}
        return {'blocked':False,'multiplier':1.0,'status':'ACTIVE'}
    def _canonical_route_edges(self):
        edges=[]
        for route in self.lod.canonical_routes:
            seq=[]
            for p in (route.get('geometry') or {}).get('coordinates',[]):
                b=self._block_for_point(p[0],p[1])
                if b and (not seq or seq[-1]['id']!=b['id']):seq.append(b)
            if len(seq)<2:continue
            total=float(route.get('distance_km') or route.get('geometry_distance_km') or 0.0)
            leg_dist=total/max(1,len(seq)-1)
            for a,b in zip(seq,seq[1:]):
                ba,bb=self._bridge_state(a),self._bridge_state(b)
                if ba['blocked'] or bb['blocked']:continue
                env=min(self.environment.state_for_block(a['id'])['movement_factor'],self.environment.state_for_block(b['id'])['movement_factor'])
                mult=max(ba['multiplier'],bb['multiplier']);cost=leg_dist*0.55*(1.0/max(.25,env))*mult
                base={'distance_km':round(leg_dist,3),'cost':cost,'root_penalty':1.0,'environment_factor':env,'bridge_status':bb['status'],'route_ref':route['id'],'route_type':route.get('type'),'authority':'CÂNONE_ESPACIAL_NAV_EDGE'}
                edges.append((a['id'],{'to':b['id'],**base}))
                if bool(route.get('bidirectional',True)):edges.append((b['id'],{'to':a['id'],**base}))
        return edges
    def _adjacency(self):
        blocks=self._blocks(); g={b['id']:[] for b in blocks}
        # Runtime terrain graph is a fallback for areas without canonical roads.
        for b in blocks:
            nearest=sorted(((self._dist(b,o),o['id'],o) for o in blocks if o['id']!=b['id']),key=lambda x:(x[0],x[1]))[:4]
            for d,_,o in nearest:
                if d>900:continue
                br=self._bridge_state(o); root_pen=2.5 if o.get('root_deep') else 1.0
                if br['blocked']:continue
                cl=self.environment.state_for_block(o['id']); terrain=1.0/cl['movement_factor']; cost=d*root_pen*terrain*br['multiplier']
                g[b['id']].append({'to':o['id'],'distance_km':round(d,3),'cost':cost,'root_penalty':root_pen,'environment_factor':cl['movement_factor'],'bridge_status':br['status'],'authority':'RUNTIME_DERIVED_NAV_EDGE'})
        # Canonical edges override equivalent derived edges and are preferred by lower cost.
        for src,e in self._canonical_route_edges():
            g[src]=[x for x in g[src] if x['to']!=e['to'] or x.get('authority')=='CÂNONE_ESPACIAL_NAV_EDGE']
            g[src].append(e)
        for src in g:g[src].sort(key=lambda e:(e['cost'],e['to'],e.get('route_ref','')))
        return g
    def plan_blocks(self,origin_block_id,destination_block_id):
        if origin_block_id==destination_block_id:return {'status':'PASS','blocks':[origin_block_id],'distance_km':0.0,'cost':0.0,'canonical_route_refs':[],'authority':self.AUTHORITY}
        g=self._adjacency();pq=[(0.0,origin_block_id,[])];best={origin_block_id:0.0}
        while pq:
            cost,node,path=heapq.heappop(pq)
            if cost!=best.get(node):continue
            if node==destination_block_id:
                refs=sorted({e['route_ref'] for e in path if e.get('route_ref')})
                return {'status':'PASS','blocks':[origin_block_id]+[e['to'] for e in path],'edges':path,'distance_km':round(sum(e['distance_km'] for e in path),3),'cost':round(cost,3),'canonical_route_refs':refs,'authority':self.AUTHORITY}
            for e in g.get(node,[]):
                nc=cost+e['cost']
                if nc<best.get(e['to'],math.inf):best[e['to']]=nc;heapq.heappush(pq,(nc,e['to'],path+[e]))
        return {'status':'REJECTED','reason':'NO_PATH','origin_block_id':origin_block_id,'destination_block_id':destination_block_id,'authority':self.AUTHORITY}
    def verify(self):
        g=self._adjacency();blocks=self._blocks();failures=[]
        for b in blocks:
            if b['id'] not in g:failures.append('BLOCK_GRAPH_MISSING:'+b['id'])
        for src,edges in g.items():
            for e in edges:
                if e['cost']<0 or e['distance_km']<0:failures.append('NEGATIVE_EDGE:'+src+':'+e['to'])
        return {'status':'PASS' if not failures else 'FAIL','failures':failures,'blocks':len(blocks),'edges':sum(map(len,g.values())),'canonical_edges':sum(1 for v in g.values() for e in v if e.get('route_ref'))}
