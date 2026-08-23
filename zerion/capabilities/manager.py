"""Persistent, open-ended capability records; categories emerge as tags."""
from __future__ import annotations
import re
from knowledge.manager import KnowledgeManager
import config
from .models import Capability,STAGES
def _name(text):
 words=re.findall(r'[\w-]{3,}',text.lower())[:5];return '-'.join(words) or 'general-problem-solving'
class CapabilityManager:
 def __init__(self,knowledge=None):self.knowledge=knowledge or KnowledgeManager()
 def find(self,goal,limit=None):
  if limit is None:
   limit=config.thinking_scale(6,60)
  return self.knowledge.searcher.search(goal,limit,['capability'])
 def acquire(self,goal,knowledge='',tags=None):
  name=_name(goal); return self.knowledge.store(knowledge or f'Capability candidate for: {goal}','capability',tags or name.split('-'),.55,.25,{'name':name,'stage':'learning','experience_count':0},'capability')
 def improve(self,goal,method,success,confidence=.5):
  records=self.find(goal,1); meta=records[0]['metadata'] if records else {}; count=int(meta.get('experience_count',0))+1
  stage=STAGES[min(len(STAGES)-1,1+count//3)] if success else meta.get('stage','learning')
  text=f'Method: {method}. Outcome: {"success" if success else "failure"}. Lessons retained for {goal}.'
  return self.knowledge.store(text,'capability_experience',[_name(goal)],.7 if success else .5,confidence,{'name':_name(goal),'stage':stage,'experience_count':count},'capability')
