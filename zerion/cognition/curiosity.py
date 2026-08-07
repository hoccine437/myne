from dataclasses import dataclass
from knowledge.manager import KnowledgeManager
@dataclass(frozen=True)
class KnowledgeGap:
 goal:str; question:str; confidence:float
class CuriosityEngine:
 def __init__(self,knowledge=None):self.knowledge=knowledge or KnowledgeManager()
 def detect(self,goal:str)->KnowledgeGap|None:
  hits=self.knowledge.searcher.search(goal,limit=1)
  if hits and hits[0]['score'] >= .45:return None
  return KnowledgeGap(goal,f'What reliable information or experience is needed to solve: {goal}?',.25)
 def record(self,gap:KnowledgeGap)->int:
  return self.knowledge.store(gap.question,'knowledge_gap',['curiosity'],.55,gap.confidence,{'goal':gap.goal},'knowledge')
