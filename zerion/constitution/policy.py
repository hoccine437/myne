"""Immutable operational policy: cognitive freedom, governed external effects."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .constitution import ConstitutionEngine
@dataclass(frozen=True)
class Decision:
 allowed: bool; requires_approval: bool; reason: str; alternative: str=''
class Constitution:
 """Small deterministic policy boundary; it never executes an action."""
 VERSION='1.0'
 def evaluate(self, action:str, target:str='')->Decision:
  action=action.lower().strip()
  if action in {'deploy','modify','delete'} and target and ConstitutionEngine.is_protected(target):
   return Decision(False,False,'Protected constitutional component cannot be changed.','Create an additive module or proposal instead.')
  if action in {'deploy','modify','delete','execute_shell','execute_python'}:
   return Decision(True,True,'Consequential action requires explicit user approval.')
  if action in {'research','reason','learn','retrieve','reflect','propose'}:
   return Decision(True,False,'Cognitive action is permitted.')
  return Decision(True,False,'Action is permitted; existing tool policy still applies.')
