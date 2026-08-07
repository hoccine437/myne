from __future__ import annotations
import json
from pathlib import Path
class VersionManager:
 def __init__(self,root):self.dir=Path(root)/'.zerion/evolution/versions';self.dir.mkdir(parents=True,exist_ok=True)
 def record(self,manifest:dict)->Path:
  p=self.dir/f"{manifest['id']}.json"; tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(manifest,indent=2),encoding='utf8');tmp.replace(p);return p
 def get(self,ident):return json.loads((self.dir/f'{ident}.json').read_text(encoding='utf8'))
