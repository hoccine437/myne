"""Orchestrates explicit, bounded learning; never changes code or prompts."""
from __future__ import annotations
from .experience import Experience,ExperienceStore
from .reflection import reflect,ReflectionStore
from knowledge.manager import KnowledgeManager
class LearningEngine:
 def __init__(self):self.knowledge=KnowledgeManager();self.experiences=ExperienceStore(self.knowledge);self.reflections=ReflectionStore(self.knowledge)
 def learn_task(self,goal,result,tools=None,elapsed=0.,failures=None,corrections=None):
  e=Experience(goal,tools=tools or [],execution_time=elapsed,failures=failures or [],corrections=corrections or [],final_result=result,confidence=.75 if result and not failures else .5,recommendation='Reuse successful tool sequence.' if result else 'Ask for clarification or revise plan.')
  self.experiences.record(e); r=reflect(goal,result,e.failures); self.reflections.record(r)
  if result and len(result)>80:self.knowledge.store(result,'summary',['task-output'],.55,e.confidence,layer='knowledge')
  return r
