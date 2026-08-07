from __future__ import annotations
from dataclasses import asdict,dataclass,field
from knowledge.manager import KnowledgeManager
@dataclass
class ExecutionExperience:
 context:str;goal:str;strategy:str;alternatives:list[str]=field(default_factory=list);path:list[str]=field(default_factory=list);success:bool=False;latency:float=0.;resource_usage:float=0.;lessons:str='';confidence:float=.5
class ExperienceEngine:
 def __init__(self,knowledge=None):self.knowledge=knowledge or KnowledgeManager()
 def record(self,e):return self.knowledge.store(e.lessons or e.goal,'rich_experience',e.path,.75 if e.success else .5,e.confidence,asdict(e),'experience')
