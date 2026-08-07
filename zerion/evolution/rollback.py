from __future__ import annotations
import shutil
from pathlib import Path
class RollbackEngine:
 def __init__(self,root):self.root=Path(root);self.base=self.root/'.zerion/evolution/backups'
 def rollback(self,ident):
  backup=self.base/ident
  if not backup.exists():raise FileNotFoundError(f'rollback point not found: {ident}')
  restored=[]
  for source in backup.rglob('*'):
   if source.is_file():
    rel=source.relative_to(backup)
    if rel.name.endswith('.absent'):
     target=self.root/str(rel)[:-7]
     if target.exists(): target.unlink()
     restored.append(str(rel)[:-7]); continue
    target=self.root/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);restored.append(rel.as_posix())
  return restored
