"""Goal-first cognition facade. It only prepares reasoning context/proposals."""
from dataclasses import dataclass
from constitution import Constitution
from .modes import ReasoningMode,select_mode
from .curiosity import CuriosityEngine,KnowledgeGap
@dataclass(frozen=True)
class CognitiveContext:
 goal:str; mode:ReasoningMode; gap:KnowledgeGap|None; constitutional_reason:str
class CognitiveEngine:
 def __init__(self):self.constitution=Constitution();self.curiosity=CuriosityEngine()
 def prepare(self,goal:str)->CognitiveContext:
  decision=self.constitution.evaluate('reason')
  gap=self.curiosity.detect(goal)
  if gap:self.curiosity.record(gap)
  mode=select_mode(goal)
  # Personality rules ride the same prompt channel (reasoning_rules) main.py
  # already feeds the model — real behavioral influence, not a label change.
  try:
   import personality
   persona_rules=personality.persona_rules()
  except Exception:
   persona_rules=()
  if persona_rules:
   from dataclasses import replace
   mode=replace(mode,rules=tuple(mode.rules)+tuple(persona_rules))
  return CognitiveContext(goal,mode,gap,decision.reason)
 def propose_capability(self,goal:str,observed_limit:str)->dict:
  """Proposal only; Phase 5 remains responsible for review/test/deployment."""
  return {'goal':goal,'problem':observed_limit,'action':'propose','requires_approval':True,
          'next_step':'Create a Phase 5 upgrade manifest; do not modify code automatically.'}
