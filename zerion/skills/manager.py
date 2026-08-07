from .base import Skill
from .software import SKILL as SOFTWARE
from .finance import SKILL as FINANCE
from .electronics import SKILL as ELECTRONICS
from .human import SKILL as HUMAN
class SkillManager:
 def __init__(self,skills=None):self.skills={x.name:x for x in (skills or [SOFTWARE,FINANCE,ELECTRONICS,HUMAN])}
 def select(self,text):
  t=text.lower(); keys={'financial_markets':('stock','market','invest','finance'),'electronics':('circuit','voltage','resistor','arduino'),'software_engineering':('code','python','bug','program')}
  return self.skills[next((n for n,k in keys.items() if any(x in t for x in k)),'human_knowledge')]
