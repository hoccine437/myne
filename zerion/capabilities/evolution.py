"""Bounded evolution: creates proposals/records, never autonomously researches or deploys."""
from .manager import CapabilityManager
from .reasoning import CapabilityReasoner
class CapabilityEvolution:
 def __init__(self):self.manager=CapabilityManager();self.reasoner=CapabilityReasoner(self.manager)
 def prepare(self,goal):
  context=self.reasoner.assess(goal)
  if context.gap:self.manager.acquire(goal,tags=['capability-gap'])
  return context
 def learn(self,goal,method,success,confidence=.5):return self.manager.improve(goal,method,success,confidence)
 def idle_review(self,limit=10):
  """Local-only review: returns weak records for supervised research proposals."""
  rows=self.manager.knowledge.db.query('SELECT * FROM records WHERE layer=? ORDER BY confidence ASC LIMIT ?',('capability',limit))
  return [{'capability':r['content'],'recommendation':'Review evidence or propose a safe experiment.'} for r in rows]
