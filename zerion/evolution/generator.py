"""Stages reviewed text only. Generation is intentionally supplied by a supervised caller."""
from pathlib import Path
from .manifest import UpgradeManifest,normalize
class UpgradeGenerator:
 def __init__(self,root):self.root=Path(root);self.stage=self.root/'.zerion/evolution/staging'
 def stage_changes(self,manifest:UpgradeManifest,changes:dict[str,str])->list[Path]:
  manifest.validate(); self.stage.mkdir(parents=True,exist_ok=True); out=[]
  for path,text in changes.items():
   p=self.stage/manifest.id/normalize(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf8');out.append(p)
  return out
