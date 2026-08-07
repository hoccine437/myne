"""Approval-gated atomic deployment. Existing files are backed up first."""
from __future__ import annotations
import json,shutil
from pathlib import Path
from .manifest import UpgradeManifest,normalize
from .version import VersionManager
class DeploymentEngine:
 def __init__(self,root):self.root=Path(root);self.base=self.root/'.zerion/evolution';self.versions=VersionManager(root)
 def deploy(self,manifest:UpgradeManifest, approved:bool, test_results:list)->str:
  if not approved:raise PermissionError('explicit user approval is required')
  manifest.validate()
  if not test_results or not all(x.passed for x in test_results):raise RuntimeError('deployment blocked: tests did not pass')
  stage=self.base/'staging'/manifest.id; backup=self.base/'backups'/manifest.id;backup.mkdir(parents=True,exist_ok=False)
  changed=[]
  try:
   for rel in manifest.files:
    rel=normalize(rel); source=stage/rel; target=self.root/rel
    if not source.exists():raise FileNotFoundError(f'missing staged {rel}')
    if target.exists():
     dst=backup/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,dst)
    else:
     dst=backup/(rel + '.absent');dst.parent.mkdir(parents=True,exist_ok=True);dst.write_text('', encoding='utf8')
    target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_suffix(target.suffix+'.zerion.tmp');shutil.copy2(source,tmp);tmp.replace(target);changed.append(rel)
  except Exception:
   from .rollback import RollbackEngine; RollbackEngine(self.root).rollback(manifest.id);raise
  manifest.tests_passed=[x.name for x in test_results if x.passed];data=manifest.data();data['files_changed']=changed;data['rollback_id']=manifest.id;self.versions.record(data)
  return manifest.id
