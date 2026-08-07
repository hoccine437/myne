"""Ephemeral, task-scoped reasoning modes—data, not permanent agents."""
from dataclasses import dataclass
@dataclass(frozen=True)
class ReasoningMode:
 name:str; rules:tuple[str,...]
def select_mode(goal:str)->ReasoningMode:
 text=goal.lower()
 if any(x in text for x in ('code','bug','python','program')): return ReasoningMode('programming',('inspect interfaces first','prefer tested minimal changes'))
 if any(x in text for x in ('research','compare','source','why')): return ReasoningMode('research',('identify evidence gaps','separate evidence from inference'))
 if any(x in text for x in ('plan','steps','strategy')): return ReasoningMode('planning',('start from the goal','identify dependencies before tools'))
 if any(x in text for x in ('security','risk','threat')): return ReasoningMode('security_analysis',('minimize privilege','validate external effects'))
 return ReasoningMode('general_reasoning',('start from the user goal','consider alternatives before tools'))
