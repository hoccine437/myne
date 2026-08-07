from .engine import PhoneIntelligence
class AutomationEngine:
 """Builds dynamic plans; execution remains explicitly approved."""
 def __init__(self,phone=None):self.phone=phone or PhoneIntelligence()
 def propose(self,goal):return self.phone.plan(goal)
