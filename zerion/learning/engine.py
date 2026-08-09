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
  if result and len(result)>80:
   importance=.55;confidence=e.confidence;tags=['task-output']
   # Self-Critic gate on what gets committed to long-term knowledge: the
   # review is LOCAL (structural checks + confidence), costing no extra LLM
   # call; a flagged summary is stored but marked, never silently promoted.
   try:
    import config
    if config.ENABLE_SELF_CRITIC:
     from intelligence.critic import self_critic
     critique=self_critic.review(goal,result,.65 if not failures else .4)
     if critique.should_improve:
      importance=.45;confidence=max(.3,confidence-.15);tags=['task-output','critic-flagged']
   except Exception:pass
   # route via the Memory Coordinator (single write-policy point)
   try:
    from memory.coordinator import coordinator
    coordinator.store('task.summary', result, category='summary', tags=tags,
                      importance=importance, confidence=confidence, layer='knowledge')
   except Exception:
    self.knowledge.store(result,'summary',tags,importance,confidence,layer='knowledge')
  return r
