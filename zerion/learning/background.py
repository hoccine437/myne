"""Cooperative idle maintenance: one cheap operation per call, load-aware."""
import os
from learning.optimizer import MemoryOptimizer
class BackgroundLearning:
 def run_once(self)->str:
  try:
   if hasattr(os,'getloadavg') and os.getloadavg()[0] > 1.5:return 'paused: system load is high'
   msg=f'consolidated {MemoryOptimizer().consolidate()} empty records'
   # spaced-recall visibility: the scheduler owns the math (doubling/halving
   # intervals); idle time only REPORTS what is due — it never re-answers
   # anything, so a quiet host learns nothing and burns nothing.
   try:
    from learning.retention import RetentionScheduler
    due=RetentionScheduler().due()
    if due:msg+=f'; {len(due)} item(s) due for review (say /learn or ask about them)'
   except Exception:pass
   return msg
  except Exception as exc:return f'deferred: {exc}'
