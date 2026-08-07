"""Lightweight metadata/lifecycle extension over existing knowledge and world storage."""
from __future__ import annotations
import time
from knowledge.manager import KnowledgeManager
from intelligence.world import WorldModel
class MemoryIntelligence:
 def __init__(self,knowledge=None,world=None):self.knowledge=knowledge or KnowledgeManager();self.world=world or WorldModel()
 def capture(self,content,kind='fact',importance=.5,confidence=.5,source='runtime',evidence=None,status='captured',related=None):
  meta={'memory_type':kind,'source':source,'evidence':evidence or [],'creation_time':time.time(),'last_verified':None,'last_used':time.time(),'usage_count':0,'related_memories':related or [],'status':status,'confidence_history':[confidence]}
  ident=self.knowledge.store(content,kind,[kind,status],importance,confidence,meta,'knowledge')
  for rel in related or []:self.world.link(f'memory:{ident}','related_to',str(rel),.5)
  return ident
 def inference(self,statement,confidence,evidence,chain,supporting=None):
  return self.capture(statement,'inference',.45,confidence,'reasoning',evidence,'hypothesis',supporting or [])
 def procedure(self,workflow,tools,prerequisites,verification,confidence=.6):
  return self.capture(workflow,'procedure',.7,confidence,'experience',{'tools':tools,'prerequisites':prerequisites,'verification':verification},'verified')
 def episodic(self,goal,context,actions,outcome,lessons,confidence):
  return self.capture(outcome or goal,'episode',.7,confidence,'experience',{'goal':goal,'context':context,'actions':actions,'lessons':lessons},'reviewed')
 def retrieve(self,query,active_goal='',limit=6):
  rows=self.knowledge.searcher.search(query+' '+active_goal,limit)
  return sorted(rows,key=lambda r:(r['score'],r['confidence'],r['importance']),reverse=True)
 def consolidate(self,limit=50):
  """Bounded, non-destructive cleanup: archive only inactive low-value records."""
  rows=self.knowledge.db.query('SELECT id,importance,confidence,uses,accessed FROM records ORDER BY accessed ASC LIMIT ?',(limit,)); archived=0
  cutoff=time.time()-60*60*24*180
  for row in rows:
   if row['accessed']<cutoff and row['importance']<.25 and row['confidence']<.3 and row['uses']==0:
    self.knowledge.db.update('UPDATE records SET category=? WHERE id=?',('archived',row['id']));archived+=1
  return {'reviewed':len(rows),'archived':archived}
