import copy, json, os, sqlite3, tempfile, threading, unittest, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '01_RUNTIME'))

from living_runtime import LivingRuntime, ValidationError, IntegrityError, ConflictError, NotFoundError, OfflinePolicyError, new_runtime_id, clock_point
from agent_brain import AgentBrain, IntentValidator
from social_memory import SocialMemorySystem, MAX_RUMOR_HOPS

MASTER='/mnt/data/ANDROMEDA_CODEX_MASTER_V2_0_1_RELEASE.zip'

def make_entity(rt,w,kind='AGENT',data=None,canonical_ref=None,protection=None):
    c=rt.get_clock(w['world_instance_id'])
    s={'state_id':new_runtime_id('state'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],
       'entity_runtime_id':new_runtime_id(kind.lower()),'origin':'CANONICAL_BACKED' if canonical_ref else 'RUNTIME_BORN',
       'entity_kind':kind,'lifecycle':'ACTIVE','version':0,'updated_at':clock_point(c['day'],c['tick']),'data':copy.deepcopy(data or {})}
    if canonical_ref:s['canonical_ref']=canonical_ref
    if protection:s['protection']=copy.deepcopy(protection)
    rt.register_entity(w['world_instance_id'],s); return s

def action(rt,w,actor,event_type='SOCIAL_EVENT'):
    c=rt.get_clock(w['world_instance_id'])
    return {'action_id':new_runtime_id('action'),'intent_id':new_runtime_id('intent'),'world_instance_id':w['world_instance_id'],'timeline_id':w['timeline_id'],
            'actor_ref':actor,'action_type':event_type,'parameters':{},'precondition_snapshot':{},'idempotency_key':new_runtime_id('idem'),'created_at':clock_point(c['day'],c['tick']),'status':'SCHEDULED'}

class SocialCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=os.path.join(self.tmp.name,'w.db')
        self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.w=self.rt.create_world('social-test',606,ticks_per_day=24); self.wid=self.w['world_instance_id']
        self.val=IntentValidator(self.rt); self.brain=AgentBrain(self.rt,self.val); self.social=SocialMemorySystem(self.rt)
        self.a=make_entity(self.rt,self.w,'AGENT',{'needs':{'social':80},'goals':{'survive':80},'risk_tolerance':50})
        self.b=make_entity(self.rt,self.w,'AGENT',{'needs':{'social':50},'goals':{},'risk_tolerance':50,'marker':0})
        self.c=make_entity(self.rt,self.w,'AGENT',{'needs':{'social':50},'goals':{},'risk_tolerance':50,'marker':0})
    def tearDown(self): self.rt.close(); self.tmp.cleanup()
    def memory(self,**kw):
        base=dict(memory_type='OBSERVATION',content={'seen':True},source='SENSORY',subject_ref=self.b['entity_runtime_id'],confidence=.8,salience=60,emotional_weight=10)
        base.update(kw); return self.social.record_memory(self.wid,self.a['entity_runtime_id'],**base)
    def claim(self,agent=None,subject=None,**kw):
        base=dict(claim_key='b.state',predicate='state',value='SAFE',confidence=.8,source='SENSORY',subject_ref=(subject or self.b['entity_runtime_id']))
        base.update(kw); return self.social.add_claim(self.wid,agent or self.a['entity_runtime_id'],**base)
    def make_event(self,event_type='HELPED',subject=None):
        subject=subject or self.b['entity_runtime_id']
        a=action(self.rt,self.w,self.a['entity_runtime_id'],event_type)
        r=self.rt.apply_action(self.wid,a,[{'target_ref':subject,'operation':'INCREMENT','field_path':'data.marker','amount':1}])
        return self.rt.get_event(r['event_id'])

class MemoryTests(SocialCase):
    def test_record_memory(self): self.assertTrue(self.memory()['memory_id'].startswith('rt:memory:'))
    def test_invalid_memory_type(self):
        with self.assertRaises(ValidationError): self.memory(memory_type='DREAM_CANON')
    def test_invalid_memory_source(self):
        with self.assertRaises(ValidationError): self.memory(source='LLM_TRUTH')
    def test_non_authoritative_verified_memory_blocked(self):
        with self.assertRaises(ValidationError): self.memory(truth_status='VERIFIED_TRUE')
    def test_confidence_bounds(self):
        with self.assertRaises(ValidationError): self.memory(confidence=2)
    def test_salience_bounds(self):
        with self.assertRaises(ValidationError): self.memory(salience=101)
    def test_emotional_bounds(self):
        with self.assertRaises(ValidationError): self.memory(emotional_weight=-101)
    def test_invalid_persistence(self):
        with self.assertRaises(ValidationError): self.memory(persistence='ERASE')
    def test_memory_immutable_update(self):
        m=self.memory()
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("UPDATE social_memories SET memory_json='{}' WHERE memory_id=?",(m['memory_id'],))
    def test_memory_immutable_delete(self):
        m=self.memory()
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("DELETE FROM social_memories WHERE memory_id=?",(m['memory_id'],))
    def test_recall_subject_filter(self):
        self.memory(); self.memory(subject_ref=self.c['entity_runtime_id'],content={'other':1})
        xs=self.social.recall_memories(self.wid,self.a['entity_runtime_id'],subject_ref=self.b['entity_runtime_id']); self.assertEqual(len(xs),1)
    def test_recall_salience_ranking(self):
        self.memory(salience=20,content={'rank':'low'}); self.memory(salience=90,content={'rank':'high'})
        self.assertEqual(self.social.recall_memories(self.wid,self.a['entity_runtime_id'])[0]['content']['rank'],'high')
    def test_permanent_memory_does_not_decay(self):
        m=self.memory(salience=50,persistence='PERMANENT'); before=self.social.recall_memories(self.wid,self.a['entity_runtime_id'])[0]['recall_score']
        self.rt.advance_ticks(self.wid,24*300); after=self.social.recall_memories(self.wid,self.a['entity_runtime_id'])[0]['recall_score']; self.assertEqual(before,after)
    def test_standard_memory_decays(self):
        self.memory(salience=50,persistence='STANDARD'); before=self.social.recall_memories(self.wid,self.a['entity_runtime_id'])[0]['recall_score']
        self.rt.advance_ticks(self.wid,24*60); after=self.social.recall_memories(self.wid,self.a['entity_runtime_id'])[0]['recall_score']; self.assertLess(after,before)
    def test_remember_event_verified(self):
        ev=self.make_event(); x=self.social.remember_event(self.wid,self.a['entity_runtime_id'],ev.event_id); self.assertEqual(x['claim']['truth_status'],'VERIFIED_TRUE')
    def test_cross_world_event_rejected(self):
        w2=self.rt.create_world('other',1); other=make_entity(self.rt,w2,'AGENT',{'x':0}); rr=self.rt.apply_action(w2['world_instance_id'],action(self.rt,w2,other['entity_runtime_id'],'X'),[{'target_ref':other['entity_runtime_id'],'operation':'INCREMENT','field_path':'data.x','amount':1}]); ev=self.rt.get_event(rr['event_id'])
        with self.assertRaises(ValidationError): self.social.remember_event(self.wid,self.a['entity_runtime_id'],ev.event_id)

class KnowledgeTests(SocialCase):
    def test_add_unknown_claim(self): self.assertEqual(self.claim()['truth_status'],'UNKNOWN')
    def test_non_authority_verified_claim_blocked(self):
        with self.assertRaises(ValidationError): self.claim(truth_status='VERIFIED_TRUE')
    def test_system_verification_allowed(self):
        c=self.social.verify_claim(self.wid,self.a['entity_runtime_id'],claim_key='door.open',predicate='open',value=True,is_true=True,subject_ref=self.b['entity_runtime_id']); self.assertEqual(c['truth_status'],'VERIFIED_TRUE')
    def test_knowledge_materializes(self):
        self.claim(); k=self.social.get_knowledge(self.wid,self.a['entity_runtime_id'],'b.state'); self.assertEqual(k['current_value'],'SAFE')
    def test_independent_sources_raise_confidence(self):
        self.claim(confidence=.5); self.claim(confidence=.5,source='INFERENCE'); k=self.social.get_knowledge(self.wid,self.a['entity_runtime_id'],'b.state'); self.assertGreater(k['confidence'],.5)
    def test_same_origin_does_not_echo_amplify(self):
        c=self.claim(confidence=.5); self.social.add_claim(self.wid,self.a['entity_runtime_id'],claim_key='b.state',predicate='state',value='SAFE',confidence=.5,source='MEMORY',subject_ref=self.b['entity_runtime_id'],origin_claim_id=c['origin_claim_id'],provenance_chain=[self.a['entity_runtime_id']],rumor_hop=0)
        self.assertEqual(self.social.get_knowledge(self.wid,self.a['entity_runtime_id'],'b.state')['confidence'],.5)
    def test_conflicting_unknown_claims_contested(self):
        self.claim(value='SAFE',confidence=.8); self.claim(value='DANGER',confidence=.7); self.assertEqual(self.social.get_knowledge(self.wid,self.a['entity_runtime_id'],'b.state')['truth_status'],'CONTESTED')
    def test_verified_truth_wins_unknown(self):
        self.claim(value='DANGER',confidence=.99); self.social.verify_claim(self.wid,self.a['entity_runtime_id'],claim_key='b.state',predicate='state',value='SAFE',is_true=True,subject_ref=self.b['entity_runtime_id']); self.assertEqual(self.social.get_knowledge(self.wid,self.a['entity_runtime_id'],'b.state')['current_value'],'SAFE')
    def test_conflicting_verified_truth_rejected(self):
        self.social.verify_claim(self.wid,self.a['entity_runtime_id'],claim_key='b.state',predicate='state',value='SAFE',is_true=True,subject_ref=self.b['entity_runtime_id'])
        with self.assertRaises(IntegrityError): self.social.verify_claim(self.wid,self.a['entity_runtime_id'],claim_key='b.state',predicate='state',value='DANGER',is_true=True,subject_ref=self.b['entity_runtime_id'])
    def test_claim_immutable(self):
        c=self.claim()
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("DELETE FROM knowledge_claims WHERE claim_id=?",(c['claim_id'],))
    def test_invalid_provenance_duplicate_agent(self):
        with self.assertRaises(ValidationError): self.social.add_claim(self.wid,self.a['entity_runtime_id'],claim_key='x',predicate='x',value=1,confidence=.5,source='COMMUNICATION',provenance_chain=[self.a['entity_runtime_id'],self.a['entity_runtime_id']],rumor_hop=1)
    def test_hop_mismatch_rejected(self):
        with self.assertRaises(ValidationError): self.social.add_claim(self.wid,self.a['entity_runtime_id'],claim_key='x',predicate='x',value=1,confidence=.5,source='COMMUNICATION',provenance_chain=[self.a['entity_runtime_id']],rumor_hop=1)
    def test_hop_limit_rejected(self):
        chain=[self.a['entity_runtime_id']]+[new_runtime_id('agent') for _ in range(MAX_RUMOR_HOPS+1)]
        with self.assertRaises(ValidationError): self.social.add_claim(self.wid,self.a['entity_runtime_id'],claim_key='x',predicate='x',value=1,confidence=.5,source='COMMUNICATION',provenance_chain=chain,rumor_hop=MAX_RUMOR_HOPS+1)

class RelationshipTests(SocialCase):
    def test_default_relationship_zero(self): self.assertEqual(self.social.get_relationship(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'])['trust'],0)
    def test_apply_relationship_delta(self): self.assertEqual(self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':25},reason='help')['trust'],25)
    def test_directed_relationship(self):
        self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':25},reason='help'); self.assertEqual(self.social.get_relationship(self.wid,self.b['entity_runtime_id'],self.a['entity_runtime_id'])['trust'],0)
    def test_relationship_clamps_positive(self): self.assertEqual(self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':200},reason='x')['trust'],100)
    def test_relationship_clamps_negative(self): self.assertEqual(self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':-200},reason='x')['trust'],-100)
    def test_fear_never_negative(self): self.assertEqual(self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'fear':-50},reason='x')['fear'],0)
    def test_invalid_dimension(self):
        with self.assertRaises(ValidationError): self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'love':5},reason='x')
    def test_self_relationship_rejected(self):
        with self.assertRaises(ValidationError): self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.a['entity_runtime_id'],{'trust':5},reason='x')
    def test_relationship_idempotency(self):
        k='same-rel'; self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':5},reason='x',idempotency_key=k); r=self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':5},reason='x',idempotency_key=k); self.assertTrue(r['idempotent']); self.assertEqual(self.social.get_relationship(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'])['trust'],5)
    def test_protected_holder_relationship_blocked(self):
        p=make_entity(self.rt,self.w,'AGENT',{},protection={'relationship_change':'BLOCKED'})
        with self.assertRaises(ValidationError): self.social.apply_relationship_delta(self.wid,p['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':5},reason='x')
    def test_relationship_event_immutable(self):
        r=self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':5},reason='x')
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("DELETE FROM relationship_events WHERE relationship_event_id=?",(r['relationship_event_id'],))

class ReputationTests(SocialCase):
    def test_default_global_reputation_zero(self): self.assertEqual(self.social.get_reputation(self.wid,self.b['entity_runtime_id'])['score'],0)
    def test_apply_reputation(self): self.assertEqual(self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],-20,reason='crime')['score'],-20)
    def test_reputation_clamps(self): self.assertEqual(self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],200,reason='hero')['score'],100)
    def test_global_scope_ref_rejected(self):
        with self.assertRaises(ValidationError): self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],5,scope_type='GLOBAL',scope_ref='FAC-008',reason='x')
    def test_non_global_requires_scope_ref(self):
        with self.assertRaises(ValidationError): self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],5,scope_type='FACTION',reason='x')
    def test_faction_scope(self): self.assertEqual(self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],10,scope_type='FACTION',scope_ref='FAC-008',reason='x')['score'],10)
    def test_scopes_isolated(self):
        self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],10,scope_type='FACTION',scope_ref='FAC-008',reason='x'); self.assertEqual(self.social.get_reputation(self.wid,self.b['entity_runtime_id'])['score'],0)
    def test_reputation_idempotency(self):
        self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],10,reason='x',idempotency_key='r1'); r=self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],10,reason='x',idempotency_key='r1'); self.assertTrue(r['idempotent']); self.assertEqual(self.social.get_reputation(self.wid,self.b['entity_runtime_id'])['score'],10)
    def test_reputation_event_immutable(self):
        r=self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],10,reason='x')
        with self.assertRaises(sqlite3.DatabaseError): self.rt.conn.execute("DELETE FROM reputation_events WHERE reputation_event_id=?",(r['reputation_event_id'],))

class PolicyWitnessTests(SocialCase):
    def policy(self,**kw):
        p={'policy_key':'social.help','event_type':'HELPED','subject_index':1,'relationship_deltas':{'trust':20,'affinity':10,'respect':5},'reputation_delta':8,'reputation_scope_type':'GLOBAL','rumor_effect_factor':.5}; p.update(kw); return self.social.register_effect_policy(self.wid,p)
    def test_register_policy(self): self.assertEqual(self.policy()['status'],'ACTIVE')
    def test_invalid_policy_dimension(self):
        with self.assertRaises(ValidationError): self.policy(relationship_deltas={'love':1})
    def test_witness_applies_effects(self):
        self.policy(); ev=self.make_event('HELPED',self.b['entity_runtime_id']); x=self.social.witness_event(self.wid,self.a['entity_runtime_id'],ev.event_id); self.assertEqual(x['effects']['relationship']['trust'],20); self.assertEqual(x['effects']['reputation']['score'],8)
    def test_witness_idempotent_effects(self):
        self.policy(); ev=self.make_event('HELPED',self.b['entity_runtime_id']); self.social.witness_event(self.wid,self.a['entity_runtime_id'],ev.event_id); self.social.witness_event(self.wid,self.a['entity_runtime_id'],ev.event_id); self.assertEqual(self.social.get_relationship(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'])['trust'],20)
    def test_policy_event_mismatch(self):
        self.policy(); ev=self.make_event('ATTACKED',self.b['entity_runtime_id'])
        with self.assertRaises(ValidationError): self.social.witness_event(self.wid,self.a['entity_runtime_id'],ev.event_id,policy_key='social.help')

class RumorTests(SocialCase):
    def source_claim(self,agent=None,subject=None,meta=None):
        return self.social.add_claim(self.wid,agent or self.a['entity_runtime_id'],claim_key='crime.x',predicate='committed_crime',value=True,confidence=.9,source='SENSORY',subject_ref=subject or self.c['entity_runtime_id'],metadata=meta or {})
    def test_rumor_transmits_unknown(self):
        c=self.source_claim(); t=self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); self.assertEqual(t['status'],'ACCEPTED'); k=self.social.get_knowledge(self.wid,self.b['entity_runtime_id'],'crime.x'); self.assertNotEqual(k['truth_status'],'VERIFIED_TRUE')
    def test_rumor_confidence_attenuates(self):
        c=self.source_claim(); t=self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); self.assertLess(t['resulting_confidence'],.9)
    def test_listener_trust_increases_confidence(self):
        c=self.source_claim(); self.social.apply_relationship_delta(self.wid,self.b['entity_runtime_id'],self.a['entity_runtime_id'],{'trust':80},reason='trusted'); t=self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); self.assertGreater(t['resulting_confidence'],.6)
    def test_listener_distrust_reduces_confidence(self):
        c=self.source_claim(); self.social.apply_relationship_delta(self.wid,self.b['entity_runtime_id'],self.a['entity_runtime_id'],{'trust':-100},reason='distrust'); t=self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); self.assertLess(t['resulting_confidence'],.4)
    def test_duplicate_transmission_idempotent(self):
        c=self.source_claim(); self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); t=self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); self.assertTrue(t['idempotent'])
    def test_provenance_cycle_blocked(self):
        c=self.source_claim(); t=self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); with_claim=t['listener_claim_id']
        with self.assertRaises(ConflictError): self.social.transmit_claim(self.wid,self.b['entity_runtime_id'],self.a['entity_runtime_id'],with_claim)
    def test_offline_rumor_blocked(self):
        c=self.source_claim(); self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE')
        with self.assertRaises(OfflinePolicyError): self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id'])
    def test_offline_routine_safe_rumor_allowed(self):
        c=self.source_claim(); self.rt.set_simulation_mode(self.wid,'ROUTINE_OFFLINE'); self.assertEqual(self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id'],routine_safe=True)['status'],'ACCEPTED')
    def test_rumor_effects_attenuated(self):
        p=self.social.register_effect_policy(self.wid,{'policy_key':'social.crime','event_type':'CRIME','subject_index':1,'relationship_deltas':{'trust':-40},'reputation_delta':-30,'reputation_scope_type':'GLOBAL','rumor_effect_factor':.5})
        c=self.source_claim(meta={'effect_policy_key':'social.crime','event_type':'CRIME'}); t=self.social.transmit_claim(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],c['claim_id']); self.assertGreater(self.social.get_relationship(self.wid,self.b['entity_runtime_id'],self.c['entity_runtime_id'])['trust'],-40); self.assertLess(self.social.get_reputation(self.wid,self.c['entity_runtime_id'])['score'],0)

class BrainProjectionTests(SocialCase):
    def register_behavior(self,key,flag,priority):
        return self.brain.register_behavior(self.wid,{'behavior_key':key,'intent_type':'SOCIAL_CHOICE','need_key':'social','threshold':1,'target_strategy':'PERCEPTION','need_weight':1,'base_priority':priority,'risk_cost':0,'risk_penalty_weight':1,'opportunity_bonus':0,'goal_key':None,'goal_weight':0,'target_kinds':['AGENT'],'target_fact_equals':{f'flags.{flag}':True},'agent_state_equals':{},'parameters':{}})
    def test_projection_contains_relationship_flags(self):
        self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':-50},reason='betrayal'); p=self.social.project_social_perception(self.brain,self.wid,self.a['entity_runtime_id'],[self.b['entity_runtime_id']]); self.assertTrue(p['observations'][0]['facts']['flags']['untrusted'])
    def test_memory_social_state_changes_decision(self):
        self.register_behavior('approach.trusted','trusted',20); self.register_behavior('avoid.untrusted','untrusted',30)
        self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':40},reason='help'); self.social.project_social_perception(self.brain,self.wid,self.a['entity_runtime_id'],[self.b['entity_runtime_id']]); d1=self.brain.decide(self.wid,self.a['entity_runtime_id']); self.assertEqual(d1['selected']['behavior_key'],'approach.trusted')
        self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':-100},reason='betrayal'); self.social.project_social_perception(self.brain,self.wid,self.a['entity_runtime_id'],[self.b['entity_runtime_id']]); d2=self.brain.decide(self.wid,self.a['entity_runtime_id']); self.assertEqual(d2['selected']['behavior_key'],'avoid.untrusted')
    def test_reputation_flag_projection(self):
        self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],-60,reason='crime'); p=self.social.project_social_perception(self.brain,self.wid,self.a['entity_runtime_id'],[self.b['entity_runtime_id']]); self.assertTrue(p['observations'][0]['facts']['flags']['notorious'])
    def test_projection_counts_subject_knowledge(self):
        self.claim(); p=self.social.project_social_perception(self.brain,self.wid,self.a['entity_runtime_id'],[self.b['entity_runtime_id']]); self.assertEqual(p['observations'][0]['facts']['knowledge']['known_claims'],1)

class IntegrityTests(SocialCase):
    def test_clean_integrity(self):
        self.memory(); self.claim(); self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':5},reason='x'); self.social.apply_reputation_delta(self.wid,self.b['entity_runtime_id'],5,reason='x'); self.assertEqual(self.social.full_integrity_check(self.wid)['status'],'PASS')
    def test_corrupt_memory_detected(self):
        m=self.memory(); self.rt.conn.execute('DROP TRIGGER memories_no_update'); self.rt.conn.execute("UPDATE social_memories SET memory_json='{}' WHERE memory_id=?",(m['memory_id'],)); self.assertEqual(self.social.full_integrity_check(self.wid)['status'],'FAIL')
    def test_corrupt_relationship_materialization_detected(self):
        self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':10},reason='x'); self.rt.conn.execute("UPDATE relationships_current SET relationship_json='{}' WHERE world_instance_id=?",(self.wid,)); self.assertEqual(self.social.full_integrity_check(self.wid)['status'],'FAIL')
    def test_integrity_guard_blocks_world(self):
        m=self.memory(); self.rt.conn.execute('DROP TRIGGER memories_no_update'); self.rt.conn.execute("UPDATE social_memories SET memory_json='{}' WHERE memory_id=?",(m['memory_id'],)); r=self.social.integrity_guard(self.wid); self.assertEqual(r['status'],'FAIL'); self.assertEqual(self.rt.get_world(self.wid)['status'],'CORRUPT_BLOCKED')
    def test_reopen_persists_social_state(self):
        self.social.apply_relationship_delta(self.wid,self.a['entity_runtime_id'],self.b['entity_runtime_id'],{'trust':15},reason='x'); aid=self.a['entity_runtime_id']; bid=self.b['entity_runtime_id']; self.rt.close(); self.rt=LivingRuntime(self.db,master_release_path=MASTER); self.social=SocialMemorySystem(self.rt); self.assertEqual(self.social.get_relationship(self.wid,aid,bid)['trust'],15)

if __name__=='__main__': unittest.main()
