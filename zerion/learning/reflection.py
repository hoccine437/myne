from __future__ import annotations
from dataclasses import dataclass
from knowledge.manager import KnowledgeManager
@dataclass
class Reflection: content:str; important:bool=False; confidence:float=.6
def reflect(goal:str,result:str,failures:list[str]|None=None)->Reflection:
 failures=failures or []; worked='completed response was produced' if result else 'no usable result'
 text=f"Goal: {goal}. What worked: {worked}. What failed: {', '.join(failures) or 'none observed'}. Improvement: {'apply correction before retrying' if failures else 'reuse this approach when relevant'}."
 return Reflection(text,bool(result or failures),.75 if not failures else .55)
class ReflectionStore:
 def __init__(self,manager=None):self.manager=manager or KnowledgeManager()
 def record(self,r:Reflection):return self.manager.store(r.content,'reflection',['reflection'],.7,r.confidence,layer='reflection')
