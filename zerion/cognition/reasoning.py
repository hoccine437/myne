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

# Analytic goals ("why/how/compare/should I/cause/best") trigger multi-path
# hypothesis scaffolding. Each path has a distinct job:
#   evidence-led    — best explanation supported by retrieved records
#   context-gap     — explanation that needs information we don't have yet
#   environment-led — explanation rooted in external state (device/network/
#                     tools), not the request itself
# One generic pass is never a substitute for named paths with jobs.
_ANALYTIC_MARKERS = ('why', 'how ', 'how do', 'compare', 'should i', 'cause', 'reason', 'best way', 'explain')

class CognitiveReasoningEngine:
 def __init__(self,knowledge=None):self.knowledge=knowledge or KnowledgeManager()
 def reason(self,goal:str,records:list[dict]=())->ReasoningResult:
  text=goal.lower(); evidence=tuple(r.get('content','')[:160] for r in records[:3]) or (goal,)
  inferences=[]
  if any(x in text for x in ('offline','local','privacy')):
   inferences.append(Inference('User may prefer local or privacy-preserving execution.',.65,evidence,('request mentions offline/local/privacy','preference remains revisable'),time.time()))
  hypotheses=['reuse relevant validated records','ask only for missing required information','propose a safe alternative when uncertain']
  if any(m in text for m in _ANALYTIC_MARKERS):
   base=min(.7,.35+.15*len(records))
   candidates=[
    ('Evidence-led explanation: most-supported account from retrieved records.',base+.10,evidence),
    ('Context-gap explanation: the answer depends on information not yet supplied.',max(.3,base-.05),evidence),
    ('Environment-led explanation: an external state factor (device/network/tool/availability) is likely causal.',max(.3,base),evidence),
   ]
   for statement,conf,ev in candidates:
    inferences.append(Inference(statement,round(min(conf,.75),2),ev,('analytic goal detected','competing paths ranked by evidence','revisable'),time.time()))
   hypotheses+=[c[0] for c in candidates]
  confidence=min(.9,max(.35,min(.9,.35+.1*len(records)+.1*len(inferences))))
  strategy='evidence-guided reuse' if records else 'clarify or research proposal before consequential action'
  for item in inferences:self.knowledge.store(item.statement,'inference',['hypothesis'],.45,item.confidence,{'evidence':item.evidence,'chain':item.chain,'status':item.status,'timestamp':item.timestamp},'inference')
  return ReasoningResult(goal,tuple(hypotheses),strategy,confidence,tuple(inferences))
