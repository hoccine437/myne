"""Transparent, bounded reasoning records; not claims of human cognition."""
from __future__ import annotations
from dataclasses import dataclass
import time
from knowledge.manager import KnowledgeManager
@dataclass(frozen=True)
class Inference:
 statement:str; confidence:float; evidence:tuple[str,...]; chain:tuple[str,...]; timestamp:float; status:str='hypothesis'
@dataclass(frozen=True)
class ReasoningResult:
 goal:str; hypotheses:tuple[str,...]; strategy:str; confidence:float; inferences:tuple[Inference,...]
class CognitiveReasoningEngine:
 def __init__(self,knowledge=None):self.knowledge=knowledge or KnowledgeManager()
 def reason(self,goal:str,records:list[dict]=())->ReasoningResult:
  text=goal.lower(); evidence=tuple(r.get('content','')[:160] for r in records[:3]) or (goal,)
  inferences=[]
  if any(x in text for x in ('offline','local','privacy')):
   inferences.append(Inference('User may prefer local or privacy-preserving execution.',.65,evidence,('request mentions offline/local/privacy','preference remains revisable'),time.time()))
  hypotheses=('reuse relevant validated records','ask only for missing required information','propose a safe alternative when uncertain')
  confidence=min(.9,.35+.1*len(records)+.1*len(inferences))
  strategy='evidence-guided reuse' if records else 'clarify or research proposal before consequential action'
  for item in inferences:self.knowledge.store(item.statement,'inference',['hypothesis'],.45,item.confidence,{'evidence':item.evidence,'chain':item.chain,'status':item.status,'timestamp':item.timestamp},'inference')
  return ReasoningResult(goal,hypotheses,strategy,confidence,tuple(inferences))
