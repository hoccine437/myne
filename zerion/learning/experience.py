from __future__ import annotations
from dataclasses import asdict,dataclass,field
from knowledge.manager import KnowledgeManager
@dataclass
class Experience:
 goal:str; plan:str=''; tools:list[str]=field(default_factory=list); execution_time:float=0.; failures:list[str]=field(default_factory=list); corrections:list[str]=field(default_factory=list); final_result:str=''; confidence:float=.6; recommendation:str=''
class ExperienceStore:
 def __init__(self,manager=None):self.manager=manager or KnowledgeManager()
 def record(self,e:Experience)->int:
  return self.manager.store(e.final_result or e.goal,'execution',e.tools,.8 if not e.failures else .55,e.confidence,asdict(e),'experience')
