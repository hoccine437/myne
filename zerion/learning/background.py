"""Cooperative idle maintenance: one cheap operation per call, load-aware."""
import os
from learning.optimizer import MemoryOptimizer
class BackgroundLearning:
 def run_once(self)->str:
  try:
   if hasattr(os,'getloadavg') and os.getloadavg()[0] > 1.5:return 'paused: system load is high'
   return f'consolidated {MemoryOptimizer().consolidate()} empty records'
  except Exception as exc:return f'deferred: {exc}'
