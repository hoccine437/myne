"""Constitutional gate over the existing Phase 5 staged evolution engine."""
from __future__ import annotations
from .constitution import ConstitutionEngine
from evolution.engine import EvolutionEngine
class ProtectedEvolution:
 def __init__(self,root):self.engine=EvolutionEngine(root)
 def prepare(self,reason,changes,**proposal):
  # Staging is non-deployment analysis. It may never target immutable core;
  # owner approval is enforced later at the consequential deploy boundary.
  for path in changes:
   if ConstitutionEngine.is_protected(path):
    raise PermissionError('Target is Constitution-protected.')
  return self.engine.prepare(reason,changes,**proposal)
 def deploy(self,manifest,tests,owner_approved=False):
  for path in manifest.files:
   allowed,message=ConstitutionEngine.can_execute('deploy',path,owner_approved)
   if not allowed:raise PermissionError(message)
  return self.engine.deploy(manifest,tests,approved=owner_approved)
