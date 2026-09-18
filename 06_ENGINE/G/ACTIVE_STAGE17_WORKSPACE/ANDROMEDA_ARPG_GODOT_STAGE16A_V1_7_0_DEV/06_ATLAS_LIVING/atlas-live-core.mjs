export function assertReadOnlyProjection(p) {
  if (!p || p.projection_authority !== 'READ_ONLY_DERIVED_VIEW') throw new Error('invalid living projection authority');
  if (p.access?.runtime_write_authority !== false) throw new Error('runtime write authority forbidden');
  if (p.access?.canonical_level_4_hidden !== true) throw new Error('level 4 must remain hidden');
  return true;
}
export function layer(p,key){ assertReadOnlyProjection(p); return p.layers?.[key] ?? (key==='LIVE_SOCIAL'?{relationships:[],reputation:[]}:[]); }
export function overlayForCanonical(p,canonicalId){ return layer(p,'LIVE_ENTITY_STATE').filter(x=>x.canonical_ref===canonicalId); }
export function decorateCanonicalEntity(entity,p){
  const overlays=overlayForCanonical(p,entity.id); if(!overlays.length)return {...entity,runtime:null};
  return {...entity,runtime:{timeline_id:p.world?.timeline_id,states:overlays.map(o=>({entity_runtime_id:o.entity_runtime_id,lifecycle:o.lifecycle,entity_kind:o.entity_kind,version:o.version,data:o.data,authority:o.authority}))}};
}
export function runtimeBadges(state){
  const b=[]; const d=state?.data||{};
  if(state?.lifecycle==='DESTROYED')b.push('DESTROYED');
  if(d.burning)b.push('BURNING'); if(d.operational===false)b.push('ROUTE_BLOCKED');
  if(Number(d.shortage_pressure)>0)b.push('SHORTAGE'); if(Number(d.wildlife_threat)>0)b.push('WILDLIFE_THREAT');
  return b;
}
export function eventTimeline(p,{type=null,limit=100}={}){ return layer(p,'LIVE_EVENTS').filter(e=>!type||e.event_type===type).slice(0,limit); }
export function causalTrail(p,eventId){
  const rows=layer(p,'LIVE_CAUSAL'); const byEvent=new Map(rows.map(x=>[x.event_id,x])); const out=[]; let cur=byEvent.get(eventId); const seen=new Set();
  while(cur&&!seen.has(cur.event_id)){seen.add(cur.event_id);out.push(cur); if(cur.root_event_id===cur.event_id)break;cur=byEvent.get(cur.root_event_id);} return out;
}
export function accessSummary(p){assertReadOnlyProjection(p);return {role:p.access.role,runtime_access:p.runtime_access,spoiler_max:p.access.spoiler_max,level4_hidden:p.access.canonical_level_4_hidden};}
