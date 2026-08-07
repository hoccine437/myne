"""Shared immutable-core policy and typed upgrade manifests."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from pathlib import Path
import time, uuid
# Paths are project-relative. Prefix matching protects whole core directories.
PROTECTED_PATHS=("main.py","constitution/constitution.txt","constitution/constitution.py","constitution/constitution.lock","constitution/protected.lock","config.py","prompt.txt","terminal.py","speech.py","api.py","memory/","intent/","planner/","providers/","core/", ".env")
def normalize(path:str)->str:
 p=Path(path)
 if p.is_absolute() or '..' in p.parts: raise ValueError("path must be a safe project-relative path")
 return p.as_posix()
def is_protected(path:str)->bool:
 p=normalize(path); return any(p==x or p.startswith(x) for x in PROTECTED_PATHS)
@dataclass
class UpgradeManifest:
 reason:str; files:list[str]; risk:str; dependencies:list[str]; expected_improvement:str; rollback_strategy:str; complexity:str
 id:str=field(default_factory=lambda:uuid.uuid4().hex[:12]); created:float=field(default_factory=time.time); tests_passed:list[str]=field(default_factory=list); performance_impact:str="not measured"
 def validate(self)->None:
  if not self.files: raise ValueError("upgrade must affect at least one file")
  blocked=[p for p in self.files if is_protected(p)]
  if blocked: raise PermissionError(f"Constitution file(s) blocked: {blocked}")
 def data(self):return asdict(self)
