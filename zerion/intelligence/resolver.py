from __future__ import annotations
import time
from .models import *
from .registry import ProviderRegistry
class ExecutionResolver:
 """Chooses/retries providers from evidence; external approval stays upstream."""
 def __init__(self,registry=None,quality=None):self.registry=registry or ProviderRegistry();self.quality=quality or {}
 def select(self,request,state):
  candidates=self.registry.candidates(state)
  if not candidates:return None,DecisionRecord(request.goal,'',(), 'No compatible execution provider.',0)
  def score(p):
   q=self.quality.get(p.name,{});return q.get('reliability',.5)*.45+q.get('confidence',.5)*.2-q.get('latency',.1)*.15-q.get('cost',.1)*.1-(.15 if state.battery>=0 and state.battery<15 and q.get('battery',0)>.4 else 0)
  ranked=sorted(candidates,key=score,reverse=True); chosen=ranked[0]
  return chosen,DecisionRecord(request.goal,chosen.name,tuple(x.name for x in ranked[1:]),'Best compatible reliability/latency/resource score.',score(chosen))
 def execute(self,request,state):
  provider,decision=self.select(request,state)
  if not provider:return ExecutionOutcome(False,decision.reason),decision
  # Retry/failover exactly once per alternative; no blind repeated effects.
  for p in [provider]+[x for x in self.registry.candidates(state) if x.name!=provider.name]:
   started=time.monotonic();out=p.execute(request);out=ExecutionOutcome(out.success,out.message,time.monotonic()-started,out.resource_cost,p.name,out.verified)
   if out.success or request.consequential:return out,decision
  return out,decision
