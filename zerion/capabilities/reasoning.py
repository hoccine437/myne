"""Goal-first composition of retrieved knowledge, not a predefined domain list."""
from dataclasses import dataclass
from .manager import CapabilityManager
from .models import CapabilityGap
@dataclass(frozen=True)
class CapabilityContext:
 goal:str; records:tuple[dict,...]; gap:CapabilityGap|None; strategy:str
class CapabilityReasoner:
 def __init__(self,manager=None):self.manager=manager or CapabilityManager()
 def assess(self,goal):
  records=tuple(self.manager.find(goal)); gap=None if records else CapabilityGap(goal,f'No validated reusable method for {goal}')
  strategy='Compose retrieved methods around the goal.' if records else 'Propose safe research/documentation study before external execution.'
  return CapabilityContext(goal,records,gap,strategy)
