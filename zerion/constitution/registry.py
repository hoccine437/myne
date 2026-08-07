"""Protected-file registry derived from constitutional law, with hashes for audit."""
from hashlib import sha256
from pathlib import Path
from .constitution import ConstitutionEngine
class ProtectedFileRegistry:
 def __init__(self,root):self.root=Path(root)
 def entries(self):
  result=[]
  for path in ConstitutionEngine.PROTECTED:
   p=self.root/path; result.append({'path':path,'reason':'Constitutional immutable core','owner':'owner','priority':95,'modification_allowed':False,'hash':sha256(p.read_bytes()).hexdigest() if p.exists() else None,'version':'1.0'})
  return result
